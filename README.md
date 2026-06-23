# claim-evaluator-bot

A claims processing system for an insurance company. Members submit
claims with line items; the system adjudicates each line item against
coverage rules, moves the claim through its lifecycle, and explains
every decision.

Built as a take-home assignment. See [`docs/decisions.md`](docs/decisions.md)
for the reasoning behind every non-trivial choice.

## Status

Foundation only — folder skeleton, docs scaffolding, and agent guidance
are in place. No application code yet. See the
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
├── app/                       # Python backend (FastAPI) — scaffolded in phase 05
│   ├── api/                   # Route handlers (thin HTTP layer)
│   ├── domain/                # Pure domain logic (entities, state machines) — no DB, no HTTP
│   ├── adjudication/          # Coverage-rule engine
│   ├── persistence/           # SQLAlchemy models + repositories
│   └── tests/                 # pytest suite
│       ├── domain/            # Pure domain tests (no DB, no HTTP)
│       └── api/               # API integration tests
├── frontend/                  # React + TS + Vite SPA — scaffolded in phase 07
├── data/                      # Sample policies, claims, seed data
├── docs/
│   ├── domain-model.md        # Entities, relationships, state machines
│   ├── decisions.md           # Running log of decisions & trade-offs
│   └── self-review.md         # Honest assessment of what's good vs. rough
├── ai-artifacts/              # Raw Cursor JSONL session logs (copied at the end, one per phase)
├── AGENTS.md                  # Agent guidance: project context + general rules
├── README.md
└── .gitignore

# Added in later phases (not present yet):
#   pyproject.toml             # uv-managed Python project (phase 05)
#   .python-version            # 3.11 pin (phase 05)
#   frontend/package.json      # Vite + React + TS (phase 07)
```

## Prerequisites

- Python ≥ 3.11
- [`uv`](https://docs.astral.sh/uv/getting-started/installation/) (`brew install uv` or `pipx install uv`)
- Node.js ≥ 20 and `npm` (for the frontend)

## Setup

```bash
git clone <this-repo>
cd claim-evaluator-bot

# Backend (works once phase 05 lands a pyproject.toml)
uv sync

# Frontend (works once phase 07 scaffolds the Vite app)
cd frontend
npm install
cd ..
```

> **Note:** Neither command does anything useful yet — this repo is
> currently foundation only (folder skeleton + docs + agent guidance).
> See the [phase tracker in `AGENTS.md`](AGENTS.md#phase-tracker).

## Running

```bash
# Backend — from repo root
uv run uvicorn app.main:app --reload

# Frontend — in a separate terminal
cd frontend
npm run dev
```

> Both commands will be functional once their respective phases land
> (backend: phase 05; frontend: phase 07).

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
