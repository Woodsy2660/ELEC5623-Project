# 13 — D1 dev results, first live run

Run on 3 November 2026. This file records the first live runs of one dev scenario, in the order they
happened. Use "Three-repeat results" for current figures; earlier sections explain how the code reached
that state. None of this is the experiment's result: no holdout was scored, and D1 has only 14 gold
events.

## Configuration

| Setting | Value |
|---|---|
| Scenario | `scenarios/dev/D1`, 2 meetings, 14 gold events |
| Resource and deployment | `Consulting-Agent-System`, `cia-chat` |
| Served model | `gpt-4o-2024-11-20` |
| Temperature, seed | 0, 42 |
| Mode, repeat | `eval`, 1 |

| Column | Run ID | Database (local, gitignored) |
|---|---|---|
| oracle | `a035b9cd-4bd3-4c5c-a599-548ceb35c115` | `d1-oracle-r3.db` |
| pipeline | `f79713e4-2c90-41ae-8b1b-8a3e15b6baf4` | `d1-pipeline-r1.db` |
| baseline | `f13764fb-44c0-4ecc-98c0-58d1db4aa6ea` | `d1-baseline-r1.db` |

Full figures are in `runs/<run_id>/score.json`, which is also gitignored.

Three earlier oracle attempts failed on Azure configuration and are excluded because no model output
exists for them: `38920de9-c0b0-49b9-ad72-4959aad76ceb` and `78397776-57ca-47e0-9e7d-b118337f7a0e`
(401), and `dbf97b63-0fa9-4c90-9982-e4c7b492c2f0` (404).

## Results

The fair system comparison is pipeline against baseline, because both start from the transcript. Oracle
uses gold candidates, so it isolates the stages after extraction.

| Metric | Oracle | Pipeline | Baseline |
|---|---:|---:|---:|
| Four-class macro-F1 (see note) | 0.782 | 0.349 | 0.747 |
| F1 `new` (support 8) | 0.824 | 0.824 | 0.824 |
| F1 `refinement` (support 4) | 0.857 | 0.222 | 0.750 |
| F1 `supersession` (support 2) | 0.667 | 0.000 | 0.667 |
| Extraction precision / recall / F1 (E2) | skipped | 0.600 / 0.643 / 0.621 | skipped |
| Evidence support accuracy | skipped | 0.750 | skipped |
| Fused retrieval recall at 3, 5, 8 (support 6) | 0.833 | 0.333 | not applicable |
| Historical-id accuracy (support 6) | 4/6 | 1/6 | 5/6 |
| No-match accuracy (support 8) | 8/8 | 7/8 | 7/8 |
| No-match precision | 0.800 | 0.700 | 0.778 |
| Joint id and label (support 14) | 11/14 | 8/14 | 11/14 |
| E4 illegal-transition rate | 0/21 | 0/23 | 0/23 |
| E5 accuracy, meeting 1 (support 6) | 5/6 | 4/6 | 6/6 |
| E5 accuracy, meeting 2 (support 8) | 5/8 | 2/8 | 6/8 |
| Reversal final-state accuracy (support 2) | 0/2 | 0/2 | 1/2 |
| False supersession (support 12) | 0 | 0 | 0 |
| Invented-id rate | 0/4 | 0/5 | 0/5 |
| Classifier errors | 0 | 0 | 0 |
| Model calls, including local embeds | 28 | 32 | 2 |
| Input / output tokens | 14,242 / 628 | 18,467 / 1,740 | 3,281 / 985 |
| Logged cost | 0.0414 | 0.0630 | 0.0181 |
| Latency p50 / p95, ms | 938 / 1,255 | 924 / 1,426 | 2,284 / 2,316 |

Note: `contradiction` has no gold support in D1, so the headline mean covers three classes.

## Reading

- On this run the pipeline does worse than the baseline on classification, id accuracy, E5 and reversal
  accuracy. Reversal support is 2, so this is a direction and not an effect size.
- Most of the loss comes before classification. Macro-F1 falls from 0.782 with gold candidates to 0.349
  with extracted candidates. Extraction missed 5 of 14 gold events and returned 6 spurious candidates;
  5 of 20 returned candidates failed evidence resolution.
- With gold candidates the system and baseline are close on classification, and the baseline is still
  ahead on E5. These stages have not shown an advantage on D1.
- E4 does not separate the systems here: the baseline also had 0 illegal transitions. At this register
  size the baseline is also cheaper, so the cost argument in the null-result protocol does not hold on D1
  either.
