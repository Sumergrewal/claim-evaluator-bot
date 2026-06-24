# AGENTS.md

> **Project-specific guidance is at the top. General behavioral rules are
> at the bottom. On conflict, project-specific wins.**

---

## Onboarding for a new chat (READ FIRST)

Whenever a chat in this workspace starts, do this before anything else:

1. Read this entire `AGENTS.md`.
2. Read `docs/decisions.md` — the running log of what was built, what was
   skipped, and the reasoning behind each call. This is the single source
   of truth for "where we are."
3. Read `docs/domain-model.md` — entities, relationships, state machines.
4. Run `git log --oneline -20` to see the recent commit narrative.
5. Only then start on the task the user asked for.

The user's one-liner to paste in any new chat is:

> "Read `AGENTS.md`, `docs/decisions.md`, `docs/domain-model.md`, and
> `git log --oneline -20`. Then: <today's task>."

---

## Project context

**What this is:** a take-home assignment to build a working **Claims
Processing System** for an insurance company. The deliverable is a
runnable system that ingests claims, adjudicates them against coverage
rules, tracks them through lifecycle states, and explains every decision.

**Time budget:** 24-48 hours total.

**Submission must include** (per the rubric):

- `app/` — backend application code
- `frontend/` — web UI
- `docs/domain-model.md` — entities, relationships, state machines
- `docs/decisions.md` — what was built, what was skipped, assumptions
- `docs/self-review.md` — honest assessment
- `ai-artifacts/` — **raw `.jsonl` Cursor session logs covering every
  phase** (framing, research, planning, coding, docs, testing, QA).
  Missing JSONLs = auto-reject.
- `README.md` — setup and run instructions
- `.git/` — full commit history (no single-commit dumps)

**Out of scope** (explicitly per the spec — do not build):

- Auth, login, registration
- Policy purchase / enrollment flows
- Member / provider account management
- Email notifications
- Analytics dashboards
- Admin panels
- Multi-tenancy or RBAC

---

## Stack

| Layer | Choice | Notes |
|---|---|---|
| Backend language | Python 3.11+ | Type hints required |
| Backend framework | FastAPI | REST API serving the frontend |
| Package manager | `uv` | Fast, modern, lockfile-based |
| Persistence | SQLite + SQLAlchemy | File-based, zero setup for reviewer |
| Backend testing | `pytest` | Tests encode domain behavior, not just HTTP codes |
| Frontend | Vite + React + TypeScript | Strict TS |
| Frontend testing | Vitest + React Testing Library | Only if time permits — backend tests come first |
| Interface | Single-page web UI | Talks to the FastAPI backend over REST |

---

## Repo layout (target — will fill in as we scaffold)

```text
claim-evaluator-bot/
├── app/                       # Python backend (FastAPI)
│   ├── api/                   # Route handlers
│   ├── domain/                # Pure domain logic (entities, rules, state machines)
│   ├── adjudication/          # Coverage-rule engine
│   ├── persistence/           # SQLAlchemy models + repos
│   ├── main.py                # FastAPI app entrypoint
│   └── tests/                 # pytest suite
├── frontend/                  # React + TS UI
│   ├── src/
│   ├── package.json
│   └── vite.config.ts
├── docs/
│   ├── domain-model.md
│   ├── decisions.md
│   └── self-review.md
├── ai-artifacts/              # Raw JSONL session logs (copied at the end)
├── data/                      # Sample policies, claims, seed data
├── AGENTS.md                  # This file
├── README.md
├── pyproject.toml             # uv-managed Python project
└── .git/
```

---

## Project-specific conventions

### Domain modeling

- Domain logic lives in `app/domain/`. It must be **pure** — no DB
  imports, no FastAPI imports. The domain should be testable with plain
  Python objects.
- Persistence (`app/persistence/`) and API (`app/api/`) are thin
  adapters around the domain.
- Coverage rules are **data, not code** — represented as structured
  configuration the rules engine interprets. Reason: business rules
  change often, code shouldn't be the place rules live.

### State machines

- Both **claims** and **line items** have lifecycles. Model both
  separately. A claim's state is derived from its line items' states,
  not stored independently as a source of truth that can drift.
- Every state transition must produce an audit-log entry with: who/what
  triggered it, before/after state, timestamp, reason.

### Explanations

- Every adjudication decision (approve / deny / partial / needs review)
  must carry a structured explanation: the rule(s) that fired, the
  inputs that were checked, the amount math. The UI surfaces this; the
  API returns it as part of the line item response.

### Tests

- Tests appear **in the same commit as or before** the code they cover.
  The git history is reviewed for this — do not bolt tests on at the
  end.
