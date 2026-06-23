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

<!--
Future entries below. Format:

## YYYY-MM-DD — <short title>

**Context:** ...

**Options considered:** ...

**Choice:** ...

**Reasoning:** ...
-->
