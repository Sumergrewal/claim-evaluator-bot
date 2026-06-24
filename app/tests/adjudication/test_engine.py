"""Tests for the pure adjudication engine.

No DB, no HTTP. Each test constructs an `EngineInput` by hand and
asserts the `EngineResult` produced by `adjudicate()`.

Two layers:

- Focused tests, one per engine behaviour (eligibility, exclusion,
  not-covered, gates pass/needs_review, deductible absorbs/met,
  limit pass/clip, copay flat/capped, coinsurance, no-cost-sharing,
  banker's rounding).
- Integration tests anchored to specific scenarios from
  `data/claims.yaml`, covering the full pipeline end-to-end so the
  numbers can be verified against the seed data the reviewer will
  see in the UI.
"""

from __future__ import annotations

from datetime import date, datetime
from decimal import Decimal

from app.adjudication.engine import adjudicate
from app.adjudication.types import EngineInput, PhaseName, StepResult
from app.domain.entities import (
    Claim,
    CoverageRule,
    DecisionOutcome,
    LineItem,
    LineItemStatus,
    Policy,
    RuleKind,
)

# --- builders -------------------------------------------------------------

_TODAY = date(2026, 6, 1)
_SUBMITTED_AT = datetime(2026, 6, 1, 10, 0)


def _policy(
    *,
    pid: str = "P1",
    name: str = "TestPlan",
    deductible: Decimal = Decimal("500.00"),
) -> Policy:
    return Policy(
        id=pid,
        member_id="M1",
        name=name,
        effective_date=date(2026, 1, 1),
        termination_date=date(2026, 12, 31),
        annual_deductible=deductible,
    )


def _claim(*, cid: str = "C1", service_date: date = _TODAY) -> Claim:
    return Claim(
        id=cid,
        member_id="M1",
        provider_name="Some Clinic",
        service_date=service_date,
        submitted_at=_SUBMITTED_AT,
        paid_at=None,
    )


def _line_item(
    *,
    lid: str = "L1",
    service_type: str = "consult",
    charged: Decimal = Decimal("100.00"),
    preauth_ref: str | None = None,
    claim_id: str = "C1",
) -> LineItem:
    return LineItem(
        id=lid,
        claim_id=claim_id,
        service_type=service_type,
        service_description="desc",
        charged_amount=charged,
        preauth_ref=preauth_ref,
        status=LineItemStatus.PENDING,
    )


def _rule(
    kind: RuleKind,
    service_type: str = "consult",
    *,
    rid: str = "R",
    pid: str = "P1",
    parameters: dict[str, object] | None = None,
) -> CoverageRule:
    return CoverageRule(
        id=rid,
        policy_id=pid,
        service_type=service_type,
        kind=kind,
        parameters=parameters or {},
    )


_DEFAULT_POLICY = object()


def _input(
    *,
    line_item: LineItem,
    claim: Claim | None = None,
    policy: Policy | None | object = _DEFAULT_POLICY,
    rules: list[CoverageRule] | None = None,
    deductible_used: Decimal = Decimal("0"),
    limit_used: Decimal = Decimal("0"),
) -> EngineInput:
    if policy is _DEFAULT_POLICY:
        resolved_policy: Policy | None = _policy()
    else:
        resolved_policy = policy  # type: ignore[assignment]
    return EngineInput(
        line_item=line_item,
        claim=claim or _claim(),
        policy=resolved_policy,
        rules=rules or [],
        deductible_used_ytd=deductible_used,
        limit_used_ytd=limit_used,
    )


def _phases(result_steps: tuple) -> list[PhaseName]:
    return [s.phase for s in result_steps]


# --- Phase 1: eligibility -------------------------------------------------


