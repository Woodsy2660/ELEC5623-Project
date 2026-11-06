# Provisional out-of-sample test on AI-authored drafts

Commit f444ad8 (prompts and rules frozen). Scenarios: scenarios/provisional-ai-drafts/H1-H5,
AI-authored, dialogue and labels from one source, no adjudication, ~145 words per scenario,
structure cloned from D2. Folder renamed from "holdout" so the dev scorer's holdout guard is not bypassed
by name; these drafts are not a holdout. Three repeats each of oracle, pipeline, baseline; all 45 exited 0.
Per-scenario tables: report.md.

## Mean of per-scenario means, H1-H5

| Metric | oracle | pipeline | baseline |
|---|---:|---:|---:|
| Four-class macro-F1 | 0.63 | 0.70 | 0.71 |
| Six-class macro-F1 | 0.73 | 0.76 | 0.41 |
| Extraction F1 | - | 0.98 | - |
| Historical-id accuracy | 0.53 | 0.58 | 0.47 |
| No-match accuracy | 0.92 | 0.94 | 0.51 |
| Joint id+label accuracy | 0.66 | 0.68 | 0.40 |
| Reversals correct (H1+H2, support 5) | 1 | 1.33 | 2 |
| Illegal-transition rate | 0 | 0 | 0.17 (H1), 0.08 (H2) |

## Findings

1. Replacement guard does not generalise. "Replace X with Y" (H1, H2) and "Do X instead of Y"
   (H2) carry no "we will / let's" frame, so explicit_replacement() returns False and every
   supersession is held unresolved. The guard was written against D1/D2 wording.
2. Wrong contradictions reached the register. H3 has two near-duplicate requirements (parcels
   collected at pickup vs delivered to household). The classifier labelled the second as a
   contradiction of the first and a later restatement as a contradiction; the authorised,
   unhedged speaker passed the authority guard. Oracle wrote 2 wrong contradictions in each repeat,
   pipeline 1. H5 oracle r3 wrote 1. The guard checks who spoke and how, not what was said.
3. H1 contradiction is correct in state but scored wrong on version (v3 vs v2) when the
   delayed approval was labelled refinement instead of restatement.
4. Extraction F1 near 1.0 reflects draft simplicity (every turn is one clean sentence), not skill.

No prompt or rule was changed after reading these drafts.

## Scorer fix (applies to every run)

`_prediction_records` took per-meeting cutoffs only from meetings that produced register
events, so a meeting with only restatements, no-ops or rejections had no state and every
requirement was scored wrong there. Cutoffs now also come from proposals; the state carries
over. Test: `test_meeting_without_writes_keeps_the_carried_over_register_state`. Rescoring
every stored run changed only H1 pipeline r1 above (reversals 0 to 1); D1, D2 and CMU
snapshot numbers are unchanged. Baselines use the same scorer.

## Post-hoc guard fix (after reading these drafts)

Both defects were fixed with general wording rules, not the draft sentences, then checked
on D1, D2 and CMU for regression. One repeat each, oracle and pipeline; before = f444ad8
mean of 3. These numbers are post hoc for H1-H5 and must be reported as such; the f444ad8
tables above remain the primary out-of-sample result.

- `explicit_replacement` accepts "Replace A with B", "Change/switch/move ... to B" at the
  start of a sentence, and unhedged "instead of" / "rather than"; "no longer" is not negation.
- `cancellation_stated`: a contradiction must state a withdrawal (cannot, won't, no longer,
  not needed, drop, remove, withdraw, ...) or it is held unresolved.

| Scenario | System | Reversals correct | Reversal writes | Wrong reversal writes | 4-class F1 |
|---|---|---:|---:|---:|---:|
| D1 | oracle | 1 → 1 | 1 → 1 | 0 → 0 | 0.70 → 0.70 |
| D1 | pipeline | 1 → 1 | 1 → 1 | 0 → 0 | 0.56 → 0.62 |
| D2 | oracle | 3 → 3 | 3 → 3 | 0 → 0 | 0.86 → 0.83 |
| D2 | pipeline | 3 → 3 | 3 → 3 | 0 → 0 | 0.74 → 0.73 |
| H1 | oracle | 0 → 1 | 1 → 2 | 0 → 0 | 0.69 → 0.84 |
| H1 | pipeline | 0.33 → 2 | 1 → 2 | 0 → 0 | 0.76 → 0.88 |
| H2 | oracle | 1 → 3 | 1 → 3 | 0 → 0 | 0.83 → 0.88 |
| H2 | pipeline | 1 → 3 | 1 → 3 | 0 → 0 | 0.88 → 0.84 |
| H3 | oracle | — | 2 → 0 | 2 → 0 | 0.63 → 0.67 |
| H3 | pipeline | — | 1 → 0 | 1 → 0 | 0.57 → 0.56 |
| H5 | oracle | — | 0.33 → 0 | 0.33 → 0 | 0.56 → 0.65 |

No D1, D2 or CMU reversal changed. CMU has no reversals, so its movement in new/refinement
counts (for example github pipeline non-requirements written 7 → 2) is run-to-run model
variation from one repeat, not the rules, which only gate supersession and contradiction.
H1 oracle stays at 1 because the delayed approval was labelled refinement (version v3 vs v2).
Run directory: runs/eval-guards-fix (gitignored).
