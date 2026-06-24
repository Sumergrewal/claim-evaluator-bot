"""Read-only coverage-rule catalog for UI tooltips."""

from __future__ import annotations

import logging
from typing import Annotated

from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from app.api.schemas import CoverageRuleOut
from app.persistence import repositories as repo
from app.persistence.database import get_session

logger = logging.getLogger("app.api.coverage_rules")

router = APIRouter(prefix="/api/coverage-rules", tags=["coverage-rules"])

SessionDep = Annotated[Session, Depends(get_session)]


@router.get("", response_model=list[CoverageRuleOut])
def list_coverage_rules(session: SessionDep) -> list[CoverageRuleOut]:
    """All coverage rules with human-readable descriptions for tooltips."""
    rows = repo.list_coverage_rules(session)
    out = [
        CoverageRuleOut.from_domain(rule, policy_name) for rule, policy_name in rows
    ]
    logger.info("GET /api/coverage-rules -> %d rule(s)", len(out))
    return out


__all__ = ("router",)
