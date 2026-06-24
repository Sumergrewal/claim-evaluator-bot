"""HTTP routes for claims.

Three endpoints, all under `/api/claims`:

- `GET /api/claims` — list every claim, optionally filtered by
  `member_id`. Each row carries the derived `adjudication_state` and
  a money rollup so the list view renders without further fetches.
- `GET /api/claims/{claim_id}` — drill-down for one claim: line
  items + each line item's current `AdjudicationDecision` (with the
  structured explanation) + an embedded audit-event timeline that
  merges claim-level events with line-item-level events in
  chronological order.
- `POST /api/claims` — submit a new claim. Server generates the ids,
  inserts the claim + its line items as `pending`, records a
  `claim.submitted` audit event, then walks `adjudicate_line_item`
  over each line item in submission order. The response is the same
  `ClaimDetailOut` shape `GET /api/claims/{claim_id}` returns so the
  decisions and explanations are already on the wire.

Member-name resolution on the list endpoint pulls the members table
once into a dict keyed by id so the per-claim lookup is O(1) — small
data, but writing this as N+1 would still be wrong.

Unknown member ids on `?member_id=` (filter) and `body.member_id`
(submit) return 404 with the offending id in the detail. The
alternative — empty list / FK IntegrityError — hides typos and
surfaces as a 500.

Server-generated ids share a suffix per claim:
`C-<uuid hex>` / `L-<uuid hex>-001` / `L-<uuid hex>-002` / .... The
`-NNN` tail makes the line-item ids sort in submission order so
`list_line_items_for_claim` (which orders by `LineItem.id`) returns
them the same way the client sent them — both for the immediate POST
response and for any later GET.

Transactionality: the per-request session set up in
`app/persistence/database.py` commits on clean return and rolls back
on any exception, so the claim row, its line items, the
`claim.submitted` audit event, and every `line_item.decided` event
written by `adjudicate_line_item` either all land or none do. The
audit timeline reads through the same session, which is why the
response carries everything written above.
"""

from __future__ import annotations

import logging
import uuid
from datetime import UTC, datetime
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.orm import Session

from app.adjudication.service import adjudicate_line_item
from app.api.schemas import ClaimDetailOut, ClaimSubmitIn, ClaimSummaryOut
from app.domain.entities import Claim, LineItem, LineItemStatus
from app.persistence import repositories as repo
from app.persistence.audit import record_audit_event
from app.persistence.database import get_session
from app.persistence.models import ClaimModel, LineItemModel

logger = logging.getLogger("app.api.claims")

router = APIRouter(prefix="/api/claims", tags=["claims"])

SessionDep = Annotated[Session, Depends(get_session)]


@router.get("", response_model=list[ClaimSummaryOut])
def list_claims(
    session: SessionDep,
    member_id: Annotated[
        str | None,
        Query(description="Filter to claims submitted by this member id"),
    ] = None,
) -> list[ClaimSummaryOut]:
    """All claims, oldest-submitted first; optionally filtered by member."""
    if member_id is not None and repo.get_member(session, member_id) is None:
        raise HTTPException(
            status_code=404, detail=f"Member {member_id!r} not found"
        )

    claims = repo.list_claims(session, member_id=member_id)
    member_by_id = {m.id: m for m in repo.list_members(session)}

    out: list[ClaimSummaryOut] = []
    for claim in claims:
        member = member_by_id.get(claim.member_id)
        member_name = member.name if member is not None else "(unknown member)"
        line_items = repo.list_line_items_for_claim(session, claim.id)
        out.append(
            ClaimSummaryOut.from_domain(claim, member_name, line_items)
        )

    logger.info(
        "GET /api/claims%s -> %d claim(s)",
        f"?member_id={member_id}" if member_id is not None else "",
        len(out),
    )
    return out


