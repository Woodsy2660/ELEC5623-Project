# Track C — current status and integration contract

**Owner:** Lucas  
**Scope:** FR01–FR03, FR09, FR11; shared ownership of the model-call logger.

This document is the working hand-off for Track C. It records implemented work,
interfaces offered to other tracks, and decisions that still require agreement.

## Implemented now

- `src/engine/state_machine.py` is a pure, standard-library lifecycle transition table.
- `src/engine/proposal_rules.py` deterministically assesses a classification proposal
  before it can reach persistence.
- Engine tests cover listed transitions, unlisted transitions, relationship-to-event
  mapping, no-ops, invalid classifier combinations, and the supersession authority
  guard (FR11 / E4).
- `src/review_ui/app.py` provides a read-only Streamlit homepage using clearly marked
  preview data. It establishes the FR01–FR03 layout without connecting actions to
  persistence.

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

1. **Now, Track C:** maintain engine tests and agree the unresolved decisions below.
2. **With Track A:** scenario ingest, project/speaker persistence, idempotency, and
   the shared model-call logger interface.
3. **With Track B:** adapter from `Classification` to `assess_proposal`; B must not
   allow an ID outside `retrieved_ids`.
4. **After those interfaces exist:** transactional event/version/current-row writes,
   replay, then connect the existing Streamlit preview to real proposals and records.

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
