"""File a member dispute against a decided line item.

Resolution by a human reviewer is out of scope for this build — filing
records the dispute, moves the line item to `needs_review`, and writes
audit events. The existing `AdjudicationDecision` row is left in place.
"""

from __future__ import annotations

import logging
import uuid
from datetime import UTC, datetime

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.domain.entities import Dispute, DisputeStatus, LineItemStatus
from app.persistence import repositories as repo
from app.persistence.audit import record_audit_event
from app.persistence.models import DisputeModel, LineItemModel

logger = logging.getLogger("app.disputes")

_DISPUTABLE = frozenset({LineItemStatus.APPROVED, LineItemStatus.DENIED})


class DisputeError(Exception):
    """Raised when a dispute cannot be filed for the given line item."""


def file_dispute(
    session: Session,
    line_item_id: str,
    reason: str,
    *,
    now: datetime | None = None,
) -> str:
    """File an open dispute and return the parent claim id.

    Raises:
        DisputeError: unknown line item, non-disputable status, or an
            open dispute already exists on this line item.
    """
    row = session.get(LineItemModel, line_item_id)
    if row is None:
        raise DisputeError(f"line item {line_item_id!r} not found")

    existing = session.scalar(
        select(DisputeModel.id)
        .where(DisputeModel.line_item_id == line_item_id)
        .where(DisputeModel.status == DisputeStatus.OPEN)
        .limit(1)
    )
    if existing is not None:
        raise DisputeError(
            f"line item {line_item_id!r} already has an open dispute"
        )

    if row.status not in _DISPUTABLE:
        raise DisputeError(
            f"line item {line_item_id!r} is {row.status.value!r}; "
            f"only approved or denied line items can be disputed"
        )

    filed_at = now or datetime.now(UTC).replace(tzinfo=None)
    dispute_id = f"D-{uuid.uuid4().hex}"
    previous_status = row.status.value

    dispute = Dispute(
        id=dispute_id,
        line_item_id=line_item_id,
        filed_at=filed_at,
        reason=reason,
        status=DisputeStatus.OPEN,
    )
    session.add(DisputeModel.from_domain(dispute))

    row.status = LineItemStatus.NEEDS_REVIEW

    record_audit_event(
        session,
        event_type="dispute.filed",
        entity_type="dispute",
        entity_id=dispute_id,
        actor="member",
        payload={
            "line_item_id": line_item_id,
            "claim_id": row.claim_id,
            "reason": reason,
            "previous_line_item_status": previous_status,
        },
        occurred_at=filed_at,
    )
    record_audit_event(
        session,
        event_type="line_item.state_changed",
        entity_type="line_item",
        entity_id=line_item_id,
        actor="member",
        payload={
            "previous_status": previous_status,
            "new_status": LineItemStatus.NEEDS_REVIEW.value,
            "dispute_id": dispute_id,
        },
        occurred_at=filed_at,
    )

    claim = repo.get_claim(session, row.claim_id)
    if claim is None:
        raise DisputeError(
            f"line item {line_item_id!r} references unknown claim "
            f"{row.claim_id!r}"
        )

    logger.info(
        "filed dispute %s on line item %s (claim %s)",
        dispute_id,
        line_item_id,
        row.claim_id,
    )
    session.flush()
    return claim.id
