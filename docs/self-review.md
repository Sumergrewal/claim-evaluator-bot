# Self-Review

Honest assessment for the reviewer: what held up, what’s missing, the
trade-offs behind the gaps, and how I used Cursor deliberately — not as a
black box. Details live in [`decisions.md`](decisions.md) and
[`domain-model.md`](domain-model.md); this is the summary.

---

## At a glance

I’m happy with where the app landed for the time box. It runs end-to-end:
seed data loads, the rules engine adjudicates every line item, QuickClaim
lets you list claims, drill into coverage decisions and audit history,
submit new ones, and file disputes on approved/denied line items. I don’t
have a background in insurance, but the system still speaks the domain
language — coverage rules, deductibles, limits, preauth gates, derived
claim state — because research and modeling were part of the build, not a
prelude to coding.

---

## What worked

- **Domain modeling first** — `decisions.md` and `domain-model.md` locked
  entities, state machines, and deferrals early so each phase had a target
  across many disconnected chats. I can explain *why* rules are data, why
  claim state is derived, and why decisions are immutable with supersession.
- **Rules as data** — YAML coverage rules + a six-phase engine; curated seed
  claims hit every important path (deductible, caps, exclusions, preauth,
  cross-claim accumulators) without needing domain intuition.
- **Explainability** — structured per-step explanations in the API and UI;
  I could validate outcomes by reading reasoning, not gut feel.
- **Tests with the code** — ~202 pytest + 31 Vitest in the same commits as
  features (domain, engine, API, disputes, `reset_db`); git history shows
  behavior-named tests weren’t bolted on at the end.
- **QA that changed behavior** — e.g. `reset_db` leaving line items pending
  until server restart; 404 UI blaming the backend for a bad claim id. Both
  fixed; README troubleshooting updated.
- **Late-scope wins** — file-only dispute flow (raise → `needs_review` →
  audit + UI confirmation, prior decision unchanged) and policy-scoped
  service-type dropdown on submit — scoped to avoid reviewer auth and
  fake resolution.

---

## Gaps and limitations

Each gap is intentional for the time box; the trade-off is noted.

- **Reviewer loop incomplete** — filing works; no API/UI to supersede a
  decision or emit `dispute.resolved`. *Trade-off:* ship the member-facing
  half and prove state derivation without building reviewer identity or auth.
- **Preauth `needs_review` stuck** — gate failures park line items; no human
  resolution path in the demo. Same trade-off as above.
- **No mark-paid** — `paid` on two seed claims only. *Trade-off:* demo the
  derived `paid` state without a payment workflow.
- **Submit form still thin** — dropdown helps; no policy summary or autofill.
  *Trade-off:* quick UX win over a full intake experience.
- **Narrow by design** — ingest, adjudicate, explain, display; auth, admin,
  and notifications correctly out of scope per the brief.
- **Explanations are auditable, not member-friendly** — structured steps,
  not conversational copy. *Trade-off:* correctness and auditability over
  LLM polish.

---

## With more time

1. **Reviewer resolution** — superseding decision, `dispute.resolved` audit,
   line item status aligned with the new outcome (filing is already shipped).
2. **Mark claim paid** — small API + UI when a claim is payable, with a
   `claim.paid` audit event.
3. **Submit polish** — policy context on the form, richer validation, autofill
   from prior claims (service-type dropdown is already shipped).
4. **Optional narrative layer** — LLM plain-English summaries on top of the
   existing explanation JSON, if product value justified the dependency.

---

## Working with AI

I used Cursor throughout — **one chat per phase**, with `AGENTS.md` and the
docs as the coherence layer so each new session knew where we were. Raw
`.jsonl` logs for every phase are in `ai-artifacts/` (framing through QA and
final polish); that trail is part of the submission, not an afterthought.

| Practice | Purpose |
|---|---|
| Phased chats | Isolate framing, research, planning, backend, frontend, tests, QA |
| `AGENTS.md` ritual | New chat reads agents file, decisions, domain model, `git log` |
| Append-only `decisions.md` | Trade-offs written down so later sessions don’t re-litigate |
| I own merges | Read diffs, run the app, reject out-of-scope suggestions |

**Where I pushed back or corrected the agent**

- **Doc vs engine drift** — `domain-model.md` had limits before deductible;
  cost-sharing math said the opposite. Fixed the spec in phase 06 before
  trusting the implementation.
- **`paid` badge lying** — `paid_at` showed **Paid** while line items were
  still pending until startup adjudication finished. Derivation tightened.
- **Scope creep** — auth, admin panels, and similar features declined per
  the brief.
- **QA findings** — reset-script and 404 issues came from me running the
  app, not from the agent anticipating them.

**Where AI helped materially**

- Persistence scaffolding (ORM ↔ domain, repos, seed loader) so I could focus
  on rule semantics.
- Behavioral tests for engine edge cases — accumulators, phase short-circuits
  — I wouldn’t have enumerated alone without domain experience.
- Drafting `decisions.md` entries so trade-offs stayed out of chat-only history.

**Ownership**

I don’t treat the output as “the AI’s project.” I read diffs, ran QA,
adjusted docs when they didn’t match behavior, and used planning artifacts
to steer each phase. The JSONL logs show that back-and-forth
