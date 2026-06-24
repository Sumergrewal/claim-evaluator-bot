"""Build `ClaimDetailOut` for route handlers."""

from __future__ import annotations

from sqlalchemy.orm import Session

from app.api.schemas import ClaimDetailOut
from app.persistence import repositories as repo


def build_claim_detail_out(session: Session, claim_id: str) -> ClaimDetailOut:
    claim = repo.get_claim(session, claim_id)
    if claim is None:
        msg = f"Claim {claim_id!r} not found"
        raise LookupError(msg)

    member = repo.get_member(session, claim.member_id)
    member_name = member.name if member is not None else "(unknown member)"

    line_items = repo.list_line_items_for_claim(session, claim_id)
    line_items_with_decisions = [
        (li, repo.get_current_decision_for_line_item(session, li.id))
        for li in line_items
    ]
    audit_events = repo.list_audit_events_for_claim(session, claim_id)

    return ClaimDetailOut.from_domain(
        claim, member_name, line_items_with_decisions, audit_events
    )
