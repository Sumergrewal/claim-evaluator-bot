"""Pure adjudication engine.

`adjudicate(EngineInput) -> EngineResult` walks the six phases in the
fixed order defined by `docs/domain-model.md`'s *Evaluation pipeline*:

    1. eligibility    — active policy on the claim's service_date
    2. coverage       — service_excluded short-circuits; service_covered required
    3. gates          — preauth_required (if any) checked against line_item.preauth_ref
    4. deductible     — annual deductible accumulator eats first
    5. limits         — annual cap (if any) clips coverable, the rest is over-limit
    6. cost-sharing   — copay OR coinsurance applied on the coverable amount

The function is pure: it takes a fully-populated `EngineInput` and
returns an `EngineResult`. The caller (the service layer) is
responsible for loading the input from a `Session` and for persisting
the result as an `AdjudicationDecision`. No phase function reads from
the network, DB, or filesystem.

Math conventions follow the "Cost-sharing math" section of
`docs/domain-model.md`. Every intermediate is run through
`quantize_money` so the ledger invariant
(`payable + member == charged`) holds to the cent — the
`EngineResult.__post_init__` will raise loudly if it ever doesn't.
"""

from __future__ import annotations

from collections.abc import Sequence
from decimal import Decimal

from app.adjudication.types import (
    EngineInput,
    EngineResult,
    ExplanationStep,
    PhaseName,
    StepResult,
    quantize_money,
)
from app.domain.entities import CoverageRule, DecisionOutcome, RuleKind

_ZERO = Decimal("0.00")
_HUNDRED = Decimal("100")


