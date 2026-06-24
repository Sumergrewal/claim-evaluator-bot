"""Audit-event helper.

The single way to record an `AuditEvent`. Service-layer call sites
write events explicitly — no SQLAlchemy event listeners, no
`after_update` magic. See sub-decision G in `docs/decisions.md` for
why explicit beats magical here.

Atomicity comes from the per-request transaction set up in
`app/persistence/database.py`: the audit row and whatever row caused
the event share the request's session, so they commit or roll back
together. The helper itself doesn't flush or commit.
"""

from __future__ import annotations

import logging
import uuid
from datetime import UTC, datetime
from typing import Any

from sqlalchemy.orm import Session

from app.domain.entities import AuditEvent
from app.persistence.models import AuditEventModel

logger = logging.getLogger("app.audit")


def record_audit_event(
    session: Session,
    *,
    event_type: str,
    entity_type: str,
    entity_id: str,
    actor: str,
    payload: dict[str, Any] | None = None,
    occurred_at: datetime | None = None,
    event_id: str | None = None,
) -> AuditEvent:
    """Construct an `AuditEvent` and stage it on the session.

    `occurred_at` defaults to the current time as a naive UTC
    datetime (matches the domain convention); `event_id` defaults to
    a fresh UUID. Both are overridable for tests, seed data, and any
    place where the event timestamp should match an event the helper
    didn't construct itself.

    The constructed domain object is returned so the caller can log
    or inspect it; the ORM row goes on the session and is committed
    by the surrounding transaction.
    """
    event = AuditEvent(
        id=event_id or uuid.uuid4().hex,
        event_type=event_type,
        entity_type=entity_type,
        entity_id=entity_id,
        actor=actor,
        occurred_at=occurred_at or _utcnow_naive(),
        payload=dict(payload) if payload is not None else {},
    )
    session.add(AuditEventModel.from_domain(event))
    logger.info(
        "recorded %s on %s:%s (by %s)",
        event.event_type,
        event.entity_type,
        event.entity_id,
        event.actor,
    )
    return event


def _utcnow_naive() -> datetime:
    """Current UTC time as a naive `datetime` (matches the domain convention)."""
    return datetime.now(UTC).replace(tzinfo=None)
