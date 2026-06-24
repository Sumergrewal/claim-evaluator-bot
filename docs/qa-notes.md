# QA Notes (Phase 11)

Running log from manual and automated break-testing. Use this to re-run
checks before submission or during the pairing interview.

**Session JSONL:** `ai-artifacts/11-qa__1fd2a39f-5d58-457d-8d6e-885a3b98d428.jsonl`

---

## Setup

```bash
# Stop any running uvicorn first, then:
cd claim-evaluator-bot
uv run python -m app.scripts.reset_db   # seeds + adjudicates 15 line items
uv run uvicorn app.main:app --reload    # Terminal 1
cd frontend && npm run dev              # Terminal 2 → http://localhost:5173
```

**Automated baseline (should be green):**

```bash
uv run pytest          # 197+ backend tests
cd frontend && npm test
```

**Important:** `reset_db` now runs `adjudicate_all_pending` after seeding
(fixed during QA). Without that fix, every claim showed **Submitted** with
pending line items until the next server restart.

---

## Seed claim matrix (QA-A2)

After a fresh reset, open each claim in the UI and verify:

| Claim | Expected state | What to check |
|-------|----------------|---------------|
| `C-BOB-001`, `C-CAROL-001` | **Paid** | Badge = Paid; line items decided; totals ≠ $0 |
| `C-CAROL-002` | **Partially approved** | One approved, one denied (whitening) |
| `C-CAROL-003`, `C-BOB-003` | **Under review** | `needs_review` (missing preauth) |
| `C-ALICE-006` | **Denied** | Bariatric excluded on BASIC |
| `C-ALICE-001`–`005`, `C-BOB-002`, `C-CAROL-004` | **Approved** | Explanations + money math |

Quick API check:

```bash
curl -s http://localhost:8000/api/claims | python3 -c "
import sys, json
from collections import Counter
print(Counter(r['adjudication_state'] for r in json.load(sys.stdin)))
"
```

Expected: `approved: 7, paid: 2, under_review: 2, partially_approved: 1, denied: 1` — no `submitted`.

---

## Manual test cases

### Engine paths (submit via UI `/submit` or `POST /api/claims`)

| ID | Member | Input | Expected |
|----|--------|-------|----------|
| **B1** | Alice | `general_consultation` $400, date 2026-02-10 | Approved; deductible absorbs charge |
| **B2a** | Alice | `bariatric_surgery` $20k, no preauth | Denied (coverage phase) |
| **B2b** | Bob | `bariatric_surgery` $25k, `preauth_ref: PRE-99999` | Approved (coinsurance) |
| **B3** | Alice | `mri` $1500, no preauth | Under review (gates phase) |
| **B4** | Alice | any service, `service_date: 2027-03-01` | 201 + denied (eligibility) |
| **B5** | Carol | `general_consultation` $150 | Denied (dental plan only) |
| **B6** | Carol | Open seed `C-CAROL-004` | L1 plan $420 / L2 plan $231 on $600 + $400 crowns |
| **B7** | Alice | New `physiotherapy` $500 after seed | Heavy member share (cap mostly used by C-ALICE-003/004) |
| **B8** | Carol | `filling` $150 + `cosmetic_whitening` $200 | Partially approved |
| **B9** | Alice | `charged_amount: 0.00` | 201; ledger holds |
| **B10** | Alice | `service_type: totally_made_up` | Denied, not 500 |
| **B11** | Alice | `wellness_visit` $100 | Plan $100 / Member $0 (no cost-sharing rule) |

**B6 nuance:** Line status **Approved** does not mean the plan pays the
full charge. It means adjudication finished favorably. Cap clipping shows
up in the money split and explanation **limits** phase. For the canonical
intra-claim crown demo, use seed claim `C-CAROL-004` — not a new submit
after other Carol crown claims (cross-claim accumulator will shrink plan
pay).

**B11 nuance:** No cost split is correct — `wellness_visit` on BASIC has
`service_covered` only, no copay/coinsurance.

### API abuse (`curl` or Swagger)

