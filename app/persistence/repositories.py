"""Functional repositories: SQL → domain objects.

Every function here takes a `Session` and returns domain entities (or
collections of them), never ORM models. Module-level functions, no
classes; the persistence story is small enough that classes would be
ceremony.

What's covered:

- Lookups for members, policies, rules, claims, line items, decisions
  and audit events.
- The accumulator query (`sum_payable_for_accumulator`) — the one
  interesting aggregate the engine needs for limit and deductible
  checks.

What's not (yet):

- Disputes. Repos for them land alongside the dispute flow in
  phase 06/07; nothing in phase 05 reads disputes.
- Write helpers. Callers add ORM rows directly via
  `session.add(Model.from_domain(...))`. The exception is audit
  events, which get their own helper in `audit.py` because the helper
  also constructs the entity (see decisions log sub-decision G).
"""

from __future__ import annotations

from collections.abc import Sequence
from datetime import date
from decimal import Decimal

from sqlalchemy import func, or_, select
from sqlalchemy.orm import Session, aliased

from app.domain.entities import (
    AdjudicationDecision,
    AuditEvent,
    Claim,
    CoverageRule,
    DecisionOutcome,
    LineItem,
    LineItemStatus,
    Member,
    Policy,
)
from app.persistence.models import (
    AdjudicationDecisionModel,
    AuditEventModel,
    ClaimModel,
    CoverageRuleModel,
    LineItemModel,
    MemberModel,
    PolicyModel,
)

# --- Members ---------------------------------------------------------------


def get_member(session: Session, member_id: str) -> Member | None:
    row = session.get(MemberModel, member_id)
    return row.to_domain() if row else None


def list_members(session: Session) -> list[Member]:
    rows = session.scalars(select(MemberModel).order_by(MemberModel.id)).all()
    return [r.to_domain() for r in rows]


# --- Policies & coverage rules --------------------------------------------


def get_policy(session: Session, policy_id: str) -> Policy | None:
    row = session.get(PolicyModel, policy_id)
    return row.to_domain() if row else None


def get_active_policy_for(
    session: Session, member_id: str, on_date: date
) -> Policy | None:
    """The single policy active for `member_id` on `on_date`, or `None`.

    Invariant: at most one policy is active per (member, date). The
    query uses `.one_or_none()` so a violation surfaces as an error
    rather than silently picking one.
    """
    stmt = (
        select(PolicyModel)
        .where(PolicyModel.member_id == member_id)
        .where(PolicyModel.effective_date <= on_date)
        .where(
            or_(
                PolicyModel.termination_date.is_(None),
                PolicyModel.termination_date >= on_date,
            )
        )
    )
    row = session.scalars(stmt).one_or_none()
    return row.to_domain() if row else None


def list_rules_for_policy(
    session: Session, policy_id: str
) -> list[CoverageRule]:
    rows = session.scalars(
        select(CoverageRuleModel)
        .where(CoverageRuleModel.policy_id == policy_id)
        .order_by(CoverageRuleModel.id)
    ).all()
    return [r.to_domain() for r in rows]


def list_rules_for_service(
    session: Session, policy_id: str, service_type: str
) -> list[CoverageRule]:
    """All coverage rules for one `(policy, service_type)`.

    The engine pulls these and groups them into phases by `kind`; the
    repo just hands back the raw set.
    """
    rows = session.scalars(
        select(CoverageRuleModel)
        .where(CoverageRuleModel.policy_id == policy_id)
        .where(CoverageRuleModel.service_type == service_type)
        .order_by(CoverageRuleModel.id)
    ).all()
    return [r.to_domain() for r in rows]


# --- Claims & line items ---------------------------------------------------


def get_claim(session: Session, claim_id: str) -> Claim | None:
    row = session.get(ClaimModel, claim_id)
    return row.to_domain() if row else None


def list_claims(
    session: Session, member_id: str | None = None
) -> list[Claim]:
    stmt = select(ClaimModel).order_by(
        ClaimModel.submitted_at, ClaimModel.id
    )
    if member_id is not None:
        stmt = stmt.where(ClaimModel.member_id == member_id)
    rows = session.scalars(stmt).all()
    return [r.to_domain() for r in rows]


