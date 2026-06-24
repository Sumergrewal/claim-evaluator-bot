"""Drop and recreate the database, then re-seed from `data/*.yaml`.

Usage:

    uv run python -m app.scripts.reset_db

DESTRUCTIVE: drops every table in the configured database and
recreates the schema from the current SQLAlchemy models. Any data
written through the API since the last seed is lost.

When to run it:

- After changing any SQLAlchemy model (the app uses
  `Base.metadata.create_all()` on startup, which is additive only —
  it won't migrate existing tables).
- To wipe demo state and return to the freshly-seeded baseline.

After seeding, runs the same `adjudicate_all_pending` batch the app
lifespan runs on startup so a reset DB is immediately reviewable —
seed YAML plants line items as `pending`, and without this step every
claim would show **Submitted** until the next server restart.

Reads `DATABASE_URL` (default `sqlite:///./claims.db`) the same way
the app does, so the script always operates on whatever DB the app
would. Stop the dev server before running this; SQLite raises
"database is locked" if there's a concurrent connection.

See the persistence-layer decision in `docs/decisions.md` and the
"Resetting the database" section of `README.md`.
"""

from __future__ import annotations

import logging

from sqlalchemy.orm import Session

from app.adjudication.startup import adjudicate_all_pending
from app.logging_config import configure_logging
from app.persistence import models  # noqa: F401  registers tables on Base.metadata
from app.persistence.database import Base, engine
from app.persistence.seed import SeedLoadError, load_seed_data

logger = logging.getLogger("app.reset_db")


def main() -> int:
    configure_logging()
    logger.info("target = %s", engine.url)

    try:
        logger.info("dropping all tables")
        Base.metadata.drop_all(engine)

        logger.info("recreating schema")
        Base.metadata.create_all(engine)

        logger.info("loading seed data")
        with Session(engine) as session:
            load_seed_data(session)
            session.commit()

        logger.info("adjudicating pending line items")
        with Session(engine) as session:
            decided = adjudicate_all_pending(session)
            session.commit()
        logger.info("decided %d line item(s)", len(decided))
    except SeedLoadError:
        logger.exception("seed failed")
        return 1
    except Exception:
        logger.exception("unexpected error during reset")
        return 1

    logger.info("done")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
