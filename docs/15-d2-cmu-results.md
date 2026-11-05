# 15 — D2 and CMU results, three repeats

Run on 5 November 2026. Oracle, pipeline and baseline were each run three times on the new dev scenario
D2 and on the three CMU interviews with draft gold (`scenarios/real-cmu/`). None of this is the
experiment's result: no holdout was scored, D2 is one dev scenario with 18 events, and the CMU set is a
supplementary real-speech set, not a holdout.

## Configuration

| Setting | Value |
|---|---|
| Code and prompts | commit `23378b3`; prompts unchanged since |
| Resource and deployment | `Consulting-Agent-System`, `cia-chat` |
| Served model | `gpt-4o-2024-11-20` |
| Temperature, seed | 0, 42 |
| Mode | `eval`, repeats 1–3, one fresh database per run |
| Gold | AI-drafted; Lucas reports a human review on 5 November with no edits. Reviewer names still to be recorded in the scenario READMEs |

Run IDs are listed in `runs/eval-2026-11-05/runs.tsv`; databases, logs and every `score.json` are under
`runs/`, which is gitignored. All 36 runs exited cleanly and were scored without errors.

## D2 (dev, authored, three meetings)

Each cell is the mean, the sample standard deviation, and the three values in repeat order.

| Metric | Oracle | Pipeline | Baseline |
|---|---:|---:|---:|
| Four-class macro-F1 | 0.831 ± 0.000 | 0.549 ± 0.157 (0.412, 0.721, 0.512) | 0.810 ± 0.000 |
| Six-class macro-F1 | 0.874 ± 0.000 | 0.540 ± 0.133 (0.432, 0.688, 0.499) | 0.540 ± 0.000 |
| Extraction F1 (precision / recall) | skipped | 0.767 (0.846 / 0.704) | skipped |
| Historical-id accuracy, of 12 | 0.833 | 0.528 (0.500, 0.583, 0.500) | 0.250 |
| No-match accuracy, of 6 | 1.000 | 0.722 (0.667, 0.833, 0.667) | 0.333 |
| Joint id and label correct, of 18 | 0.833 | 0.519 (0.444, 0.611, 0.500) | 0.278 |
| Reversal final state correct, of 3 | 2 (2, 2, 2) | 1.67 (2, 1, 2) | 2 (2, 2, 2) |
| Supersession label on a non-supersession event | 1 (1, 1, 1) | 1.33 (2, 1, 1) | 0 |
| Illegal-transition rate, invented-id rate | 0, 0 | 0, 0 | 0, 0 |
| Logged cost per run | 0.054 | 0.066 ± 0.007 | 0.019 |
| Input tokens per run | 18,258 | 19,778 | 4,276 |
| Latency p50, ms | 1,020 | 997 | 1,803 |

### Reading

- The baseline leads on the four-class headline (0.810 against 0.549) and is far cheaper. The pipeline
  leads on matching: historical-id accuracy 0.528 against 0.250, no-match accuracy 0.722 against 0.333,
  joint accuracy 0.519 against 0.278. The baseline emits no `restatement` or `not_requirement`, so its
  six-class score is low for a different reason than the pipeline's.
- With gold candidates the classifier reaches 0.831, so most of the pipeline gap comes from extraction
  (recall 0.704), as on D1.
- The baseline was identical across all three repeats; the pipeline varied from 0.412 to 0.721.
- Every system ended 2 of 3 reversals correct, for different reasons (below).

### Failure analysis

1. **The replacement guard blocks a real replacement.** In Meeting 3 the client says "from now on
   password reset links should be sent by text message instead of email". The classifier labelled it
   `supersession` in every run, but `explicit_replacement` requires a decision phrase such as "we'll" or
   "let's", so the proposal became `unresolved` and was rejected. R02 stays on email: this is the
   reversal every system misses. The same guard correctly stopped the back-reference "the old email
   reset links are gone now, replaced by text messages as of today", which the classifier also labelled
   `supersession`. The guard trades recall on natural phrasing for safety.
2. **The supersession metric counts labels, not writes.** "Supersession label on a non-supersession
   event" is the `false_supersession.applied` field of `score.py`. It counts classifier labels after any
   downgrade. In the oracle runs the one counted case was the back-reference above, which the engine did
   not apply. A register-level false-supersession count would read 0 here.
3. **Hedges reach the register through `contradiction`.** In pipeline repeat 1 the extractor rewrote the
   question "could they go out as a text message rather than email?" as "The system should consider
   sending receipts as text messages instead of emails." The classifier labelled it `contradiction`
   against R03 and the engine allowed it, so R03 was contradicted in Meeting 1. The hedge guard covers
   supersession only.
4. **The extractor rephrases.** Candidates are normalised into "The system should…" sentences, which
   removes the hedging words the guard looks for. Failure 3 depends on this.

## Replacement rule fix (failure 1)

Two changes to `src/persist/review.py`, then oracle and pipeline rerun three times on D1 and D2 (12
runs, same day, same model and prompts). The baseline has no rule engine, so its runs above still apply.

