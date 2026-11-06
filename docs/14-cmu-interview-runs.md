# 14 — CMU interview runs

Run on 3 November 2026 on the three public CMU interviews in `scenarios/cmu-demo/`. The aim was to repeat
the D1 test on real elicitation interviews.

**No accuracy figure exists for these runs.** The interviews have no gold labels, so `score.py` cannot
score them and the oracle column cannot run. What follows is gold-free: repeat stability, agreement
between systems, register size and cost. Writing gold for these files would need the independent
annotation protocol in `docs/05-annotation-and-corpus.md`; a gold file written by the developers or an
AI assistant would not count.

Each interview is a separate one-meeting project, so the cross-meeting lifecycle is not exercised.

## Setup

- Pipeline: `run_pipeline --mode eval --candidate-source extracted`, three repeats per interview.
- Baseline: `run_baseline --mode eval`, three repeats per interview.
- `cia-chat`, `gpt-4o-2024-11-20`, temperature 0, seed 42, current working tree (uncommitted).
- Neither speaker can confirm scope. Eval auto-confirms every engine-allowed proposal, and the rule table
  allows `new` from any speaker, so the register below is what eval would write, not approved scope.
- Databases are `cmu-<interview>-pipe-rep<n>.db` and `cmu-<interview>-base-rep<n>.db` (local,
  gitignored). An earlier demo-mode run per interview is in `cmu-<interview>.db`.

## Results

Register size is the number of requirements written by the end of the run.

| Interview | Pipeline register (r1, r2, r3) | Baseline register (r1, r2, r3) |
|---|---|---|
| GitHub, 111 turns | 6, 7, 4 | 0, 0, 0 |
| Email client, 104 turns | 10, 10, 6 | 4, 4, 4 |
| Messaging, 84 turns | 5, 4, 7 | 1, 1, 2 |

| Measure | GitHub | Email | Messaging |
|---|---|---|---|
| Pipeline proposals per run | 7, 9, 4 | 11, 12, 6 | 6, 4, 8 |
| Pipeline candidates rejected by the evidence check | 1, 0, 0 | 4, 3, 2 | 0, 0, 0 |
| Pipeline evidence-turn overlap between repeats (Jaccard) | 0.33, 0.57, 0.44 | 0.58, 0.27, 0.25 | 0.25, 0.62, 0.38 |
| Turns cited in all three pipeline repeats / in any | 4 / 12 | 3 / 14 | 2 / 9 |
| Pipeline vs baseline evidence-turn overlap, per repeat | 0, 0, 0 | 0.18, 0.27, 0.50 | 0, 0.25, 0.12 |
| Pipeline logged cost per run, mean | 0.050 | 0.058 | 0.043 |
| Baseline logged cost per run, mean | 0.021 | 0.025 | 0.018 |
| Pipeline candidates from the interviewer | 0 of 20 | 1 of 29 | 0 of 18 |

No run had a classifier error. All non-`new` pipeline labels were within-meeting refinements.

## Reading

- **The pipeline is unstable on long interviews.** Only 2 to 4 cited turns appear in all three repeats,
  and the register size varies by up to 4 items between repeats with the same prompts and seed.
- **The two systems disagree about what a requirement is.** The baseline wrote nothing for GitHub and at
  most 4 items elsewhere, with stable output. The pipeline wrote 4 to 10. The pipeline extraction prompt
  asks for every statement that proposes a requirement, so it records user wishes; the baseline records
  only what it treats as a register change. Without gold, neither can be called correct.
- **Interviews are not decisions.** The interviewed user cannot approve scope, but eval still creates
  confirmed requirements because the authority check covers only supersession. In demo mode the same
  proposals stay pending for a person, which is the intended use.
- **Prompt-example leakage.** In the demo-mode GitHub run, the extractor returned "users log in using
  email" and "a logout button", both copied from examples in `prompts/extract_v1.jinja` and cited to the
  interviewer's greeting. The evidence check passed them because the quote exists in the turn. It checks
  that a quote exists, not that it supports the statement. This did not recur in the nine eval-mode runs.
- **Evidence rejections were correct.** Every rejection was a quote the model altered, such as a comma
  changed to a full stop, or a paraphrase.

## What this does not show

- Extraction precision or recall, classification accuracy, or any E5 state accuracy.
- Anything about reversals or other cross-meeting behaviour.
- That either system is better on these interviews.
