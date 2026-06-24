"""Tests for `derive_claim_state` — pure function, no DB, no HTTP."""

from __future__ import annotations

from datetime import datetime
from decimal import Decimal

from app.domain.claim_state import ClaimAdjudicationState, derive_claim_state
from app.domain.entities import LineItem, LineItemStatus


def _li(
    status: LineItemStatus,
    payable: Decimal | None = None,
    member: Decimal | None = None,
) -> LineItem:
    return LineItem(
        id="x",
        claim_id="c",
        service_type="t",
        service_description="d",
        charged_amount=Decimal("100.00"),
        preauth_ref=None,
        status=status,
        payable_amount=payable,
        member_responsibility=member,
    )


_APPROVED = _li(LineItemStatus.APPROVED, Decimal("100.00"), Decimal("0.00"))
_DENIED = _li(LineItemStatus.DENIED, Decimal("0.00"), Decimal("100.00"))
_PENDING = _li(LineItemStatus.PENDING)
_NEEDS_REVIEW = _li(LineItemStatus.NEEDS_REVIEW)


def test_paid_at_with_pending_line_items_does_not_return_paid() -> None:
    state = derive_claim_state(datetime(2026, 1, 1), [_PENDING])
    assert state is ClaimAdjudicationState.SUBMITTED


def test_paid_at_with_all_approved_returns_paid() -> None:
    state = derive_claim_state(datetime(2026, 1, 1), [_APPROVED])
    assert state is ClaimAdjudicationState.PAID


def test_paid_at_with_partially_approved_mix_returns_paid() -> None:
    state = derive_claim_state(datetime(2026, 1, 1), [_APPROVED, _DENIED])
    assert state is ClaimAdjudicationState.PAID


def test_empty_line_items_returns_submitted() -> None:
    assert derive_claim_state(None, []) is ClaimAdjudicationState.SUBMITTED


def test_all_pending_returns_submitted() -> None:
    state = derive_claim_state(None, [_PENDING, _PENDING])
    assert state is ClaimAdjudicationState.SUBMITTED


def test_any_pending_alongside_decisions_returns_under_review() -> None:
    state = derive_claim_state(None, [_APPROVED, _PENDING])
    assert state is ClaimAdjudicationState.UNDER_REVIEW


def test_needs_review_present_returns_under_review() -> None:
    state = derive_claim_state(None, [_APPROVED, _NEEDS_REVIEW])
    assert state is ClaimAdjudicationState.UNDER_REVIEW


def test_all_approved_returns_approved() -> None:
    state = derive_claim_state(None, [_APPROVED, _APPROVED])
    assert state is ClaimAdjudicationState.APPROVED


def test_all_denied_returns_denied() -> None:
    state = derive_claim_state(None, [_DENIED, _DENIED])
    assert state is ClaimAdjudicationState.DENIED


def test_mix_of_approved_and_denied_returns_partially_approved() -> None:
    state = derive_claim_state(None, [_APPROVED, _DENIED])
    assert state is ClaimAdjudicationState.PARTIALLY_APPROVED