- A missed `new` shifts later ids and removes that family from the E5 and retrieval denominators' reach,
  so one early error can cost several downstream items.

## Extraction failure analysis

**The pipeline column above is affected by a defect, so it does not yet measure the design.** The prompt
template `prompts/extract_v1.jinja:79` renders turn text with Jinja's `tojson` filter, which escapes `'`
as `'`. The extractor is the only call that does this: the classifier and the baseline use
`json.dumps(..., ensure_ascii=False)` and send a plain apostrophe. The baseline did not have this defect.

The model then returned quotes in which the apostrophe had become U+2019 in meeting 1 and U+0001 in
meeting 2. `resolve_quote` is byte-exact, as FR06 requires, so those candidates were rejected.

| Rejected candidate | Quote problem | Gold events lost |
|---|---|---|
| `D1-M01-C0004` special character | apostrophe | 2 |
| `D1-M02-C0000` sixty minutes | apostrophe | 7 |
| `D1-M02-C0001` two-factor | apostrophe | 8, 9 |
| `D1-M02-C0002` account balance | apostrophe | 10 |
| `D1-M01-C0005` recent orders | model cut the quote and added a full stop | none directly |

Those four apostrophe rejections match all 5 extraction misses, including one of the two reversals. The
link between the escape and the changed character is inferred from these outputs; a rerun with the
escape removed is the test.

Other extraction issues remain after that fix:

- **Hedges lose their hedge.** The prompt's NORMALISE rule turns "Should we consider social login?" into
  "The system should support social login". It was classified `new` and confirmed, although the next turn
  declines it. This is one of the target failure modes.
- **Over-extraction changes the register.** Five of the 6 spurious candidates were confirmed under eval
  auto-confirm: one wrong `new`, and four wrong refinements (R01 and three on R08).
- **Compound handling is uneven.** One two-factor candidate merged gold events 8 and 9, while the
  recent-orders and pending-shipments sentence was split, and only the second half survived.

The exact-match validator should stay as it is. Loosening it would repair output by parsing, which
`AGENTS.md` rule 8 forbids. The fix belongs on the input side.

## Rerun after the escaping fix

`extract_v1.jinja` now receives text from `json.dumps(..., ensure_ascii=False)`, so apostrophes reach the
model unescaped. The run is `9661ec55-1200-49de-97db-3d1900aca5d9` in `d1-pipeline-r2.db`, extract prompt
blob `de9ff641ad70a7fb18285f2abfc23ee8070094b3`. This is still one repeat. Use the "after" column in place
of the pipeline column above; the earlier run stays on record as the defect's measured effect.

| Metric | Before | After | Baseline |
|---|---:|---:|---:|
| Evidence rejections | 5/20 | 0/15 | not applicable |
| Extraction precision / recall / F1 | 0.600 / 0.643 / 0.621 | 0.800 / 0.857 / 0.828 | skipped |
| Evidence support accuracy | 0.750 | 1.000 | skipped |
| Four-class macro-F1 | 0.349 | 0.563 | 0.747 |
| F1 `new` / `refinement` / `supersession` | 0.824 / 0.222 / 0.000 | 0.737 / 0.286 / 0.667 | 0.824 / 0.750 / 0.667 |
| Fused retrieval recall at 3, 5, 8 | 0.333 | 0.667 | not applicable |
| Historical-id accuracy | 1/6 | 2/6 | 5/6 |
| No-match accuracy / precision | 7/8, 0.700 | 7/8, 0.636 | 7/8, 0.778 |
| Joint id and label | 8/14 | 9/14 | 11/14 |
| E4 illegal-transition rate | 0/23 | 0/25 | 0/23 |
| E5 meeting 1 / meeting 2 | 4/6, 2/8 | 4/6, 2/8 | 6/6, 6/8 |
| Reversal final-state accuracy | 0/2 | 0/2 | 1/2 |
| Input / output tokens | 18,467 / 1,740 | 18,435 / 1,396 | 3,281 / 985 |
| Logged cost | 0.0630 | 0.0594 | 0.0181 |

The rerun confirms the escaping diagnosis. It does not close the gap to the baseline. The pipeline is
still behind on the stages after extraction.

### Reversals are blocked by the replacement rule

The classifier got the session-timeout reversal right in both the oracle and the rerun: the correct
family, `supersession`, `replacement_stated` true, from an authorised speaker. The engine still returned
`unresolved`, so eval rejected it.