def get_line_item(session: Session, line_item_id: str) -> LineItem | None:
    row = session.get(LineItemModel, line_item_id)
    if row is None:
        return None
    return _line_item_with_current_decision(session, row)


def list_line_items_for_claim(
    session: Session, claim_id: str
) -> list[LineItem]:
    """Line items in submission order with derived amounts populated.

    "Submission order" is the line item insertion order, stable across
    runs via the `id` tiebreak — line item ids in seed/API submission
    are generated in order.
    """
    rows = session.scalars(
        select(LineItemModel)
        .where(LineItemModel.claim_id == claim_id)
        .order_by(LineItemModel.id)
    ).all()
    return [_line_item_with_current_decision(session, r) for r in rows]


def list_pending_line_item_ids(session: Session) -> list[str]:
    """All `pending` line item ids in claim-arrival order.

    Ordering: `(claim.submitted_at, line_item.id)`. The startup batch
    walks them in this order so that within a single member's history
    the engine's accumulators see the chronologically-correct YTD
    totals — a later claim's deductible/limit lookup against this
    same session picks up the earlier flushed decisions.

    The `line_item.id` tiebreak keeps the order stable when two
    claims share a `submitted_at` (currently impossible in seed data,
    but worth pinning).
    """
    rows = session.execute(
        select(LineItemModel.id)
        .join(ClaimModel, ClaimModel.id == LineItemModel.claim_id)
        .where(LineItemModel.status == LineItemStatus.PENDING)
        .order_by(ClaimModel.submitted_at, LineItemModel.id)
    ).all()
    return [r[0] for r in rows]


# --- Adjudication decisions ------------------------------------------------


def get_current_decision_for_line_item(
    session: Session, line_item_id: str
) -> AdjudicationDecision | None:
    """The non-superseded decision for `line_item_id`, if any.

    "Current" = no other row's `supersedes_id` points at this row.
    """
    superseder = aliased(AdjudicationDecisionModel)
    stmt = (
        select(AdjudicationDecisionModel)
        .outerjoin(
            superseder,
            superseder.supersedes_id == AdjudicationDecisionModel.id,
        )
        .where(AdjudicationDecisionModel.line_item_id == line_item_id)
        .where(superseder.id.is_(None))
    )
    row = session.scalars(stmt).one_or_none()
    return row.to_domain() if row else None


def list_decisions_for_line_item(
    session: Session, line_item_id: str
) -> list[AdjudicationDecision]:
    """Full history for a line item, oldest first."""
    rows = session.scalars(
        select(AdjudicationDecisionModel)
        .where(AdjudicationDecisionModel.line_item_id == line_item_id)
        .order_by(AdjudicationDecisionModel.decided_at)
    ).all()
    return [r.to_domain() for r in rows]


# --- Accumulator -----------------------------------------------------------


def sum_payable_for_accumulator(
    session: Session,
    *,
    member_id: str,
    service_type: str,
    period_start: date,
    period_end: date,
    exclude_line_item_id: str | None = None,
) -> Decimal:
    """Sum of `payable_amount` over current approved decisions for the
    `(member, service_type)` pair whose claim's `service_date` falls
    in `[period_start, period_end]`.

    Used by the engine's limit and deductible phases. `exclude_line_item_id`
    is for the line item currently being adjudicated — we don't count
    its own historical decisions toward "what's been spent so far,"
    since a re-adjudication should always be measured against
    everything *else* counted.

    Intra-claim ordering is handled by the engine flushing each
    decision before adjudicating the next line item; this query sees
    pending writes through the same session.
    """
    superseder = aliased(AdjudicationDecisionModel)
    stmt = (
        select(
            func.coalesce(
                func.sum(AdjudicationDecisionModel.payable_amount), 0
            )
        )
        .join(
            LineItemModel,
            LineItemModel.id == AdjudicationDecisionModel.line_item_id,
        )
        .join(ClaimModel, ClaimModel.id == LineItemModel.claim_id)
        .outerjoin(
            superseder,
            superseder.supersedes_id == AdjudicationDecisionModel.id,
        )
        .where(superseder.id.is_(None))
        .where(AdjudicationDecisionModel.outcome == DecisionOutcome.APPROVED)
        .where(ClaimModel.member_id == member_id)
        .where(LineItemModel.service_type == service_type)
        .where(ClaimModel.service_date >= period_start)
        .where(ClaimModel.service_date <= period_end)
    )
    if exclude_line_item_id is not None:
        stmt = stmt.where(LineItemModel.id != exclude_line_item_id)

    result = session.scalar(stmt)
    return Decimal(result) if result is not None else Decimal("0")