@router.get("/{claim_id}", response_model=ClaimDetailOut)
def get_claim(claim_id: str, session: SessionDep) -> ClaimDetailOut:
    """One claim with its line items, current decisions, and audit timeline."""
    claim = repo.get_claim(session, claim_id)
    if claim is None:
        raise HTTPException(
            status_code=404, detail=f"Claim {claim_id!r} not found"
        )

    member = repo.get_member(session, claim.member_id)
    member_name = member.name if member is not None else "(unknown member)"

    line_items = repo.list_line_items_for_claim(session, claim_id)
    line_items_with_decisions = [
        (li, repo.get_current_decision_for_line_item(session, li.id))
        for li in line_items
    ]
    audit_events = repo.list_audit_events_for_claim(session, claim_id)

    logger.info(
        "GET /api/claims/%s -> %d line item(s), %d audit event(s)",
        claim_id,
        len(line_items),
        len(audit_events),
    )
    return ClaimDetailOut.from_domain(
        claim, member_name, line_items_with_decisions, audit_events
    )


@router.post("", response_model=ClaimDetailOut, status_code=201)
def submit_claim(body: ClaimSubmitIn, session: SessionDep) -> ClaimDetailOut:
    """Submit a new claim and return its adjudicated drill-down.

    Member must exist; an unknown id is a 404 rather than letting the
    FK constraint surface as a 500. Eligibility (no policy active on
    `service_date`) is *not* a 4xx — the engine handles that case in
    its eligibility phase and returns a `denied` decision with a
    structured explanation, so callers always see a consistent shape
    for "submitted but won't be paid."

    Actor is `member` for the `claim.submitted` event (the submission
    is a member-originated action) and `system` for each
    `line_item.decided` event the engine writes (the existing
    contract from `adjudicate_line_item`).
    """
    member = repo.get_member(session, body.member_id)
    if member is None:
        raise HTTPException(
            status_code=404, detail=f"Member {body.member_id!r} not found"
        )

    submitted_at = datetime.now(UTC).replace(tzinfo=None)
    suffix = uuid.uuid4().hex
    claim_id = f"C-{suffix}"

    session.add(
        ClaimModel.from_domain(
            Claim(
                id=claim_id,
                member_id=body.member_id,
                provider_name=body.provider_name,
                service_date=body.service_date,
                submitted_at=submitted_at,
                paid_at=None,
            )
        )
    )

    line_item_ids: list[str] = []
    for idx, params in enumerate(body.line_items, start=1):
        line_item_id = f"L-{suffix}-{idx:03d}"
        line_item_ids.append(line_item_id)
        session.add(
            LineItemModel.from_domain(
                LineItem(
                    id=line_item_id,
                    claim_id=claim_id,
                    service_type=params.service_type,
                    service_description=params.service_description,
                    charged_amount=params.charged_amount,
                    preauth_ref=params.preauth_ref,
                    status=LineItemStatus.PENDING,
                )
            )
        )

    # `adjudicate_line_item` looks the line item up via `session.get(...)`,
    # which doesn't see pending (un-flushed) instances. Flush here so the
    # adjudication loop and the post-loop response reads find them.
    session.flush()

    record_audit_event(
        session,
        event_type="claim.submitted",
        entity_type="claim",
        entity_id=claim_id,
        actor="member",
        occurred_at=submitted_at,
        payload={
            "member_id": body.member_id,
            "provider_name": body.provider_name,
            "service_date": body.service_date.isoformat(),
            "line_item_count": len(line_item_ids),
        },
    )

    for line_item_id in line_item_ids:
        adjudicate_line_item(session, line_item_id, actor="system")

    persisted_claim = repo.get_claim(session, claim_id)
    if persisted_claim is None:
        raise RuntimeError(
            f"Claim {claim_id!r} disappeared from the session mid-request"
        )
    line_items = repo.list_line_items_for_claim(session, claim_id)
    pairs = [
        (li, repo.get_current_decision_for_line_item(session, li.id))
        for li in line_items
    ]
    audit_events = repo.list_audit_events_for_claim(session, claim_id)

    logger.info(
        "POST /api/claims -> %s (member=%s, %d line item(s) adjudicated)",
        claim_id,
        body.member_id,
        len(line_item_ids),
    )
    return ClaimDetailOut.from_domain(
        persisted_claim, member.name, pairs, audit_events
    )


__all__ = ("router",)
