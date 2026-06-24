"""Persistence foundation: engine, session factory, declarative base,
and the per-request session dependency.

SQLite + SQLAlchemy 2.x. The DB URL is `sqlite:///./claims.db` by
default; tests and one-off scripts can point elsewhere via the
`DATABASE_URL` environment variable.

`get_session` runs each HTTP request inside a single transaction
(commit on success, rollback on exception). That guarantee is what
lets the adjudication write and its audit event land atomically
together — see sub-decisions D and G in `docs/decisions.md`.
"""

from __future__ import annotations

import logging
import os
from collections.abc import Iterator

from sqlalchemy import create_engine, event
from sqlalchemy.engine import Engine
from sqlalchemy.orm import DeclarativeBase, Session, sessionmaker

logger = logging.getLogger("app.database")

DATABASE_URL = os.environ.get("DATABASE_URL", "sqlite:///./claims.db")


def _make_engine(url: str) -> Engine:
    connect_args: dict[str, object] = {}
    if url.startswith("sqlite"):
        # FastAPI may hand the same SQLite connection across threads;
        # the default check would refuse that.
        connect_args["check_same_thread"] = False

    new_engine = create_engine(url, connect_args=connect_args)

    if new_engine.dialect.name == "sqlite":
        # SQLite ships with foreign-key enforcement off by default;
        # without this pragma `ForeignKey(...)` declarations are
        # documentation, not constraints. The pragma is per-connection.
        @event.listens_for(new_engine, "connect")
        def _enable_sqlite_foreign_keys(dbapi_connection, _record) -> None:
            cursor = dbapi_connection.cursor()
            cursor.execute("PRAGMA foreign_keys=ON")
            cursor.close()

    return new_engine


engine: Engine = _make_engine(DATABASE_URL)


SessionLocal = sessionmaker(
    bind=engine,
    autoflush=False,
    autocommit=False,
    expire_on_commit=False,
)


class Base(DeclarativeBase):
    """Declarative base for every ORM model. Lives in `app/persistence/`."""


def get_session() -> Iterator[Session]:
    """FastAPI dependency: yield a per-request session in a transaction.

    Commit on clean exit, rollback on any exception, close in either
    case. Use as `Depends(get_session)` on route handlers so every
    request is one atomic unit of work.
    """
    session = SessionLocal()
    try:
        yield session
        session.commit()
    except Exception as e:
        logger.warning(
            "rolling back request transaction: %s: %s", type(e).__name__, e
        )
        session.rollback()
        raise
    finally:
        session.close()