| ID | Request | Expected |
|----|---------|----------|
| **C1** | `POST` with `member_id: M-999` | 404 |
| **C2** | `POST` with `line_items: []` | 422 |
| **C3** | Negative `charged_amount` | 422 |
| **C4** | Extra JSON field (`mystery_field`) | 422 |
| **C5** | `GET /api/claims?member_id=M-999` | 404 |
| **C6** | `GET /api/claims/C-FAKE` | 404 |

### UI

| ID | Action | Expected |
|----|--------|----------|
| **D1** | `/claims/not-a-real-id` | "Claim not found" + back link; **no** backend hint |
| **D2** | Stop uvicorn, refresh list | Error state, not infinite spinner |
| **D3** | Submit with empty provider | Client validation |
| **D4** | XSS in provider/description | Rendered as text (API stores raw) |

### Audit & invariants

| ID | Check | Expected |
|----|-------|----------|
| **E1** | New claim audit timeline | `claim.submitted` then `line_item.decided` |
| **E2** | POST body vs GET same claim | Same state and decisions |
| **E3** | Every line item | `payable + member_responsibility == charged` |

### Known gaps (not bugs)

| Feature | Probe | Expected |
|---------|-------|----------|
| Disputes | `POST /api/disputes` | 404 |
| Mark paid | No UI | Only seed `paid_at` claims |
| Auth | All routes | Open |
| Pagination | `GET /api/claims` | Full list |
| OOPM | Heavy cost-sharing | Not modeled |

---

## Bugs found and fixed during QA

### 1. `reset_db` left all line items pending

**Symptom:** After reset, every claim showed **Submitted**; 0 audit events;
startup log said `no pending line items` if server restarted at wrong time.

**Cause:** `reset_db` re-seeded `pending` line items but did not run
`adjudicate_all_pending` (only the app lifespan did, on boot).

**Fix:** `app/scripts/reset_db.py` — adjudicate after seed commit.
Test: `app/tests/scripts/test_reset_db.py`. README updated.

### 2. Invalid claim URL showed misleading backend hint

**Symptom:** `/claims/not-a-real-id` said "make sure the backend is
running" with wrong command `uvicorn main:app`.

**Fix:** `ErrorState.tsx` — correct command `uv run uvicorn app.main:app
--reload`; hide backend hint on 404. `ClaimDetailPage.tsx` — distinguish
404 from network errors; add back link.

---

## Automated live API QA (2026-06-24)

Run against `http://localhost:8000` after fresh reset:

| Result | Count |
|--------|-------|
| Passed | 27/28 core + 8/10 additional |
| Real failures | **0** |

False failures from polluted DB (extra test claims submitted during the
same session):

- **B6** new submit expected $420/$231 but got less — Carol's crown cap
  already consumed by seed + prior QA submits.
- **Alice filter** expected 6 claims, got 17 — QA submissions for M-001.

**Invariants verified:** ledger held across all claims; no 500s on edge
cases; seed `C-CAROL-004` crown math correct ($420 / $231).

---

## curl helper

```bash
curl -s -X POST http://localhost:8000/api/claims \
  -H 'Content-Type: application/json' \
  -d '{
    "member_id": "M-001",
    "provider_name": "QA Clinic",
    "service_date": "2026-06-15",
    "line_items": [{
      "service_type": "general_consultation",
      "service_description": "QA visit",
      "charged_amount": "200.00",
      "preauth_ref": null
    }]
  }' | python3 -m json.tool
```

---

## Before submission demo

1. Stop servers.
2. `uv run python -m app.scripts.reset_db` — confirm `decided 15 line item(s)`.
3. Start backend + frontend.
4. Spot-check QA-A2 table (13 claims, correct state mix).
5. Optionally submit one new claim to show live adjudication.

Avoid running many QA submits on the demo DB — accumulators (crown cap,
physio cap) are member-scoped and persist.

---

## Suggested QA order

1. Automated tests (`pytest` + `npm test`)
2. Fresh `reset_db` + seed matrix (A2)
3. Engine submits (B series) on clean DB
4. API abuse (C series)
5. UI checks (D series)
6. Re-reset before reviewer handoff
