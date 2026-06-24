"""Derive a claim's adjudication state from its line items and `paid_at`.

Pure domain logic — no DB, no HTTP. Lives next to `entities.py` because
the rule it implements is part of the domain (see the claim lifecycle
in `docs/domain-model.md`). The persistence layer calls this after
loading a claim's line items; the API serialises the result.

Per `docs/decisions.md`, claim adjudication state is never stored
(only `paid_at` is); recomputing it from line items is the source of
truth.
"""

from __future__ import annotations

from collections.abc import Sequence
from datetime import datetime
from enum import StrEnum

from app.domain.entities import LineItem, LineItemStatus


class ClaimAdjudicationState(StrEnum):
    """Derived state of a claim. Never stored; always recomputed."""

    SUBMITTED = "submitted"
    UNDER_REVIEW = "under_review"
    APPROVED = "approved"
    DENIED = "denied"
    PARTIALLY_APPROVED = "partially_approved"
    PAID = "paid"


def derive_claim_state(
    paid_at: datetime | None,
    line_items: Sequence[LineItem],
) -> ClaimAdjudicationState:
    """Return the claim's current adjudication state.

    Order of checks matches `docs/domain-model.md`:

    1. `paid_at` set → `paid` (precondition: only set when state was
       already `approved` or `partially_approved`).
    2. No line items, or all line items still `pending` → `submitted`.
    3. Any line item `pending` or `needs_review` → `under_review`.
    4. All `approved` → `approved`; all `denied` → `denied`;
       otherwise (mix of approved + denied) → `partially_approved`.

    NOTE (seed/engine ordering): the `paid_at` short-circuit means a
    seeded claim with `paid_at` set will derive as `paid` even before
    the engine has produced decisions for its line items. The engine
    (phase 06) runs on startup right after the seed loader, so the
    intermediate state — claim labelled `paid` while line items are
    still `pending` — is not observable through the UI. Anyone
    inspecting the DB between seed-load and engine-run will see it.
    """
    if paid_at is not None:
        return ClaimAdjudicationState.PAID

    statuses = {li.status for li in line_items}

    if not statuses or statuses == {LineItemStatus.PENDING}:
        return ClaimAdjudicationState.SUBMITTED

    if LineItemStatus.PENDING in statuses or LineItemStatus.NEEDS_REVIEW in statuses:
        return ClaimAdjudicationState.UNDER_REVIEW

    if statuses == {LineItemStatus.APPROVED}:
        return ClaimAdjudicationState.APPROVED

    if statuses == {LineItemStatus.DENIED}:
        return ClaimAdjudicationState.DENIED

    return ClaimAdjudicationState.PARTIALLY_APPROVED