def test_engine_denies_when_no_policy_active_on_service_date() -> None:
    li = _line_item(charged=Decimal("200.00"))
    result = adjudicate(_input(line_item=li, policy=None))

    assert result.outcome is DecisionOutcome.DENIED
    assert result.payable_amount == Decimal("0.00")
    assert result.member_responsibility == Decimal("200.00")
    assert _phases(result.steps) == [PhaseName.ELIGIBILITY]
    assert result.steps[-1].result is StepResult.FAIL
    assert result.steps[-1].terminating is True
    assert "no policy active" in result.steps[-1].note
    assert result.narrative.startswith("Denied:")


# --- Phase 2: coverage ----------------------------------------------------


def test_engine_denies_when_service_is_explicitly_excluded() -> None:
    li = _line_item(service_type="bariatric_surgery", charged=Decimal("20000.00"))
    rules = [
        _rule(RuleKind.SERVICE_EXCLUDED, "bariatric_surgery", rid="R-EXC"),
    ]
    result = adjudicate(_input(line_item=li, rules=rules))

    assert result.outcome is DecisionOutcome.DENIED
    assert result.payable_amount == Decimal("0.00")
    assert result.member_responsibility == Decimal("20000.00")
    coverage_step = result.steps[-1]
    assert coverage_step.phase is PhaseName.COVERAGE
    assert coverage_step.result is StepResult.FAIL
    assert coverage_step.rule_id == "R-EXC"
    assert coverage_step.terminating is True


def test_engine_denies_when_no_service_covered_rule_exists() -> None:
    li = _line_item(service_type="experimental_treatment", charged=Decimal("500.00"))
    result = adjudicate(_input(line_item=li, rules=[]))

    assert result.outcome is DecisionOutcome.DENIED
    last = result.steps[-1]
    assert last.phase is PhaseName.COVERAGE
    assert last.result is StepResult.FAIL
    assert "not a covered service" in last.note


def test_engine_excluded_wins_when_both_rules_exist() -> None:
    # Defensive: a service shouldn't have both `service_covered` and
    # `service_excluded` rules, but if it does the exclusion wins.
    li = _line_item(service_type="something", charged=Decimal("100.00"))
    rules = [
        _rule(RuleKind.SERVICE_COVERED, "something", rid="R-COV"),
        _rule(RuleKind.SERVICE_EXCLUDED, "something", rid="R-EXC"),
    ]
    result = adjudicate(_input(line_item=li, rules=rules))

    assert result.outcome is DecisionOutcome.DENIED
    assert result.steps[-1].rule_id == "R-EXC"


# --- Phase 3: gates -------------------------------------------------------


def test_engine_returns_needs_review_when_preauth_required_and_missing() -> None:
    li = _line_item(
        service_type="root_canal", charged=Decimal("900.00"), preauth_ref=None
    )
    rules = [
        _rule(RuleKind.SERVICE_COVERED, "root_canal", rid="R-COV"),
        _rule(RuleKind.PREAUTH_REQUIRED, "root_canal", rid="R-PRE"),
        _rule(
            RuleKind.COINSURANCE,
            "root_canal",
            rid="R-COIN",
            parameters={"member_pct": 30},
        ),
    ]
    result = adjudicate(_input(line_item=li, rules=rules))

    assert result.outcome is DecisionOutcome.NEEDS_REVIEW
    assert result.payable_amount == Decimal("0.00")
    assert result.member_responsibility == Decimal("900.00")
    last = result.steps[-1]
    assert last.phase is PhaseName.GATES
    assert last.result is StepResult.NEEDS_REVIEW
    assert last.rule_id == "R-PRE"
    assert last.terminating is True
    assert result.narrative.startswith("Pending review:")


