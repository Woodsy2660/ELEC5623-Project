# E3 development classification scoring

This adds offline scoring for **already aligned E3-oracle candidates** (FR07/FR08).
It reads saved predictions and separate development labels. It does not call a
model, align extracted candidates, read the database, replay lifecycle events, or
run the baseline. No authored holdout labels were opened while building it.

The existing retrieval scoring command remains available. This slice adds:

```bash
.venv/bin/python -m src.eval.score \
  --predictions runs/<run-id>/classification-predictions.json \
  --gold <reviewed-dev-classification-labels.json> \
  --output runs/<run-id>/classification-metrics.json
```

These paths describe files supplied by the future logged caller/harness, not
evaluation data shipped by this PR. Output goes into an existing directory.
The tests create temporary software-check inputs; they are not model results.

## Saved prediction format

`src/eval/classification_schemas.py` defines the label-free run and observation
schemas. The top-level JSON object has the following fields:

| Field | Value |
|---|---|
| `schema_version` | `1` (default) |
| `kind` | `"dev-e3-oracle"` |
| `split` | `"dev"`; this entry point refuses holdout paths and split values |
| `method` | `"pipeline"`, `"full_history"`, or `"baseline"` |
| `run_id`, `repeat_index` | Actual logged run ID and repeat `1`, `2`, or `3` |
| `model` | Actual pinned deployment/model identity |
| `prompt_hash` | Actual 40-character lower-case git blob SHA-1 of the prompt |
| `inputs_sha256` | Actual 64-character lower-case SHA-256 of label-free candidate/context inputs |
| `cases` | Array of observations; may be empty so a wholly missing run scores as failures |

Each observation uses `(project_id, case_id)` to identify the same supplied
candidate across methods. It is not matched by text or by list position. IDs
must be preserved by the caller, and must not be invented by the model.

```json
{
  "project_id": "D1",
  "case_id": "M2-C1",
  "status": "ok",
  "offered_ids": ["LOGIN", "RESET"],
  "raw_content": "{\"matched_requirement_id\":\"LOGIN\",\"relation\":\"supersession\",\"rationale\":\"The source explicitly replaces email login with SSO.\"}"
}
```

This is a format example, not an actual prediction. `raw_content` must preserve
the model's per-candidate JSON string before human correction. Its three fields
match the current LLM-2 output schema. No fence removal, field extraction,
defaulting or other JSON repair is performed. A future baseline/harness exporter
must supply compatible per-candidate outputs with original logged provenance;
this scorer does not transform an arbitrary baseline register response.

`offered_ids` comes from request metadata, never from a model's own claim:

- `pipeline`: top-k family IDs actually offered. An empty list is valid for empty
  history. An ok output requires the list; a selected non-null ID outside it is
  an invalid output.
- `full_history`: all family IDs actually offered to the constrained classifier.
  The same validation applies, but no retrieval diagnostics are claimed.
- `baseline`: absent or null. No retrieval enum is imposed. A syntactically valid
  wrong/invented baseline ID is an incorrect match, while its relation is scored
  independently. This scorer cannot identify invented baseline IDs separately
  from other wrong IDs without an independent register manifest.

For a timeout, refusal, exhausted retry, or unresolved result, use `status` of
`"error"` or `"unresolved"` with a nonblank `error` reason. Preserve offered IDs
if available. Raw content may be retained for audit, but receives no metric credit.
Every attempt still needs the project's shared model-call logger; these saved
observations do not replace it or prove that a run was correctly logged.

## Development labels

Only `src/eval/score.py` defines and reads the label schema. The separate JSON file
contains `schema_version: 1`, `split: "dev"`, and a non-empty `cases` array:

```json
{
  "project_id": "D1",
  "case_id": "M2-C1",
  "expected_requirement_id": "LOGIN",
  "expected_relation": "supersession"
}
```

That is one array item, not a complete file. Use independently reviewed dev
labels under the corpus protocol. This format is not the D2 draft event sequence
or the future database `gold_events` format. Keep labels out of inference inputs.

## Scoring rules

- Historical-ID accuracy uses only gold cases with non-null historical IDs.
  Overall ID accuracy also includes null/no-match labels. Joint accuracy requires
  both ID and relation to be correct. A wrong ID can still have a correct relation;
  the two separate metrics must not be confused with joint task success.
- No-match accuracy is correct null IDs / gold null IDs, including any
  `not_requirement` controls labelled with null. No-match precision is correct
  null IDs / valid predicted null IDs. A failed or missing output is never a
  predicted no-match. Undefined denominators are JSON null.
- The headline macro-F1 averages the fixed four driving labels. Secondary F1
  averages all six labels. All gold rows remain in the confusion matrix, so a
  control mislabelled supersession contributes a supersession false positive.
- Missing, invalid, failed and unresolved predictions remain incorrect in primary
  accuracy denominators. Their gold relations contribute false negatives. They
  appear in the confusion matrix's `error` column, not as a seventh relation.
- For each class, `F1 = 2TP / (2TP + FP + FN)`. Zero-denominator class F1 is zero;
  zero-support classes remain in the fixed macro average and are listed explicitly.
  If an entire reported group has no gold support, its macro-F1 is null. Small or
  imbalanced fixtures cannot establish the proposal's target accuracy.
- Identifiable malformed observations count as invalid. Duplicate observations,
  unknown project/case IDs, unidentifiable records, inconsistent gold, malformed
  manifests and duplicate JSON keys in source files abort scoring. Alignment
  errors must be corrected at the source, not guessed or silently discarded.
- For `pipeline`, historical cases distinguish gold absent from offered IDs,
  gold offered but wrong ID selected, and gold offered but no valid output.
  If provenance is unavailable, no retrieval cause is invented. These are
  diagnostics, not E5 final-state or false-supersession scores.

The output records denominators, coverage, error categories, per-class counts,
per-case results, prompt/input identity, and prediction/gold file SHA-256 hashes.
Hashes make source changes detectable; caller-supplied metadata is not verified
against Azure or a database by this offline command.

## Verification and integration boundary

```bash
.venv/bin/python -m pytest tests/test_classification_evaluation.py -q
```

Checks include hand-calculated four/six-class F1, control false positives,
failure accounting, separate matching denominators, project-scoped IDs,
comparator behavior, malformed outputs, holdout read prevention and the real CLI.
For full-suite tests, build the existing frontend first as described in
`docs/10-track-b-handoff.md`; CI now includes that prerequisite.

Before real results: connect the shared logged caller, export aligned dev
predictions, and obtain reviewed dev labels. Compare runs at matching model,
settings, input data and prompt-development effort. Three-repeat aggregation,
E3-pipeline extraction alignment, held-out evaluation and E5 state scoring remain
outside this PR. No model-accuracy claim follows from passing these checks.
