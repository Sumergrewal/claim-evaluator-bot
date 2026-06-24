"""Domain entities for the claims-processing system.

Pure-Python frozen dataclasses and the enums they use. No SQLAlchemy,
no FastAPI, no I/O of any kind — the adjudication engine and tests
operate on these objects directly; the persistence layer translates
them to and from ORM models at the boundary.

The shapes here mirror `docs/domain-model.md`. Invariants validated in
`__post_init__` are the ones that can be checked from a single entity
without crossing entity boundaries (cross-entity invariants, like a
claim's service_date falling inside its policy's coverage window, live
at the service layer where both entities are in hand).

Datetime convention: all `datetime` fields are **naive UTC**. SQLite's
default `DateTime` column strips `tzinfo` on round-trip, so domain
construction sites use `datetime.utcnow()` (or equivalent) and treat
the values as UTC throughout. No mixed naive/aware datetimes.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date, datetime
from decimal import Decimal
from enum import StrEnum
from typing import Any


class LineItemStatus(StrEnum):
    """Stored status of a `LineItem`; mirrors the outcome of its current decision."""

    PENDING = "pending"
    APPROVED = "approved"
    DENIED = "denied"
    NEEDS_REVIEW = "needs_review"


class DecisionOutcome(StrEnum):
    """Outcome recorded on an `AdjudicationDecision`."""

    APPROVED = "approved"
    DENIED = "denied"
    NEEDS_REVIEW = "needs_review"


class RuleKind(StrEnum):
    """The catalogue of coverage-rule kinds the engine understands.

    Parameter shapes per kind are documented in `docs/domain-model.md`
    and enforced at the seed-loader boundary by Pydantic models. The
    engine assumes parameters are valid by the time they reach it.
    """

    SERVICE_COVERED = "service_covered"
    SERVICE_EXCLUDED = "service_excluded"
    PREAUTH_REQUIRED = "preauth_required"
    ANNUAL_LIMIT = "annual_limit"
    COPAY = "copay"
    COINSURANCE = "coinsurance"


class DisputeStatus(StrEnum):
    """Lifecycle state of a `Dispute`."""

    OPEN = "open"
    RESOLVED = "resolved"


@dataclass(frozen=True, slots=True)
class Member:
    id: str
    name: str


@dataclass(frozen=True, slots=True)
class Policy:
    id: str
    member_id: str
    name: str
    effective_date: date
    termination_date: date | None
    annual_deductible: Decimal

    def __post_init__(self) -> None:
        if (
            self.termination_date is not None
            and self.effective_date > self.termination_date
        ):
            raise ValueError(
                f"Policy {self.id}: effective_date {self.effective_date} "
                f"is after termination_date {self.termination_date}"
            )
        if self.annual_deductible < 0:
            raise ValueError(
                f"Policy {self.id}: annual_deductible must be non-negative "
                f"(got {self.annual_deductible})"
            )


@dataclass(frozen=True, slots=True)
class CoverageRule:
    """One composable rule about a (policy, service_type).

    `parameters` is a JSON-shaped dict whose schema depends on `kind`.
    Validation happens at the seed-loader boundary; downstream code
    trusts the shape.
    """

    id: str
    policy_id: str
    service_type: str
    kind: RuleKind
    parameters: dict[str, Any]


@dataclass(frozen=True, slots=True)
class Claim:
    id: str
    member_id: str
    provider_name: str
    service_date: date
    submitted_at: datetime
    paid_at: datetime | None


@dataclass(frozen=True, slots=True)
class LineItem:
    """One billable service inside a claim — the unit of adjudication.

    `status` is stored on the row and mirrors the current decision's
    outcome. `payable_amount` and `member_responsibility` are derived
    from the current `AdjudicationDecision` and populated by the
    persistence layer when a current decision exists; both are `None`
    when the line item has not been adjudicated yet.
    """

    id: str
    claim_id: str
    service_type: str
    service_description: str
    charged_amount: Decimal
    preauth_ref: str | None
    status: LineItemStatus
    payable_amount: Decimal | None = None
    member_responsibility: Decimal | None = None

    def __post_init__(self) -> None:
        if self.charged_amount < 0:
            raise ValueError(
                f"LineItem {self.id}: charged_amount must be non-negative "
                f"(got {self.charged_amount})"
            )
        # Derived amounts are populated together or not at all.
        if (self.payable_amount is None) != (self.member_responsibility is None):
            raise ValueError(
                f"LineItem {self.id}: payable_amount and member_responsibility "
                "must both be set or both be None"
            )
        if (
            self.payable_amount is not None
            and self.member_responsibility is not None
            and self.payable_amount + self.member_responsibility != self.charged_amount
        ):
            raise ValueError(
                f"LineItem {self.id}: payable_amount + member_responsibility "
                f"({self.payable_amount + self.member_responsibility}) "
                f"must equal charged_amount ({self.charged_amount})"
            )


@dataclass(frozen=True, slots=True)
class AdjudicationDecision:
    """One immutable record of an adjudication pass on a line item.

    Re-decisions (manual override, dispute resolution) are written as
    new rows whose `supersedes_id` points at the previous current row.
    See `docs/decisions.md` for why decisions are append-only.

    `deductible_applied` is the amount this decision contributed to
    the member's annual deductible — the `deductible_taken` term from
    the cost-sharing math. Stored explicitly so the cross-service-type
    deductible accumulator query is a straight SQL sum rather than
    parsing prior decisions' explanation JSON (see the 2026-06-24
    phase-06 entry in `docs/decisions.md`).
    """

    id: str
    line_item_id: str
    decided_at: datetime
    decided_by: str
    outcome: DecisionOutcome
    payable_amount: Decimal
    member_responsibility: Decimal
    explanation: dict[str, Any]
    supersedes_id: str | None = None
    deductible_applied: Decimal = Decimal("0.00")

    def __post_init__(self) -> None:
        if self.payable_amount < 0:
            raise ValueError(
                f"AdjudicationDecision {self.id}: payable_amount must be "
                f"non-negative (got {self.payable_amount})"
            )
        if self.member_responsibility < 0:
            raise ValueError(
                f"AdjudicationDecision {self.id}: member_responsibility must "
                f"be non-negative (got {self.member_responsibility})"
            )
        if self.deductible_applied < 0:
            raise ValueError(
                f"AdjudicationDecision {self.id}: deductible_applied must be "
                f"non-negative (got {self.deductible_applied})"
            )


@dataclass(frozen=True, slots=True)
class Dispute:
    id: str
    line_item_id: str
    filed_at: datetime
    reason: str
    status: DisputeStatus
    resolution_note: str | None = None
    resolved_at: datetime | None = None

    def __post_init__(self) -> None:
        if self.status is DisputeStatus.RESOLVED:
            if self.resolved_at is None:
                raise ValueError(
                    f"Dispute {self.id}: resolved status requires resolved_at"
                )
        else:
            if self.resolved_at is not None or self.resolution_note is not None:
                raise ValueError(
                    f"Dispute {self.id}: only resolved disputes carry "
                    "resolved_at or resolution_note"
                )


@dataclass(frozen=True, slots=True)
class AuditEvent:
    """Append-only log entry. Never updated, never deleted."""

    id: str
    event_type: str
    entity_type: str
    entity_id: str
    actor: str
    occurred_at: datetime
    payload: dict[str, Any]
