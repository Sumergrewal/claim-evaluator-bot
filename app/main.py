"""FastAPI application entrypoint.

Phase 04 scaffolding: this module exists so a reviewer can launch the
backend (`uv run uvicorn app.main:app --reload`) and hit a single
hello-world endpoint that the frontend uses to verify the CORS-protected
boundary works end-to-end.

Real routes, the persistence layer wiring, and the seed loader land in
later phases.
"""

from __future__ import annotations

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel

# Origins allowed to call the API. Vite's default dev server is
# http://localhost:5173. We list 127.0.0.1 separately because browsers
# treat the two as distinct origins.
ALLOWED_ORIGINS = [
    "http://localhost:5173",
    "http://127.0.0.1:5173",
]


class HelloResponse(BaseModel):
    """Payload returned by `GET /api/hello`."""

    message: str
    phase: str


app = FastAPI(
    title="Claim Evaluator Bot",
    version="0.1.0",
    description=(
        "Claims processing system for an insurance company. "
        "Phase 04 scaffolding — only the hello-world endpoint is wired up."
    ),
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=ALLOWED_ORIGINS,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


@app.get("/api/hello", response_model=HelloResponse)
def hello() -> HelloResponse:
    return HelloResponse(
        message="Hello from the claim-evaluator-bot backend.",
        phase="04-scaffolding",
    )
