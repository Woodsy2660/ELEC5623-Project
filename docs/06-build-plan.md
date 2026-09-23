# 06 — Build plan

Three members, Weeks 6–13. Scope already reduced for the lost member (see `docs/01-context.md`
§Deviations).

## Build order

Do not start with Streamlit. Do not start with baseline polish. Do not start with framework spikes.

| # | Stage | Owner | Blocks |
|---|---|---|---|
| 1 | **State engine + Hypothesis property tests** — all legal and illegal transitions, restatement no-op, hedge cannot supersede without authority | C | 7 |
| 2 | **Schema + ingest + idempotent re-import + project isolation** — turns, source hash, export round-trip (E1 slice) | A, C | 3, 4 |
| 3 | **Harness skeleton** — load one scenario, write dummy events, `replay_to_cutoff`, print one metric | C | everything measurable |
| 4 | **Retrieval** — embed, BM25, collapse-then-RRF, versioned corpus. Recall@k on gold candidates, dev only. No LLM | B | 5 |
| 5 | **LLM-2 on gold candidates** — E3-oracle loop, three-repeat logger | B | 6, 7 |
| 6 | **LLM-1 + evidence validator** — then E3-pipeline and E2 | A | 7 |
| 7 | **Rule table + engine wired to proposals + gold-decision replay** — E4/E5 on dev | C | 8, 9 |
| 8 | **Thin Streamlit** — evidence context, pending vs confirmed vs superseded, confirm/edit/reject | C | demo |
| 9 | **Baseline** — reuse ingest, store, logger. Parity or the comparison is invalid | A + B paired | 10 |
| 10 | **Freeze prompts. Holdout scoring. 20 cost/latency runs (E8)** | all | report |

Stage 1 needs no API key, no database and no data. Start it on day one.

**Run Ablation A (classifier with full register instead of top-k) as soon as stage 5 works on dev.**
It is a cheap early read on whether retrieval earns its place at n ≤ 60. Finding out in Week 8 is
recoverable; finding out in Week 12 is not.

## Indicative schedule

| Week | Target |
|---|---|
| 6 | Stages 1–2. Azure deployment pinned, `.env` pattern agreed, repo scaffolded. Dev scenarios D1–D3 gold files authored |
| 7 | Stage 3–4. D1–D3 dialogue written. Recall@k measured on dev |
| 8 | Stages 5–6. Ablation A run on dev. Holdout scenarios H1–H3 authored |
| 9 | Stage 7. E4/E5 passing on dev. H4–H5 authored, independent labelling begins |
| 10 | Stage 8–9. Baseline at parity. Adjudication of holdout labels complete |
| 11 | **Freeze prompts.** Holdout scoring, three repeats. E8 runs |
| 12 | Lightweight E6. Failure analysis. Report drafting |
| 13 | Demonstration: normal case, reversal, unresolved conflict. Each member explains their track |

Week labels are provisional. Check against the course demonstration schedule.

## Three-way split

> Ownership has been assigned to the remaining team members for the final implementation split.

| Track | Owner | Owns | Also |
|---|---|---|---|
| **A** | Benjamin Wood | Ingest (FR04), LLM-1 extraction (FR05), evidence validator (FR06), export (FR12) | Co-owns logger interface; pairs on baseline |
| **B** | Danyang | Retrieval (FR10), LLM-2 matching and classification (FR07, FR08), prompt registry | Extends `score.py`; pairs on baseline |
| **C** | Lucas | State engine (FR11), persistence and events (FR09), Streamlit review (FR01–03), run logger | Builds harness skeleton; co-owns logger interface |

Shared and unassigned work that will otherwise fall through:

- **Corpus authoring** — rotation table in `docs/05-annotation-and-corpus.md`. All three. Largest
  non-engineering cost.
- **Logger interface** — agreed once by A and C in Week 6, then frozen. Every call site writes the same
  row shape or E8 is unusable.
- **Report writing** — begins Week 11, not Week 13.

Each member must be able to explain their track and the overall claim in the demonstration.

## Cut list

If the calendar slips, cut in this order. Do not add complexity to avoid a cut.

1. **Formal E6 study.** Keep the Streamlit demo UI for FR01–FR03. Run a lightweight protocol on
   teammates plus one outsider if Week 12 allows, and declare the sample limit.
2. **Scenario count.** Already cut 12 → 8. If needed, 6 (2 dev / 4 holdout) — but protect class balance
   including restatement, not_requirement and reversal.
3. **Synthetic n≈200 retrieval stress register.** Only build it if Ablation A shows top-k losing.
4. **Ablation B** (baseline prompt plus state engine).
5. **Any UI beyond the three scripted demo tasks.**

**Never cut:** engine property tests, the call logger, the evidence validator, gold-decision replay,
three repeats, prompt freeze, the baseline.

## Risk register with tests

| Risk | Guard |
|---|---|
| Wrong historical ID | Reviewer sees retrieved families; E3 confusion matrix; per-call enum makes invented IDs structurally 0 |
| False supersession on hedges | Annotation guide + `not_requirement` label + authority guard in rule table; ≤0.05 target on E5 |
| Compound utterances | Extractor `atomic` requirement; split before classify |
| Re-import duplicates | `source_hash` idempotency test (E1) |
| Prompt injection in transcript | Dev and **holdout** adversarial files; tools cannot leave project; outputs schema-validated |
| Schema / JSON failure | One retry, logged; second failure counted as error, never a fallback |
| Temperature 0 not deterministic | Three repeats, mean and spread; never claim bitwise reproducibility |
| No-match bias toward picking an ID | Report no-match precision separately. Accepted residual risk: the model always receives k candidates, which biases against `no_match`. A score floor would help but needs tuning on three dev scenarios, so we measure instead of tune |
| Prompt author contamination | Holdout gold unreadable during prompt iteration |
| Near-duplicate distinct requirements | At least one dev scenario built solely around this trap |
| Retrieval loses to full-context at n≤60 | Ablation A early; synthetic stress register as contingency |
| Corpus authoring slips | Dev split of 3 unsticks all build stages; holdout can land as late as Week 9 |