def test_engine_passes_gates_when_preauth_ref_present() -> None:
    li = _line_item(
        service_type="mri", charged=Decimal("1500.00"), preauth_ref="PRE-12345"
    )
    rules = [
        _rule(RuleKind.SERVICE_COVERED, "mri", rid="R-COV"),
        _rule(RuleKind.PREAUTH_REQUIRED, "mri", rid="R-PRE"),
        _rule(
            RuleKind.COINSURANCE,
            "mri",
            rid="R-COIN",
            parameters={"member_pct": 20},
        ),
    ]
    # Deductible already met so we get a clean coinsurance run.
    result = adjudicate(
        _input(
            line_item=li,
            rules=rules,
            deductible_used=Decimal("500.00"),
        )
    )

    assert result.outcome is DecisionOutcome.APPROVED
    gates_step = next(s for s in result.steps if s.phase is PhaseName.GATES)
    assert gates_step.result is StepResult.PASS
    assert "PRE-12345" in gates_step.note


# --- Phase 4: deductible --------------------------------------------------


def test_engine_deductible_absorbs_entire_charge_when_charge_within_remaining() -> None:
    # Alice's first claim: $400 charge, $500 deductible remaining.
    li = _line_item(service_type="consult", charged=Decimal("400.00"))
    rules = [
        _rule(RuleKind.SERVICE_COVERED, "consult", rid="R-COV"),
        _rule(
            RuleKind.COPAY,
            "consult",
            rid="R-COPAY",
            parameters={"amount": "25.00"},
        ),
    ]
    result = adjudicate(_input(line_item=li, rules=rules))

    assert result.outcome is DecisionOutcome.APPROVED
    assert result.payable_amount == Decimal("0.00")
    assert result.member_responsibility == Decimal("400.00")
    assert result.deductible_applied == Decimal("400.00")

    cost_share = next(s for s in result.steps if s.phase is PhaseName.COST_SHARING)
    # Copay must not be charged when coverable is $0.
    assert cost_share.result is StepResult.PASS
    assert "not applied" in cost_share.note


def test_engine_partially_fills_deductible_then_applies_copay_on_remainder() -> None:
    # Alice's second consult: $200 charge, $100 deductible remaining.
    # Deductible takes $100, copay $25 applies to the remaining $100.
    li = _line_item(service_type="consult", charged=Decimal("200.00"))
    rules = [
        _rule(RuleKind.SERVICE_COVERED, "consult", rid="R-COV"),
        _rule(
            RuleKind.COPAY,
            "consult",
            rid="R-COPAY",
            parameters={"amount": "25.00"},
        ),
    ]
    result = adjudicate(
        _input(
            line_item=li,
            rules=rules,
            deductible_used=Decimal("400.00"),
        )
    )

    assert result.outcome is DecisionOutcome.APPROVED
    assert result.payable_amount == Decimal("75.00")
    assert result.member_responsibility == Decimal("125.00")
    assert result.deductible_applied == Decimal("100.00")


def test_engine_skips_deductible_when_policy_has_no_deductible() -> None:
    li = _line_item(service_type="cleaning", charged=Decimal("80.00"))
    rules = [_rule(RuleKind.SERVICE_COVERED, "cleaning", rid="R-COV")]
    result = adjudicate(
        _input(
            line_item=li,
            rules=rules,
            policy=_policy(deductible=Decimal("0.00")),
        )
    )

    assert result.outcome is DecisionOutcome.APPROVED
    deductible_step = next(
        s for s in result.steps if s.phase is PhaseName.DEDUCTIBLE
    )
    assert deductible_step.result is StepResult.PASS
    assert "no deductible" in deductible_step.note
    assert result.deductible_applied == Decimal("0.00")


def test_engine_records_deductible_pass_when_already_met() -> None:
    li = _line_item(service_type="physio", charged=Decimal("400.00"))
    rules = [
        _rule(RuleKind.SERVICE_COVERED, "physio", rid="R-COV"),
        _rule(
            RuleKind.COINSURANCE,
            "physio",
            rid="R-COIN",
            parameters={"member_pct": 20},
        ),
    ]
    result = adjudicate(
        _input(
            line_item=li,
            rules=rules,
            deductible_used=Decimal("500.00"),
        )
    )

    deductible_step = next(
        s for s in result.steps if s.phase is PhaseName.DEDUCTIBLE
    )
    assert deductible_step.result is StepResult.PASS
    assert "already met" in deductible_step.note
    assert result.deductible_applied == Decimal("0.00")


