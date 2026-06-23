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

## 2026-06-23 — Coverage rules are composable; engine evaluates by fixed phase order

**Context:** A real policy says things like "physiotherapy is covered
up to $1,000/year with a $20 copay" — that's coverage + a limit +
cost-sharing all attached to one service type. Question: do we bundle
these into one fat rule per service type, or model each as its own row?

**Options considered:**

- One row per `(policy, service_type)` bundling coverage flag, limit,
  copay, etc.
- Many composable rows per `(policy, service_type)` of different
  `kind`s (`service_covered`, `annual_limit`, `copay`, etc.). Engine
  pulls all rules for the service type and runs them in a fixed phase
  order.

**Choice:** Composable rows. The catalog of `kind`s starts small:
`service_covered`, `service_excluded`, `preauth_required`,
`annual_limit`, `copay`, `coinsurance`. The engine groups them into
six phases (eligibility → coverage → gates → limits → deductible →
cost-sharing) and processes them in that order, independent of how
rules are ordered in the DB.

**Reasoning:**

- Adding a new rule kind (e.g. visit-count limit, network restriction)
  is a new row type, not a schema change to a fat record.
- Each rule row carries only the fields it needs; no nullable
  parameter soup.
- The fixed phase order is what makes the engine explainable —
  reviewers (and the UI) can show every phase that ran, in order, with
  the rule that fired at each step.

---

## 2026-06-23 — Cost-sharing precedence: deductible → limits-as-cap → cost-sharing; over-limit does not count toward deductible

**Context:** Once a line item is covered, several things compete for
the dollars: the annual deductible, an annual cap, a copay or
coinsurance. The order in which they apply changes the math.

**Options considered:**

- Cost-sharing first, then deductible on the residual.
- Deductible first, then cost-sharing on the residual; limit caps the
  *coverable* amount before any cost-sharing is applied.

**Choice:**

1. Deductible eats first (member-paid, plan contributes nothing to
   it).
2. Annual limit caps the *coverable* amount on the remainder. The
   overage is straight member-pay.
3. Cost-sharing (copay or coinsurance) applies only to the coverable
   portion.
4. **Over-limit amounts do not count toward the deductible.**
5. Line items within a claim are processed in submission order, so
   accumulator updates from earlier items are visible to later ones.

**Reasoning:**

- Matches the typical real-world precedence on US-style health plans:
  the deductible is an out-of-pocket threshold the member has to clear
  before plan-side cost-sharing applies.
- Treating limit overages as uncovered means they shouldn't help the
  member fulfill a *plan-side* obligation (the deductible). Anything
  else would let the member "use" overages to meet the deductible
  faster, which doesn't match how plans work.
- Submission order is the only order present in the input; we don't
  need to invent a tie-breaker.

---

## 2026-06-23 — Claim adjudication state is derived from line items; only `paid_at` is stored

**Context:** Both claims and line items have lifecycles. The state of
a claim ("approved", "partially_approved", etc.) is a function of its
line items' states.

**Options considered:**

- Store claim state explicitly; update it on every line-item
  transition. Risk: it can drift from the line items if anything's
  ever missed.
- Compute claim state from line items at read time. Only the
  payment-issued timestamp (`paid_at`) is stored.

**Choice:** Compute. The claim's `adjudication_state` is derived from
line items every time it's needed. The only stored claim-status field
is `paid_at` (nullable).

**Reasoning:**

- Cannot drift — there's nothing to drift from.
- "Has it been paid" is a real external event that isn't derivable
  from line items, so it stays as a stored field.
- Trivially small data; recomputation cost is irrelevant.
- Read time becomes a single SQL group-by per claim; cacheable later
  if it ever matters.

---

## 2026-06-23 — Partial coverage is `approved` with reduced amount, not its own state

**Context:** A $150 physiotherapy line item where only $80 is covered
(annual cap met on the overage) — is that line item `approved`,
`partially_approved`, or something else?

**Options considered:**

- New `partially_approved` line-item state.
- Keep `approved`; encode the partial-ness as `payable_amount <
  charged_amount`, with the explanation explaining why.

**Choice:** Keep `approved`. Partial-ness lives in the amounts and
the explanation, not in the state.

**Reasoning:**

- Three-state outcomes (approved / denied / needs_review) are easier
  to reason about than four. The line item either has a payable
  amount (any amount, including less than charged) or it doesn't.
