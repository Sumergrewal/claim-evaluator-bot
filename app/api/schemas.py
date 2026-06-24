"""Pydantic request/response schemas for the HTTP layer.

Kept separate from `app/domain/entities.py` so:

1. The wire contract can evolve without touching the domain entities,
   and vice versa.
2. The domain layer stays free of FastAPI/Pydantic concerns (per the
   "domain layer is pure" rule in `AGENTS.md`).
3. Translation lives at the boundary: each output schema exposes a
   `from_domain` classmethod that route handlers call after pulling
   data through repositories. Input schemas carry their own
   validation; the route handler maps them into domain entities.

Money is serialised as a JSON string by Pydantic v2's default
`Decimal` serialiser, matching the seed-file convention (money quoted
as strings) and the engine's explanation JSON.

Status / outcome / phase / result fields use the same `StrEnum`s the
engine and persistence layers use. That makes the OpenAPI schema
self-documenting (allowed values appear in `/docs`) and lets the
frontend rely on a closed set.
"""

from __future__ import annotations

from collections.abc import Sequence
from datetime import date, datetime
from decimal import Decimal
from typing import Any, Self

from pydantic import BaseModel, ConfigDict, Field

from app.adjudication.types import PhaseName, StepResult
from app.domain.claim_state import ClaimAdjudicationState, derive_claim_state
from app.api.rule_descriptions import (
    describe_coverage_rule,
    format_rule_parameters,
)
from app.domain.entities import (
    AdjudicationDecision,
    AuditEvent,
    Claim,
    CoverageRule,
    DecisionOutcome,
    LineItem,
    LineItemStatus,
    Member,
    RuleKind,
)

_ZERO_MONEY = Decimal("0.00")


# --- Outputs ---------------------------------------------------------------


class CoverageRuleOut(BaseModel):
    """One coverage rule with a tooltip-friendly description."""

    id: str
    policy_id: str
    policy_name: str
    service_type: str
    kind: RuleKind
    parameters: dict[str, Any]
    description: str
    parameters_summary: str

    @classmethod
    def from_domain(cls, rule: CoverageRule, policy_name: str) -> Self:
        return cls(
            id=rule.id,
            policy_id=rule.policy_id,
            policy_name=policy_name,
            service_type=rule.service_type,
            kind=rule.kind,
            parameters=dict(rule.parameters),
            description=describe_coverage_rule(rule, policy_name),
            parameters_summary=format_rule_parameters(rule),
        )


class MemberOut(BaseModel):
    """One member as exposed by `GET /api/members` and embedded in claim
    payloads via `ClaimSummaryOut.member_name`.
    """

    id: str
    name: str

    @classmethod
    def from_domain(cls, m: Member) -> Self:
        return cls(id=m.id, name=m.name)


class ExplanationStepOut(BaseModel):
    """One row of the explanation `steps[]` array.

    Shape matches the JSON the engine writes into
    `AdjudicationDecision.explanation` (see `to_explanation_json` in
    `app/adjudication/types.py`). `amount` and `terminating` are
    optional because the engine omits them on steps that don't carry
    those fields; we mirror that here so the wire shape round-trips
    cleanly.
    """

    phase: PhaseName
    rule_id: str | None
    result: StepResult
    note: str
    amount: str | None = None
    terminating: bool | None = None


class ExplanationOut(BaseModel):
    """The structured explanation persisted on every decision.

    Constructed from `AdjudicationDecision.explanation` via
    `model_validate(decision.explanation)` — the engine already shapes
    the dict to match. All money fields stay as JSON strings end-to-end
    so `Decimal` round-trip is exact.
    """

    outcome: DecisionOutcome
    charged_amount: str
    payable_amount: str
    member_responsibility: str
    steps: list[ExplanationStepOut]
    narrative: str