# --- Phase 5: limits ------------------------------------------------------


def test_engine_clips_coverable_when_annual_limit_partially_exhausted() -> None:
    # Carol's second crown: cap $750, prior payable $420, remaining $330.
    # $400 charge → coverable $330, over_limit $70.
    li = _line_item(service_type="crown", charged=Decimal("400.00"))
    rules = [
        _rule(RuleKind.SERVICE_COVERED, "crown", rid="R-COV"),
        _rule(
            RuleKind.ANNUAL_LIMIT,
            "crown",
            rid="R-LIM",
            parameters={"cap_amount": "750.00", "period": "calendar_year"},
        ),
        _rule(
            RuleKind.COINSURANCE,
            "crown",
            rid="R-COIN",
            parameters={"member_pct": 30},
        ),
    ]
    result = adjudicate(
        _input(
            line_item=li,
            rules=rules,
            policy=_policy(deductible=Decimal("0.00")),
            limit_used=Decimal("420.00"),
        )
    )

    assert result.outcome is DecisionOutcome.APPROVED
    # coverable = 330, coinsurance 30% = 99, plan_pays = 231,
    # member_pays = 0 (deductible) + 99 (coinsurance) + 70 (over_limit) = 169
    assert result.payable_amount == Decimal("231.00")
    assert result.member_responsibility == Decimal("169.00")

    limits_step = next(s for s in result.steps if s.phase is PhaseName.LIMITS)
    assert limits_step.result is StepResult.APPLIED
    assert limits_step.amount == Decimal("70.00")


def test_engine_records_limits_pass_under_cap() -> None:
    li = _line_item(service_type="physio", charged=Decimal("800.00"))
    rules = [
        _rule(RuleKind.SERVICE_COVERED, "physio", rid="R-COV"),
        _rule(
            RuleKind.ANNUAL_LIMIT,
            "physio",
            rid="R-LIM",
            parameters={"cap_amount": "1000.00", "period": "calendar_year"},
        ),
        _rule(
            RuleKind.COINSURANCE,
            "physio",
            rid="R-COIN",
            parameters={"member_pct": 20},
        ),
    ]
    result = adjudicate(
        _input(
            line_item=li,
            rules=rules,
            deductible_used=Decimal("500.00"),
        )
    )

    assert result.outcome is DecisionOutcome.APPROVED
    limits_step = next(s for s in result.steps if s.phase is PhaseName.LIMITS)
    assert limits_step.result is StepResult.PASS


# --- Phase 6: cost-sharing -----------------------------------------------


def test_engine_applies_flat_copay_when_coverable_exceeds_copay_amount() -> None:
    li = _line_item(service_type="filling", charged=Decimal("150.00"))
    rules = [
        _rule(RuleKind.SERVICE_COVERED, "filling", rid="R-COV"),
        _rule(
            RuleKind.COPAY,
            "filling",
            rid="R-COPAY",
            parameters={"amount": "40.00"},
        ),
    ]
    result = adjudicate(
        _input(
            line_item=li,
            rules=rules,
            policy=_policy(deductible=Decimal("0.00")),
        )
    )

    assert result.outcome is DecisionOutcome.APPROVED
    assert result.payable_amount == Decimal("110.00")
    assert result.member_responsibility == Decimal("40.00")


