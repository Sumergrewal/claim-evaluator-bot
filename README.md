# claim-evaluator-bot

A claims processing system for an insurance company. Members submit
claims with line items; the system adjudicates each line item against
coverage rules, moves the claim through its lifecycle, and explains
every decision.

Built as a take-home assignment. See [`docs/decisions.md`](docs/decisions.md)
for the reasoning behind every non-trivial choice.

## Status

Backend through **phase 07** (REST API for members, claims, and
audit). On first launch the app seeds from `data/*.yaml` and
adjudicates every pending line item before serving requests.

The frontend is still the phase-04 hello-world scaffold — it calls
`GET /api/hello`, which no longer exists. Phase 08 replaces it with
the real claims UI. Until then, explore the API via
[http://localhost:8000/docs](http://localhost:8000/docs) (Swagger UI)
or the endpoints below.

See the [phase tracker in `AGENTS.md`](AGENTS.md#phase-tracker) for
progress.

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
│   ├── scripts/               # CLI entrypoints (reset_db)
│   ├── main.py                # FastAPI app entrypoint
│   └── tests/                 # pytest suite
│       ├── domain/            # Pure domain tests (no DB, no HTTP)
│       ├── persistence/       # Repository and seed-loader tests
│       ├── adjudication/      # Rules engine and service tests
│       └── api/               # HTTP integration tests (TestClient)
├── frontend/                  # React + TS + Vite SPA (phase-04 stub until phase 08)
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

Open [http://localhost:8000/docs](http://localhost:8000/docs) for
interactive API docs. The frontend page will error until phase 08
replaces the hello-world call.

## API (phase 07)

All routes are under `/api`. Responses use JSON; money fields are
strings (e.g. `"150.00"`) for exact `Decimal` round-trip.

| Method | Path | Purpose |
|---|---|---|
| `GET` | `/api/members` | List members (for filters and submit form) |
| `GET` | `/api/claims` | List claims; optional `?member_id=` filter |
| `GET` | `/api/claims/{claim_id}` | Claim drill-down: line items, current decisions, explanations, embedded audit timeline |
| `POST` | `/api/claims` | Submit a new claim; server generates ids, adjudicates every line item, returns the same shape as the drill-down |
| `GET` | `/api/claims/{claim_id}/audit` | Audit timeline for a claim and its line items |
| `GET` | `/api/line-items/{line_item_id}/audit` | Audit timeline scoped to one line item |

**Submit body** (`POST /api/claims`):

```json
{
  "member_id": "M-001",
  "provider_name": "Northside Family Clinic",
  "service_date": "2026-06-15",
  "line_items": [
    {
      "service_type": "general_consultation",
      "service_description": "Follow-up visit",
      "charged_amount": "200.00",
      "preauth_ref": null
    }
  ]
}
```

Unknown `member_id` on filter or submit returns **404**. Invalid
JSON shape returns **422**. A claim with no active policy on
`service_date` is still accepted (**201**); the engine denies it with
a structured explanation in the response.

Design rationale for these choices lives in
[`docs/decisions.md`](docs/decisions.md) (2026-06-24 phase 07 entry).

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
