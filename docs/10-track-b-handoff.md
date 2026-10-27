# Track B handoff

Owner: Danyang. Reconciled on 27 October 2026 with main `2424ab9`.

## Integration status

The original retrieval/classification foundation through `df81ea3` is already in
main. Ben's `c6ee3d2` adds the shared live classifier, versioned persistence,
strong baseline and database-backed scoring; `2424ab9` adds the Windows MiniLM
symlink probe. `handover.md` describes that integration and its measured/unmeasured
boundary. This document does not replace it.

PR #3 is the compatibility follow-up: declare existing runtime dependencies and
lock them, build the frontend before hosted API tests, run CI on dependent PRs,
and apply existing import/format rules. The merge conflict in `run_pipeline.py`
was resolved by retaining Ben's new pipeline; changes to it are import ordering
and formatting only. The original gold-label replay is not restored.

PR #4 adds offline scoring for already aligned development classification
predictions. It must preserve Ben's separate `score.py --run` entry point and
accept the classifier's added `replacement_stated` field. It is not a replacement
for the database-backed experiment harness.

## Track B components

| Component | Location | Boundary |
|---|---|---|
| Hybrid retrieval | `src/retrieve/hybrid.py` | Project-scoped BM25/cosine, collapse families before RRF, retain all versions |
| Local embeddings | `src/retrieve/embeddings.py` | Pinned MiniLM, CPU and explicit encode logging |
| Retrieval evaluation | `src/eval/run_retrieval.py`, `score.py --rankings` | Label-free inputs; development labels read by the scorer |
| Classification request | `src/classify/request.py`, `prompts/classify_v1.txt` | Evidence/history data and per-request offered-ID enum |
| Output validation | `src/classify/output.py` | Strict decoding; no JSON repair or default prediction |
| Proposal adapter | `src/classify/output.py::assess_classification` | Calls Track C rules, never confirms or writes scope |
| D2 | `scenarios/dev/D2/` | Authoring draft; not a completed evaluation scenario |

Ben's integration adds `src/classify/classify.py`, `src/retrieve/embedder.py`,
`src/persist/register.py` and `src/eval/run_baseline.py`. Both gold-candidate and
extracted paths now call the same retrieval/classification processing loop. The
live output schema has four fields: ID, relation, rationale, replacement_stated.
Speaker authority remains project configuration, not a model field.

The encoder identity is model, revision and dimension; query and history must
agree on all three. The active default remains local MiniLM (384 dimensions).
The deployed `cia-embed` encoder has 1536 dimensions and must not be mixed with
existing local vectors. Deployment settings are in `docs/09-model-deployment.md`.
The model preparation command includes the Windows symlink probe from main.

## Validation and running

The original Track B foundation had 105 software checks. At this integration
revision PR #3 has 239 passing repository test items. These are software checks,
not model-accuracy results. PR #4 has additional offline scoring checks.

Install the base Python requirements and build the existing frontend before the
full suite. The build is needed by the hosted API test; it does not make the UI
read the live database.

```bash
.venv/bin/python -m pip install -r requirements.txt
npm --prefix web ci
npm --prefix web run build
.venv/bin/python -m pytest src/engine tests --ignore=tests/live
.venv/bin/ruff check src tests
.venv/bin/ruff format --check src tests
```

Use a Node version supported by the locked Vite dependencies (CI uses Node 24).
For a real local encoder install `requirements-retrieval.txt`, then run:

```bash
.venv/bin/python -m src.retrieve.prepare_model
```

Do not run a second package installer into the same environment concurrently.
Credentials, model weights, database files and `runs/` remain outside Git.

## Remaining handoff

- Use `handover.md` for the live D1 oracle/extracted/baseline commands. Use a fresh
  database per run and record actual score JSON before writing report results.
- The review API still serves fixtures; UI approval is not database approval.
- D2 remains a draft. Do not present the planned eight-project corpus as completed.
- The proposal and repository use different FR10/FR11/FR12 numbering. Refer to
  retrieval/classification as report FR07/FR08 and E3; preserve the proposal IDs.
- The offline aligned scorer and database-backed scorer have different macro-F1
  zero-support policies. Name the policy beside a score; do not combine outputs
  or treat the offline file format as a database-run export.
