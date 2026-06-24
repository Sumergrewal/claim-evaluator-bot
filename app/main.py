"""FastAPI application entrypoint.

Wires the persistence layer to the HTTP layer:

- On app startup, the lifespan handler creates any missing tables
  (`Base.metadata.create_all`) and runs the idempotent seed loader
  (`seed_if_empty`). The first launch populates the DB from
  `data/*.yaml`; subsequent launches no-op because the policies
  table is non-empty.
- The only HTTP route at this point is `GET /api/hello`, kept so the
  frontend's CORS check still passes. Real routes land in phase 07.

What's deliberately not here yet:

- The adjudication engine and its startup hook (phase 06). Until that
  lands, seeded line items remain `pending` and the two claims with
  `paid_at` derive as `paid` while their line items haven't been
  decided — see the NOTE in `app/domain/claim_state.py`.
- Logging configuration. Currently uses `print` for startup
  diagnostics; a single logging pass replaces all of these after
  phase 05's structural pieces stabilise.
"""

from __future__ import annotations

import logging
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel

from app.logging_config import configure_logging
from app.persistence import models  # noqa: F401  registers tables on Base.metadata
from app.persistence.database import Base, SessionLocal, engine
from app.persistence.seed import SeedLoadError, seed_if_empty

configure_logging()
logger = logging.getLogger("app.main")

ALLOWED_ORIGINS = [
    "http://localhost:5173",
    "http://127.0.0.1:5173",
]


@asynccontextmanager
async def lifespan(_: FastAPI) -> AsyncIterator[None]:
    """Startup: ensure schema exists, then seed if the DB is empty.

    `SeedLoadError` is logged and re-raised so uvicorn aborts startup —
    an unseeded DB would otherwise surface much later as confusing
    404s and empty lists.
    """
    logger.info("starting; database = %s", engine.url)
    Base.metadata.create_all(engine)
    logger.info("schema ready")

    try:
        with SessionLocal() as session:
            seed_if_empty(session)
            session.commit()
    except SeedLoadError:
        logger.exception("seed failed; aborting startup")
        raise

    yield
    logger.info("shutting down")


app = FastAPI(
    title="Claim Evaluator Bot",
    version="0.1.0",
    description=(
        "Claims processing system for an insurance company. "
        "Phase 05 backend core — persistence layer wired up; "
        "engine and API routes land in phases 06 and 07."
    ),
    lifespan=lifespan,
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=ALLOWED_ORIGINS,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


class HelloResponse(BaseModel):
    """Payload returned by `GET /api/hello`."""

    message: str
    phase: str


@app.get("/api/hello", response_model=HelloResponse)
def hello() -> HelloResponse:
    return HelloResponse(
        message="Hello from the claim-evaluator-bot backend.",
        phase="05-backend-core",
    )
