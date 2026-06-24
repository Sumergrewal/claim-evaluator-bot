# claim-evaluator-bot

A claims processing system for an insurance company. Members submit
claims with line items; the system reviews each line item against
coverage rules, tracks claim lifecycle, and explains every decision.

See [`docs/decisions.md`](docs/decisions.md)
for the reasoning behind every non-trivial choice.

## Status

Runnable end-to-end: **QuickClaim** UI + FastAPI backend + six-phase
rules engine. On first launch the backend seeds from `data/*.yaml` and
reviews every pending line item before serving HTTP requests.

| Layer | Delivered |
|---|---|
| Backend | Domain model, SQLite persistence, YAML seed, rules engine, REST API |
| Frontend | Claims list (member filter), claim drill-down, submit form, rule tooltips |
| Tests | 197 pytest + 29 Vitest |
| Docs | [`domain-model.md`](docs/domain-model.md), [`decisions.md`](docs/decisions.md) — [`self-review.md`](docs/self-review.md) in progress |

See [`docs/decisions.md`](docs/decisions.md) for application flow, built
vs skipped, and assumptions.

## Stack

| Layer | Choice |
|---|---|
| Backend | Python 3.11+, FastAPI, SQLAlchemy 2.x, Pydantic |
| Package manager | [`uv`](https://docs.astral.sh/uv/) |
| Persistence | SQLite (`claims.db` in repo root, gitignored) |
| Backend testing | `pytest` + `httpx` |
| Frontend | React 19 + TypeScript, Vite, React Router |
| Frontend testing | Vitest + React Testing Library + jsdom |

## Repo layout

```text
claim-evaluator-bot/
├── app/                       # Python backend (FastAPI)
│   ├── api/                   # Route handlers + Pydantic schemas
│   ├── domain/                # Pure domain logic — no DB, no HTTP
│   ├── adjudication/          # Coverage-rule engine + service layer
│   ├── persistence/           # SQLAlchemy models + repositories + seed loader
│   ├── scripts/               # CLI entrypoints (reset_db)
│   ├── main.py                # FastAPI app entrypoint
│   └── tests/                 # pytest suite (domain, persistence, engine, API)
├── frontend/                  # QuickClaim React SPA
│   └── src/
│       ├── api/               # Fetch client for /api/*
│       ├── components/        # UI building blocks
│       ├── pages/             # Claims list, detail, submit
│       ├── utils/             # Formatting + label helpers
│       └── test/              # Vitest setup
├── data/                      # Seed YAML (members, policies, claims)
├── docs/
│   ├── domain-model.md
│   ├── decisions.md
│   └── self-review.md
├── ai-artifacts/              # Raw Cursor JSONL session logs (one per phase)
├── AGENTS.md
├── pyproject.toml
├── uv.lock
└── README.md
```

## Prerequisites

- Python ≥ 3.11
- [`uv`](https://docs.astral.sh/uv/getting-started/installation/)
- Node.js ≥ 20 and `npm`

## Quick start

From a fresh clone — **run all commands from the repo root** unless
noted.

```bash
git clone <this-repo>
cd claim-evaluator-bot

# 1. Install dependencies
uv sync
cd frontend && npm install && cd ..

# 2. Terminal 1 — API at http://localhost:8000
uv run uvicorn app.main:app --reload

# 3. Terminal 2 — QuickClaim UI at http://localhost:5173
cd frontend
npm run dev
```

Open [http://localhost:5173](http://localhost:5173). The first backend
start creates `claims.db` in the repo root, loads seed data, and
adjudicates every pending line item before accepting HTTP traffic.

**Sanity check** (with the backend running):

```bash
curl -s http://localhost:8000/api/members | head -c 80
# → JSON array of 3 members

curl -s -o /dev/null -w "%{http_code}\n" http://localhost:8000/api/claims
# → 200
```

Interactive API docs: [http://localhost:8000/docs](http://localhost:8000/docs)

## Setup

Same as step 1 above if you already cloned:

```bash
uv sync

cd frontend
npm install
cd ..
```

### QuickClaim UI

| Route | What it does |
|---|---|
| `/` | Claims list with member filter |
| `/claims/:id` | Claim detail — summary, line items, coverage decision breakdown, audit timeline |
| `/submit` | Submit a new claim; navigates to the reviewed result |

The UI talks to the backend at `http://localhost:8000` by default. Override
with `VITE_API_BASE` if needed.

### Sample members (seed data)

| Member | Policy | Good demos |
|---|---|---|
| Alice (M-001) | Basic | Deductible absorption, cross-claim caps, exclusions |
| Bob (M-002) | Premium | Preauth + MRI, bariatric covered with preauth |
| Carol (M-003) | Dental | Paid claim, partial approval, missing preauth |

Try service types like `general_consultation`, `physiotherapy`, `mri`,
`bariatric_surgery`, `cleaning`, `cosmetic_whitening`.

## API

All routes are under `/api`. Money fields are JSON strings (e.g.
`"150.00"`) for exact `Decimal` round-trip.

| Method | Path | Purpose |
|---|---|---|
| `GET` | `/api/members` | List members (filters + submit form) |
| `GET` | `/api/coverage-rules` | Coverage rule catalog with tooltip descriptions |
| `GET` | `/api/claims` | List claims; optional `?member_id=` filter |
| `GET` | `/api/claims/{claim_id}` | Drill-down: line items, decisions, explanations, audit timeline |
| `POST` | `/api/claims` | Submit claim; server generates ids, reviews line items, returns drill-down shape |
| `GET` | `/api/claims/{claim_id}/audit` | Audit timeline for a claim and its line items |
| `GET` | `/api/line-items/{line_item_id}/audit` | Audit timeline for one line item |

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

Unknown `member_id` → **404**. Invalid JSON → **422**. No active policy
on `service_date` → still **201**; the engine denies with a structured
explanation in the response.

## Resetting the database

The SQLite file `claims.db` lives in the repo root (gitignored). First
launch auto-seeds from `data/*.yaml`; later launches persist your state.

To wipe and re-seed (after schema changes or to start fresh). Stop
the dev server first (SQLite locks), then restart after reset:

```bash
uv run python -m app.scripts.reset_db
uv run uvicorn app.main:app --reload
```

The reset script adjudicates every pending seed line item after
loading YAML, so the DB matches what a first launch would show.

Run this whenever SQLAlchemy models change — the app uses
`create_all()` (not Alembic), so existing tables are not migrated in
place.

## Running tests

```bash
# Backend — from repo root (197 tests)
uv run pytest

# Frontend — from frontend/ (29 tests)
cd frontend
npm test
```

Other frontend scripts: `npm run lint`, `npm run build`.

## Troubleshooting

| Symptom | Fix |
|---|---|
| UI shows "Make sure the backend is running…" | Start terminal 1 from the **repo root**: `uv run uvicorn app.main:app --reload` |
| `database is locked` on `reset_db` | Stop the dev server first, then run reset, then restart |
| `ModuleNotFoundError: app` | You are not in the repo root — `pyproject.toml` and `app/` must be in the cwd |
| Empty claims list after reset | Use `uv run python -m app.scripts.reset_db` (not raw `rm claims.db` alone) — reset re-seeds **and** adjudicates pending line items |
| Frontend cannot reach API | Default API URL is `http://localhost:8000`; override with `VITE_API_BASE` when starting Vite |

## Documentation

- [`AGENTS.md`](AGENTS.md) — agent instructions and phase tracker
- [`docs/domain-model.md`](docs/domain-model.md) — entities, state machines
- [`docs/decisions.md`](docs/decisions.md) — decisions and trade-offs
- [`docs/self-review.md`](docs/self-review.md) — honest gap list

## AI session logs

Raw `.jsonl` Cursor session logs for each build phase live in
`ai-artifacts/`. Filenames follow `NN-phase-name__<uuid>.jsonl`.
