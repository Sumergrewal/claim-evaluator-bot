"""API-level fixtures: a `TestClient` against an in-memory DB.

Each test gets its own fresh in-memory SQLite engine, schema created
from the live ORM metadata, the same YAML seed loader applied, and
the startup adjudication batch run — so the DB the test client sees
matches what a freshly-launched app would. The production
`get_session` dependency is overridden to yield sessions bound to
the in-memory engine, so route handlers under test never touch the
real `claims.db` file.

We construct `TestClient(app)` *without* the `with` block on purpose:
that skips the production lifespan (which would otherwise try to
seed against the module-level engine), and lets us drive the seed
explicitly against the test engine here. The dependency override is
torn down after the test so a later test that doesn't use this
fixture isn't affected.

Each fixture is function-scoped to keep tests isolated — POST tests
in later steps will mutate state, and shared fixtures would create
order dependencies.
"""

from __future__ import annotations

from collections.abc import Iterator

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine, event
from sqlalchemy.engine import Engine
from sqlalchemy.orm import Session, sessionmaker
from sqlalchemy.pool import StaticPool

from app.adjudication.startup import adjudicate_all_pending
from app.main import app
from app.persistence import models  # noqa: F401  registers tables on Base.metadata
from app.persistence.database import Base, get_session
from app.persistence.seed import seed_if_empty


@pytest.fixture
def api_engine() -> Iterator[Engine]:
    """A fresh in-memory SQLite engine with FK enforcement, seeded + adjudicated.

    `StaticPool` is essential here: a bare `:memory:` SQLite gives each
    new connection its own private database, so the seed would land on
    one connection and the route's per-request session would open a
    fresh empty one. `StaticPool` reuses a single connection across
    the whole engine, so seed and request see the same data.
    """
    eng = create_engine(
        "sqlite:///:memory:",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )

    @event.listens_for(eng, "connect")
    def _enable_foreign_keys(dbapi_connection, _record) -> None:
        cursor = dbapi_connection.cursor()
        cursor.execute("PRAGMA foreign_keys=ON")
        cursor.close()

    Base.metadata.create_all(eng)

    factory = sessionmaker(
        bind=eng, autoflush=False, expire_on_commit=False
    )
    with factory() as s:
        seed_if_empty(s)
        s.commit()
    with factory() as s:
        adjudicate_all_pending(s)
        s.commit()

    try:
        yield eng
    finally:
        eng.dispose()


@pytest.fixture
def api_client(api_engine: Engine) -> Iterator[TestClient]:
    """A `TestClient` whose `get_session` is overridden to use `api_engine`.

    Mirrors the production `get_session` semantics (commit on success,
    rollback on exception, close in either case) so the route's
    transactional contract is what the test exercises.
    """
    factory = sessionmaker(
        bind=api_engine, autoflush=False, expire_on_commit=False
    )

    def _override_get_session() -> Iterator[Session]:
        session = factory()
        try:
            yield session
            session.commit()
        except Exception:
            session.rollback()
            raise
        finally:
            session.close()

    app.dependency_overrides[get_session] = _override_get_session
    try:
        yield TestClient(app)
    finally:
        app.dependency_overrides.pop(get_session, None)
