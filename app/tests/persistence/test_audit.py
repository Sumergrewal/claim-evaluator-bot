"""Tests for `record_audit_event`."""

from __future__ import annotations

from datetime import datetime
from uuid import UUID

from sqlalchemy.orm import Session

from app.persistence import repositories as repo
from app.persistence.audit import record_audit_event


def test_record_audit_event_generates_uuid_id_when_omitted(
    session: Session,
) -> None:
    ev = record_audit_event(
        session,
        event_type="claim.submitted",
        entity_type="claim",
        entity_id="C1",
        actor="system",
    )
    session.commit()

    UUID(hex=ev.id)
    assert ev.payload == {}


def test_record_audit_event_accepts_explicit_id_and_timestamp(
    session: Session,
) -> None:
    fixed_at = datetime(2026, 1, 1, 12, 0)
    ev = record_audit_event(
        session,
        event_type="line_item.decided",
        entity_type="line_item",
        entity_id="L1",
        actor="reviewer:1",
        payload={"outcome": "approved"},
        occurred_at=fixed_at,
        event_id="fixed-id",
    )
    session.commit()

    stored = repo.list_audit_events_for(session, "line_item", "L1")
    assert len(stored) == 1
    assert stored[0].id == "fixed-id"
    assert stored[0].occurred_at == fixed_at
    assert stored[0].payload == {"outcome": "approved"}
    assert stored[0].actor == "reviewer:1"
    assert ev == stored[0]


def test_record_audit_event_does_not_commit(session: Session) -> None:
    record_audit_event(
        session,
        event_type="x.one",
        entity_type="x",
        entity_id="X1",
        actor="system",
    )
    # No commit; events should not be visible after rollback.
    session.rollback()
    assert repo.list_audit_events_for(session, "x", "X1") == []


def test_two_events_committed_together_land_atomically(session: Session) -> None:
    record_audit_event(
        session, event_type="claim.submitted", entity_type="claim",
        entity_id="C1", actor="member",
    )
    record_audit_event(
        session, event_type="line_item.decided", entity_type="line_item",
        entity_id="L1", actor="system", payload={"outcome": "approved"},
    )
    session.commit()

    claim_events = repo.list_audit_events_for(session, "claim", "C1")
    line_item_events = repo.list_audit_events_for(session, "line_item", "L1")
    assert len(claim_events) == 1
    assert len(line_item_events) == 1
