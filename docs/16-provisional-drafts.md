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
| Reversals correct (H1+H2, support 5) | 1 | 1 | 2 |
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
3. H1 contradiction is correct in state but scored wrong on version (v3 vs v2) because the
   delayed approval was labelled refinement instead of restatement.
4. Extraction F1 near 1.0 reflects draft simplicity (every turn is one clean sentence), not skill.

No prompt or rule was changed after reading these drafts.
