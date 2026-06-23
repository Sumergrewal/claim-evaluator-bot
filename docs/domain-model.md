# Domain Model

> **Status:** skeleton — populated during phase 03 (planning) and updated
> as the model evolves.

This document captures the entities, relationships, state machines, and
invariants of the claims-processing domain. It reflects the *current*
state of the model; historical decisions and rejected alternatives live
in `decisions.md`.

---

## Entities (TBD)

<!--
For each entity:

### EntityName

- **Purpose:** one line.
- **Fields:** name, type, notes.
- **Invariants:** rules that must always hold.
- **Relationships:** what it points to, what points to it.
-->

- `Member` — TBD
- `Policy` — TBD
- `CoverageRule` — TBD
- `Claim` — TBD
- `LineItem` — TBD
- `AdjudicationDecision` — TBD
- `Dispute` — TBD
- `AuditEvent` — TBD

---

## Relationships (TBD)

<!-- ASCII or mermaid diagram of how entities connect. -->

---

## State machines (TBD)

### Claim lifecycle

<!-- States, transitions, who triggers each, what guards each. -->

- `submitted` → `under_review` → `approved` | `denied` → `paid`
- Disputes loop back into `under_review`.

### Line-item lifecycle

<!-- Independent of the Claim's state. -->

- `pending` → `approved` | `denied` | `needs_review`

### Relationship between Claim state and LineItem state

<!--
A Claim's state is derived from the aggregate state of its LineItems,
not stored independently as a source of truth that can drift.
-->

---

## Coverage-rule representation (TBD)

<!--
- Schema for a rule record.
- Supported rule kinds (annual limit, per-visit cap, preauth required, ...).
- How the engine evaluates them in order.
- How the engine produces an explanation.
-->

---

## Explanation format (TBD)

<!--
Structure of the explanation attached to every adjudication decision:
- which rule(s) fired,
- inputs checked,
- math performed,
- human-readable narrative.
-->

---

## Open questions

<!-- Drop questions here as they come up. Move to decisions.md when resolved. -->
