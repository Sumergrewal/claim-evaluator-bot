"""HTTP routes for members.

The take-home spec is explicit that member account management is out
of scope — there is no create/update/delete here. The single
read-only `GET /api/members` exists because the frontend (phase 08)
needs a list of members to populate the claim-list filter dropdown
and the submit-claim form's member picker. Same reason `member_name`
is denormalised onto `ClaimSummaryOut` / `ClaimDetailOut`.
"""

from __future__ import annotations

import logging
from typing import Annotated

from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from app.api.schemas import MemberOut
from app.persistence import repositories as repo
from app.persistence.database import get_session

logger = logging.getLogger("app.api.members")

router = APIRouter(prefix="/api/members", tags=["members"])

SessionDep = Annotated[Session, Depends(get_session)]


@router.get("", response_model=list[MemberOut])
def list_members(session: SessionDep) -> list[MemberOut]:
    """All members, ordered by id."""
    members = repo.list_members(session)
    logger.info("GET /api/members -> %d members", len(members))
    return [MemberOut.from_domain(m) for m in members]


__all__ = ("router",)