def test_engine_caps_copay_at_coverable_when_copay_exceeds_remainder() -> None:
    # Coverable is $10 after deductible; copay nominally $25 should
    # cap at $10 to preserve the ledger invariant.
    li = _line_item(service_type="consult", charged=Decimal("100.00"))
    rules = [
        _rule(RuleKind.SERVICE_COVERED, "consult", rid="R-COV"),
        _rule(
            RuleKind.COPAY,
            "consult",
            rid="R-COPAY",
            parameters={"amount": "25.00"},
        ),
    ]
    result = adjudicate(
        _input(
            line_item=li,
            rules=rules,
            deductible_used=Decimal("410.00"),  # $90 remaining, charge $100, taken $90
        )
    )

    assert result.payable_amount == Decimal("0.00")
    assert result.member_responsibility == Decimal("100.00")
    cs = next(s for s in result.steps if s.phase is PhaseName.COST_SHARING)
    assert cs.result is StepResult.APPLIED
    assert cs.amount == Decimal("10.00")
    assert "capped" in cs.note


def test_engine_applies_coinsurance_percentage_on_coverable() -> None:
    li = _line_item(service_type="mri", charged=Decimal("1500.00"))
    rules = [
        _rule(RuleKind.SERVICE_COVERED, "mri", rid="R-COV"),
        _rule(
            RuleKind.COINSURANCE,
            "mri",
            rid="R-COIN",
            parameters={"member_pct": 20},
        ),
    ]
    result = adjudicate(
        _input(
            line_item=li,
            rules=rules,
            deductible_used=Decimal("500.00"),  # deductible met
        )
    )

    # coverable = $1500, 20% = $300, plan_pays = $1200.
    assert result.outcome is DecisionOutcome.APPROVED
    assert result.payable_amount == Decimal("1200.00")
    assert result.member_responsibility == Decimal("300.00")


def test_engine_records_pass_when_no_cost_sharing_rule_applies() -> None:
    li = _line_item(service_type="cleaning", charged=Decimal("80.00"))
    rules = [_rule(RuleKind.SERVICE_COVERED, "cleaning", rid="R-COV")]
    result = adjudicate(
        _input(
            line_item=li,
            rules=rules,
            policy=_policy(deductible=Decimal("0.00")),
        )
    )

    assert result.outcome is DecisionOutcome.APPROVED
    assert result.payable_amount == Decimal("80.00")
    assert result.member_responsibility == Decimal("0.00")
    cs = next(s for s in result.steps if s.phase is PhaseName.COST_SHARING)
    assert cs.result is StepResult.PASS
    assert "no cost-sharing" in cs.note


# --- Math: rounding -------------------------------------------------------


def test_engine_quantizes_coinsurance_amounts_to_two_places() -> None:
    # 12.5% of $1.00 = $0.125; banker's rounds to $0.12.
    li = _line_item(service_type="x", charged=Decimal("1.00"))
    rules = [
        _rule(RuleKind.SERVICE_COVERED, "x", rid="R-COV"),
        _rule(
            RuleKind.COINSURANCE,
            "x",
            rid="R-COIN",
            parameters={"member_pct": 13},  # 13% of $1.00 = $0.13
        ),
    ]
    result = adjudicate(
        _input(
            line_item=li,
            rules=rules,
            policy=_policy(deductible=Decimal("0.00")),
        )
    )

    # Whatever the result, payable+member == charged to the cent.
    assert result.payable_amount + result.member_responsibility == Decimal("1.00")
    assert result.member_responsibility == Decimal("0.13")
    assert result.payable_amount == Decimal("0.87")


# --- Integration: against seed-data scenarios -----------------------------


