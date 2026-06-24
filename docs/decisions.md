# Decisions

What was built, what was skipped, and why. Each dated entry below
captures **context**, **options considered**, **choice**, and
**reasoning** for a non-trivial call made during the build.

---

## Summary

### What shipped

| Layer | Delivered |
|---|---|
| **Backend** | Python 3.11+, FastAPI, SQLAlchemy 2.x, SQLite. Pure domain layer (`app/domain/`), rules engine (`app/adjudication/`), persistence + YAML seed loader (`app/persistence/`), REST API (`app/api/`). |
| **Frontend** | **QuickClaim** — Vite + React + TypeScript SPA: claims list (member filter), claim drill-down (line items, coverage decisions, audit timeline), submit form. |
| **Data** | Three members, three policies (32 coverage rules), 13 curated seed claims in `data/*.yaml`. DB file is gitignored; auto-seeds on first launch. |
| **Tests** | ~202 pytest (domain, persistence, engine, API, scripts) + 29 Vitest (formatters, API client, component smoke tests). Tests land in the same commit as the code they cover. |
| **Tooling** | `uv` + lockfile, `reset_db` CLI, raw Cursor JSONL logs in `ai-artifacts/`. |

### Application flow (logic)

```text
Startup (lifespan)
  ├─ create_all()          — SQLite schema from ORM models
  ├─ seed_if_empty()       — load data/*.yaml when policies table is empty
  └─ adjudicate_all_pending() — decide every pending line item before HTTP serves
       (order: claim.submitted_at, then line_item.id)

GET /api/claims[?member_id=]
  └─ derive claim.adjudication_state from line items + paid_at; roll up money

GET /api/claims/{id}
  └─ line items + current AdjudicationDecision (explanation JSON) + merged audit timeline

POST /api/claims
  ├─ validate member exists (else 404)
  ├─ insert claim + line items (status: pending)
  ├─ audit: claim.submitted
  └─ for each line item in submission order:
       adjudicate_line_item()
         ├─ load active policy for claim.service_date
         ├─ engine: eligibility → coverage → gates → deductible → limits → cost-sharing
         ├─ insert AdjudicationDecision (immutable; supersedes_id chain for re-decisions)
         ├─ audit: line_item.decided
         └─ line item status mirrors decision outcome
  └─ return ClaimDetailOut (201) — including eligibility denials, not HTTP 422

GET /api/coverage-rules
  └─ rule catalog for denial tooltips (frontend joins rule_id → plain-English description)

POST /api/line-items/{id}/dispute
  ├─ validate line item exists (else 404); status must be approved or denied (else 409)
  ├─ reject if an open dispute already exists (409)
  ├─ insert Dispute (status: open); line item → needs_review
  ├─ audit: dispute.filed, line_item.state_changed
  └─ return ClaimDetailOut (201) — current AdjudicationDecision unchanged until reviewer resolves

reset_db CLI
  └─ drop tables → create_all → re-seed → adjudicate_all_pending (same end state as startup)
```

Per-line-item engine behaviour, cost-sharing math, and explanation shape
are specified in [`domain-model.md`](domain-model.md). Claim
`adjudication_state` is **derived** at read time from line items; only
`paid_at` is stored as a claim-level status marker.

### Built vs skipped

| Shipped | Not shipped (documented / deferred) |
|---|---|
| System adjudication of pending line items | Dispute resolution, reviewer override UI, mark-claim-paid API |
| Structured per-phase explanations on every decision | Auth, pagination, email, admin panels |
| Audit log (claim submit, line item decided, dispute filed) | `dispute.resolved`, `claim.paid` audit events |
| Submit + list + drill-down UI with rule tooltips | Visit-count limits, OOPM, plan-year / rolling limit periods |
| Dispute filing (`POST /api/line-items/{id}/dispute` + UI modal) | Provider / Preauthorization as first-class entities |
| Seed `paid_at` on two claims for demo of `paid` state | Post-payment dispute / claim reopen |
| `Dispute` entity + ORM (forward-compatible schema) | Alembic migrations (throwaway DB + `reset_db`) |

Full deferral reasoning lives in the dated entries below and in
`domain-model.md` § Explicitly deferred.

### Assumptions

- **No diagnosis codes (ICD-10) on claims.** The brief cites them as PHI
  context; we adjudicate on `service_type` + `service_description` only.
- **One active policy per member per `service_date`.** No overlapping
  policy windows; the engine picks the policy active on the claim's
  service date.
