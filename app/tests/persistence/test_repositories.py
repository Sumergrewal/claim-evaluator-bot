"""Tests for the functional repositories.

Focus on the queries with non-trivial behaviour: active-policy
selection, current-decision filtering with supersession, the
accumulator query under various filters, and derived-amount
population on line items.
"""

from __future__ import annotations

from datetime import date, datetime
from decimal import Decimal

import pytest
from sqlalchemy.orm import Session

from app.domain.entities import (
    AdjudicationDecision,
    Claim,
    DecisionOutcome,
    LineItem,
    LineItemStatus,
    Member,
    Policy,
)
from app.persistence import repositories as repo
from app.persistence.models import (
    AdjudicationDecisionModel,
    ClaimModel,
    LineItemModel,
    MemberModel,
    PolicyModel,
)

_NOW = datetime(2026, 6, 1)


def _seed_alice_with_2026_policy(
    session: Session, *, deductible: Decimal = Decimal("500.00")
) -> None:
    session.add(MemberModel.from_domain(Member(id="M1", name="Alice")))
    session.add(
        PolicyModel.from_domain(
            Policy(
                id="P-2026",
                member_id="M1",
                name="BASIC",
                effective_date=date(2026, 1, 1),
                termination_date=date(2026, 12, 31),
                annual_deductible=deductible,
            )
        )
    )
    session.flush()


def _add_approved_physio(
    session: Session,
    *,
    claim_id: str,
    line_id: str,
    decision_id: str,
    payable: Decimal,
    service_date: date,
    supersedes_id: str | None = None,
    outcome: DecisionOutcome = DecisionOutcome.APPROVED,
) -> None:
    session.add(
        ClaimModel.from_domain(
            Claim(
                id=claim_id,
                member_id="M1",
                provider_name="x",
                service_date=service_date,
                submitted_at=_NOW,
                paid_at=None,
            )
        )
    )
    session.flush()
    session.add(
        LineItemModel.from_domain(
            LineItem(
                id=line_id,
                claim_id=claim_id,
                service_type="physio",
                service_description="x",
                charged_amount=payable,
                preauth_ref=None,
                status=LineItemStatus.APPROVED
                if outcome is DecisionOutcome.APPROVED
                else LineItemStatus.DENIED,
            )
        )
    )
    session.flush()
    session.add(
        AdjudicationDecisionModel.from_domain(
            AdjudicationDecision(
                id=decision_id,
                line_item_id=line_id,
                decided_at=_NOW,
                decided_by="system",
                outcome=outcome,
                payable_amount=payable
                if outcome is DecisionOutcome.APPROVED
                else Decimal("0.00"),
                member_responsibility=Decimal("0.00")
                if outcome is DecisionOutcome.APPROVED
                else payable,
                explanation={},
                supersedes_id=supersedes_id,
            )
        )
    )


# --- Active policy --------------------------------------------------------


def test_active_policy_returned_when_service_date_is_inside_window(
    session: Session,
) -> None:
    _seed_alice_with_2026_policy(session)
    p = repo.get_active_policy_for(session, "M1", date(2026, 6, 15))
    assert p is not None
    assert p.id == "P-2026"


def test_active_policy_is_none_when_service_date_is_before_window(
    session: Session,
) -> None:
    _seed_alice_with_2026_policy(session)
    assert repo.get_active_policy_for(session, "M1", date(2025, 12, 31)) is None


def test_active_policy_is_none_when_service_date_is_after_window(
    session: Session,
) -> None:
    _seed_alice_with_2026_policy(session)
    assert repo.get_active_policy_for(session, "M1", date(2027, 1, 1)) is None


def test_active_policy_handles_open_ended_termination(session: Session) -> None:
    session.add(MemberModel.from_domain(Member(id="M1", name="A")))
    session.add(
        PolicyModel.from_domain(
            Policy(
                id="P-OPEN",
                member_id="M1",
                name="x",
                effective_date=date(2026, 1, 1),
                termination_date=None,
                annual_deductible=Decimal("0.00"),
            )
        )
    )
    session.flush()
    p = repo.get_active_policy_for(session, "M1", date(2030, 1, 1))
    assert p is not None
    assert p.id == "P-OPEN"


# --- Current decision (supersession) --------------------------------------


def test_current_decision_returns_latest_when_supersession_chain_exists(
    session: Session,
) -> None:
    _seed_alice_with_2026_policy(session)
    _add_approved_physio(
        session,
        claim_id="C1",
        line_id="L1",
        decision_id="D1",
        payable=Decimal("100.00"),
        service_date=date(2026, 3, 1),
    )
    # A later denial decision supersedes the original approval.
    session.add(
        AdjudicationDecisionModel.from_domain(
            AdjudicationDecision(
                id="D2",
                line_item_id="L1",
                decided_at=_NOW,
                decided_by="reviewer:1",
                outcome=DecisionOutcome.DENIED,
                payable_amount=Decimal("0.00"),
                member_responsibility=Decimal("100.00"),
                explanation={},
                supersedes_id="D1",
            )
        )
    )
    session.commit()

    current = repo.get_current_decision_for_line_item(session, "L1")
    assert current is not None
    assert current.id == "D2"
    assert current.outcome is DecisionOutcome.DENIED

    # And the full history is still readable in chronological order.
    hist = repo.list_decisions_for_line_item(session, "L1")
    assert [d.id for d in hist] == ["D1", "D2"]


