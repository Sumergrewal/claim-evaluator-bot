"""Value types and small pure helpers for the adjudication engine.

Pure-Python frozen dataclasses, enums, and one money helper. No
SQLAlchemy, no FastAPI, no I/O — the engine's pipeline (next module)
consumes and produces these types directly; the service layer is the
only thing that knows how to assemble an `EngineInput` from a session
and persist an `EngineResult` as an `AdjudicationDecision`.

The shapes here implement the `explanation` JSON format documented in
`docs/domain-model.md` ("Explanation format"). Money is quoted as a
string in JSON to keep `Decimal` round-trip exact, matching the
seed-loader convention. `quantize_money` is the one rounding step the
engine ever applies; every phase calls it on its own output so the
ledger invariant (`payable + member == charged`) holds to the cent.
"""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass
from decimal import ROUND_HALF_EVEN, Decimal
from enum import StrEnum
from typing import Any

from app.domain.entities import (
    Claim,
    CoverageRule,
    DecisionOutcome,
    LineItem,
    Policy,
)


class PhaseName(StrEnum):
    """One enum value per engine phase that can appear in an explanation step.

    Execution order is fixed by the engine — see the *Evaluation
    pipeline* table in `docs/domain-model.md`. Listing values in the
    same order here is convention, not a mechanism: the engine
    walks them explicitly.
    """

    ELIGIBILITY = "eligibility"
    COVERAGE = "coverage"
    GATES = "gates"
    DEDUCTIBLE = "deductible"
    LIMITS = "limits"
    COST_SHARING = "cost_sharing"


class StepResult(StrEnum):
    """Outcome of one phase, as serialised into the explanation `steps`."""

    PASS = "pass"
    APPLIED = "applied"
    FAIL = "fail"
    NEEDS_REVIEW = "needs_review"


_MONEY_QUANT = Decimal("0.01")


def quantize_money(x: Decimal) -> Decimal:
    """Round a `Decimal` to two places using banker's rounding.

    `ROUND_HALF_EVEN` is the standard pick for money math because it
    avoids the upward bias of `ROUND_HALF_UP` when many midpoints are
    aggregated. Engine phases call this on every output amount so
    `plan_pays + member_pays == charged` always holds to the cent.
    """
    return x.quantize(_MONEY_QUANT, rounding=ROUND_HALF_EVEN)


@dataclass(frozen=True, slots=True)
class ExplanationStep:
    """One row in the explanation `steps` array.

    Shape matches the example in `docs/domain-model.md`. `rule_id` is
    always present in the serialised form (as `null` when absent);
    `amount` and `terminating` are omitted when they don't apply, so
    the JSON stays small and obvious for non-terminal phases.
    """

    phase: PhaseName
    result: StepResult
    note: str
    rule_id: str | None = None
    amount: Decimal | None = None
    terminating: bool = False

    def to_json(self) -> dict[str, Any]:
        out: dict[str, Any] = {
            "phase": str(self.phase),
            "rule_id": self.rule_id,
            "result": str(self.result),
            "note": self.note,
        }
        if self.amount is not None:
            out["amount"] = str(quantize_money(self.amount))
        if self.terminating:
            out["terminating"] = True
        return out


@dataclass(frozen=True, slots=True)
class EngineResult:
    """Immutable value the pure engine returns for one line item.

    `steps` is the in-memory tuple (handy in tests); `to_explanation_json`
    is what the service layer persists into
    `AdjudicationDecision.explanation`. `charged_amount` is carried so
    the ledger invariant can be checked here — this catches engine bugs
    one layer before `LineItem.__post_init__` would, and gives a clearer
    error message.

    `deductible_applied` is the amount this decision contributed to the
    member's annual deductible (the `deductible_taken` term from the
    cost-sharing math in `docs/domain-model.md`). The service layer
    persists it into the same-named column on `AdjudicationDecision` so
    the cross-service-type deductible accumulator query stays a simple
    SQL sum. See the 2026-06-24 phase-06 entry in `docs/decisions.md`.
    """

    outcome: DecisionOutcome
    charged_amount: Decimal
    payable_amount: Decimal
    member_responsibility: Decimal
    steps: tuple[ExplanationStep, ...]
    narrative: str
    deductible_applied: Decimal = Decimal("0.00")

    def __post_init__(self) -> None:
        if self.payable_amount < 0:
            raise ValueError(
                f"EngineResult: payable_amount must be non-negative "
                f"(got {self.payable_amount})"
            )
        if self.member_responsibility < 0:
            raise ValueError(
                f"EngineResult: member_responsibility must be non-negative "
                f"(got {self.member_responsibility})"
            )
        if self.deductible_applied < 0:
            raise ValueError(
                f"EngineResult: deductible_applied must be non-negative "
                f"(got {self.deductible_applied})"
            )
        total = self.payable_amount + self.member_responsibility
        if total != self.charged_amount:
            raise ValueError(
                f"EngineResult: payable_amount + member_responsibility "
                f"({total}) must equal charged_amount "
                f"({self.charged_amount})"
            )

    def to_explanation_json(self) -> dict[str, Any]:
        """Serialise to the JSON shape stored in `AdjudicationDecision.explanation`."""
        return {
            "outcome": str(self.outcome),
            "charged_amount": str(quantize_money(self.charged_amount)),
            "payable_amount": str(quantize_money(self.payable_amount)),
            "member_responsibility": str(
                quantize_money(self.member_responsibility)
            ),
            "steps": [s.to_json() for s in self.steps],
            "narrative": self.narrative,
        }


@dataclass(frozen=True, slots=True)
class EngineInput:
    """Everything the pure engine needs to adjudicate one line item.

    Constructed by the service layer from repository reads. `policy`
    is `None` when no policy is active for the member on
    `claim.service_date`; the engine handles that via the eligibility
    phase (deny with an explanation step) rather than raising.

    `deductible_used_ytd` and `limit_used_ytd` are Decimals so the
    engine has zero coupling to the session or the accumulator query.
    Same shape whether called from the API path or from a test that
    constructs them by hand.
    """

    line_item: LineItem
    claim: Claim
    policy: Policy | None
    rules: Sequence[CoverageRule]
    deductible_used_ytd: Decimal
    limit_used_ytd: Decimal


__all__ = (
    "EngineInput",
    "EngineResult",
    "ExplanationStep",
    "PhaseName",
    "StepResult",
    "quantize_money",
)