- **Calendar year is the only supported limit period.** `annual_limit`
  rules carry `period: "calendar_year"`; other period kinds are schema-ready
  but rejected by the engine.
- **Deductible is member-scoped across all service types; limits are
  service-type-scoped.** See the 2026-06-24 deductible-accumulator entry.
- **Line items process in submission order** within a claim, and the
  startup batch uses `(claim.submitted_at, line_item.id)` across claims so
  accumulator math is deterministic.
- **Disputes occur before payment.** `paid_at` is set only on seed data
  for demo; there is no HTTP route to mark a claim paid or reopen one.
- **Members can file disputes; reviewers cannot resolve them in this
  build.** Filing moves the line item to `needs_review` and writes
  `dispute.filed` + `line_item.state_changed`. The current
  `AdjudicationDecision` is left in place until a reviewer writes a
  superseding decision (no reviewer API).
- **Human-only resolution for `needs_review`.** The engine writes
  `decided_by = "system"`; gate failures and filed disputes stay in
  review until a reviewer supersedes the decision.
- **Out-of-scope per spec:** auth, enrollment, member/provider account
  management, notifications, analytics, multi-tenancy.
- **Naive UTC datetimes** throughout — SQLite strips `tzinfo` on
  round-trip; all `datetime` fields are treated as UTC.
- **Synchronous submit:** `POST /api/claims` creates the claim and
  adjudicates every line item in the same request/transaction before
  returning.

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

## 2026-06-24 — Phase 06 engine pre-flight: deductible before limits, eligibility as a real phase, `deductible_applied` stored on `AdjudicationDecision`

**Context:** With the engine being built in phase 06, three open
questions surfaced while re-reading the planning docs and the
domain rules together: (a) the *Evaluation pipeline* table in
`docs/domain-model.md` had `limits` (phase 4) before `deductible`
(phase 5), but the "Cost-sharing precedence" entry above and the
cost-sharing math formula
(`coverable = min(post_deductible, limit_remaining)`) both have
deductible eating first; (b) the engine's task description in the
phase-06 chat did not mention eligibility, but the domain spec
listed it as phase 1 and the `Claim` invariant requires
`service_date` to fall inside the active policy's window; (c) the
deductible accumulator is member-scoped and cross-service-type, but
the existing accumulator query (`sum_payable_for_accumulator`) is
service-type-scoped and operates on `payable_amount` — and
`payable_amount` is not enough to recover `deductible_taken` for
prior decisions (it collapses deductible + cost-share + over-limit
into a single number).

This entry locks all three before any engine code lands.

**Sub-decision A — Phase order: deductible runs *before* limits.**

The cost-sharing math formula and the earlier "Cost-sharing
precedence" entry are the source of truth. The phase table
previously had them reversed; that was a documentation bug, now
fixed in `docs/domain-model.md`. The order the engine walks:

1. eligibility
2. coverage (including `service_excluded` short-circuit)
3. gates (preauth)
4. **deductible**
5. **limits**
6. cost-sharing (copay or coinsurance)

Reasoning: the math is the contract, the phase table is a summary
of the math. The two were soft-mismatched; pick the math, rewrite
the table. The ordering matters in a concrete case: on a $1,500
MRI charged against $500 deductible-remaining and $0
limit-remaining, deductible-first puts $500 toward the deductible
accumulator and the remaining $1,000 to over-limit member-pay;
limit-first would put the whole $1,500 to over-limit and advance
the deductible accumulator by $0. The "over-limit amounts do not
count toward the deductible" invariant still holds — that rule is
about the *post-deductible* over-limit portion, not about the
entire charge.

**Sub-decision B — Eligibility is a real phase that can produce
`denied`.**

When no policy is active for the claim's member on
`claim.service_date`, the engine writes a decision with
`outcome = denied`, an `ELIGIBILITY` step marked `result: "fail"`
with `terminating: true`, and amounts `payable_amount = 0`,
`member_responsibility = charged_amount`.

Reasoning: the spec already lists eligibility as phase 1. Making
it a real engine phase means a missing-policy scenario produces a
normal explainable denial through the same path every other
denial uses, rather than the engine raising an exception that the
API would later have to map to a 422 by hand. The seed data never
triggers it (all 13 claims have active policies on their
`service_date`), but the engine's contract becomes total over its
inputs — which matters for the API path in phase 07, where claims
arrive without any guarantee of an active policy.

**Sub-decision C — Store `deductible_applied` on
`AdjudicationDecision`.**