def sum_deductible_applied(
    session: Session,
    *,
    member_id: str,
    period_start: date,
    period_end: date,
    exclude_line_item_id: str | None = None,
) -> Decimal:
    """Sum of `deductible_applied` over current approved decisions for
    `member_id` whose claim's `service_date` falls in
    `[period_start, period_end]`.

    The deductible accumulator is *member-scoped* and *cross-service-type*
    (the limit accumulator is service-type-scoped). Same supersession
    and exclude-line-item rules as `sum_payable_for_accumulator`. See
    the 2026-06-24 phase-06 entry in `docs/decisions.md` for the
    rationale for storing this as a column rather than parsing prior
    decisions' explanation JSON.
    """
    superseder = aliased(AdjudicationDecisionModel)
    stmt = (
        select(
            func.coalesce(
                func.sum(AdjudicationDecisionModel.deductible_applied), 0
            )
        )
        .join(
            LineItemModel,
            LineItemModel.id == AdjudicationDecisionModel.line_item_id,
        )
        .join(ClaimModel, ClaimModel.id == LineItemModel.claim_id)
        .outerjoin(
            superseder,
            superseder.supersedes_id == AdjudicationDecisionModel.id,
        )
        .where(superseder.id.is_(None))
        .where(AdjudicationDecisionModel.outcome == DecisionOutcome.APPROVED)
        .where(ClaimModel.member_id == member_id)
        .where(ClaimModel.service_date >= period_start)
        .where(ClaimModel.service_date <= period_end)
    )
    if exclude_line_item_id is not None:
        stmt = stmt.where(LineItemModel.id != exclude_line_item_id)

    result = session.scalar(stmt)
    return Decimal(result) if result is not None else Decimal("0")


# --- Audit events ----------------------------------------------------------


def list_audit_events_for(
    session: Session, entity_type: str, entity_id: str
) -> list[AuditEvent]:
    """All audit events for one (entity_type, entity_id), oldest first."""
    rows = session.scalars(
        select(AuditEventModel)
        .where(AuditEventModel.entity_type == entity_type)
        .where(AuditEventModel.entity_id == entity_id)
        .order_by(AuditEventModel.occurred_at, AuditEventModel.id)
    ).all()
    return [r.to_domain() for r in rows]


# --- Internals -------------------------------------------------------------


def _line_item_with_current_decision(
    session: Session, row: LineItemModel
) -> LineItem:
    """Translate a line-item row to its domain entity, filling derived
    amounts from the current decision when one exists.
    """
    current = get_current_decision_for_line_item(session, row.id)
    if current is None:
        return row.to_domain()
    return row.to_domain(
        payable_amount=current.payable_amount,
        member_responsibility=current.member_responsibility,
    )


__all__: Sequence[str] = (
    "get_member",
    "list_members",
    "get_policy",
    "get_active_policy_for",
    "list_rules_for_policy",
    "list_rules_for_service",
    "get_claim",
    "list_claims",
    "get_line_item",
    "list_line_items_for_claim",
    "list_pending_line_item_ids",
    "get_current_decision_for_line_item",
    "list_decisions_for_line_item",
    "sum_payable_for_accumulator",
    "sum_deductible_applied",
    "list_audit_events_for",
)
