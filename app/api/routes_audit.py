"""HTTP routes for audit-event history.

Two read-only endpoints that expose the same `AuditEventOut` shape
already embedded on `ClaimDetailOut.audit_events`, but as a narrow
slice the UI can refresh without re-fetching the full drill-down:

- `GET /api/claims/{claim_id}/audit` — merged timeline for the claim
  and every line item under it (`list_audit_events_for_claim`).
- `GET /api/line-items/{line_item_id}/audit` — events scoped to one
  line item (`list_audit_events_for` with `entity_type='line_item'`).

Both return 404 when the parent entity doesn't exist. An empty list
is never returned for a missing id — that would be indistinguishable
from "entity exists but nothing happened yet," which isn't a case we
have today (every adjudicated line item gets a `line_item.decided`
event; POST always writes `claim.submitted`).

Ordering is always `(occurred_at, id)` ascending, matching the repo
helpers and the embedded timeline on the claim detail view.
"""

from __future__ import annotations

import logging
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from app.api.schemas import AuditEventOut
from app.persistence import repositories as repo
from app.persistence.database import get_session

logger = logging.getLogger("app.api.audit")

router = APIRouter(tags=["audit"])

SessionDep = Annotated[Session, Depends(get_session)]


@router.get("/api/claims/{claim_id}/audit", response_model=list[AuditEventOut])
def get_claim_audit(claim_id: str, session: SessionDep) -> list[AuditEventOut]:
    """Chronological audit timeline for a claim and its line items."""
    if repo.get_claim(session, claim_id) is None:
        raise HTTPException(
            status_code=404, detail=f"Claim {claim_id!r} not found"
        )

    events = repo.list_audit_events_for_claim(session, claim_id)
    logger.info(
        "GET /api/claims/%s/audit -> %d event(s)", claim_id, len(events)
    )
    return [AuditEventOut.from_domain(e) for e in events]


@router.get(
    "/api/line-items/{line_item_id}/audit", response_model=list[AuditEventOut]
)
def get_line_item_audit(
    line_item_id: str, session: SessionDep
) -> list[AuditEventOut]:
    """Chronological audit timeline for one line item."""
    if repo.get_line_item(session, line_item_id) is None:
        raise HTTPException(
            status_code=404, detail=f"Line item {line_item_id!r} not found"
        )

    events = repo.list_audit_events_for(session, "line_item", line_item_id)
    logger.info(
        "GET /api/line-items/%s/audit -> %d event(s)",
        line_item_id,
        len(events),
    )
    return [AuditEventOut.from_domain(e) for e in events]


__all__ = ("router",)
