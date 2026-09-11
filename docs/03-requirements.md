# 03 — Requirements and ownership

`Proposed by` in the submitted proposal records who contributed a requirement. It is fixed and does not
change. **Implementation ownership below is separate and has been reallocated across three members.**
The proposal states this separation explicitly, so no inconsistency arises.

## Ownership tracks

> **FILL IN:** one member withdrew in Week 6. Replace `Member B` and `Member C` with the two remaining
> names in this table and in `docs/06-build-plan.md`. Nothing else needs editing.

| Track | Owner | Scope |
|---|---|---|
| **A — Ingestion, extraction, evidence, export** | Benjamin Wood | FR04, FR05, FR06, FR12 |
| **B — Retrieval, matching, classification, scoring** | Member B | FR07, FR08, FR10 |
| **C — State engine, persistence, review, logging** | Member C | FR01, FR02, FR03, FR09, FR11 |

Shared: corpus authoring (rotation in `docs/05-annotation-and-corpus.md`), the baseline (built last,
paired), and the harness skeleton (C builds it, B extends scoring).

**Logger interface is owned jointly by A and C.** Every call site must write the same `model_calls` row
shape, so the interface is agreed once and not changed unilaterally.

## Functional requirements

| ID | Requirement | Proposed by | Implements | Evaluated by |
|---|---|---|---|---|
| FR01 | Reviewers can open the meeting evidence supporting each proposed requirement or change | Danyang | C | E2, E6 |
| FR02 | An authorised reviewer can confirm or reject a proposed change before it alters agreed scope | Danyang | C | E4 |
| FR03 | Current confirmed requirements displayed separately from pending proposals and superseded or contradicted records | Danyang | C | E5, E6 |
| FR04 | Import a transcript into a named project, assigning every turn a stable identifier | Ben | A | E1 |
| FR05 | Extract discrete atomic candidate requirement statements as normalised text | Ben | A | E2 |
| FR06 | Attach ≥1 evidence span to every candidate; reject candidates whose evidence does not resolve to stored turn text | Ben | A | E2 |
| FR07 | Match each candidate against the project's requirement history, identifying the relevant historical requirement or determining no match exists | Lucas | B | E3 |
| FR08 | Classify each candidate relative to the history | Lucas | B | E3 |
| FR09 | Preserve the previous version and decision history when an approved change updates a requirement | Lucas | C | E4, E5 |
| FR10 | Retrieve top-k plausibly matching requirement families using combined semantic and lexical search over versioned history | Vikram | B | E3 |
| FR11 | Validate every proposed transition against permitted transitions; reject invalid proposals leaving the register unchanged | Vikram | C | E4 |
| FR12 | Export the current register and decision history as a structured file | Vikram | A | E1 |

## Non-functional requirements

| ID | Requirement | Implements | Evaluated by |
|---|---|---|---|
| NFR01 | 95th-percentile end-to-end processing ≤120 s for a transcript within the agreed size limit, over 20 runs | C | E8 |
| NFR02 | Cost per processed meeting within an agreed cap; cost per correctly reconciled requirement reported | C | E8 |
| NFR03 | Project-level isolation, access control, no cross-project retrieval, tested deletion, documented external processing | C | E7 |
| NFR04 | State engine fully deterministic; model stages reproducible within a reported spread at fixed version, settings and prompt | C | E4 + analysis |
| NFR05 | Transcript text treated as untrusted data; cannot alter instructions, tool access, or records outside the project | B | E4, E7 |
| NFR06 | Model output must not be presented in a way implying verified certainty or client approval | C | E6 |

## Constraints

| ID | Constraint | Verification |
|---|---|---|
| C01 | Exported transcript text only; no live capture or meeting-platform integration | Demonstration runs from files; integration listed as deferred |
| C02 | Hosted foundation model via API at a pinned version; no fine-tuning or training | Model and version in every run log; no training code in repo |
| C03 | Scripted or de-identified transcripts only | Corpus audit before each evaluation run |
| C04 | Total API expenditure within a single agreed team cap | Provider cap configured after pilot; cost logs reviewed weekly |

## Scale assumptions

Bound NFR01 and NFR02. Confirm against the corpus before E8.

| Parameter | Assumed |
|---|---|
| Meeting length | ≤ ~8,000 tokens |
| Requirements per project | ≤ 60 families |
| Meetings per project | 3 |
| Retrieval `k` | 5 (default; measure before changing) |