- The interesting information is already there: `payable_amount`,
  `member_responsibility`, and the explanation step describing the
  limit. A `partially_approved` state would just duplicate that.
- `partially_approved` still exists at the *claim* level — it's the
  derived state when a claim has a mix of approved + denied line
  items. That's a different concept and is genuinely useful at that
  level.

---

## 2026-06-23 — Accumulators are computed on demand, not stored

**Context:** Annual limits and deductibles need to know how much has
been used year-to-date. Question: keep a running tally somewhere, or
compute it each time?

**Options considered:**

- Maintain an `Accumulator` table updated transactionally on each
  approval.
- Compute on demand by summing `payable_amount` over current,
  approved `AdjudicationDecision` rows scoped to the member, service
  type, and period.

**Choice:** Compute on demand. No `Accumulator` table.

**Reasoning:**

- Single source of truth: the decisions themselves. No risk of the
  accumulator drifting from the underlying truth.
- Re-adjudication (dispute → new decision supersedes old) just
  changes which decision is "current" — the accumulator query
  naturally picks up the right answer with no extra bookkeeping.
- Data volumes for this take-home are tiny; performance is not a
  concern. If it ever became one, we can materialize the same query
  as a view or a cache.

---

## 2026-06-23 — Adjudication decisions are immutable; re-decisions supersede via `supersedes_id`

**Context:** Disputes, manual overrides, and re-adjudication all
change a line item's decision. We need to keep the history without
losing the original decision.

**Options considered:**

- Mutate the existing `AdjudicationDecision` row in place; keep
  history in `AuditEvent` only.
- Make `AdjudicationDecision` append-only. New decisions are inserted
  with `supersedes_id` pointing at the previous current row. The line
  item's "current" decision is the one no other row supersedes.

**Choice:** Append-only with `supersedes_id`.

**Reasoning:**

- A decision is an output the member was once shown; rewriting it in
  place is misleading. Keeping the full chain visible is honest.
- The accumulator query becomes "sum over *current* approved
  decisions" — naturally handles disputes that flip an approval to a
  denial (the old decision is no longer current and stops counting).
- `AuditEvent` carries the *why*; `AdjudicationDecision` history
  carries the *what*. Different purposes, both kept.

---

## 2026-06-23 — Money modeled as `Decimal`

**Context:** Floating point for currency is a classic bug source.

