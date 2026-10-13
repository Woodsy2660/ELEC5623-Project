# Track C — current status and integration contract

**Owner:** Lucas  
**Scope:** FR01–FR03, FR09, FR11; shared ownership of the model-call logger.

This document is the working hand-off for Track C. It records implemented work,
interfaces offered to other tracks, and decisions that still require agreement.

**Last reviewed:** 2026-10-13, after merging upstream `219a5a4` into `lucas-track-c`.

## Implemented now

- The existing upstream `src/engine/state_machine.py` is a pure, standard-library
  lifecycle transition table; Track C did not author or change that base table.
- `src/engine/proposal_rules.py` deterministically assesses a classification proposal
  before it can reach persistence.
- Engine tests cover listed transitions, unlisted transitions, relationship-to-event
  mapping, no-ops, invalid classifier combinations, and the supersession authority
  guard (FR11 / E4). Of the 26 passing engine test items, 10 came from upstream;
  Track C added 15 proposal-rule cases and one Hypothesis test. The latter currently
  uses the production transition table as its oracle; strengthening it remains work.
- `src/persist/database.py` now provides SQLite engine creation, per-connection
  foreign keys, idempotent schema initialization, and a commit/rollback Session
  context. `python -m src.persist` initializes the existing 13-table schema; see
  `docs/09-database.md`. This is storage infrastructure, not a validated register
  write service or a connection to the review API.
- The upstream React/Vite frontend in `/web` is now the **only** review UI. The
  earlier Track C Streamlit homepage and its dependency have been removed. They
  remain recoverable from commit `599eca6` / branch `lucas-track-c-backup-20261013`.
- Upstream `src/api/` offers fixture-backed review, evidence display, meeting import,
  settings, and transcript replay. Its decision gate calls `validate_transition`,
  but it does **not** call `assess_proposal` or execute a database transaction.
  A `register_changed` flag in a response is not proof of a persisted register update.

The real pipeline, business-level event/version/current-row transactions,
model-call logger, and evaluation harness are not implemented. The upstream API
fixtures are demonstration data, not authored evaluation scenarios or model outputs.

**Verified in this slice:** 11 new database test items and 26 engine test items pass
(plus one existing placeholder test). Ruff checks pass for the new storage modules
and tests. This is not a full-suite/API test result or full E4 acceptance.

The engine does **not** write to a database, call a model, parse transcript text, or
read gold data. That separation is deliberate and required by the experiment.

## Interface for Tracks A and B

The future integration layer calls:

```python
assess_proposal(
    relation: str,
    matched_requirement_id: str | None,
    retrieved_ids: Collection[str],
    current_state: State | None,
    speaker_can_confirm_scope: bool,
    replacement_stated: bool,
) -> RuleVerdict
```

`relation`, `matched_requirement_id`, and `retrieved_ids` come from Track B's
`Classification`. `current_state` comes from the persisted matched requirement.
`speaker_can_confirm_scope` comes from Track A's per-project `speakers`
configuration. `replacement_stated` must be derived from validated evidence, not
assumed merely because the classifier emitted `supersession`.

`RuleVerdict` is one of:

| Verdict | Meaning | May persistence mutate the register? |
|---|---|---|
| `allowed` | Legal lifecycle event proposed | Only after confirmation |
| `rejected` | Invalid classifier output or illegal transition | No |
| `unresolved` | Supersession lacks authority or explicit replacement | No |
| `no_op` | Restatement or non-requirement | No |

## Current rule table

| Relation | Proposed event | Preconditions |
|---|---|---|
| `new` | `create` | No matched ID and no current state |
| `refinement` | `refine` | Retrieved matched ID and legal state transition |
| `contradiction` | `contradict` | Retrieved matched ID and legal state transition |
| `supersession` | `supersede` | Retrieved matched ID, legal state, authorised speaker, explicit replacement |
| `restatement` | none | Retrieved matched ID; no state change |
| `not_requirement` | none | No lifecycle mutation |

