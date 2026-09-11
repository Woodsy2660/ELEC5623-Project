# 04 — Evaluation

The system exists to produce these numbers. Build the harness before the model stages.

## Run modes

Same code, two modes. Mode is a run-level parameter recorded in `runs`.

| Mode | Candidate source | Confirmation |
|---|---|---|
| `demo` | Extracted (LLM-1) | Human via Streamlit |
| `eval` | Switchable: `extracted` or `gold` | Gold decision file |

**Gold-candidate injection is not optional.** Without it, extraction error is reported as matching
failure and the two-call design buys nothing measurable.

| Score | Candidate source | Measures |
|---|---|---|
| **E3-oracle** | gold | Retrieval + classification in isolation |
| **E3-pipeline** | extracted | End-to-end matching as a user would experience it |
| **E2** | extracted | Extraction quality and evidence support |

`E3-oracle − E3-pipeline` is a reportable quantity: how much extraction error costs downstream.

## Tests

| Test | Procedure | Target |
|---|---|---|
| E1 | Register integrity: valid/invalid import, idempotent re-import, export round-trip comparing IDs, content, status, evidence | All cases pass; no mutation on invalid input |
| E2 | Extraction precision/recall/F1 vs gold; evidence support accuracy; unsupported rate | F1 ≥0.80; evidence support ≥0.95; unsupported ≤0.05 |
| E3 | Retrieval recall@k (dense-only, BM25-only, fused, reported separately); historical-ID accuracy; no-match accuracy and precision; relationship macro-F1 + confusion matrix | Recall ≥0.90; ID accuracy ≥0.85; macro-F1 ≥0.80 |
| E4 | Rule, audit, restart, duplicate-event, interruption tests; confirmation authority; reject/edit paths; adversarial injection | All deterministic cases pass; illegal-transition rate 0 |
| E5 | After each meeting, compare every gold item's version/status with expected state; false supersession rate | Reversal final-state accuracy ≥0.90; false supersession ≤0.05 |
| E6 | Review tasks: identify current scope, inspect evidence, resolve a proposed change | Unaided completion ≥0.80 |
| E7 | Provenance, unauthorised access, project separation, deletion, external-processing configuration | All access/deletion cases pass |
| E8 | 20 performance runs; latency, calls, tokens, retries, cost | 95th percentile ≤120 s |

### Macro-F1 denominator — read this

The submitted proposal states macro-F1 ≥0.80 over **four** classes. The classifier now emits **six**
(four transition-driving plus `restatement` and `not_requirement`).

**Headline the four-class transition-driving macro-F1** so the result is comparable to the published
target. Report six-class macro-F1 as secondary, with per-class support. Do not silently switch
denominators — a marker checking results against Section 9.4 of the proposal will notice.

## Required comparisons

Minimum four runs. Same model, temperature, pinned version, transcripts and logger throughout.

| # | System | Retrieval | Engine |
|---|---|---|---|
| 1 | System under test | top-k hybrid | yes |
| 2 | **Strong baseline** | none — full register in context | none |
| 3 | **Ablation A** | full register in context | yes |
| 4 | Ablation B (if time) | none — full register in context | yes |

**Ablation A is the honest test.** At n ≤ 60, the whole register fits in the prompt, so top-k retrieval
may lose. Run Ablation A on the dev split early, before building much around retrieval. If retrieval
loses at this scale, the remaining defence is that it is a *scaling* mechanism — which is what the
optional synthetic n≈200 stress register would show. That is low priority but high option value: it is
the only thing that rescues mechanism (1) if Ablation A goes badly. Not on the Week 6–8 critical path.

**Never weaken the baseline.** It gets a well-designed prompt asking for extracted statements, evidence,
historical ID or no-match, one of the four driving labels, and an updated register. It differs from the
system under test in exactly two ways: no explicit retrieval stage, no deterministic transition
validator. Its output may be written after a trivial schema parse.

## Null-result protocol (pre-committed)

If E5 accuracy does not separate the systems, lead with:

1. Illegal-transition rate (structurally 0 for the system under test; measure the baseline's)
2. Invented-ID rate (structurally 0 under the enum constraint; measure the baseline's)
3. Three-repeat variance on both systems
4. False-supersession rate on hedged utterances specifically
5. Tokens and cost as register size grows

These are real properties that survive an accuracy tie. Decide the framing now, not after seeing the
numbers.

## Methodological commitments

- **Score raw model outputs before human correction.** Missing, invalid and unresolved predictions count
  as errors in primary metrics; coverage reported separately.
- **Gold-decision replay** for sequential state tests, so human choices do not confound the system
  comparison. Both systems receive the identical decision sequence.
- **Three repeats** at fixed prompts, versions and settings. Report mean and spread. Do not claim
  bitwise reproducibility — temperature 0 is not fully deterministic on hosted endpoints due to batching.
  NFR04's wording (deterministic engine, model stages reproducible within a reported spread) is
  correct; keep it.
- **Prompt author does not read holdout gold.** Prompts iterate on the dev split only, then freeze.
- **Adversarial injection has a holdout set.** `scenarios/dev-adversarial/` is for development;
  `scenarios/holdout-adversarial/` is not opened until final scoring. Five to ten turns each is enough.

## Harness scripts

Built in `src/eval/`. Skeleton exists **before** any LLM work.

| Script | Purpose |
|---|---|
| `ingest_scenario.py` | Load authored meetings plus gold event file |
| `run_pipeline.py --mode eval --candidate-source {gold,extracted} --repeat {1,2,3}` | Main run entry point |
| `replay_to_cutoff.py --after-meeting N` | Rebuild expected vs actual state from `events` |
| `score.py` | E2, E3-oracle, E3-pipeline, E5, confusion matrices, illegal-transition rate |
| `run_baseline.py` | Same logger, same store, no retrieval, no engine |

`score.py` is the only module permitted to read `gold_events`.

## Acceptance bar — "evaluable"

The build is ready to evaluate when all of these hold, even with an ugly UI and only 8 scenarios:

- Engine has property tests for every legal and illegal transition
- A meeting can be ingested twice without duplicate turns
- Hybrid retrieval recall@k measured on gold candidates for the dev split
- LLM-2 runs on gold candidates with enum IDs and logged calls
- LLM-1 plus FR06 validator exists; unsupported candidates dropped and counted
- Eval mode replays a gold decision file and scores state after each meeting
- Baseline runs on the same transcripts through the same logger
- Prompts are files with hashes recorded on every call
- Export of register plus decision history works

**Demo-complete** is the above plus Streamlit for FR01–FR03.