**Choice:** All monetary fields are `Decimal` end-to-end:
SQLAlchemy `Numeric`, Pydantic `Decimal`, Python `Decimal`. Two-place
rounding (banker's rounding) at each math step.

**Reasoning:** Standard practice. Avoids drift like
`80 - 16.000000000000004`. Cost is negligible.

---

## 2026-06-23 — Disputes are always resolved by a human, never auto-re-adjudicated

**Context:** When a member disputes a line item decision, the line
item goes back to `needs_review`. Question: does the engine try to
auto-re-adjudicate (re-run the rules), or does the line item stay in
`needs_review` until a human writes a new decision?

**Options considered:**

- Auto-re-adjudicate. The engine re-runs the pipeline. If inputs
  haven't changed, the answer is identical and the dispute is
  effectively rejected by the machine.
- Human-only resolution. Filing a dispute always parks the line item
  in `needs_review`; only a reviewer can write the next decision.

**Choice:** Human-only resolution. The engine never resolves a
`needs_review` line item — neither for gate-failure cases (e.g.
missing preauth) nor for disputes. A new
`AdjudicationDecision` written by a reviewer (with
`decided_by = "reviewer:<id>"`) supersedes the previous current
decision and transitions the line item out of `needs_review`.

**Reasoning:**

- Disputes are by definition the member objecting to the rules'
  output. Re-running the same rules on the same inputs adds no
  information; pretending otherwise would be theatre.
- The valuable thing a dispute surfaces is *human review with new
  context* (a missed preauth, a misclassified service type, an
  exception the policy administrator wants to grant). Modeling that
  explicitly is more honest than pretending the engine can self-correct.
- Keeps the engine's contract simple: the engine writes decisions
  with `decided_by = "system"`; humans write decisions with
  `decided_by = "reviewer:<id>"`. No mixed cases.
- The UI surface this implies is small: a "review this line item"
  action that lets a reviewer pick approved/denied, edit the payable
  amount, and write a note. That fits the take-home scope.

---

## 2026-06-23 — Calendar year is the only supported limit period

**Context:** `annual_limit` rules carry a `period` field. Real plans
also have plan years (start date independent of January 1) and rolling
12-month windows.

**Choice:** The engine only accepts `period: "calendar_year"` for now.
The field stays on the rule schema so adding more period kinds later
is a non-breaking change.

**Reasoning:**

- Calendar year is the most common case and the easiest to verify in
  a demo (the year boundary is the only edge to test).
- Other period kinds change only the date-range function used by the
  accumulator query — the rest of the engine doesn't care.
- Keeping `period` in the schema means seed data and stored rules are
  forward-compatible; we just narrow the accepted values right now.

---

## 2026-06-23 — Explicitly deferred for the take-home (visit-count limits, Preauth entity, Provider entity, post-paid reopens)

**Context:** Four things came up during planning that we *could*
model but that don't earn signal proportional to the time they'd cost.
Tracking them here so the reviewer can see they were considered.

**Deferred:**

1. **Visit-count limits** (e.g. "20 physio visits/year"). Same shape
   as `annual_limit` but counting line items instead of summing
   dollars. New rule kind, otherwise mechanical. Skipped because
   dollar-cap limits already exercise the same accumulator + partial
   approval path; visit counts wouldn't add a new pattern.
2. **Preauthorization as an entity.** Currently a string `preauth_ref`
   on `LineItem` whose presence is the only thing the gate checks.
   Promoting it would let us model issuance, expiry, scope —
   realistic but out of scope. The current string is enough to
   exercise the `needs_review` flow end-to-end.
3. **Provider as an entity.** Currently a string `provider_name` on
   `Claim`. Promoting it would unlock network/tier-based rules
   (in-network vs out-of-network coinsurance), which is a separate
   modelling exercise we don't need to show domain decomposition.
4. **Reopening a claim after `paid`.** We assume disputes occur before
   payment. Supporting post-payment reopens would require either a
   separate `reopened_at` field or modelling payments as a first-class
   entity with reversal events. Cleaner to defer than to half-build.

**Reasoning:** Each of these is real future work, none of them changes
the *shape* of the model meaningfully. The interview rubric values
domain decomposition, rule representation, state management, edge
cases, and explanations — the deferred items don't unlock new signal
in any of those dimensions for the time they'd cost. They're listed
in `docs/domain-model.md` under "Explicitly deferred" so the reviewer
can see they were considered.

---

## 2026-06-23 — Out-of-pocket maximum (OOPM) deferred

**Context:** OOPM is a near-universal field on real US health plans
(commonly $5k–$10k for an individual). Once a member's year-to-date
cost-sharing hits the OOPM, the plan pays 100% of further covered
charges — deductible-eligible amounts, copays, and coinsurance no
longer apply for the rest of the period.

**Options considered:**

- Model it. Add `annual_oopm` to `Policy`, maintain a member-scoped
  OOPM accumulator alongside the existing limit accumulator, and have
  the cost-sharing phase short-circuit member share to zero once the
  cap is hit.
- Defer. Acknowledge it's missing in `domain-model.md`'s "Explicitly
  deferred" table; note that nothing in the engine prevents adding it
  later.

**Choice:** Defer.

**Reasoning:**

- An OOPM accumulator has the same query shape as the existing limit
  accumulator (sum payable-equivalent over current approved decisions,
  member-scoped, period-scoped). Building it exercises no new
  domain-modelling pattern the engine doesn't already demonstrate.
- The rubric values domain decomposition, rule representation, state
  management, edge cases, and explanations — none of those dimensions
  is unlocked by adding OOPM. Same reasoning that deferred visit-count
  limits and the Provider entity.
- Forward-compatible: `annual_oopm` is a non-breaking nullable column
  on `Policy` later, and an OOPM short-circuit step can be added in
  front of copay/coinsurance in the cost-sharing phase without
  changing the explanation format or any other phase.

---

## 2026-06-23 — Cost-sharing is mutually exclusive: copay OR coinsurance per `(policy, service_type)`, not both

**Context:** The original `CoverageRule` invariant said "at most one
rule of *each* cost-sharing kind per `(policy, service_type)`," which
allowed a copay rule and a coinsurance rule to coexist on the same
service. Real plans sometimes do this ("$250 ER copay + 20%
coinsurance"). The engine's cost-sharing phase, however, is written
as if a single rule applies — `member_cost_share = cost_sharing_rule(
coverable)`. The two were soft-mismatched.

**Options considered:**

- **Define stacking math.** Pick a precedence (e.g. copay first, then
  coinsurance on the remainder, or vice versa) and bake it into the
  engine. Cost-sharing phase fires both steps when both rules exist
  and the explanation shows two cost-sharing lines.
- **Forbid the combination.** Tighten the invariant to "at most one
  cost-sharing rule (`copay` *or* `coinsurance`, not both) per
  `(policy, service_type)`." Cost-sharing phase fires at most one
  rule per line item.

**Choice:** Forbid. Invariant tightened in `docs/domain-model.md`.

**Reasoning:**

- Real-world stacking rules vary by plan; there is no canonical
  precedence. Hardcoding one would be opinionated and would not
  generalise to other plans the reviewer might imagine.
- Tightening the invariant makes schema and engine agree, rather than
  papering over the soft mismatch with defensive code or undefined
  behaviour.
- Keeps the explanation clean: every cost-sharing step cites exactly
  one rule. The drill-down stays one-step-per-phase, which is the
  property that makes the engine explainable.
- Seed data already respects this — no service in any of the three
  planned policies uses both kinds — so it is a schema-tightening
  change, not a behavioural one.
- If a future plan genuinely needed stacked cost-sharing, the right
  move would be a new rule `kind` (e.g. `copay_plus_coinsurance`)
  carrying both parameters with explicit math, not retrofitting two
  existing rules to stack. Each rule kind stays unambiguous.

---

## 2026-06-23 — Seed data is YAML in `data/`, loaded on first startup; DB persists across restarts; reset via CLI

**Context:** Need to ship reproducible sample data — three policies
with full coverage-rule sets, plus sample members and claims — to a
reviewer who clones the repo. The SQLite DB file is gitignored
(`*.db` in `.gitignore` with the comment "we ship seed data, not a
populated DB"), so seed data has to live in the repo as text files
and be loaded into a fresh DB on first run.

**Options considered:**

- **Seed-as-code.** A `seed.py` module with policies, rules, members,
  and claims as Python literals; called from startup.
- **Seed-as-data: YAML files** under `data/`, validated against
  Pydantic models and inserted by a loader.
- **Seed-as-data: JSON files** in the same place.
- **SQL fixtures or Alembic data migration.**
- Loading strategy: **reset on every startup** vs **auto-seed only
  when DB is empty** (and persist across restarts) vs **manual seed
  CLI only**.

**Choice:**

- YAML files under `data/`: `policies.yaml` (policies + their rules),
  `members.yaml`, `claims.yaml`. Money fields quoted as strings to
  keep `Decimal` parsing exact.
- A loader in `app/persistence/seed.py` validates each file against
  Pydantic models matching the rule-kind catalogue, then inserts in
  dependency order (Member → Policy → CoverageRule → Claim →
  LineItem) inside a single transaction.
- FastAPI startup hook calls the loader iff the `policies` table is
  empty. Otherwise the DB persists across restarts.
- A separate command, `uv run python -m app.scripts.reset_db`, drops
  all tables and re-seeds. Documented in the README under "if you
  want to start over."

**Reasoning:**

- **Coverage rules are already declared "data, not code"** (earlier
  entry). Encoding rules as Python literals in a `seed.py` would
  contradict that decision. YAML lets the reviewer open one file,
  change `cap_amount: "2000.00"` to `"500.00"`, restart, and observe
  the engine produce a different outcome — that *is* the demo of a
  data-driven engine.
- **YAML over JSON** because rule `parameters` are heterogeneous per
  `kind`; indented YAML is easier to scan and edit than JSON's
  punctuation. JSON would also force string-quoting on every key.
- **Money quoted as strings** because YAML's native float parsing
  silently coerces `1500.00` to `1500.0` (and worse for repeating
  decimals); quoting keeps the source-of-truth a string until
  `Decimal()` parses it.
- **Validate via Pydantic in the loader** so seed-data errors surface
  at startup with a clear message instead of as a `KeyError` deep
  inside the engine days later.
- **Auto-seed-on-empty + CLI reset** is the right ergonomics for a
  reviewer: realistic by default (they submit a claim, restart the
  server, the claim is still there), with a single documented command
  to wipe the slate. Reset-on-every-startup would lose the
  "submit-and-it-persists" demo. Manual-seed-only would mean the
  reviewer has to run an extra step before the app is usable.
- **Idempotent loader** (skip if `policies` table is non-empty) means
  there is no "re-seed?" prompt or ambiguity.

**Out of scope for the loader (deferred):**

- Schema migrations via Alembic. For the take-home, SQLAlchemy
  `Base.metadata.create_all()` on startup is sufficient — the schema
  is small, the DB is throwaway, and a reviewer never carries data
  across schema changes. Alembic would be the right move if this
  went production.

---

## 2026-06-23 — Sample data: 3 members one-per-policy, ~13 curated claims covering every engine path

**Context:** Need to seed enough data for a reviewer to see every
engine behaviour (covered, partial via cap, denied, `needs_review`,
within-claim accumulator, cross-claim accumulator, cross-plan outcome
difference) without burying them in noise. The seed has to be small
enough to read in one sitting and complete enough that no engine
path is implicitly "untested by the demo."

**Options considered:**

- **Minimal:** 1–2 claims per member, happy-path only. Reviewer has
  to file claims via the UI to see anything interesting.
- **Comprehensive:** many claims per member combinatorially
  exercising every rule.
- **Curated per-path:** one claim per distinct engine path,
  hand-designed.

**Choice:** curated per-path.

- **3 members**, one per policy: Alice → BASIC, Bob → PREMIUM, Carol
  → DENTAL. One policy per member.
- **~13 claims** designed so every engine path appears at least
  once:
  - Pure covered, no cost-sharing (preventive dental)
  - Deductible absorbs the entire charge (`plan_pays = 0`)
  - Deductible filled mid-claim then coinsurance applies on the
    remainder
  - Multi-line-item claim with accumulator updating between lines
  - Cross-claim accumulator (an earlier claim consumes a cap; the
    next one hits zero remaining)
  - Annual-cap partial coverage with over-limit going to member
  - Hard exclusion → `denied`
  - Missing preauth → `needs_review` (only path the engine produces
    `needs_review`)
  - Same service, different outcome across plans (bariatric surgery
    excluded in BASIC, covered with preauth in PREMIUM)
- Two seed claims marked `paid_at` so the `paid` claim lifecycle
  state is visible from the first page load.

**Reasoning:**

- **Curated > comprehensive** because the rubric values "is every
  domain behaviour exercised" more than "is every rule combinatorially
  enumerated." A short list of well-chosen claims is more legible
  than a long list of random ones.
- **Curated > minimal** because making the reviewer file claims to
  see interesting outcomes hides the engine's range and risks
  looking underbuilt.
- **One member per policy** keeps the mental model simple — "Alice
  has BASIC, Bob has PREMIUM, Carol has DENTAL" — and makes the
  cross-policy comparison demo (same bariatric surgery, different
  outcomes) read as "look how the same service hits different rules
  under different plans."
- **`paid_at` set on two seed claims** means the `paid` lifecycle
  state has an instance on first launch; reviewer doesn't have to
  manually pay a claim to see what `paid` looks like.

The full claim table (which line items per claim, with what charges)
lives outside this log so it can evolve inside `data/claims.yaml`
during implementation. The shape and the coverage matrix are what's
frozen here.

---

## 2026-06-23 — Persistence layer: SQLAlchemy 2.x, separated domain/ORM, functional repos, per-request session, `create_all` + reset CLI

**Context:** With the domain model, rule schema, and seed-data
format locked in, the persistence layer needs to bridge pure domain
entities to a SQLite-backed store while preserving the architectural
rules already established (domain layer has no DB or HTTP imports;
"rules are data, not code").

This entry bundles eight tightly-coupled sub-decisions in one place
because splitting them would force a reader to chase four entries to
understand any one of them.

**Sub-decision A — ORM: SQLAlchemy 2.x with typed `Mapped[...]`
columns.** Aligns with project-wide "type hints required" rule; gives
mypy/pyright proper coverage on the persistence layer.

**Sub-decision B — Domain ↔ ORM separation: two classes per entity
with translation at the boundary.**

- Domain entity: `@dataclass(frozen=True)` in
  `app/domain/entities.py`. Pure Python.
- ORM model: SQLAlchemy declarative class in
  `app/persistence/models.py` with `to_domain()` / `from_domain()`
  classmethods.
- Repositories return *domain* objects, never ORM models.

Reasoning:

- `AGENTS.md` mandates the domain layer has no DB imports.
  Separation is the mechanical enforcement.
- Frozen dataclasses force explicit mutation — no stealth attribute
  writes that secretly hit the DB on commit. The adjudication engine
  becomes a pure function: takes domain objects, returns an
  `AdjudicationResult` value object.
- Engine tests need no fixtures, no in-memory DB, no session — plain
  Python objects only.
- Translation cost is ~100 mechanical lines across the ~8 entities,
  upfront and finite.

**Sub-decision C — Repository pattern: module-level functions taking
a `Session` parameter, returning domain objects.**

Examples: `get_policy_by_id(session, policy_id) -> Policy`,
`get_active_policy_for(session, member_id, on_date) -> Policy`,
`sum_payable_for_accumulator(session, member_id, service_type,
period_start, period_end, before) -> Decimal`.

Reasoning: no shared state; functions are simpler than classes for
this size; the accumulator query is a SQL aggregate, naturally a
repo concern — the engine never builds it itself.

**Sub-decision D — Session handling: FastAPI `Depends(get_session)`,
per-request transaction.** Commit on success, rollback on exception.
Single transaction per HTTP request — guarantees the
`AdjudicationDecision` row and the `AuditEvent` row land atomically
together.

**Sub-decision E — Schema management: `Base.metadata.create_all()`
at app startup; no Alembic. Schema changes require running
`uv run python -m app.scripts.reset_db`.**

Reasoning:

- DB is gitignored; every reviewer creates a fresh DB on first run;
  no shared environment with persistent data.
- YAML is the source of truth; `reset_db` drops, recreates the
  schema from the current models, and re-seeds from YAML. Loses
  nothing.
- Alembic is the right answer for production; adding it later is
  non-breaking (it reads from the same declarative base).
- `create_all()` is additive-only against an existing DB, so the
  README explicitly tells the reviewer to run `reset_db` after any
  schema change.

**Sub-decision F — `CoverageRule.parameters` stored as a JSON
column.** `mapped_column(JSON)`. Validated by Pydantic at the
seed-loader boundary; engine assumes valid parameters internally.

Reasoning: SQLite has stable JSON support; parameter shapes are
heterogeneous per `kind`, so per-kind tables would be overkill;
boundary validation keeps engine reads fast and SQL simple.

**Sub-decision G — Audit events: explicit writes from the service
layer via a helper, not SQLAlchemy event listeners.**

Single helper `record_audit_event(session, event_type, entity_type,
entity_id, actor, payload)` in `app/persistence/audit.py`.

Reasoning: explicit beats magical. The audit log is a deliberate
output the reviewer will inspect; encoding it as `after_update` side
effects makes "where does this event come from" hard to trace.
Atomicity is preserved by the per-request transaction (D). Easier
to test — a service test asserts the right event was recorded by
inspecting the session.

**Sub-decision H — File layout under `app/persistence/`.**

```text
app/persistence/
├── __init__.py
├── database.py         # engine, SessionLocal, get_session dependency, Base
├── models.py           # SQLAlchemy ORM classes + to_domain/from_domain
├── repositories.py     # functions, grouped by entity within the file
├── seed.py             # YAML loader
└── audit.py            # record_audit_event helper
```

The reset entrypoint lives at `app/scripts/reset_db.py` so it's
discoverable as a CLI script, not buried in the persistence package.

**Why bundle these eight?** They're mutually-reinforcing: the
domain ↔ ORM separation (B) is what lets repositories return domain
objects (C); functional repos work because session handling is
uniform (D); explicit audit writes (G) work because per-request
transactions (D) guarantee atomicity; JSON parameters (F) work
because Pydantic validation lives in the seed loader. Keeping them
together makes the persistence story readable as one narrative
instead of eight disconnected fragments.

---

<!--
Future entries below. Format:

## YYYY-MM-DD — <short title>

**Context:** ...

**Options considered:** ...

**Choice:** ...

**Reasoning:** ...
-->