## Dependencies and next work

### Work that can start without waiting for A or B

Except for the database foundation noted below, these are planned tasks, not
claims of completed implementation. Use temporary
databases and explicit test inputs, not cloud calls, UI fixtures presented as real
results, or holdout labels.

1. **Database foundation (FR09; E4 groundwork) — implemented:** SQLite/session helper,
   per-connection foreign keys, existing-schema initialization, and commit/rollback/
   close-reopen tests. No transcript parser or fixture API wire contract was changed.
   Project-scoped lookups, schema constraints, and business write operations remain
   follow-up work; E7 access/deletion guarantees are not established by this slice.
2. **Stronger pure-engine tests (FR11; E4):** verify every state/event pair against
   an independent expected table, rather than reading production `TRANSITIONS` as
   the expected answer. Add deterministic event-sequence and guard tests. These do
   not establish persistence, interruption safety, or full E4 acceptance on their own.
3. **Transaction tests for settled events (FR09; E4):** with synthetic records,
   exercise documented single-family transitions such as Confirm, Refine,
   Contradict, and Resolve; verify old versions remain, current rows agree with
   events, invalid/unconfirmed requests do not write, and injected failures roll
   back all writes. Defer replacement-family and new-item confirmation semantics
   until the decisions below are agreed. Version creation also needs B's embedding
   contract before this can be claimed as fully integrated.
4. **Replay/harness groundwork (E5):** define a small explicit event test sequence
   and expected meeting-cutoff states. Implement replay of actual events only once
   their payload and ordering are fixed. Gold comparisons belong in `score.py`;
   do not import gold labels into inference or replay helpers.
5. **Logger contract review (NFR02/NFR04; E8):** prepare proposed fields, retry and
   failure examples, prompt-hash handling, and injected pricing tests. AGENTS.md
   requires deployment, temperature, and retries to be recorded for every call;
   review the existing `runs` / `model_calls` schema for compliance with A before
   freezing or implementing the shared call wrapper. Do not invent provider rates.

**Recommended next independent slice:** stronger pure-engine tests, then settled
single-family transaction tests on the database foundation. It requires no model,
real transcript, new frontend, or decision about supersession semantics.

### Work needing coordination before integration

- **With A / Ben:** confirm any unpushed work, transcript parsing and source-hash
  contract, project/speaker persistence ownership, and the shared logger interface.
  Keep `/web` and existing HTTP response shapes stable during this discussion.
- **With B:** confirm `Classification`, retrieved-family history and embedding
  inputs. Build the adapter to `assess_proposal` outside `src/engine/`; do not let
  a matched ID outside `retrieved_ids` pass validation.
- **Across tracks:** agree the decisions below before replacing the fixture gate
  with the real validation/confirmation/transaction chain. An `unresolved` flag
  alone cannot establish the explicit-replacement guard from validated evidence.
- **Documentation:** upstream adopts React/FastAPI in `docs/01` and `docs/07`, but
  `AGENTS.md` still lists them under "Do not build". Ask the team to reconcile this
  restriction; do not infer permission to add another frontend or framework.

## Decisions still needed from the team

1. **Supersession replacement:** when an old family is superseded, should the new
   replacement statement create a new requirement family (recommended), or a version
   of the superseded family? The former preserves an active replacement in the
   current register.
2. **New-item confirmation:** should confirmation persist `Create` then `Confirm`
   events in one transaction (recommended), or use a different event representation?
3. **Explicit replacement test:** define the deterministic evidence rule used to set
   `replacement_stated`. The current engine treats it as an integration input so it
   cannot silently trust an LLM label.
4. **Reviewer edits:** edits to text, relation, matched ID, or evidence must rerun
   evidence validation and this rule table before persistence; confirm the allowed
   edit scope.
5. **No-op audit:** decide whether `restatement` should create an optional `Noted`
   audit event. The current MVP uses `no_op` only.