# --- Accumulator ----------------------------------------------------------


def test_accumulator_counts_only_current_approved_decisions(
    session: Session,
) -> None:
    _seed_alice_with_2026_policy(session)
    _add_approved_physio(
        session, claim_id="C1", line_id="L1", decision_id="D1",
        payable=Decimal("600.00"), service_date=date(2026, 3, 1),
    )
    _add_approved_physio(
        session, claim_id="C2", line_id="L2", decision_id="D2",
        payable=Decimal("300.00"), service_date=date(2026, 4, 1),
    )
    # D2 is then superseded by a denial; should drop out of the sum.
    session.add(
        AdjudicationDecisionModel.from_domain(
            AdjudicationDecision(
                id="D2b",
                line_item_id="L2",
                decided_at=_NOW,
                decided_by="reviewer:1",
                outcome=DecisionOutcome.DENIED,
                payable_amount=Decimal("0.00"),
                member_responsibility=Decimal("300.00"),
                explanation={},
                supersedes_id="D2",
            )
        )
    )
    session.commit()

    total = repo.sum_payable_for_accumulator(
        session,
        member_id="M1",
        service_type="physio",
        period_start=date(2026, 1, 1),
        period_end=date(2026, 12, 31),
    )
    assert total == Decimal("600.00")


def test_accumulator_respects_period_window(session: Session) -> None:
    _seed_alice_with_2026_policy(session)
    _add_approved_physio(
        session, claim_id="C1", line_id="L1", decision_id="D1",
        payable=Decimal("400.00"), service_date=date(2026, 3, 1),
    )
    session.commit()

    in_window = repo.sum_payable_for_accumulator(
        session,
        member_id="M1",
        service_type="physio",
        period_start=date(2026, 1, 1),
        period_end=date(2026, 12, 31),
    )
    out_of_window = repo.sum_payable_for_accumulator(
        session,
        member_id="M1",
        service_type="physio",
        period_start=date(2025, 1, 1),
        period_end=date(2025, 12, 31),
    )
    assert in_window == Decimal("400.00")
    assert out_of_window == Decimal("0.00")


def test_accumulator_exclude_line_item_drops_that_lines_history(
    session: Session,
) -> None:
    _seed_alice_with_2026_policy(session)
    _add_approved_physio(
        session, claim_id="C1", line_id="L1", decision_id="D1",
        payable=Decimal("400.00"), service_date=date(2026, 3, 1),
    )
    _add_approved_physio(
        session, claim_id="C2", line_id="L2", decision_id="D2",
        payable=Decimal("200.00"), service_date=date(2026, 4, 1),
    )
    session.commit()

    total = repo.sum_payable_for_accumulator(
        session,
        member_id="M1",
        service_type="physio",
        period_start=date(2026, 1, 1),
        period_end=date(2026, 12, 31),
        exclude_line_item_id="L2",
    )
    assert total == Decimal("400.00")


# --- Derived amounts on line items ----------------------------------------


def test_list_line_items_populates_derived_amounts_from_current_decision(
    session: Session,
) -> None:
    _seed_alice_with_2026_policy(session)
    _add_approved_physio(
        session, claim_id="C1", line_id="L1", decision_id="D1",
        payable=Decimal("100.00"), service_date=date(2026, 3, 1),
    )
    session.commit()

    items = repo.list_line_items_for_claim(session, "C1")
    assert len(items) == 1
    assert items[0].status is LineItemStatus.APPROVED
    assert items[0].payable_amount == Decimal("100.00")
    assert items[0].member_responsibility == Decimal("0.00")


def test_list_line_items_leaves_derived_amounts_none_when_no_decision(
    session: Session,
) -> None:
    _seed_alice_with_2026_policy(session)
    session.add(
        ClaimModel.from_domain(
            Claim(
                id="C1",
                member_id="M1",
                provider_name="x",
                service_date=date(2026, 3, 1),
                submitted_at=_NOW,
                paid_at=None,
            )
        )
    )
    session.flush()
    session.add(
        LineItemModel.from_domain(
            LineItem(
                id="L1",
                claim_id="C1",
                service_type="physio",
                service_description="x",
                charged_amount=Decimal("100.00"),
                preauth_ref=None,
                status=LineItemStatus.PENDING,
            )
        )
    )
    session.commit()

    items = repo.list_line_items_for_claim(session, "C1")
    assert items[0].payable_amount is None
    assert items[0].member_responsibility is None


# --- FK enforcement on the underlying schema ------------------------------


def test_inserting_line_item_with_unknown_claim_raises(session: Session) -> None:
    from sqlalchemy.exc import IntegrityError

    session.add(
        LineItemModel.from_domain(
            LineItem(
                id="L1",
                claim_id="C-MISSING",
                service_type="x",
                service_description="x",
                charged_amount=Decimal("100.00"),
                preauth_ref=None,
                status=LineItemStatus.PENDING,
            )
        )
    )
    with pytest.raises(IntegrityError):
        session.commit()
