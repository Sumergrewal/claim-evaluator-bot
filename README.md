# claim-evaluator-bot

A claims processing system for an insurance company. Members submit
claims with line items; the system adjudicates each line item against
coverage rules, moves the claim through its lifecycle, and explains
every decision.

Built as a take-home assignment. See [`docs/decisions.md`](docs/decisions.md)
for the reasoning behind every non-trivial choice.

## Status

Phase 04 scaffolding complete. Backend boots (FastAPI on
`localhost:8000`) and the frontend (Vite on `localhost:5173`) calls a
single hello-world endpoint across the CORS boundary, proving the
end-to-end loop. Domain entities, ORM models, the adjudication engine,
and the seed loader land in later phases. See the
[phase tracker in `AGENTS.md`](AGENTS.md#phase-tracker) for progress.

## Stack

| Layer | Choice |
|---|---|
| Backend | Python 3.11+, FastAPI, SQLAlchemy, Pydantic |
| Package manager | [`uv`](https://docs.astral.sh/uv/) |
| Persistence | SQLite (file-based, zero external setup) |
| Backend testing | `pytest` + `httpx` |
| Frontend | React + TypeScript, Vite |
| Frontend testing | Vitest + React Testing Library (if time permits) |

## Repo layout

```text
claim-evaluator-bot/
├── app/                       # Python backend (FastAPI)
│   ├── api/                   # Route handlers (thin HTTP layer)
│   ├── domain/                # Pure domain logic (entities, state machines) — no DB, no HTTP
│   ├── adjudication/          # Coverage-rule engine
│   ├── persistence/           # SQLAlchemy models + repositories
│   ├── scripts/               # CLI entrypoints (e.g. reset_db) — lands in phase 05
│   ├── main.py                # FastAPI app entrypoint (hello-world stub for now)
│   └── tests/                 # pytest suite
│       ├── domain/            # Pure domain tests (no DB, no HTTP)
│       └── api/               # API integration tests
├── frontend/                  # React + TS + Vite SPA (hello-world page for now)
├── data/                      # Sample policies, claims, seed data
├── docs/
│   ├── domain-model.md        # Entities, relationships, state machines
│   ├── decisions.md           # Running log of decisions & trade-offs
│   └── self-review.md         # Honest assessment of what's good vs. rough
├── ai-artifacts/              # Raw Cursor JSONL session logs (copied at the end, one per phase)
├── AGENTS.md                  # Agent guidance: project context + general rules
├── pyproject.toml             # uv-managed Python project
├── uv.lock                    # Locked Python deps
├── .python-version            # 3.11 pin
├── README.md
└── .gitignore
```

## Prerequisites

- Python ≥ 3.11
- [`uv`](https://docs.astral.sh/uv/getting-started/installation/) (`brew install uv` or `pipx install uv`)
- Node.js ≥ 20 and `npm` (for the frontend)

## Setup

```bash
git clone <this-repo>
cd claim-evaluator-bot

# Backend
uv sync

# Frontend
cd frontend
npm install
cd ..
```

## Running

```bash
# Backend — from repo root, http://localhost:8000
uv run uvicorn app.main:app --reload

# Frontend — in a separate terminal, http://localhost:5173
cd frontend
npm run dev
```

Open the frontend in a browser; it calls `GET /api/hello` and renders
the response, confirming the CORS boundary is wired correctly.

## Resetting the database

The SQLite database lives at `claims.db` in the repo root (gitignored,
so it never enters version control). On first launch the backend
auto-seeds it from `data/*.yaml`; on subsequent launches your state
persists across restarts.

If you want to start from a clean slate — for example after pulling
schema changes, or to throw away demo state you've created via the UI:

```bash
uv run python -m app.scripts.reset_db
```

This drops every table, recreates the schema from the current
SQLAlchemy models, and re-seeds from `data/*.yaml`.

> **When to run it:** any time the SQLAlchemy models change. The
> backend uses `Base.metadata.create_all()` (not Alembic) for schema
> management — that means new tables get created on startup, but
> existing tables aren't migrated in place. After a model change,
> `reset_db` is the way to get the new schema. See the persistence
> decision in [`docs/decisions.md`](docs/decisions.md) for the
> reasoning.

> Lands in phase 05 alongside the persistence layer; the command and
> the `claims.db` file don't exist yet.

## Running tests

```bash
uv run pytest
```

## Documentation

- [`AGENTS.md`](AGENTS.md) — agent instructions, phase tracker, and the
  one-liner to paste into any new Cursor chat for full context.
- [`docs/domain-model.md`](docs/domain-model.md) — entities,
  relationships, state machines.
- [`docs/decisions.md`](docs/decisions.md) — every non-trivial decision,
  with options considered and reasoning.
- [`docs/self-review.md`](docs/self-review.md) — honest gap list and
  things I'd change with more time.

## AI session logs

Raw `.jsonl` session logs from every phase live in `ai-artifacts/`.
These are unmodified Cursor session files — UUIDs preserved in the
filename — prefixed by phase number for readability.
