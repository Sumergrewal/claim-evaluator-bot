"""HTTP route for filing a member dispute on a line item."""

from __future__ import annotations

import logging
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from app.api.claim_detail import build_claim_detail_out
from app.api.schemas import ClaimDetailOut, DisputeFileIn
from app.disputes.service import DisputeError, file_dispute
from app.persistence.database import get_session

logger = logging.getLogger("app.api.disputes")

router = APIRouter(prefix="/api/line-items", tags=["disputes"])

SessionDep = Annotated[Session, Depends(get_session)]


@router.post("/{line_item_id}/dispute", response_model=ClaimDetailOut)
def submit_dispute(
    line_item_id: str,
    body: DisputeFileIn,
    session: SessionDep,
) -> ClaimDetailOut:
    """File a dispute; returns the parent claim drill-down refreshed."""
    try:
        claim_id = file_dispute(session, line_item_id, body.reason)
    except DisputeError as exc:
        message = str(exc)
        if "not found" in message:
            raise HTTPException(status_code=404, detail=message) from exc
        if "already has an open dispute" in message:
            raise HTTPException(status_code=409, detail=message) from exc
        raise HTTPException(status_code=400, detail=message) from exc

    logger.info(
        "POST /api/line-items/%s/dispute -> claim %s",
        line_item_id,
        claim_id,
    )
    return build_claim_detail_out(session, claim_id)


__all__ = ("router",)