def adjudicate(engine_input: EngineInput) -> EngineResult:
    """Walk the six phases and return the engine's decision for one line item.

    Pre-rounding `line_item.charged_amount` to two places happens once
    at the top so every comparison/subtraction afterwards is exact.
    """
    li = engine_input.line_item
    claim = engine_input.claim
    charged = quantize_money(li.charged_amount)
    steps: list[ExplanationStep] = []

    # === Phase 1: eligibility =============================================
    if engine_input.policy is None:
        steps.append(
            ExplanationStep(
                phase=PhaseName.ELIGIBILITY,
                result=StepResult.FAIL,
                note=(
                    f"no policy active for member {claim.member_id} on "
                    f"{claim.service_date}"
                ),
                terminating=True,
            )
        )
        return _terminal(DecisionOutcome.DENIED, charged, steps)

    policy = engine_input.policy
    steps.append(
        ExplanationStep(
            phase=PhaseName.ELIGIBILITY,
            result=StepResult.PASS,
            note=f"policy {policy.id} active on {claim.service_date}",
        )
    )

    # === Phase 2: coverage ================================================
    service_type = li.service_type
    excluded = _first_of_kind(engine_input.rules, RuleKind.SERVICE_EXCLUDED)
    if excluded is not None:
        steps.append(
            ExplanationStep(
                phase=PhaseName.COVERAGE,
                result=StepResult.FAIL,
                note=f"{service_type} is excluded under {policy.name}",
                rule_id=excluded.id,
                terminating=True,
            )
        )
        return _terminal(DecisionOutcome.DENIED, charged, steps)

    covered = _first_of_kind(engine_input.rules, RuleKind.SERVICE_COVERED)
    if covered is None:
        steps.append(
            ExplanationStep(
                phase=PhaseName.COVERAGE,
                result=StepResult.FAIL,
                note=(
                    f"{service_type} is not a covered service under "
                    f"{policy.name}"
                ),
                terminating=True,
            )
        )
        return _terminal(DecisionOutcome.DENIED, charged, steps)

    steps.append(
        ExplanationStep(
            phase=PhaseName.COVERAGE,
            result=StepResult.PASS,
            note=f"{service_type} is covered",
            rule_id=covered.id,
        )
    )

    # === Phase 3: gates (preauth) =========================================
    preauth = _first_of_kind(engine_input.rules, RuleKind.PREAUTH_REQUIRED)
    if preauth is not None:
        if li.preauth_ref:
            steps.append(
                ExplanationStep(
                    phase=PhaseName.GATES,
                    result=StepResult.PASS,
                    note=f"preauth_ref {li.preauth_ref!r} on file",
                    rule_id=preauth.id,
                )
            )
        else:
            steps.append(
                ExplanationStep(
                    phase=PhaseName.GATES,
                    result=StepResult.NEEDS_REVIEW,
                    note=(
                        f"preauthorization required for {service_type} "
                        f"but no preauth_ref provided"
                    ),
                    rule_id=preauth.id,
                    terminating=True,
                )
            )
            return _terminal(DecisionOutcome.NEEDS_REVIEW, charged, steps)
    else:
        steps.append(
            ExplanationStep(
                phase=PhaseName.GATES,
                result=StepResult.PASS,
                note="no gates apply",
            )
        )

    # === Phase 4: deductible ==============================================
    # Deductible eats first; the math here matches the formula in
    # docs/domain-model.md ("deductible_taken = min(charged,
    # deductible_remaining)"). The field on AdjudicationDecision is
    # named `deductible_applied` per the persistence decision; the math
    # symbol stays `deductible_taken` here to match the docs.
    deductible_total = quantize_money(policy.annual_deductible)
    deductible_used = quantize_money(engine_input.deductible_used_ytd)
    deductible_remaining = max(_ZERO, deductible_total - deductible_used)
    deductible_taken = quantize_money(min(charged, deductible_remaining))
    post_deductible = quantize_money(charged - deductible_taken)

    if deductible_total == 0:
        steps.append(
            ExplanationStep(
                phase=PhaseName.DEDUCTIBLE,
                result=StepResult.PASS,
                note="no deductible on this policy",
            )
        )
    elif deductible_taken > 0:
        new_deductible_remaining = quantize_money(
            deductible_remaining - deductible_taken
        )
        steps.append(
            ExplanationStep(
                phase=PhaseName.DEDUCTIBLE,
                result=StepResult.APPLIED,
                note=(
                    f"applied ${deductible_taken} of annual deductible "
                    f"(${new_deductible_remaining} remaining of "
                    f"${deductible_total})"
                ),
                amount=deductible_taken,
            )
        )
    else:
        steps.append(
            ExplanationStep(
                phase=PhaseName.DEDUCTIBLE,
                result=StepResult.PASS,
                note=(
                    f"annual deductible of ${deductible_total} already met "
                    f"for {claim.service_date.year}"
                ),
            )
        )

    # === Phase 5: limits ==================================================
    limit_rule = _first_of_kind(engine_input.rules, RuleKind.ANNUAL_LIMIT)
    if limit_rule is not None:
        cap = quantize_money(Decimal(str(limit_rule.parameters["cap_amount"])))
        limit_used = quantize_money(engine_input.limit_used_ytd)
        limit_remaining = max(_ZERO, cap - limit_used)
        coverable = quantize_money(min(post_deductible, limit_remaining))
        over_limit = quantize_money(post_deductible - coverable)
        new_limit_remaining = quantize_money(limit_remaining - coverable)
        if over_limit > 0:
            steps.append(
                ExplanationStep(
                    phase=PhaseName.LIMITS,
                    result=StepResult.APPLIED,
                    note=(
                        f"${over_limit} over annual cap of ${cap} for "
                        f"{service_type} (${new_limit_remaining} remaining)"
                    ),
                    rule_id=limit_rule.id,
                    amount=over_limit,
                )
            )
        else:
            steps.append(
                ExplanationStep(
                    phase=PhaseName.LIMITS,
                    result=StepResult.PASS,
                    note=(
                        f"under annual cap of ${cap} for {service_type} "
                        f"(${new_limit_remaining} remaining after this "
                        f"line item)"
                    ),
                    rule_id=limit_rule.id,
                )
            )
    else:
        coverable = post_deductible
        over_limit = _ZERO
        steps.append(
            ExplanationStep(
                phase=PhaseName.LIMITS,
                result=StepResult.PASS,
                note=f"no annual limit on {service_type}",
            )
        )

    # === Phase 6: cost-sharing ============================================
    copay_rule = _first_of_kind(engine_input.rules, RuleKind.COPAY)
    coinsurance_rule = _first_of_kind(engine_input.rules, RuleKind.COINSURANCE)
    coinsurance_pct: int | None = None

    if copay_rule is not None:
        copay_amount = quantize_money(
            Decimal(str(copay_rule.parameters["amount"]))
        )
        # Copay caps at `coverable`: a $25 copay on a $0 coverable line
        # owes $0, not $25. Otherwise plan_pays would underflow and break
        # the ledger invariant.
        member_cost_share = quantize_money(min(coverable, copay_amount))
        if coverable == 0:
            steps.append(
                ExplanationStep(
                    phase=PhaseName.COST_SHARING,
                    result=StepResult.PASS,
                    note=(
                        f"${copay_amount} copay not applied "
                        f"(nothing coverable after deductible/limits)"
                    ),
                    rule_id=copay_rule.id,
                )
            )
        elif member_cost_share < copay_amount:
            steps.append(
                ExplanationStep(
                    phase=PhaseName.COST_SHARING,
                    result=StepResult.APPLIED,
                    note=(
                        f"${copay_amount} copay capped at coverable "
                        f"${coverable}"
                    ),
                    rule_id=copay_rule.id,
                    amount=member_cost_share,
                )
            )
        else:
            steps.append(
                ExplanationStep(
                    phase=PhaseName.COST_SHARING,
                    result=StepResult.APPLIED,
                    note=f"flat ${copay_amount} copay",
                    rule_id=copay_rule.id,
                    amount=member_cost_share,
                )
            )
    elif coinsurance_rule is not None:
        coinsurance_pct = int(coinsurance_rule.parameters["member_pct"])
        member_cost_share = quantize_money(
            coverable * Decimal(coinsurance_pct) / _HUNDRED
        )
        if coverable == 0:
            steps.append(
                ExplanationStep(
                    phase=PhaseName.COST_SHARING,
                    result=StepResult.PASS,
                    note=(
                        f"{coinsurance_pct}% coinsurance not applied "
                        f"(nothing coverable after deductible/limits)"
                    ),
                    rule_id=coinsurance_rule.id,
                )
            )
        else:
            steps.append(
                ExplanationStep(
                    phase=PhaseName.COST_SHARING,
                    result=StepResult.APPLIED,
                    note=(
                        f"{coinsurance_pct}% coinsurance on coverable "
                        f"${coverable}"
                    ),
                    rule_id=coinsurance_rule.id,
                    amount=member_cost_share,
                )
            )
    else:
        member_cost_share = _ZERO
        steps.append(
            ExplanationStep(
                phase=PhaseName.COST_SHARING,
                result=StepResult.PASS,
                note="no cost-sharing applies",
            )
        )

    # === Final math =======================================================
    plan_pays = quantize_money(coverable - member_cost_share)
    member_pays = quantize_money(
        deductible_taken + member_cost_share + over_limit
    )

    narrative = _build_approved_narrative(
        service_type=service_type,
        deductible_taken=deductible_taken,
        member_cost_share=member_cost_share,
        over_limit=over_limit,
        plan_pays=plan_pays,
        charged=charged,
        is_copay=copay_rule is not None,
        coinsurance_pct=coinsurance_pct,
    )

    return EngineResult(
        outcome=DecisionOutcome.APPROVED,
        charged_amount=charged,
        payable_amount=plan_pays,
        member_responsibility=member_pays,
        steps=tuple(steps),
        narrative=narrative,
        deductible_applied=deductible_taken,
    )