class DecisionOut(BaseModel):
    """One `AdjudicationDecision`, including its structured explanation."""

    id: str
    line_item_id: str
    decided_at: datetime
    decided_by: str
    outcome: DecisionOutcome
    payable_amount: Decimal
    member_responsibility: Decimal
    deductible_applied: Decimal
    supersedes_id: str | None
    explanation: ExplanationOut

    @classmethod
    def from_domain(cls, d: AdjudicationDecision) -> Self:
        return cls(
            id=d.id,
            line_item_id=d.line_item_id,
            decided_at=d.decided_at,
            decided_by=d.decided_by,
            outcome=d.outcome,
            payable_amount=d.payable_amount,
            member_responsibility=d.member_responsibility,
            deductible_applied=d.deductible_applied,
            supersedes_id=d.supersedes_id,
            explanation=ExplanationOut.model_validate(d.explanation),
        )


class LineItemOut(BaseModel):
    """One line item with its stored status and the current decision (if any).

    `payable_amount` and `member_responsibility` are populated on the
    line item itself by `repositories._line_item_with_current_decision`
    — they mirror the current decision's amounts. We re-expose them at
    this level (rather than only nested under `current_decision`) so a
    UI rendering the line-item list doesn't have to dig into the
    decision object for every row.

    `current_decision` is `None` only when the line item is still
    `pending` — the startup batch ensures no seeded line item reaches
    the UI in that state, but newly-submitted line items pass through
    `pending` for an instant inside the submit transaction.
    """

    id: str
    claim_id: str
    service_type: str
    service_description: str
    charged_amount: Decimal
    preauth_ref: str | None
    status: LineItemStatus
    payable_amount: Decimal | None
    member_responsibility: Decimal | None
    current_decision: DecisionOut | None

    @classmethod
    def from_domain(
        cls,
        li: LineItem,
        current_decision: AdjudicationDecision | None,
    ) -> Self:
        return cls(
            id=li.id,
            claim_id=li.claim_id,
            service_type=li.service_type,
            service_description=li.service_description,
            charged_amount=li.charged_amount,
            preauth_ref=li.preauth_ref,
            status=li.status,
            payable_amount=li.payable_amount,
            member_responsibility=li.member_responsibility,
            current_decision=(
                DecisionOut.from_domain(current_decision)
                if current_decision is not None
                else None
            ),
        )


class ClaimTotalsOut(BaseModel):
    """Per-claim money rollup of `charged`, `payable`, `member_responsibility`.

    Computed from the line items' current decisions. Pending or
    `needs_review` line items contribute `0` to `payable` and `0` to
    `member_responsibility` (the engine writes those amounts on a
    decision; until then the line item has nothing to attribute).
    """

    charged: Decimal
    payable: Decimal
    member_responsibility: Decimal

    @classmethod
    def from_line_items(cls, line_items: Sequence[LineItem]) -> Self:
        charged = sum(
            (li.charged_amount for li in line_items), start=_ZERO_MONEY
        )
        payable = sum(
            ((li.payable_amount or _ZERO_MONEY) for li in line_items),
            start=_ZERO_MONEY,
        )
        member = sum(
            (
                (li.member_responsibility or _ZERO_MONEY)
                for li in line_items
            ),
            start=_ZERO_MONEY,
        )
        return cls(
            charged=charged, payable=payable, member_responsibility=member
        )


class ClaimSummaryOut(BaseModel):
    """Claim row for the listing view.

    `member_name` is denormalised onto the payload so the list UI
    doesn't need a second round trip to resolve names. `adjudication_state`
    is derived per `docs/domain-model.md` ("Claim lifecycle") from
    `paid_at` + line-item statuses; never stored.
    """

    id: str
    member_id: str
    member_name: str
    provider_name: str
    service_date: date
    submitted_at: datetime
    paid_at: datetime | None
    adjudication_state: ClaimAdjudicationState
    totals: ClaimTotalsOut

    @classmethod
    def from_domain(
        cls,
        claim: Claim,
        member_name: str,
        line_items: Sequence[LineItem],
    ) -> Self:
        return cls(
            id=claim.id,
            member_id=claim.member_id,
            member_name=member_name,
            provider_name=claim.provider_name,
            service_date=claim.service_date,
            submitted_at=claim.submitted_at,
            paid_at=claim.paid_at,
            adjudication_state=derive_claim_state(claim.paid_at, line_items),
            totals=ClaimTotalsOut.from_line_items(line_items),
        )