Add a `deductible_applied: Decimal` column to
`AdjudicationDecisionModel` and the corresponding domain entity,
plus a repo function
`sum_deductible_applied(session, member_id, period_start,
period_end, exclude_line_item_id=None)` returning the sum of
`deductible_applied` over current approved decisions for the
member whose claim's `service_date` falls in the period. The
change lands in phase 06 step 3 (service layer), before any
decision rows exist in any environment — `reset_db` re-seeds from
YAML, so there is no migration concern.

**Options considered:**

- **Column on the decision row.** One extra `Decimal` field, one
  extra repo function. Queryable in SQL; durable across changes
  to the explanation format.
- **Read `deductible_applied` out of prior decisions' `explanation`
  JSON.** No schema change, but couples the accumulator math to
  the explanation format. The explanation is a presentation
  concern; treating it as a queryable store mixes layers.

**Choice:** column. The explanation step still records the
deductible amount for the UI; the accumulator math reads from the
column. Same trade-off shape as `paid_at` on `Claim` — a
derived-but-frequently-queried number is stored when the
alternative is JSON parsing on the read path.

**Why bundle these three?** They're the only design questions the
engine pipeline raised that aren't already answered in earlier
entries. Each is small individually; together they form the
engine's ground rules before any phase code lands.

---

## 2026-06-24 — Phase 06 engine implementation: audit shape, supersession, startup hook, no engine-driven re-adjudication

**Context:** Building the engine + service + startup batch surfaced
four implementation-level calls that the pre-flight entry didn't
cover. They're individually small but each shapes how downstream
phases (API, frontend, review tooling) will interact with the
engine, so they belong in the log.

**Sub-decision A — One `line_item.decided` audit event per
adjudication, payload carries the state transition.**

`adjudicate_line_item` writes exactly one audit row each time it
runs. Event type is `line_item.decided`; entity is the line item;
payload includes `decision_id`, `outcome`, `previous_status`,
`new_status`, `payable_amount`, `member_responsibility`,
`deductible_applied`, and `supersedes_id`.

**Options considered:**

- One event per phase (six per call). Captures pipeline detail but
  duplicates the explanation JSON we already store on the decision
  row, blows up audit volume, and offers nothing the explanation
  doesn't already.
- One event per state transition (chosen). Matches the audit
  helper's design (`record_audit_event` per intentional write),
  keeps the audit log small enough to read end-to-end, and lets
  the API show a clean "what changed when" timeline.
- No audit event from the engine; reviewer-only events. Loses the
  ability to tell "the system decided this" apart from "no one
  touched it yet."

**Choice:** one event per call. The explanation JSON already
captures per-phase detail; the audit log captures per-call state
transitions. Two surfaces, two purposes.

**Sub-decision B — Supersession contract: every new decision sets
`supersedes_id` to the previously-current decision; "current"
means no one points at me.**

The first decision for a line item has `supersedes_id = NULL`.
Every subsequent decision (which doesn't happen yet, but will once
disputes land) writes a new row with `supersedes_id` pointing at
the previously-current row. The "current" decision is read with a
self-anti-join: `WHERE NOT EXISTS (SELECT 1 FROM decisions s
WHERE s.supersedes_id = d.id)`. Same query
`get_current_decision_for_line_item` already used in phase 05.