- Test names describe behavior, not implementation:
  - Good: `test_line_item_denied_when_service_type_not_covered`
  - Bad: `test_adjudicate_returns_200`
- Domain logic tests live in `app/tests/domain/` and never touch the DB
  or the HTTP layer.

### Commits

- Conventional-commit-ish prefixes: `feat:`, `fix:`, `refactor:`,
  `test:`, `docs:`, `chore:`.
- One logical change per commit. The history is read by the reviewer
  as the story of how this was built.
- Commit messages should explain **why** more than **what** when the
  what isn't obvious from the diff.

### Documentation discipline

- `docs/decisions.md` is **append-only during the project**. Every
  non-trivial decision gets a dated entry with: context, options
  considered, choice, reasoning. This is how a new chat catches up.
- `docs/domain-model.md` evolves with the model and reflects the
  current state.
- `docs/self-review.md` is written near the end. Be honest about gaps.

### AI session logs

- Cursor JSONLs live at
  `~/.cursor/projects/Users-adagrewal-Desktop-Sumer-stuff-claim-evaluator-bot/agent-transcripts/<uuid>/<uuid>.jsonl`.
- We do **one chat per phase**. Naming convention when copying into
  `ai-artifacts/` at the end: `NN-phase-name__<uuid>.jsonl` (e.g.
  `03-planning__619c8af9-...jsonl`). Keep the UUID so the file is
  obviously the raw original.
- Phases (target list):
  1. `01-framing` — understanding the assignment
  2. `02-domain-research` — insurance / adjudication research
  3. `03-planning` — architecture, schema, state machines
  4. `04-scaffolding` — repo layout, deps, AGENTS.md
  5. `05-backend-core` — entities, persistence
6. `06-backend-adjudication` — rules engine, state machine
7. `07-backend-api` — FastAPI routes for claims/decisions/audit
8. `08-frontend` — QuickClaim React UI
9. `09-tests` — finalize test coverage
10. `10-docs` — fill out the three docs
11. `11-qa` — bug hunt, polish, edge cases

---

## How to run (will fill in once scaffolded)

```bash
# Backend
cd app
uv sync
uv run uvicorn main:app --reload

# Frontend (in another terminal)
cd frontend
npm install
npm run dev
```

(README.md will mirror this with full setup steps for the reviewer.)

---

## Phase tracker

- [x] **01-framing** — assignment understood, deliverables mapped
- [x] **02-domain-research** — adjudication / rule patterns understood
- [x] **03-planning** — domain model, state machines, rule schema, cost-sharing math, deferred-feature list, sample data (3 members + 3 policies + curated claim set covering every engine path), and persistence layer (SQLAlchemy 2.x, separated domain/ORM, functional repos, per-request session, `create_all` + reset CLI) all locked in. Coverage rules and seed data are YAML in `data/`, loaded on first startup
- [x] **04-scaffolding** — uv project initialised; backend deps (FastAPI, SQLAlchemy 2.x, Pydantic, PyYAML, uvicorn) + dev deps (pytest, httpx, ruff) locked via `uv.lock`; Vite + React + TS frontend scaffolded; hello-world endpoint (`GET /api/hello`) wired with CORS for `localhost:5173`; frontend page calls it on mount and renders the response
- [x] **05-backend-core** — domain entities (frozen dataclasses) + claim-state derivation; SQLAlchemy 2.x persistence (engine, Base, per-request session, ORM models with `to_domain`/`from_domain`, functional repositories, accumulator query, explicit audit-event helper); YAML seed data (3 members, 3 policies with 32 rules, 13 curated claims, 15 line items); Pydantic seed loader with discriminated rule-kind union and cross-entity validation; `reset_db` CLI; FastAPI lifespan wires `create_all` + idempotent seeding on startup; `app.*` logger configured for startup/seed/audit/rollback visibility. Test suite (47 tests) covers entity invariants, claim-state derivation, ORM round-trip, repos (active policy, supersession, accumulator), audit helper, and seed-loader failure modes.
- [x] **06-backend-adjudication** — pure rules engine walking six phases (eligibility → coverage → gates → deductible → limits → cost-sharing) with `adjudicate(EngineInput) -> EngineResult` returning a structured per-step explanation and the ledger split; `deductible_applied` column on `AdjudicationDecision` + cross-service-type accumulator (`sum_deductible_applied`) so member-scoped deductible math is a SQL sum; `adjudicate_line_item(session, line_item_id)` service entry writing the decision row with `supersedes_id` chain and one `line_item.decided` audit event per call; `adjudicate_all_pending(session)` startup batch processing in `(claim.submitted_at, line_item.id)` order; FastAPI lifespan drains all pending line items in a separate transaction after seed commits, so the seed's paid_at-set claims never reach the UI half-decided. Test suite (107 tests total; 60 new this phase) covers engine value types + ledger invariant, each phase's exit path, three integration scenarios mirroring seed claims, service-layer happy + denied + needs_review + eligibility paths + intra/cross-claim accumulator flow, repo ordering + supersession filtering, and a real-seed integration test that verifies every pending line item — including C-BOB-001 and C-CAROL-001 — ends decided.
- [x] **07-backend-api** — FastAPI routes for claims, line items, decisions, audit
- [x] **08-frontend** — QuickClaim React SPA (list, detail, submit), rule tooltips via `GET /api/coverage-rules`, paid-state derivation fix
- [ ] **09-tests** — finalize test coverage (frontend Vitest baseline landed; coverage-rules API route + page-level FE tests still open)
- [ ] **10-docs** — fill out the three docs
- [ ] **11-qa** — bug hunt, polish, edge cases

