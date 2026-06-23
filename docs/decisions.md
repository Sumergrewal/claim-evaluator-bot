# Decisions

A running log of non-trivial decisions made during the build. Each entry
captures the **context**, the **options considered**, the **choice**, and
the **reasoning**. Append-only during the project; do not edit past
entries.

This doc is the single source of truth a new chat should read to catch
up on "where we are and why."

---

## 2026-06-23 — Stack: Python + FastAPI + uv (backend), Vite + React + TS (frontend), SQLite + SQLAlchemy

**Context:** Spec requires a runnable system with one interface. Stack
is unspecified — candidate's choice.

**Options considered:**

- Backend framework: FastAPI vs Flask vs Django.
- Package manager: `uv` vs `pip` + `venv`.
- Frontend: Vite + React + TS vs Next.js vs plain JS.
- Persistence: SQLite + SQLAlchemy vs Postgres in Docker vs in-memory.

**Choice:** FastAPI + `uv` for backend, Vite + React + TS for frontend,
SQLite + SQLAlchemy for persistence.

**Reasoning:**

- FastAPI gives type-checked request/response models and OpenAPI docs
  for free — useful when the reviewer is exploring the API.
- `uv` is fast and produces a reproducible lockfile so the reviewer's
  setup is deterministic.
- SQLite has zero install footprint — the reviewer doesn't need Docker
  or a running server. The DB file is gitignored; we seed on startup.
- Vite + React + TS is the fastest path to a working UI with type
  safety. Next.js's SSR/routing buys nothing for a claims-processing
  tool.

---

## 2026-06-23 — AGENTS.md as the coherence layer across chats

**Context:** Using multiple Cursor chats (one per phase) to keep JSONL
session logs cleanly separated per phase. Risk: each chat starts with
no memory of prior chats.

**Options considered:**

- One mega-chat for the whole project (no coherence problem, but agent
  quality degrades as context fills).
- Multiple chats per phase, coherence rebuilt via a shared artifact.

**Choice:** Multiple chats. `AGENTS.md` at the repo root acts as the
persistent context layer. Every new chat starts by reading `AGENTS.md`,
this `decisions.md`, `docs/domain-model.md`, and recent commits.

**Reasoning:**

- Cursor auto-loads `AGENTS.md` from the workspace root into every chat
  in this workspace — so the "read this first" instruction is enforced
  by tooling, not memory.
- Multiple chats keep each phase's JSONL log clean and easy for the
  reviewer to read in order.
- The rubric explicitly allows multiple agents/chats and expects
  per-phase logs.

---

## 2026-06-23 — Repo layout: domain layer kept pure, no DB or HTTP imports

**Context:** Need to decide where business logic vs persistence vs API
glue lives.

**Choice:** Three layers under `app/`:

- `app/domain/` — pure entities, value objects, state machines. No
  SQLAlchemy, no FastAPI imports allowed.
- `app/persistence/` — SQLAlchemy models + repositories.
- `app/api/` — FastAPI route handlers.
- `app/adjudication/` — the coverage-rule engine. Also pure — operates
  on domain objects, not DB models.

**Reasoning:**

- The domain layer becomes testable with plain Python objects — fast
  tests, no fixtures, no migrations.
- Forces explicit translation at the persistence/API boundaries, which
  catches a lot of accidental coupling early.
- Makes the rules engine swappable: if coverage rules ever moved to a
  DSL or external service, only the adjudication module changes.

---

## 2026-06-23 — Coverage rules represented as data, not code

**Context:** "How do you represent coverage rules?" is one of the
core questions in the spec.

**Options considered:**

- Hardcoded Python functions per rule type.
- Data-driven: rules live as structured records (JSON in seed files,
  rows in DB) that a generic rules engine interprets.
- Full DSL (overkill for 24-48 hrs).

**Choice:** Data-driven. Coverage rules are structured records the
adjudication engine reads and applies. Hardcoded fallback only for the
small handful of rule *kinds* (e.g. "annual limit," "per-visit cap,"
"requires preauthorization"), not for the specific values.

**Reasoning:**

- Real-world coverage rules change constantly per plan year and per
  policy. Code is the wrong place for them.
- Lets the demo show different policies producing different outcomes
  from the same engine — a key signal of good rule representation.
- Keeps the engine small and the rule catalog inspectable.

---

<!--
Future entries below. Format:

## YYYY-MM-DD — <short title>

**Context:** ...

**Options considered:** ...

**Choice:** ...

**Reasoning:** ...
-->