**Reasoning:** append-only history with a single derivable "head"
is the same pattern claims use for state and the same shape the
accumulator queries already filter against. No timestamp races
(monotone `decided_at` isn't required), no need to mutate prior
rows. Disputes, reviewer overrides, and engine reruns all fit
this shape unchanged.

**Sub-decision C — Startup hook runs in a separate session and
transaction, *after* the seed commits.**

`app/main.py`'s lifespan opens a `SessionLocal()` for `seed_if_empty`
+ `commit`, closes it, then opens a *second* `SessionLocal()` for
`adjudicate_all_pending` + `commit`. Both failures abort startup
(uvicorn re-raises), so no HTTP request ever lands on a
half-initialised DB.

**Options considered:**

- Same session, same transaction. Atomic, but a failed
  adjudication rolls back the seed too — meaning the next startup
  re-seeds (idempotent, so fine in isolation) but if the
  adjudication bug is data-dependent, you're rolling back a
  perfectly-good seed every restart while you debug.
- Separate sessions, separate transactions (chosen). Seed commits
  first; adjudication failures don't undo it. The next startup
  finds the seed already in place (`seed_if_empty` no-ops) and
  retries adjudication.
- No commit; defer to first request. Means the "intermediate
  state never reaches the UI" requirement breaks if the first
  HTTP request races the adjudication.

**Choice:** separate transactions. The constraint that matters is
"no HTTP request lands on an unadjudicated line item," and the
lifespan's `yield` is what guards that — both transactions
complete before yield. Splitting them keeps debugging clean.

**Sub-decision D — The engine refuses to re-adjudicate
already-decided line items.**

`adjudicate_line_item` raises `AdjudicationError` if the line item
is anything other than `PENDING`. The startup batch's repo helper
(`list_pending_line_item_ids`) only returns pending ids, so the
batch never trips this. The API path (phase 07) will get the same
error if a caller tries to re-adjudicate without going through
the reviewer flow.

**Reasoning:** re-adjudication is a *reviewer* decision (the
human disputes path), not an engine decision. Letting the engine
silently overwrite a prior decision would erase the audit trail
of what changed and why. Forcing reviewers to mark the line item
as something other than `PENDING` first (or use a dedicated
reviewer endpoint that supersedes explicitly) makes the
provenance of every decision row obvious from its actor field.

The dispute/review flow itself was not built in this submission; the
engine contract documents what the engine *won't* do so a future
reviewer flow knows where its boundary is.

**Why bundle these four?** They're the small implementation
decisions that didn't need pre-flight discussion but matter for
anyone reading the engine code or the API contract. Each one's a
single paragraph elsewhere would scatter them; together they're
the implementation-half of the pre-flight entry above.

---

## 2026-06-24 — Phase split: 07-backend-api becomes its own phase, frontend shifts to 08

**Context:** The original phase tracker in `AGENTS.md` bundled
the HTTP routes into phase 07 alongside the React UI:

```
07-frontend — React UI
```

Phase 06 deliberately stopped at `adjudicate_line_item` — a Python
entry point, no HTTP. Building routes + UI in one chat would
either: blur the per-phase JSONL discipline, or force the route
design to follow the UI's needs rather than the domain's contract.

**Options considered:**

- **Keep routes inside phase 07 (rename `07-backend-api-and-frontend`).**
  One chat, one JSONL. Routes get designed against the UI's
  actual needs. Cost: one phase doing two things; the JSONL
  loses the per-phase clarity the AGENTS.md convention is built
  around.
- **Bolt routes onto phase 06.** Engine + routes together. Cost:
  phase 06's JSONL grows large and mixes domain logic with HTTP
  glue; the reviewer can't easily find "the engine chat."
- **Split into `07-backend-api` and `08-frontend` (chosen).** Two
  chats, two JSONLs. The API contract gets finalised before any
  UI code; the UI consumes a frozen contract rather than driving
  it.

**Choice:** split. Phase numbers shift: tests → 09, docs → 10,
qa → 11. Phase list and tracker in `AGENTS.md` updated to match.

**Reasoning:** the AGENTS.md convention is one chat per phase, one
JSONL per chat. Phase 06's chat already happened with the engine
scope alone; adding routes in the *same* chat retroactively isn't
possible. Splitting forward keeps the convention intact and gives
the reviewer one chat that explains "how was the HTTP contract
designed?" separately from "how was the UI built?" — useful when
those are different design conversations.

The seed already has every line item adjudicated at startup, so
phase 07 can be pure HTTP plumbing (route → repo/service → JSON
schema) with no engine re-design surface.

---

## 2026-06-24 — Phase 07 backend API: wire contract, audit exposure, submit flow

**Context:** Phase 06 left adjudication as a Python service entry point
(`adjudicate_line_item`) with no HTTP. Phase 07 adds the REST layer
the React UI (phase 08) will consume: list claims, drill into a claim,
submit a new claim, and read audit history. No domain or engine
changes — only route handlers, Pydantic schemas, and one new repo
query for merged audit timelines.

This entry bundles the API-shape decisions made during implementation.
Each is small on its own; together they define the contract the
frontend will build against.

**Sub-decision A — Pydantic schemas in `app/api/schemas.py`, kept
separate from domain entities.**

Route handlers translate at the boundary (`MemberOut.from_domain(...)`,
`ClaimDetailOut.from_domain(...)`). Domain dataclasses never import
FastAPI or Pydantic.

**Options considered:**

- Reuse domain entities as response models directly.
- Separate Pydantic models in `app/api/schemas.py` (chosen).

**Choice:** separate schemas.

**Reasoning:** the wire shape and the domain shape diverge in obvious
ways — claim payloads carry denormalized `member_name` and derived
`adjudication_state`, line items embed a nested `current_decision`,
and money on the explanation JSON is already stored as quoted strings.
Keeping schemas separate means the API can evolve (pagination fields,
UI-only rollups) without touching the engine or persistence layers.
The domain stays pure, which was a project invariant from day one.

**Sub-decision B — `GET /api/members` plus `member_name` on every
claim payload.**

The claim list and submit form both need member names. Without them,
the UI would either fetch `/api/members` on every list render and
join client-side, or show raw ids like `M-001`.

**Options considered:**

- Members endpoint only; UI joins by id.
- Denormalized `member_name` only; UI extracts members from the claim
  list.
- Both endpoint and denormalized name (chosen).

**Choice:** both.

**Reasoning:** `/api/members` is the natural source for dropdowns
(filter + submit picker). Denormalizing `member_name` onto
`ClaimSummaryOut` / `ClaimDetailOut` means the list view renders in
one round trip — the reviewer opening `/api/claims` in a browser or
the UI's first paint doesn't need a second fetch to turn ids into
names. The duplication is tiny (three members, one name string per
claim row) and read-only.

**Sub-decision C — Audit timeline embedded on the claim drill-down
*and* available via dedicated endpoints.**

`GET /api/claims/{id}` returns `audit_events[]` inline. Two additional
read-only routes expose the same data alone:
`GET /api/claims/{id}/audit` and
`GET /api/line-items/{line_item_id}/audit`.

**Options considered:**

- Dedicated endpoints only; detail view fetches audit separately.
- Embedded only; no dedicated routes.
- Both (chosen).

**Choice:** both.

**Reasoning:** the detail view wants history on first paint — one
fetch, no waterfall. A dedicated audit route is still useful when the
UI only needs to refresh the timeline after an action (or when
building a line-item-focused panel) without re-downloading every line
item and decision. Both paths call the same repo helpers, so they
cannot drift.

**Sub-decision D — `list_audit_events_for_claim` as one SQL query.**

The merged claim timeline interleaves claim-level events
(`claim.submitted`, future `claim.paid`) with line-item events
(`line_item.decided`) in chronological order.

**Options considered:**

- Fetch claim events and line-item events separately; merge and sort
  in Python.
- One query with an `OR` over `(entity_type, entity_id)` cases
  (chosen).

**Choice:** one query in `app/persistence/repositories.py`.

**Reasoning:** sorting belongs in one place. Two queries merged in
Python can disagree with the dedicated line-item endpoint on tie-break
order or miss events if someone adds a filter on one path and not the
other. The query is straightforward; the repo already had
`list_audit_events_for` for a single entity — this extends that pattern
to the parent claim plus all its line items.

**Sub-decision E — Server-generated ids on `POST /api/claims`.**

Pattern: `C-<uuid hex>` for the claim;
`L-<uuid hex>-001`, `L-<uuid hex>-002`, … for line items in
submission order.

**Options considered:**

- Client supplies ids (like the seed YAML does).
- Server generates opaque UUIDs (chosen).
- Server generates human-readable ids mimicking seed style
  (`C-ALICE-004`).

**Choice:** server UUIDs with a shared suffix and a numeric tail on
line items.

**Reasoning:** id generation is a server concern — clients should not
need to guarantee uniqueness or know the id format. UUIDs are simple
and collision-safe. The shared suffix plus `-001`, `-002` tail is a
small extra: `list_line_items_for_claim` orders by `line_item.id`, so
lexicographic id order matches submission order without an extra
`sequence` column. Human-readable ids would be cute in a demo but
add naming rules the API doesn't need.

**Sub-decision F — Unknown `member_id` → HTTP 404 on filter and submit.**

`GET /api/claims?member_id=…` and `POST /api/claims` both 404 when
the member does not exist.

**Options considered:**

- Filter: return an empty list for any string (including typos).
- Submit: let SQLite raise a foreign-key error → 500.
- 404 with the bad id in the detail (chosen).

**Choice:** 404 in both cases.

**Reasoning:** an empty list looks like "this member has no claims,"
which is a different thing from "this member id is wrong." A 404 makes
typos visible immediately. On submit, surfacing an `IntegrityError` as
500 would tell the reviewer nothing useful; validating up front keeps
errors intentional and readable.

**Sub-decision G — Eligibility failures are engine outcomes, not HTTP
4xx on submit.**

If `service_date` falls outside every active policy window, the engine's
eligibility phase writes a `denied` decision with an explanation step
(`result: fail`, `terminating: true`). `POST /api/claims` still
returns **201** with a full `ClaimDetailOut`.

**Options considered:**

- Reject the submit with 422 when no policy is active on
  `service_date`.
- Let the engine deny with a normal decision row (chosen).

**Choice:** engine denial, 201 response.

**Reasoning:** from the caller's perspective, the claim was accepted
and processed — the rules said no. That matches how every other denial
(coverage exclusion, exhausted limit) already works. A 422 would mix
"your JSON was invalid" with "your claim was valid but uncovered,"
which are different user-facing messages. The UI can read
`adjudication_state` and the explanation the same way for eligibility
denials as for coverage denials.

**Sub-decision H — `session.flush()` before the adjudication loop on
submit.**

After inserting the claim and line-item rows, the handler flushes the
session before calling `adjudicate_line_item` for each line item.

**Reasoning:** `adjudicate_line_item` loads the line item with
`session.get(...)`, which only sees flushed rows. Without an explicit
flush, the first adjudication call raises "line item not found" even
though the row is pending in the same transaction. The seed loader
already flushes between dependency layers for the same reason; submit
follows that pattern. The per-request transaction (`Depends(get_session)`)
still commits everything atomically on success — flush is visibility
inside the transaction, not an early commit.

**Sub-decision I — Route modules split by resource; `/api/hello`
removed.**

`routes_members.py`, `routes_claims.py`, `routes_audit.py`, plus
`schemas.py`. The phase-04 hello-world route was deleted once real
routes were wired.

**Reasoning:** one file per resource keeps handlers easy to find and
matches the repo layout described in planning. Hello was scaffolding
to prove CORS; keeping it would clutter OpenAPI and confuse the
reviewer about which endpoints are real.

**Sub-decision J — API tests use in-memory SQLite with `StaticPool`.**

The `api_client` fixture builds a fresh DB per test: schema from ORM
metadata, seed YAML loaded, startup adjudication batch run,
`get_session` overridden to bind the in-memory engine.

**Reasoning:** bare `sqlite:///:memory:` creates a *new* empty database
on every connection. Seeding on one connection and handling HTTP on
another silently produced "no such table" failures. `StaticPool` reuses
a single connection so seed data and route handlers see the same DB.
Skipping the production lifespan avoids double-seeding against the
real `claims.db` file on disk.

**Not shipped (no HTTP routes):** disputes, reviewer overrides,
marking a claim paid (`paid_at`), pagination, auth. The engine and
domain model support some of these; the REST layer does not expose
them.

---

## 2026-06-24 — Claim `paid` state: `paid_at` elevates only after adjudication finishes payable

**Context:** The 2026-06-23 entry established that claim adjudication
state is derived and only `paid_at` is stored. The first implementation
of `derive_claim_state` checked `paid_at` *before* line-item statuses.
Two seeded claims (`C-BOB-001`, `C-CAROL-001`) carry `paid_at` in YAML
while their line items start `pending` and are decided by the startup
batch. That ordering made the claim badge show **Paid** while line
items still showed **Pending** and totals were `$0.00` — a confusing
UI state even though the startup batch normally completes before HTTP
serves.

**Options considered:**

- **Keep `paid_at` first.** Simple rule: payment timestamp wins.
  Startup batch is supposed to hide the gap; document it and move on.
- **Evaluate line items first; `paid_at` elevates only from a payable
  base state (chosen).** Derive a base state from line items
  (`submitted`, `under_review`, `approved`, `denied`,
  `partially_approved`). Return `paid` only when `paid_at` is set
  *and* the base is `approved` or `partially_approved`.

**Choice:** line items first, then `paid_at` guard.

**Reasoning:**

- The original decision's intent — "`paid` means payment was issued
  on an adjudicated claim" — is clearer when adjudication has actually
  finished. A claim with all-`pending` line items is not meaningfully
  paid from the reviewer's perspective even if YAML carries a
  historical `paid_at`.
- Keeps the claim header badge, line-item rows, and money rollups
  consistent without relying on startup timing alone.
- `docs/domain-model.md` derivation rule updated to match. Domain
  tests replaced `test_paid_at_set_returns_paid_regardless_of_line_items`
  with cases for pending + paid_at → not paid, and approved +
  paid_at → paid.

**Still true from the 2026-06-23 entry:** claim state is never stored;
`paid_at` remains the only persisted payment marker; startup batch
still runs before `yield` so normal operation never serves
undecided line items.

---

## 2026-06-24 — Phase 08 frontend: QuickClaim SPA

**Context:** Phase 07 delivered the HTTP contract. Phase 08 replaced
the phase-04 hello-world stub with a working UI.

**Choice:** **QuickClaim** — a Vite + React + TypeScript SPA with
React Router:

- `/` — claims list with member filter (`GET /api/members`,
  `GET /api/claims`)
- `/claims/:id` — drill-down with summary, line items, per-line
  coverage decision breakdown, embedded audit timeline
  (`GET /api/claims/{id}`)
- `/submit` — submit form (`POST /api/claims`) navigates to the
  returned drill-down

Shared pieces: typed API client, money/date formatters, status badges,
loading/error states. User-facing copy avoids "adjudication" in favour
of "review" / "coverage decision" for readability.

**Reasoning:**

- One fetch per screen where the API already denormalizes enough for
  first paint (member names on claim rows, audit embedded on detail).
- No auth, disputes, or reviewer flows — matches the not-shipped list
  from phase 07; tagline states system-only review.
- Header layout: **QuickClaim** brand dominant; nav tabs (Claims,
  Submit claim) top-right on the same row.

**Supersedes:** phase 07 sub-decision I's note that "the frontend still
calls `/api/hello` until phase 08" — that stub is gone.

---

## 2026-06-24 — Coverage rule catalog API for denial tooltips

**Context:** Denied and gate-failure explanation steps cite a `rule_id`
(e.g. `R-BASIC-009`) but the wire explanation JSON does not embed the
full rule record (kind, parameters, policy name). The UI needs a
hover tooltip describing what the rule means in plain English.

**Options considered:**

- **Hardcode rule descriptions in the frontend** from `policies.yaml`.
  Fast but duplicates data and drifts when seed changes.
- **Embed rule metadata in every explanation step at engine time.**
  Enlarges persisted JSON for all decisions retroactively.
- **Read-only `GET /api/coverage-rules` (chosen).** One catalog fetch
  on app load; frontend joins `rule_id` → description for tooltips.

**Choice:** `GET /api/coverage-rules` returning `CoverageRuleOut[]`
with `policy_name`, `kind`, `parameters`, plus server-generated
`description` and `parameters_summary` from
`app/api/rule_descriptions.py`. Repo helper
`list_coverage_rules()` joins rules to policy names.

**Reasoning:**

- Keeps explanations unchanged on existing decision rows.
- Single source of truth stays the DB (loaded from YAML seed).
- Small addition to the HTTP layer during phase 08; no engine changes.

---

## 2026-06-24 — Frontend unit tests: Vitest + Testing Library

**Context:** Backend has ~197 pytest cases across domain, persistence,
engine, API, and scripts. The stack decision listed Vitest + RTL "if
time permits."

**Choice:** Vitest with jsdom, `@testing-library/react`, and
`npm test` / `npm test:watch`. Coverage (29 tests):

- `utils/format`, `utils/labels` — pure helpers
- `api/client` — fetch URLs, `ApiError`, 404/422 bodies (mocked
  `fetch`)
- `StatusBadge`, `Money`, `AuditTimeline` — component smoke tests

Page-level flows (`ClaimsListPage`, submit form, `RulesContext`) and
coverage-rules route HTTP tests were left out — backend coverage is
the primary bar; frontend tests target helpers and components most
likely to break during copy or formatting tweaks.

**Reasoning:** Behaviour-named backend tests encode domain rules; the
frontend suite guards the thin client layer without duplicating engine
coverage in the browser.

---

## 2026-06-24 — Dispute entity modeled; filing and resolution not shipped

**Context:** The domain model includes a full `Dispute` entity (fields,
invariants, state-machine transitions back to `needs_review`). The ORM
model and domain dataclass round-trip in tests. No dispute appears in
seed YAML, no repository helpers are wired into routes, and the
QuickClaim UI has no file-or-resolve flow.

**Options considered:**

- **Remove `Dispute` from the schema** until a dispute API is built.
  Smaller DB, but drops the forward-compatible shape and forces a
  migration if disputes land later.
- **Keep the entity in domain + persistence; defer the flow** (chosen).
  Document the gap explicitly so the model doc and the running app
  don't read as the same thing.

**Choice:** Entity and table exist; the end-to-end dispute flow is not
shipped. The human-only resolution contract (2026-06-23 entry) still
applies: filing would move a line item to `needs_review`; resolving
would write a superseding `AdjudicationDecision` with
`decided_by = "reviewer:<id>"`.

> **Superseded for filing** by the 2026-06-25 entry below. Dispute
> filing is now shipped; resolution remains deferred.

**Reasoning:** Modeling disputes in the domain shows the lifecycle was
thought through — claim state derivation already accounts for
`needs_review` from disputes — without spending build time on API and
UI the rubric marks out of scope. A reviewer inspecting `DisputeModel`
should treat it as schema readiness, not a feature they can click
through.

---

## 2026-06-24 — `reset_db` runs the same adjudication batch as app startup

**Context:** QA found that `uv run python -m app.scripts.reset_db` left
every seed line item in `pending`. The app lifespan calls
`adjudicate_all_pending` after seeding, but the CLI only dropped,
recreated, and re-seeded — so claims showed **Submitted** with $0 totals
until the dev server restarted.

**Options considered:**

- **Document "restart the server after reset."** Works but hides the
  bug behind an extra step every reviewer would hit.
- **Call `adjudicate_all_pending` at the end of `reset_db`** (chosen).
  Same function, same ordering, same end state as a fresh startup.

**Choice:** After `load_seed_data`, `reset_db` opens a session and runs
`adjudicate_all_pending` before commit. A test in
`app/tests/scripts/test_reset_db.py` asserts no pending line items
remain.

**Reasoning:** Reset is the "start over" path; it should land the DB
in the same reviewable state as first boot, not an intermediate state
only the lifespan fixes. Sharing one function avoids the two paths
drifting apart again.

---

## 2026-06-24 — Deductible accumulator is member-scoped and cross-service-type

**Context:** `Policy.annual_deductible` is a single dollar cap per
member per calendar year, not per service type. A member's MRI and
their physio visit both draw from the same deductible pool. Annual
*limits* (`annual_limit` rules), by contrast, are scoped to
`(member, service_type, period)` and sum `payable_amount`.

Phase 06 added `deductible_applied` on each `AdjudicationDecision`
because `payable_amount` alone cannot recover how much of a prior line
item went toward the deductible (it bundles deductible, cost-share, and
over-limit into one number).

**Options considered:**

- **Service-type-scoped deductible.** Simpler queries, but wrong for
  the seeded policies and typical US plan shape.
- **Member-scoped, cross-service-type sum of `deductible_applied`**
  (chosen). Repo function `sum_deductible_applied` filters by member
  and calendar-year window on `claim.service_date`, not by
  `service_type`.

**Choice:** Deductible accumulator = sum of `deductible_applied` over
current approved decisions for the member in the period. Limit
accumulator = sum of `payable_amount` over current approved decisions
for the member **and** service type in the period.

**Reasoning:** Keeps the two accumulators aligned with what each rule
kind actually caps. Cross-claim ordering
`(claim.submitted_at, line_item.id)` matters here: Bob's seed claims
show deductible filling on an early claim and coinsurance on a later
one even when the service types differ. Documented in
`domain-model.md` invariants alongside the limit accumulator.

---

## 2026-06-25 — Dispute filing shipped (resolution still deferred)

**Context:** The `Dispute` entity and ORM existed from phase 05, but the
2026-06-24 entry deferred the full flow. For submission polish we
needed a member-visible path to challenge an `approved` or `denied`
line item without building reviewer tooling or re-running the engine.

**Options considered:**

- **Full dispute lifecycle** — file + reviewer resolve + superseding
  decision + `dispute.resolved` audit. Correct end state, but reviewer
  UI/API is a large slice and duplicates patterns we already defer
  (auth, `decided_by = reviewer:<id>`).
- **File-only dispute** (chosen) — persist `Dispute`, move line item to
  `needs_review`, emit audit events, return refreshed claim detail. Leave
  the current `AdjudicationDecision` row untouched so the member still
  sees what was decided while the claim shows `under_review`.
- **Auto re-adjudicate on file.** Rejected — disputes are human review
  with possible new facts, not a rules re-run (2026-06-23 entry).

**Choice:** `POST /api/line-items/{line_item_id}/dispute` with
`{"reason": "..."}`; `app/disputes/service.py` enforces status and
one-open-dispute-per-line-item (409 otherwise). QuickClaim shows a
"Raise dispute" action on approved/denied rows, modal for reason,
success banner. Claim audit timeline merges `dispute.filed` events.
Five API tests in `app/tests/api/test_routes_disputes.py`.

**Not built:** reviewer resolution route, `dispute.resolved` audit,
new `AdjudicationDecision` on file, seed dispute rows.

**Reasoning:** Filing is the member-facing half of the lifecycle and
exercises claim-state derivation (`under_review`), audit plumbing, and
the `Dispute` table without faking a reviewer persona. Leaving the
decision row stable avoids implying the dispute already changed
coverage math — the UI can show both "prior decision" and "under
review" honestly. Resolution stays the natural follow-on once auth and
reviewer identity exist.
