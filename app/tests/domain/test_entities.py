"""Tests for domain entity invariants enforced in `__post_init__`.

Pure-Python tests. No DB, no HTTP. Each test names the behaviour
under test, not the implementation.
"""

from __future__ import annotations

from datetime import date, datetime
from decimal import Decimal

import pytest

from app.domain.entities import (
    AdjudicationDecision,
    DecisionOutcome,
    Dispute,
    DisputeStatus,
    LineItem,
    LineItemStatus,
    Policy,
)

# --- LineItem --------------------------------------------------------------


def test_line_item_rejects_negative_charged_amount() -> None:
    with pytest.raises(ValueError, match="charged_amount must be non-negative"):
        LineItem(
            id="L1",
            claim_id="C1",
            service_type="x",
            service_description="x",
            charged_amount=Decimal("-1.00"),
            preauth_ref=None,
            status=LineItemStatus.PENDING,
        )


def test_line_item_requires_paired_derived_amounts() -> None:
    with pytest.raises(ValueError, match="must both be set or both be None"):
        LineItem(
            id="L1",
            claim_id="C1",
            service_type="x",
            service_description="x",
            charged_amount=Decimal("100.00"),
            preauth_ref=None,
            status=LineItemStatus.APPROVED,
            payable_amount=Decimal("80.00"),
            member_responsibility=None,
        )


def test_line_item_requires_derived_amounts_to_sum_to_charged() -> None:
    with pytest.raises(ValueError, match="must equal charged_amount"):
        LineItem(
            id="L1",
            claim_id="C1",
            service_type="x",
            service_description="x",
            charged_amount=Decimal("100.00"),
            preauth_ref=None,
            status=LineItemStatus.APPROVED,
            payable_amount=Decimal("80.00"),
            member_responsibility=Decimal("30.00"),
        )


def test_line_item_accepts_consistent_derived_amounts() -> None:
    li = LineItem(
        id="L1",
        claim_id="C1",
        service_type="x",
        service_description="x",
        charged_amount=Decimal("100.00"),
        preauth_ref=None,
        status=LineItemStatus.APPROVED,
        payable_amount=Decimal("80.00"),
        member_responsibility=Decimal("20.00"),
    )
    assert li.payable_amount + li.member_responsibility == li.charged_amount


# --- Policy ----------------------------------------------------------------


def test_policy_rejects_termination_before_effective() -> None:
    with pytest.raises(ValueError, match="is after termination_date"):
        Policy(
            id="P1",
            member_id="M1",
            name="x",
            effective_date=date(2026, 6, 1),
            termination_date=date(2026, 1, 1),
            annual_deductible=Decimal("0.00"),
        )


def test_policy_rejects_negative_deductible() -> None:
    with pytest.raises(ValueError, match="annual_deductible must be non-negative"):
        Policy(
            id="P1",
            member_id="M1",
            name="x",
            effective_date=date(2026, 1, 1),
            termination_date=date(2026, 12, 31),
            annual_deductible=Decimal("-1.00"),
        )


def test_policy_accepts_open_ended_termination() -> None:
    p = Policy(
        id="P1",
        member_id="M1",
        name="x",
        effective_date=date(2026, 1, 1),
        termination_date=None,
        annual_deductible=Decimal("0.00"),
    )
    assert p.termination_date is None


# --- AdjudicationDecision --------------------------------------------------


def test_decision_rejects_negative_amounts() -> None:
    now = datetime(2026, 1, 1)
    with pytest.raises(ValueError, match="payable_amount must be non-negative"):
        AdjudicationDecision(
            id="D1",
            line_item_id="L1",
            decided_at=now,
            decided_by="system",
            outcome=DecisionOutcome.APPROVED,
            payable_amount=Decimal("-1.00"),
            member_responsibility=Decimal("0.00"),
            explanation={},
        )


# --- Dispute ---------------------------------------------------------------


def test_dispute_resolved_status_requires_resolved_at() -> None:
    with pytest.raises(ValueError, match="resolved status requires resolved_at"):
        Dispute(
            id="DI1",
            line_item_id="L1",
            filed_at=datetime(2026, 1, 1),
            reason="x",
            status=DisputeStatus.RESOLVED,
        )


def test_dispute_open_status_forbids_resolution_fields() -> None:
    with pytest.raises(
        ValueError, match="only resolved disputes carry"
    ):
        Dispute(
            id="DI1",
            line_item_id="L1",
            filed_at=datetime(2026, 1, 1),
            reason="x",
            status=DisputeStatus.OPEN,
            resolved_at=datetime(2026, 1, 2),
        )