`explicit_replacement` in `src/persist/review.py:99` decides this from the quote, and the classifier's
value is not used. It recognises only "we will use or adopt ... instead" and "we will replace ... with",
and it returns false if the quote has a word such as `should`. "Let's change it to sixty minutes instead"
matches neither pattern. The second gold reversal, "Users should receive email notifications ...", would
fail on `should`.

So on D1 the deterministic guard cannot pass either reversal, while the baseline has no such guard. The
rule is a declared conservative MVP choice and fails safe, so this is a design decision and not a defect.
Any change needs care: fitting patterns to D1 wording would not generalise, and the claim under test
depends on this stage. The rule was changed afterwards; see the next section.

### Remaining pipeline errors

- `Passwords must include at least one special character` was classified `new`, not a refinement of the
  password requirement.
- Account balance and the email notification change were also classified `new`.
- "Email and password only for the initial release" was wrongly applied as a refinement of R01.

## Replacement rule change

The old rule also failed the project's own example: `docs/05-annotation-and-corpus.md` gives "We'll use
SSO instead" as a supersession, and the rule accepted only "we will". Four options were compared offline
on 22 sentences from the spec plus handwritten hedges, and on all 70 D1 sentences. These sentences were
written by the same author as the rule, so this is a sanity check and not an independent evaluation.

| Option | Replacements accepted | Hedges and non-replacements accepted |
|---|---:|---:|
| Current rule | 2/8 | 1/14 |
| Add the D1 sentence only | 3/8 | 1/14 |
| Trust the classifier's `replacement_stated` | 8/8 | 14/14 |
| **Decision phrase plus replacement frame (chosen)** | 8/8 | 0/14 |

The chosen rule needs a decision phrase ("we will", "we'll", "we're going to", "we decided to", "let's")
and a frame: "use, adopt or go with B instead", "replace A with B", or "change, switch or move ... to B".
It adds `unless`, `may`, `possibly` and `probably` to the hedge check and treats a curly apostrophe as
`'`, so "won’t" is now caught. Across D1 it accepts exactly one sentence, the sixty-minute change.

The rule still operates on the quote alone. A wider quote containing a hedge word, such as "Thirty minutes
might be too short ... Let's change it to sixty minutes instead", stays `unresolved`. "Users should receive
email notifications ... in addition to in-app notifications" also stays `unresolved`, which fails safe. The
rule is not covered by the run's prompt hash, so it must be frozen with the prompts by commit.

| Metric | Oracle before | Oracle after | Pipeline before | Pipeline after | Baseline |
|---|---:|---:|---:|---:|---:|
| Run | `a035b9cd` | `aebeba98` | `9661ec55` | `f82e75c1` | `f13764fb` |
| Reversal final-state accuracy | 0/2 | **1/2** | 0/2 | **1/2** | 1/2 |
| Four-class macro-F1 | 0.782 | 0.722 | 0.563 | 0.658 | 0.747 |
| Extraction F1 | skipped | skipped | 0.828 | 0.897 | skipped |
| Fused retrieval recall at 3, 5, 8 | 0.833 | 0.667 | 0.667 | 0.833 | not applicable |
| Historical-id accuracy | 4/6 | 3/6 | 2/6 | 3/6 | 5/6 |
| Joint id and label | 11/14 | 9/14 | 9/14 | 10/14 | 11/14 |
| E5 meeting 1 | 5/6 | 3/6 | 4/6 | 6/6 | 6/6 |
| E5 meeting 2 | 5/8 | 4/8 | 2/8 | 5/8 | 6/8 |
| E4 illegal-transition rate | 0/21 | 0/21 | 0/25 | 0/26 | 0/23 |
| False supersession (support 12) | 0 | 0 | 0 | 0 | 0 |
| Logged cost | 0.0414 | 0.0418 | 0.0594 | 0.0606 | 0.0181 |

Only the reversal row can be credited to the rule: the sixty-minute change now passes in both columns, and
no false supersession appeared. **Everything else in this table is run-to-run variation.** The rule cannot
change classification or extraction, yet those moved with the same prompts, model, temperature 0 and seed
42. Oracle E5 for meeting 1 fell and pipeline extraction F1 rose, and neither has anything to do with this
rule. Differences of this size between single runs must not be reported as effects. Three repeats are
required before any comparison, as `docs/04-evaluation.md` specifies.

## Three-repeat results

This is the current D1 record. The tables above show how the code reached this state. All nine runs use
the current code, `eval` mode and `cia-chat`, and none had a classifier error. Repeat 1 reuses the runs in
the section above. Total logged cost is 0.386.