1. **Dated commitment frame.** `explicit_replacement` also accepts "from now on / going forward / from
   today / as of today / starting today" together with "instead of / rather than". "Should" is accepted
   only in this frame. Past-tense back-references ("replaced by text messages as of today", "that was
   replaced by single sign-on last time") are still rejected.
2. **Whole-sentence evidence.** The extractor quoted "password reset links should be sent by text
   message instead of email" and dropped the "from now on" in front, so change 1 alone did not help the
   pipeline. `evidence_sentence` widens each span to its sentence before the rule reads it, in both the
   eval runner and the review API. This also exposes a leading "If legal agrees," that a cropped quote
   would hide.

| Scenario | Metric | Before | Change 1 only | Changes 1 and 2 | Baseline |
|---|---|---:|---:|---:|---:|
| D2 | Oracle four-class macro-F1 | 0.831 | 0.881 | 0.848 ± 0.029 | — |
| D2 | Oracle reversals correct, of 3 | 2 | 3 | 3 (3, 3, 3) | — |
| D2 | Pipeline four-class macro-F1 | 0.549 ± 0.157 | 0.462 ± 0.087 | 0.535 ± 0.120 | 0.810 |
| D2 | Pipeline reversals correct, of 3 | 1.67 (2, 1, 2) | 1.67 (2, 2, 1) | **2.67 (3, 2, 3)** | 2 |
| D1 | Oracle four-class macro-F1 | 0.710 | 0.710 | 0.617 ± 0.105 | — |
| D1 | Pipeline four-class macro-F1 | 0.573 (docs/13) | 0.594 ± 0.008 | 0.603 ± 0.021 | 0.714 |
| D1 | Pipeline reversals correct, of 2 | 1 | 1 | 1 (1, 1, 1) | 1.67 |

- The fix does what it was for: on D2 the SMS replacement now commits in every oracle run and in two of
  three pipeline runs, and the pipeline reaches 2.67 of 3 reversals against the baseline's 2.
- Every supersession that reached the register in the 12 reruns is a gold supersession (sixty minutes,
  single sign-on, SMS). No hedge or back-reference was written.
- The D1 oracle drop is classifier variance, not the rule: in repeat 1 the classifier labelled the
  password rules as refinements of login and the sixty-minute change as a contradiction of the wrong
  family, before the rule was consulted. Repeats 2 and 3 match earlier runs.
- The headline gap to the baseline remains; it comes from extraction (failure 4) and from hedges
  reaching the register through `contradiction` (failure 3), which this fix does not touch. The
  remaining D2 pipeline reversal miss (repeat 2) is the receipt contradiction: R03 ends at
  `confirmed` v2 instead of `contradicted`.

Run IDs: `runs/eval-2026-11-05-rule2/runs.tsv` (change 1) and `runs/eval-2026-11-05-rule3/runs.tsv`
(changes 1 and 2).

## Hedge guard on contradiction (failure 3)

`assess_proposal` now takes an explicit `hedged` input and returns `unresolved` for a hedged
`contradiction`. `hedged_statement` reads the same widened evidence sentences as the replacement rule
and looks for "if, unless, maybe, perhaps, possibly, probably, may, might, could, would" or a question
mark. Negation is deliberately not a hedge. Tests: 399 pass, including 69 engine tests with no network.

**Offline replay on earlier runs.** All 23 contradictions committed in the runs above (before the
guard) were re-checked with the new rule:

| Committed contradiction | Count | New rule |
|---|---:|---|
| "And the receipts, could they go out as a text message rather than email?" (D2 pipeline) | 6 | held |
| "…IT won't renew it, so the automatic receipt emails can't happen as agreed" (D2, all systems) | 13 | kept |
| "Let's change it to sixty minutes instead." classified as contradiction (D1 oracle repeat 1) | 1 | kept |
| Interviewer summary "…file sharing, and no cloud storage for your messages" (CMU messaging oracle) | 3 | kept |

The guard removes every hedge leak and keeps every genuine contradiction. The two remaining misfires
are not hedges: a classifier error, and an unauthorised speaker. The interviewer cannot confirm scope,
but contradiction has no authority guard; supersession does.

**Live reruns.** Oracle and pipeline were rerun three times on D1, D2 and the three CMU interviews
(30 runs, `runs/eval-2026-11-05-hedge/runs.tsv`). The classifier never labelled a hedge
`contradiction` in these runs, so the guard was not triggered live; its effect is shown by the replay
above, not by these scores.

| Scenario | Metric | Changes 1 and 2 | Plus hedge guard | Baseline |
|---|---|---:|---:|---:|
| D1 | Oracle four-class macro-F1 | 0.617 ± 0.105 | 0.710 ± 0.011 | — |
| D1 | Pipeline four-class macro-F1 | 0.603 ± 0.021 | 0.600 ± 0.043 | 0.714 |
| D2 | Oracle four-class macro-F1 | 0.848 ± 0.029 | 0.881 ± 0.000 | — |
| D2 | Oracle reversals correct, of 3 | 3 | 3 | — |
| D2 | Pipeline four-class macro-F1 | 0.535 ± 0.120 | 0.592 ± 0.174 (0.537, 0.787, 0.452) | 0.810 |
| D2 | Pipeline reversals correct, of 3 | 2.67 (3, 2, 3) | 1.67 (2, 2, 1) | 2 |

- Every supersession and contradiction written in the 30 reruns is a gold reversal, except the CMU
  interviewer summary above (oracle repeats 1 and 2).
- The D2 pipeline reversal count moved down although the guard never fired. In repeat 1 the extractor
  produced no candidate for the receipt contradiction. In repeat 3 it produced "The system should not
  send automatic receipt emails." and the classifier labelled it `supersession`; the replacement rule
  held it, correctly, because no replacement is stated. The same repeat turned the SMS question into
  "The system should send receipts via SMS instead of emails", also labelled `supersession` and held,
  because the widened sentence carries "could" and a question mark. With three repeats, 1.67 and 2.67
  are within extraction and classification variance; neither is a stable estimate.
- The differences in oracle scores between rounds are classifier variance at temperature 0; the rules
  run after classification.

## CMU interviews (real speech, one meeting each)

Gold here is mostly `not_requirement`: 12 of 12 events in github, 11 of 16 in email and 10 of 12 in
messaging. See `scenarios/real-cmu/README.md` for the labelling rule.

### Scorer figures

| Interview | Metric | Oracle | Pipeline | Baseline |
|---|---|---:|---:|---:|
| github | Six-class macro-F1 | 0.909 | 0.000 | 0.000 |
| github | No-match accuracy | 0.917 | 0.194 | 0.028 |
| email | Six-class macro-F1 | 0.345 ± 0.077 | 0.054 ± 0.017 | 0.084 ± 0.011 |
| email | Extraction F1 | skipped | 0.414 ± 0.060 | skipped |
| email | No-match accuracy | 0.978 | 0.400 | 0.222 |
| messaging | Six-class macro-F1 | 0.445 ± 0.032 | 0.025 ± 0.043 | 0.193 ± 0.051 |
| messaging | No-match accuracy | 1.000 | 0.333 | 0.242 |
| all three | False supersession, illegal transitions | 0, 0 | 0, 0 | 0, 0 |

These extracted-run figures are dominated by a scoring rule, not by behaviour. Under hard rule 8, a gold
event with no aligned prediction is an error. For a `not_requirement` utterance the extractor did not
pick up, that counts correct restraint as a miss. The github baseline extracted nothing in two of three
runs and scores 0. D1 had no `not_requirement` gold, so the rule had not been exercised before. The
scorer is unchanged; whether a skipped `not_requirement` should count as an error is a team decision.

### What reached the register

Counted from the six-class confusion of each run, per repeat. "Explicit asks caught" is gold `new`
predicted `new`. "Requirements from non-requirements" is gold `not_requirement` predicted as any
transition-driving label. "Requirements from unlabelled turns" is an extracted candidate that aligns with
no gold event and was predicted as a transition-driving label.

| Interview | System | Explicit asks caught | Requirements from non-requirements | Requirements from unlabelled turns |
|---|---|---|---|---|
| github | oracle | — | 2, 2, 2 of 12 | — |
| github | pipeline | — | 4, 0, 4 of 12 | 5, 4, 4 |
| github | baseline | — | 0, 1, 0 of 12 | 0, 2, 0 |
| email | oracle | 0, 1, 1 of 4 | 1, 1, 1 of 11 | — |
| email | pipeline | 1, 2, 1 of 4 | 5, 5, 4 of 11 | 5, 8, 8 |
| email | baseline | 1, 1, 1 of 4 | 2, 2, 3 of 11 | 2, 0, 0 |
| messaging | oracle | 1, 1, 1 of 1 | 3, 2, 2 of 10 | — |
| messaging | pipeline | 1, 0, 0 of 1 | 4, 4, 3 of 10 | 6, 4, 4 |
| messaging | baseline | 1, 1, 1 of 1 | 1, 1, 3 of 10 | 0, 0, 0 |

### Reading

- On real interviews the pipeline over-extracts. Per run it turned 10 to 13 non-requirements into
  register entries in email and 7 to 10 in messaging (non-requirements plus unlabelled turns), against 0 to 4 for the baseline. Human review
  would have to reject them.
- Neither system catches the explicit asks well: email asks were caught 1 or 2 of 4 times by the
  pipeline and once by the baseline.
- No system applied a supersession on unscripted talk; with one meeting per interview, little could be
  superseded.
- The classifier alone (oracle) rejects most hedges and descriptions (no-match accuracy 0.92 to 1.0), so
  the over-extraction comes from the extractor, consistent with failure 4 on D2.

## Limits

- One dev scenario and three single-meeting interviews. The standard deviation comes from three values.
  Do not cite these figures as system performance.
- Gold was drafted by the same assistant that ran the system, and the drafter had seen earlier system
  output on the CMU interviews. The reported review made no edits; independent labelling would be
  stronger.
- Eval mode auto-confirms engine-allowed proposals, so the delayed confirmation in D2 is not measured.
- The CMU "what reached the register" table is derived from the scorer's confusion matrices, not a
  scorer metric.
- The logged cost has no currency field. Treat it as the logger's unit.
