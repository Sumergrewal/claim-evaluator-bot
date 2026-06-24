"""Startup batch: adjudicate every pending line item before serving HTTP.

The seed loader (`app.persistence.seed.seed_if_empty`) plants curated
claims with `paid_at` set on the claim row but their line items
still in `pending`. That's a half-decided state — the claim's
derived status (`app.domain.claim_state.derive_claim_status`)
returns `paid`, but no line item has a decision row yet, so the
amounts the UI shows would be wrong.

`adjudicate_all_pending` closes that gap: it walks every pending
line item in claim-arrival order and calls the same service entry
point the API will eventually use. The lifespan handler in
`app/main.py` invokes this after `seed_if_empty` commits and
*before* uvicorn starts accepting requests, so the intermediate
state never reaches the UI.

Ordering matters: the engine's deductible and limit accumulators
read from already-flushed decisions in the same session. Walking
in `(claim.submitted_at, line_item.id)` order — the same order
the seed YAML lists claims, and the same order claims arrive over
HTTP — means each adjudication sees the chronologically-correct
YTD totals. Out-of-order processing would give the wrong cost
share when one claim consumes deductible that a later claim was
"supposed" to consume first.

Re-runs are safe: the second call finds nothing in `pending`
(every line item was moved to APPROVED/DENIED/NEEDS_REVIEW on the
first run) and returns an empty list — no new decisions, no new
audit events.
"""

from __future__ import annotations

import logging

from sqlalchemy.orm import Session

from app.adjudication.service import adjudicate_line_item
from app.persistence import repositories as repo

logger = logging.getLogger("app.adjudication.startup")


def adjudicate_all_pending(session: Session) -> list[str]:
    """Adjudicate every pending line item in claim-arrival order.

    Returns the list of line item ids that were decided on this
    call (empty list if nothing was pending). The caller owns
    commit/rollback — this function never commits.
    """
    pending_ids = repo.list_pending_line_item_ids(session)
    if not pending_ids:
        logger.info("no pending line items; startup batch is a no-op")
        return []

    logger.info(
        "adjudicating %d pending line item(s) at startup", len(pending_ids)
    )
    decided: list[str] = []
    for line_item_id in pending_ids:
        adjudicate_line_item(session, line_item_id, actor="system")
        decided.append(line_item_id)

    logger.info("startup batch decided %d line item(s)", len(decided))
    return decided


__all__ = ("adjudicate_all_pending",)
