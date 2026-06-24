"""FastAPI application entrypoint.

Wires the persistence layer to the HTTP layer:

- On app startup, the lifespan handler:
  1. Creates any missing tables (`Base.metadata.create_all`).
  2. Runs the idempotent seed loader (`seed_if_empty`). The first
     launch populates the DB from `data/*.yaml`; subsequent launches
     no-op because the policies table is non-empty.
  3. Adjudicates every pending line item (`adjudicate_all_pending`)
     so the seed's two paid_at-set claims (C-BOB-001, C-CAROL-001)
     never reach the UI in the "paid_at set, line items pending"
     intermediate state. The batch is a no-op on subsequent restarts.
- The only HTTP route at this point is `GET /api/hello`, kept so the
  frontend's CORS check still passes. Real routes land in phase 07.

The seed and the adjudication batch use separate transactions on
purpose: a failed adjudication shouldn't roll back the seed (the
seed is idempotent on retry, while a half-rolled-back state would
need manual recovery). uvicorn still aborts startup on either
failure, so no HTTP request lands on a half-initialised DB.
"""

from __future__ import annotations

import logging
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel

from app.adjudication.startup import adjudicate_all_pending
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
    """Startup: ensure schema exists, seed if empty, drain pending line items.

    Any failure logs and re-raises so uvicorn aborts startup — an
    unseeded or half-adjudicated DB would otherwise surface much
    later as confusing 404s, empty lists, or wrong ledger amounts.
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

    try:
        with SessionLocal() as session:
            adjudicate_all_pending(session)
            session.commit()
    except Exception:
        logger.exception("startup adjudication failed; aborting startup")
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
