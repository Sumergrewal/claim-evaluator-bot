"""Adjudication service layer: bridge between the pure engine and the DB.

`adjudicate_line_item(session, line_item_id, *, actor="system")` is the
single entry point the API path (phase 07) and the startup batch
(step 4) both call. The function:

1. Loads the line item, its claim, the member's active policy on the
   claim's `service_date`, and the rules for the line item's
   `service_type`.
2. Computes the two year-to-date accumulators the engine needs
   (`deductible_used_ytd` and `limit_used_ytd`), excluding this line
   item's own history so a re-adjudication doesn't double-count.
3. Calls the pure engine.
4. Inserts a new `AdjudicationDecision` row with `supersedes_id` set
   to the previous current decision (if any).
5. Updates the line item's stored `status` to mirror the new decision.
6. Records one audit event (`line_item.decided`) carrying the
   before/after status, the decision id, and the amounts.
7. Flushes so any subsequent call against the same session — within
   the same claim, or a later claim — sees the new accumulator values
   through the repository queries.

The caller's transaction owns commit/rollback; this function never
commits.
"""

from __future__ import annotations

import logging
import uuid
from datetime import UTC, date, datetime

from sqlalchemy.orm import Session

from app.adjudication.engine import adjudicate
from app.adjudication.types import EngineInput, EngineResult
from app.domain.entities import (
    AdjudicationDecision,
    DecisionOutcome,
    LineItemStatus,
)
from app.persistence import repositories as repo
from app.persistence.audit import record_audit_event
from app.persistence.models import AdjudicationDecisionModel, LineItemModel

logger = logging.getLogger("app.adjudication")

_OUTCOME_TO_STATUS: dict[DecisionOutcome, LineItemStatus] = {
    DecisionOutcome.APPROVED: LineItemStatus.APPROVED,
    DecisionOutcome.DENIED: LineItemStatus.DENIED,
    DecisionOutcome.NEEDS_REVIEW: LineItemStatus.NEEDS_REVIEW,
}


class AdjudicationError(Exception):
    """Raised when `adjudicate_line_item` is called on something it can't handle.

    Examples: the line item doesn't exist, or it isn't `pending` (the
    engine refuses to re-adjudicate already-decided items — those go
    through the human dispute-resolution path).
    """


def adjudicate_line_item(
    session: Session,
    line_item_id: str,
    *,
    actor: str = "system",
    now: datetime | None = None,
    decision_id: str | None = None,
) -> AdjudicationDecision:
    """Adjudicate one pending line item and persist the result.

    Returns the newly-written `AdjudicationDecision`. The caller's
    transaction is responsible for commit.

    Raises:
        AdjudicationError: if the line item doesn't exist or is not in
            the `pending` state.
    """
    li_row = session.get(LineItemModel, line_item_id)
    if li_row is None:
        raise AdjudicationError(f"line item {line_item_id!r} not found")
    if li_row.status is not LineItemStatus.PENDING:
        raise AdjudicationError(
            f"line item {line_item_id!r} is {li_row.status.value!r}, "
            f"not pending; engine only adjudicates pending line items "
            f"(disputes are resolved by reviewers, not the engine)"
        )

    line_item = li_row.to_domain()
    claim = repo.get_claim(session, line_item.claim_id)
    if claim is None:
        raise AdjudicationError(
            f"line item {line_item_id!r} references unknown claim "
            f"{line_item.claim_id!r}"
        )

    policy = repo.get_active_policy_for(
        session, claim.member_id, claim.service_date
    )
    rules = (
        repo.list_rules_for_service(session, policy.id, line_item.service_type)
        if policy is not None
        else []
    )

    period_start = date(claim.service_date.year, 1, 1)
    period_end = date(claim.service_date.year, 12, 31)
    deductible_used = repo.sum_deductible_applied(
        session,
        member_id=claim.member_id,
        period_start=period_start,
        period_end=period_end,
        exclude_line_item_id=line_item_id,
    )
    limit_used = repo.sum_payable_for_accumulator(
        session,
        member_id=claim.member_id,
        service_type=line_item.service_type,
        period_start=period_start,
        period_end=period_end,
        exclude_line_item_id=line_item_id,
    )

    logger.info(
        "adjudicating %s (service=%s charged=%s policy=%s "
        "deductible_used=%s limit_used=%s)",
        line_item_id,
        line_item.service_type,
        line_item.charged_amount,
        policy.id if policy else None,
        deductible_used,
        limit_used,
    )

    result = adjudicate(
        EngineInput(
            line_item=line_item,
            claim=claim,
            policy=policy,
            rules=rules,
            deductible_used_ytd=deductible_used,
            limit_used_ytd=limit_used,
        )
    )

    # Defensive: an engine that didn't run through the normal phases
    # would leave the previous current decision pointing nowhere. We
    # supersede whatever's currently there, if anything.
    previous = repo.get_current_decision_for_line_item(session, line_item_id)
    supersedes_id = previous.id if previous is not None else None

    decision = _build_decision(
        line_item_id=line_item_id,
        result=result,
        actor=actor,
        decided_at=now or _utcnow_naive(),
        decision_id=decision_id or uuid.uuid4().hex,
        supersedes_id=supersedes_id,
    )

    session.add(AdjudicationDecisionModel.from_domain(decision))

    new_status = _OUTCOME_TO_STATUS[result.outcome]
    previous_status = li_row.status
    li_row.status = new_status

    record_audit_event(
        session,
        event_type="line_item.decided",
        entity_type="line_item",
        entity_id=line_item_id,
        actor=actor,
        occurred_at=decision.decided_at,
        payload={
            "decision_id": decision.id,
            "outcome": str(result.outcome),
            "previous_status": str(previous_status),
            "new_status": str(new_status),
            "payable_amount": str(result.payable_amount),
            "member_responsibility": str(result.member_responsibility),
            "deductible_applied": str(result.deductible_applied),
            "supersedes_id": supersedes_id,
        },
    )

    # Flush so the next line item adjudicated in the same session sees
    # the new accumulator values through the repository queries. This
    # is what makes intra-claim accumulator updates work.
    session.flush()

    logger.info(
        "decided %s -> %s (payable=%s member=%s deductible_applied=%s)",
        line_item_id,
        result.outcome,
        result.payable_amount,
        result.member_responsibility,
        result.deductible_applied,
    )
    return decision


def _build_decision(
    *,
    line_item_id: str,
    result: EngineResult,
    actor: str,
    decided_at: datetime,
    decision_id: str,
    supersedes_id: str | None,
) -> AdjudicationDecision:
    return AdjudicationDecision(
        id=decision_id,
        line_item_id=line_item_id,
        decided_at=decided_at,
        decided_by=actor,
        outcome=result.outcome,
        payable_amount=result.payable_amount,
        member_responsibility=result.member_responsibility,
        explanation=result.to_explanation_json(),
        supersedes_id=supersedes_id,
        deductible_applied=result.deductible_applied,
    )


def _utcnow_naive() -> datetime:
    return datetime.now(UTC).replace(tzinfo=None)


__all__ = ("AdjudicationError", "adjudicate_line_item")
