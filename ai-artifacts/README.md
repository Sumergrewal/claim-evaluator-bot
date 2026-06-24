# AI Artifacts

This folder holds the **raw Cursor `.jsonl` session logs** that document
every phase of the build. Submission is auto-rejected without these.

## Where the logs come from

Cursor stores every chat in this workspace as a `.jsonl` file at:

```
~/.cursor/projects/Users-adagrewal-Desktop-Sumer-stuff-claim-evaluator-bot/agent-transcripts/<chat-uuid>/<chat-uuid>.jsonl
```

These are the raw, untouched conversation logs — exactly what the spec
asks for. No curation, no summaries, no JSON-array dumps.

## Naming convention

When copying the JSONLs in at the end of the project, prefix each with
its phase number and name. **Keep the original UUID** in the filename so
it is obviously the raw original, not a relabeled or curated version.

```
NN-phase-name__<chat-uuid>.jsonl
```

Examples:

```
01-framing__619c8af9-46f8-47aa-b22a-310a4e95f8dc.jsonl
02-domain-research__<uuid>.jsonl
03-planning__<uuid>.jsonl
...
```

## Phase list

1. `01-framing` — understanding the assignment, deliverables, foundation
2. `02-domain-research` — insurance / adjudication / coverage rules research
3. `03-planning` — architecture, schema, state machines
4. `04-scaffolding` — repo layout, dependency init
5. `05-backend-core` — entities, persistence layer
6. `06-backend-adjudication` — rules engine, state machine
7. `07-backend-api` — FastAPI routes for claims/decisions/audit
8. `08-frontend` — QuickClaim React UI
9. `09-tests` — test coverage (incremental alongside each build phase; no separate end-of-project pass)
10. `10-docs` — fill out the three docs
11. `11-qa` — bug hunt, polish, edge cases (`11-qa__1fd2a39f-….jsonl` archived)

Logs are copied in **at the end of each phase** as part of that phase's
commit. This keeps the git history coherent — each phase's JSONL is
versioned alongside the code it produced. A final refresh pass may
re-copy in-flight logs if any chat continues past its commit.