# --- Internals -------------------------------------------------------------


def _first_of_kind(
    rules: Sequence[CoverageRule], kind: RuleKind
) -> CoverageRule | None:
    """First rule of the given `kind`, or `None` if absent.

    The repo already returns rules ordered by id, so "first" here is
    deterministic across runs. The seed loader enforces the at-most-one
    invariant for cost-sharing kinds; other kinds aren't formally
    constrained but no seed authors two of the same.
    """
    for r in rules:
        if r.kind == kind:
            return r
    return None


def _terminal(
    outcome: DecisionOutcome,
    charged: Decimal,
    steps: list[ExplanationStep],
) -> EngineResult:
    """Build the short-circuit result for `denied` or `needs_review`.

    Both terminal outcomes return `payable = 0` and
    `member_responsibility = charged` — the line item is non-payable,
    so the member is on the hook for the full amount in the
    accounting view until a reviewer rewrites the decision (for
    `needs_review`) or the dispute path takes over.
    """
    terminating_note = steps[-1].note
    if outcome is DecisionOutcome.DENIED:
        narrative = f"Denied: {terminating_note}."
    elif outcome is DecisionOutcome.NEEDS_REVIEW:
        narrative = f"Pending review: {terminating_note}."
    else:
        raise ValueError(
            f"Engine bug: _terminal called with non-terminal outcome {outcome!r}"
        )
    return EngineResult(
        outcome=outcome,
        charged_amount=charged,
        payable_amount=_ZERO,
        member_responsibility=charged,
        steps=tuple(steps),
        narrative=narrative,
        deductible_applied=_ZERO,
    )


def _build_approved_narrative(
    *,
    service_type: str,
    deductible_taken: Decimal,
    member_cost_share: Decimal,
    over_limit: Decimal,
    plan_pays: Decimal,
    charged: Decimal,
    is_copay: bool,
    coinsurance_pct: int | None,
) -> str:
    """One-sentence summary for the UI on approved line items."""
    pretty = service_type.replace("_", " ")
    parts: list[str] = []
    if deductible_taken > 0:
        parts.append(f"${deductible_taken} applied to deductible")
    if over_limit > 0:
        parts.append(f"${over_limit} over annual limit")
    if member_cost_share > 0:
        if is_copay:
            parts.append(f"${member_cost_share} copay")
        elif coinsurance_pct is not None:
            parts.append(
                f"${member_cost_share} coinsurance ({coinsurance_pct}%)"
            )

    head = f"Covered under {pretty}."
    if parts:
        head = f"{head} {', '.join(parts)}."
    return f"{head} Plan pays ${plan_pays} of ${charged} charged."


__all__ = ("adjudicate",)
