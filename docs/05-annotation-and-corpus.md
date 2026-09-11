# 05 — Annotation guide and corpus authoring

Corpus authoring is the real critical path. It is not engineering and cannot be parallelised with a
coding agent. **Implementation must not block on finishing all scenarios** — the 3-scenario dev split
unsticks every build stage.

## Label definitions

Use these verbatim when annotating. They are written so that two annotators applying them independently
should agree.

### Transition-driving labels (four — these reach the state engine)

| Label | Test |
|---|---|
| **new** | The obligation does not correspond to any existing requirement. Legal only with `no_match`. |
| **refinement** | Same obligation; detail added or narrowed. **The old sentence remains true.** |
| **supersession** | The old obligation is no longer true, **and a replacement is stated.** |
| **contradiction** | The old obligation cannot stand, **and no replacement is stated.** |

The refinement/supersession boundary is the one that generates disagreement. The deciding question is
whether the previous statement is still true after this one. "Login must also support password reset"
leaves email login true → refinement. "We'll use SSO instead" makes email login false → supersession.

### Utterance labels (two — no lifecycle event)

| Label | Test |
|---|---|
| **restatement** | Same obligation, no material change. Confirmation, summary, repetition. Optional `Noted` event for audit; no state change. |
| **not_requirement** | Not an act on the register: question, hedge, rationale, scheduling, discussion. Never reaches the register; counted in coverage. |

**Hedged speech never becomes supersession.** "Could we use SSO?" is `not_requirement`, or an
`unresolved` proposal if it is clearly on-topic. This is enforced twice — once by the label, once by the
rule table's authority guard — because the classifier will sometimes get it wrong.

### Atomicity

One obligation per candidate. Compound utterances are split at extraction, never classified as a
bundle. "Users log in with SSO and the session times out after 30 minutes" is two candidates.

## Gold event file format

One file per scenario. Ordered. Per event:

```yaml
- event_index: 7
  meeting_ordinal: 2
  source_span: { turn_index: 118, start: 12, end: 64 }
  canonical_requirement_id: "R03"        # or null for no-match
  relation: supersession
  event_action: Supersede
  relevant_version: 1
  expected_state_after: Superseded
  speaker_can_confirm: true
```

Gold files are structured data, **never used as prompt few-shot examples on holdout**, and never read by
any module except `src/eval/score.py`.

## Authoring protocol

**Label author ≠ dialogue author.** One member writes the gold event sequence — what should happen, in
structured form. A different member writes the transcript dialogue that realises it. This makes labels
ground truth by construction rather than post-hoc annotation, and stops the transcript phrasing from
being anchored to whatever wording the prompt author had in mind.

With three members, rotate so nobody both labels and writes the same scenario:

| Scenario | Gold author | Dialogue author | Independent labeller (holdout only) |
|---|---|---|---|
| D1 (dev) | A | B | — |
| D2 (dev) | B | C | — |
| D3 (dev) | C | A | — |
| H1 | A | B | C |
| H2 | B | C | A |
| H3 | C | A | B |
| H4 | A | C | B |
| H5 | B | A | C |

For holdout scenarios, the third member independently labels from the dialogue alone. Disagreements are
resolved before model scoring. **Report pre-adjudication agreement** for ID and relationship labels — it
is evidence that the task is well defined.

## Corpus targets

8 scenarios: 3 dev, 5 holdout. Each 3 ordered meetings, 12–18 labelled content events.
Roughly 96–144 events total.

Reduced from the proposal's 12 because the team lost a member. Eight well-balanced scenarios beat twelve
thin ones. **Protect class balance over scenario count.**

### Required coverage

Every one of these must appear in the holdout split:

- New requirements
- Compatible refinements
- Explicit replacements (supersession)
- Unresolved conflicts (contradiction)
- Delayed confirmation
- Repeated statements (restatement)
- Hedges and questions (not_requirement)
- **Near-duplicate requirements that must NOT be merged** — at least one dev scenario built entirely
  around this trap: login email vs password-reset email vs receipt email
- **Back-references across meetings** — Meeting 3 referring to Meeting 1 wording already superseded in
  Meeting 2. This is the case that makes versioned retrieval necessary.
- **At least three no-reversal control scenarios** (across both splits), so false-supersession rate is
  measurable against something.

### Known coverage shortfall

The proposal targets ≥15 holdout examples per relationship class. Five holdout scenarios at 12–18
events gives 60–90 events across six labels — realistically 8–14 per class, fewer for rare ones.

The proposal pre-commits the correct response: **report the shortfall and limit conclusions rather than
tuning on the test set.** Do that. Do not add scenarios late to hit a number.

## Validity note

Scripted data can favour the pipeline if examples are too regular. Vary phrasing deliberately: include
indirect requests, non-native-speaker phrasing, interruptions, and statements that trail off. The
label-author/dialogue-author split is the main structural defence; conscious phrasing variation is the
second.
