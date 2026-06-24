"""Shared fixtures for any test that needs a DB session.

Lives at the test-tree root so persistence and adjudication tests
share the same `engine`/`session` fixtures without duplication. Each
test gets a fresh in-memory SQLite engine + session, isolated from
the app's module-level engine. Foreign-key enforcement is explicitly
enabled (SQLite ships with it off), matching the live app.

Domain-layer tests don't touch these fixtures — they import nothing
from this file and pytest's fixture resolver only attaches by name.
"""

from __future__ import annotations

from collections.abc import Iterator

import pytest
from sqlalchemy import create_engine, event
from sqlalchemy.engine import Engine
from sqlalchemy.orm import Session, sessionmaker

from app.persistence import models  # noqa: F401  registers tables on Base.metadata
from app.persistence.database import Base


@pytest.fixture
def engine() -> Iterator[Engine]:
    eng = create_engine(
        "sqlite:///:memory:",
        connect_args={"check_same_thread": False},
    )

    @event.listens_for(eng, "connect")
    def _enable_foreign_keys(dbapi_connection, _record) -> None:
        cursor = dbapi_connection.cursor()
        cursor.execute("PRAGMA foreign_keys=ON")
        cursor.close()

    Base.metadata.create_all(eng)
    try:
        yield eng
    finally:
        eng.dispose()


@pytest.fixture
def session(engine: Engine) -> Iterator[Session]:
    factory = sessionmaker(
        bind=engine, autoflush=False, expire_on_commit=False
    )
    with factory() as s:
        yield s
