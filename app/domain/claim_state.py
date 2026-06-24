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

    Line-item statuses are evaluated first. `paid_at` elevates the
    claim to `paid` only once adjudication has finished in a
    payable state (`approved` or `partially_approved`). That keeps
    the claim badge consistent with line-item rows — a seeded claim
    with `paid_at` set but line items still `pending` (the brief
    window before the startup adjudication batch) shows `submitted`
    or `under_review`, not `paid`.
    """
    statuses = {li.status for li in line_items}

    if not statuses or statuses == {LineItemStatus.PENDING}:
        base = ClaimAdjudicationState.SUBMITTED
    elif LineItemStatus.PENDING in statuses or LineItemStatus.NEEDS_REVIEW in statuses:
        base = ClaimAdjudicationState.UNDER_REVIEW
    elif statuses == {LineItemStatus.APPROVED}:
        base = ClaimAdjudicationState.APPROVED
    elif statuses == {LineItemStatus.DENIED}:
        base = ClaimAdjudicationState.DENIED
    else:
        base = ClaimAdjudicationState.PARTIALLY_APPROVED

    if paid_at is not None and base in (
        ClaimAdjudicationState.APPROVED,
        ClaimAdjudicationState.PARTIALLY_APPROVED,
    ):
        return ClaimAdjudicationState.PAID

    return base
