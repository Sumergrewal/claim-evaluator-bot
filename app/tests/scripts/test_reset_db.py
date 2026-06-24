"""Behavioural checks for the reset-db script's post-seed adjudication."""

from __future__ import annotations

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.adjudication.startup import adjudicate_all_pending
from app.domain.entities import LineItemStatus
from app.persistence.models import LineItemModel
from app.persistence.seed import load_seed_data


def test_load_seed_then_adjudicate_leaves_no_pending_line_items(
    session: Session,
) -> None:
    """Mirrors reset_db: seed plants pending rows; batch must decide them."""
    load_seed_data(session)
    session.commit()

    pending_before = session.scalars(
        select(LineItemModel).where(LineItemModel.status == LineItemStatus.PENDING)
    ).all()
    assert len(pending_before) == 15

    decided = adjudicate_all_pending(session)
    session.commit()

    assert len(decided) == 15
    pending_after = session.scalars(
        select(LineItemModel).where(LineItemModel.status == LineItemStatus.PENDING)
    ).all()
    assert pending_after == []