Update this list at the end of each phase.

---

# General behavioral rules

> These are cross-project defaults — they should apply regardless of
> language, framework, or repo. The project-specific guidance above
> wins on conflict.

## Safety & version control

- Never commit, amend, push, or run destructive git commands unless I
  explicitly ask.
- Never modify git config or rewrite history.
- Don't open pull requests on my behalf unless I ask.
- Don't commit files that may contain secrets (`.env`, credentials, tokens).

## File & change discipline

- Always read a file (or the relevant section) before editing it. Don't
  blind-edit based on a guess about its current contents. Re-read if you're
  unsure, even when you "remember" the file from earlier in the session.
- Prefer editing existing files over creating new ones.
- Don't create documentation, README, or summary files unless I ask.
- Keep diffs minimal and focused on the task. No drive-by refactors or
  reformatting of code I didn't ask you to touch.
- Don't add narrating comments (e.g. `// increment counter`). Comments
  should only explain non-obvious intent or constraints.

## Communication

- Be concise. Skip preamble like "Great question!" and post-amble summaries
  of what you just did unless I ask.
- No emojis unless I ask.
- If you're unsure between a few approaches, ask before going down a path
  that requires significant code changes.

## Completion & honesty

- If a task isn't fully done, something is broken, or you skipped a step,
  say so explicitly at the end. Don't claim success when there are known
  failures, untested paths, or TODOs you left behind.
- A clear "this works but I didn't test X" or "I implemented A but B is
  still failing" is always better than implying everything is fine.
- Don't paper over errors by catching and ignoring them, hardcoding
  return values, or commenting out failing assertions just to make
  things "work".

## Planning

- For non-trivial tasks (more than ~3 steps or touching multiple files),
  briefly outline the plan before editing.
- If the task is ambiguous or has meaningful trade-offs, ask clarifying
  questions instead of guessing.

## Dependencies

- Don't add new dependencies for trivial reasons.
- When you do add one, use the package manager to pick a real current
  version - never invent or guess versions.
- Prefer the existing package manager already used in the repo.

## Code quality

- Match the existing style and conventions of the file/project you're in.
  Don't impose preferences from other projects.
- Use type hints / type annotations in any language that supports them
  (TS strict, Python with type hints, etc.) for new code.
- After substantive edits, check for and fix any linter errors you
  introduced. Leave pre-existing lints alone unless I ask.
- Add logging at meaningful boundaries, especially in long or multi-step
  workflows (agent pipelines, background jobs, async tasks, retries).
  Log inputs/outputs of each major step, errors with context, and any
  state transitions that would be needed to debug a failed run after the
  fact. Use the project's existing logger / log format - don't `print()`
  into production code paths.

## Tools & shell

- Use specialized tools (read/edit/search) for file operations rather
  than `cat`/`sed`/`awk`/`grep` in the shell.
- Don't run long-lived shell commands without confirming.

## Destructive operations

- Never run destructive data or system operations without explicit
  confirmation from me, even when they seem implied by the task. This
  includes: database drops/truncates, schema migrations, mass row
  deletes or updates without a `WHERE` clause, `rm -rf` on real paths,
  force pushes, history rewrites, and bulk file deletions.
- If a task seems to require one of the above, stop and ask first,
  describing exactly what will be affected.

## Scope discipline

- Do what was asked. If you notice unrelated issues, mention them at the
  end instead of fixing them inline.
- Don't expand the task into "while we're here, let's also..." without
  asking first.
- If my request seems incoherent, internally contradictory, or unclear
  (conflicting requirements, vague scope, ambiguous target, reasoning
  that doesn't follow), stop and ask clarifying questions before
  implementing anything. Don't try to guess my intent or pick the
  "most likely" interpretation on a non-trivial task.