class AuditEventOut(BaseModel):
    """One audit event as exposed by the embedded timeline and the
    dedicated `GET .../audit` endpoints.
    """

    id: str
    event_type: str
    entity_type: str
    entity_id: str
    actor: str
    occurred_at: datetime
    payload: dict[str, Any]

    @classmethod
    def from_domain(cls, e: AuditEvent) -> Self:
        return cls(
            id=e.id,
            event_type=e.event_type,
            entity_type=e.entity_type,
            entity_id=e.entity_id,
            actor=e.actor,
            occurred_at=e.occurred_at,
            payload=dict(e.payload),
        )


class ClaimDetailOut(ClaimSummaryOut):
    """Drill-down view for one claim.

    Adds `line_items[]` (each carrying its current decision +
    explanation) and `audit_events[]` (merged claim-level +
    line-item-level events in chronological order) on top of the
    summary shape. The merged timeline is what the UI renders as the
    "history" panel without further fetches; the dedicated
    `GET .../audit` endpoints are available when the UI wants to
    refresh only that slice.
    """

    line_items: list[LineItemOut]
    audit_events: list[AuditEventOut]

    @classmethod
    def from_domain(  # type: ignore[override]
        cls,
        claim: Claim,
        member_name: str,
        line_items_with_decisions: Sequence[
            tuple[LineItem, AdjudicationDecision | None]
        ],
        audit_events: Sequence[AuditEvent],
    ) -> Self:
        line_items = [li for li, _ in line_items_with_decisions]
        return cls(
            id=claim.id,
            member_id=claim.member_id,
            member_name=member_name,
            provider_name=claim.provider_name,
            service_date=claim.service_date,
            submitted_at=claim.submitted_at,
            paid_at=claim.paid_at,
            adjudication_state=derive_claim_state(claim.paid_at, line_items),
            totals=ClaimTotalsOut.from_line_items(line_items),
            line_items=[
                LineItemOut.from_domain(li, dec)
                for li, dec in line_items_with_decisions
            ],
            audit_events=[AuditEventOut.from_domain(e) for e in audit_events],
        )


# --- Inputs ----------------------------------------------------------------


class _StrictIn(BaseModel):
    """Base for request bodies: reject unknown fields to fail fast on typos."""

    model_config = ConfigDict(extra="forbid")


class LineItemSubmitIn(_StrictIn):
    """One line item inside a `POST /api/claims` request.

    `charged_amount` is a `Decimal` validated to be non-negative —
    mirrors `LineItem.__post_init__` so callers get a clean 422
    rather than a 500 from the domain invariant. `preauth_ref` is
    optional; the engine's gate phase decides whether it's required
    for the service type.
    """

    service_type: str = Field(min_length=1)
    service_description: str = Field(min_length=1)
    charged_amount: Decimal = Field(ge=Decimal("0"))
    preauth_ref: str | None = None


class DisputeFileIn(_StrictIn):
    """`POST /api/line-items/{id}/dispute` body."""

    reason: str = Field(min_length=1)


class ClaimSubmitIn(_StrictIn):
    """`POST /api/claims` body.

    Server generates claim and line-item ids. `member_id` must
    reference an existing member — the route handler 404s on a miss
    rather than letting the FK constraint surface as a 500. The
    engine handles the "no policy active on service_date" case via
    its eligibility phase, producing a denied decision with a
    structured explanation rather than an error.
    """

    member_id: str = Field(min_length=1)
    provider_name: str = Field(min_length=1)
    service_date: date
    line_items: list[LineItemSubmitIn] = Field(min_length=1)


__all__ = (
    "AuditEventOut",
    "CoverageRuleOut",
    "ClaimDetailOut",
    "ClaimSubmitIn",
    "ClaimSummaryOut",
    "ClaimTotalsOut",
    "DecisionOut",
    "DisputeFileIn",
    "ExplanationOut",
    "ExplanationStepOut",
    "LineItemOut",
    "LineItemSubmitIn",
    "MemberOut",
)