| System | Repeat 1 | Repeat 2 | Repeat 3 |
|---|---|---|---|
| oracle | `aebeba98-462c-424b-b1a1-df2ba6e3859c` | `76a91d36-27c1-4096-b9a5-9a9e28139dc0` | `68556f64-14e5-458e-8ec6-e46e3fb2a7b9` |
| pipeline | `f82e75c1-3813-4ff4-ae30-ab5eafb1983b` | `f59e0e90-b2b5-49e6-b628-5e459c6127f1` | `d4c83b2d-af63-4850-bddb-76ee3f6cbad2` |
| baseline | `f13764fb-44c0-4ecc-98c0-58d1db4aa6ea` | `75719a4d-731b-40a9-ba71-2512e5e377aa` | `fb3710e7-fa08-486b-a296-4dec6014b226` |

Each cell is the mean, the sample standard deviation, and the three values in repeat order.

| Metric | Oracle | Pipeline | Baseline |
|---|---:|---:|---:|
| Four-class macro-F1 | 0.710 ± 0.011 (0.722, 0.704, 0.704) | 0.573 ± 0.076 (0.658, 0.511, 0.551) | 0.714 ± 0.120 (0.747, 0.581, 0.815) |
| F1 `new` | 0.769 ± 0.016 | 0.712 ± 0.021 | 0.814 ± 0.033 |
| F1 `refinement` | 0.694 ± 0.048 | 0.341 ± 0.208 | 0.606 ± 0.183 |
| F1 `supersession` | 0.667 ± 0.000 | 0.667 ± 0.000 | 0.722 ± 0.255 |
| Extraction F1 | skipped | 0.794 ± 0.106 (0.897, 0.686, 0.800) | skipped |
| Fused recall at 5 (support 6) | 0.778 ± 0.096 | 0.722 ± 0.096 | not applicable |
| Historical-id correct, of 6 | 3.00 (3, 3, 3) | 2.33 (3, 2, 2) | 3.67 (5, 2, 4) |
| Joint id and label correct, of 14 | 9.67 (9, 10, 10) | 9.33 (10, 9, 9) | 10.67 (11, 10, 11) |
| E5 correct, meeting 1 of 6 | 3.67 (3, 4, 4) | 4.67 (6, 4, 4) | 5.33 (6, 5, 5) |
| E5 correct, meeting 2 of 8 | 4.67 (4, 5, 5) | 4.33 (5, 5, 3) | 5.67 (6, 5, 6) |
| Reversal final state correct, of 2 | 1.00 (1, 1, 1) | 1.00 (1, 1, 1) | 1.67 (1, 2, 2) |
| False supersession applied, of 12 | 0 (0, 0, 0) | 0 (0, 0, 0) | 0.33 (0, 1, 0) |
| Illegal-transition rate | 0 | 0 | 0 |
| Invented-id rate | 0 | 0 | 0 |
| Logged cost per run | 0.042 ± 0.000 | 0.069 ± 0.012 | 0.018 ± 0.000 |
| Input tokens per run | 14,299 | 21,175 | 3,292 |
| Latency p50 / p95, ms | 893 / 1,395 | 942 / 1,299 | 2,258 / 2,386 |

### Reading

- The baseline leads on mean macro-F1, E5 and reversals, but the pipeline and baseline macro-F1 ranges
  overlap: 0.511 to 0.658 against 0.581 to 0.815. Three repeats on 14 events cannot show a reliable
  difference. The mean direction does not support the claim on D1.
- Pipeline instability starts at extraction. Predicted candidates ranged from 15 to 21 and extraction F1
  from 0.686 to 0.897, while oracle macro-F1 held within 0.704 to 0.722.
- Against the proposal bars, D1 means miss all four: extraction F1 0.794 against 0.80, recall 0.722
  against 0.90, historical-id accuracy 0.389 against 0.85, and macro-F1 0.573 against 0.80.
- The pipeline's deterministic guard did prevent writes: 0 false supersessions in 36 opportunities
  against 1 in 36 for the baseline. One event is a lead for the hedge-focused scenarios, not a result.
- The baseline remains cheaper at this register size, at about a quarter of the pipeline's cost.

## Limits

- Three repeats of one dev scenario, with a standard deviation from only three values. Do not cite these
  figures as the system's performance.
- D1 has no `contradiction` gold, no hedge flag and no `event_action`. False supersession is not a
  hedge-only rate, and eval auto-confirms every engine-allowed proposal.
- Oracle retrieval recall is measured through the gold-to-system id map, so it inherits classification
  misses from `new` events.
- The logged cost has no currency field. Treat it as the logger's unit.