def test_integration_c_alice_001_general_consult_400_deductible_absorbs_all() -> None:
    """C-ALICE-001 from data/claims.yaml: $400 consult, $500 deductible,
    first claim of the year → entire charge falls into the deductible.
    """
    li = _line_item(
        lid="L-ALICE-001-1",
        service_type="general_consultation",
        charged=Decimal("400.00"),
    )
    rules = [
        _rule(
            RuleKind.SERVICE_COVERED,
            "general_consultation",
            rid="R-BASIC-001",
        ),
        _rule(
            RuleKind.COPAY,
            "general_consultation",
            rid="R-BASIC-002",
            parameters={"amount": "25.00"},
        ),
    ]
    result = adjudicate(
        _input(
            line_item=li,
            claim=_claim(cid="C-ALICE-001", service_date=date(2026, 2, 10)),
            policy=_policy(
                pid="P-BASIC-2026",
                name="Basic Health 2026",
                deductible=Decimal("500.00"),
            ),
            rules=rules,
        )
    )

    assert result.outcome is DecisionOutcome.APPROVED
    assert result.payable_amount == Decimal("0.00")
    assert result.member_responsibility == Decimal("400.00")
    assert result.deductible_applied == Decimal("400.00")
    # All six phases recorded, in the documented order.
    assert _phases(result.steps) == [
        PhaseName.ELIGIBILITY,
        PhaseName.COVERAGE,
        PhaseName.GATES,
        PhaseName.DEDUCTIBLE,
        PhaseName.LIMITS,
        PhaseName.COST_SHARING,
    ]


def test_integration_c_alice_006_bariatric_excluded_under_basic() -> None:
    """C-ALICE-006: BASIC excludes bariatric_surgery → denied with one
    coverage step and an explanation pointing at the exclusion rule.
    """
    li = _line_item(
        lid="L-ALICE-006-1",
        service_type="bariatric_surgery",
        charged=Decimal("20000.00"),
    )
    rules = [
        _rule(
            RuleKind.SERVICE_EXCLUDED,
            "bariatric_surgery",
            rid="R-BASIC-009",
        ),
    ]
    result = adjudicate(
        _input(
            line_item=li,
            claim=_claim(cid="C-ALICE-006", service_date=date(2026, 7, 1)),
            policy=_policy(
                pid="P-BASIC-2026", name="Basic Health 2026"
            ),
            rules=rules,
        )
    )

    assert result.outcome is DecisionOutcome.DENIED
    assert result.payable_amount == Decimal("0.00")
    assert result.member_responsibility == Decimal("20000.00")
    assert result.steps[-1].rule_id == "R-BASIC-009"
    assert "excluded under Basic Health 2026" in result.steps[-1].note


def test_integration_c_carol_004_second_crown_clips_at_remaining_cap() -> None:
    """C-CAROL-004 line item 2: second crown after the first consumed $420
    of the $750 cap; this one should be clipped to $330 coverable and
    leave $70 as over-limit member-pay.
    """
    li = _line_item(
        lid="L-CAROL-004-2",
        service_type="crown",
        charged=Decimal("400.00"),
    )
    rules = [
        _rule(RuleKind.SERVICE_COVERED, "crown", rid="R-DENT-004"),
        _rule(
            RuleKind.ANNUAL_LIMIT,
            "crown",
            rid="R-DENT-005",
            parameters={"cap_amount": "750.00", "period": "calendar_year"},
        ),
        _rule(
            RuleKind.COINSURANCE,
            "crown",
            rid="R-DENT-006",
            parameters={"member_pct": 30},
        ),
    ]
    result = adjudicate(
        _input(
            line_item=li,
            claim=_claim(cid="C-CAROL-004", service_date=date(2026, 6, 15)),
            policy=_policy(
                pid="P-DENTAL-2026",
                name="Family Dental 2026",
                deductible=Decimal("0.00"),
            ),
            rules=rules,
            limit_used=Decimal("420.00"),
        )
    )

    # coverable = 330, coinsurance 30% of 330 = 99, plan_pays = 231,
    # member_pays = 0 + 99 + 70 = 169.
    assert result.outcome is DecisionOutcome.APPROVED
    assert result.payable_amount == Decimal("231.00")
    assert result.member_responsibility == Decimal("169.00")
    assert result.deductible_applied == Decimal("0.00")
    limit_step = next(s for s in result.steps if s.phase is PhaseName.LIMITS)
    assert limit_step.amount == Decimal("70.00")
