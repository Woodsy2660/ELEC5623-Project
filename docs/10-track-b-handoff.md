# Track B handoff

Owner: Danyang. Branch: `track-b-work`. Reviewed: 24 October 2026 against
integrated main `997a0f7`.

## Integration status

Main already contains the original four Track B commits through `df81ea3`.
PR #3 is now a compatibility follow-up: frontend build in CI, declared runtime
dependencies/lockfile, and mechanical lint/format fixes for integrated code.
The E3 classification scorer is a separate follow-up in PR #4.

This branch provides local hybrid retrieval, a development retrieval scorer, and
LLM-2 request/output contracts. Retrieval runs with a real local embedding model.
LLM-2 has not called Azure. Main adds an extraction caller, shared logger and
database/event helpers, but `run_pipeline.py` still has no extracted-candidate
retrieval/classification path and the review API still uses fixtures. Its gold
path directly supplies expected IDs/relations; it is not an E3-oracle classifier
evaluation. The existing HTTP models and `Classification` fields remain unchanged.

## What is ready

| Component | Entry point | Status |
|---|---|---|
| Hybrid retrieval | `src.retrieve.hybrid.retrieve` | BM25 and cosine rankings, family collapse, RRF, retained-version output |
| Local embeddings | `src.retrieve.embeddings.LocalEmbedder` | Pinned MiniLM model, CPU, local-only encoding, explicit trace callback |
| Retrieval evaluation | `src.eval.run_retrieval` and `src.eval.score --rankings` | Dev-only recall@3/@5/@8; labels read only by the scorer |
| LLM-2 request | `src.classify.request.prepare_request` | Versioned prompt, evidence/history data, per-request ID enum |
| LLM-2 output | `src.classify.output.decode_output` | Raw JSON validation; invalid predictions remain errors |
| Track C adapter | `src.classify.output.assess_classification` | Calls Lucas's proposal rules; no confirmation or register write |
| D2 corpus | `scenarios/dev/D2/` | Authoring draft only; dialogue, evidence offsets and semantic agreement pending |

The local tests cover 105 new Track B cases: 31 retrieval, 9 encoder/trace,
15 retrieval evaluation and 50 classification contracts. The combined repository
suite has 221 passing test items after integrating the new upstream tests. These are software checks, not measured model
accuracy or completed E3/E5 acceptance.

Traceability follows the repository's FR07/FR08/FR10 and E3 labels. The submitted
proposal uses FR10 for follow-up questions, while its methodology also labels
retrieval FR10. Use the module name and FR07/E3 contribution when discussing the
proposal until the team reconciles that numbering.

## Run and review

From the repository root, install the base Python requirements first:

```bash
python3.11 -m venv .venv
.venv/bin/python -m pip install -r requirements.txt
.venv/bin/python -m pytest src/engine tests/test_retrieval.py tests/test_local_embeddings.py tests/test_retrieval_evaluation.py tests/test_classification_contract.py
```

The command above checks 131 engine/Track B items without model downloads or
Azure credentials. The upstream integration removed the old `demo` and
`semantic_demo` entry points; use the tests and the supplied-input runner below.

For the real local encoder, install the optional requirements and download the
pinned public model once:

```bash
.venv/bin/python -m pip install -r requirements-retrieval.txt
.venv/bin/python -m src.retrieve.prepare_model
.venv/bin/python -m src.eval.run_retrieval --inputs <label-free-dev-inputs.json> --repeat 1
```

The fixed model/revision and encoder settings are in
`src/retrieve/model_config.json`. Encoding keeps text on the laptop. The smoke
runner records calls and results under ignored `runs/` directories. The input
file must follow `RetrievalDataset`; the D2 draft is not runnable input. Model weights,
run outputs, `.env` and database files are excluded from Git.

For the complete repository suite, the existing hosted-API test also needs the
upstream frontend build:

```bash
npm --prefix web ci
npm --prefix web run build
.venv/bin/python -m pytest src/engine tests --ignore=tests/live
.venv/bin/ruff check src tests
```

Use a Node version supported by the locked Vite dependencies. The interface build
is a test prerequisite; it does not connect the fixture API to the model pipeline.

## Inputs needed from Tracks A and C

For retrieval, supply a validated `Candidate`, its query vector, and
`RequirementVersion` records visible at the current processing point. Include
all retained states and versions from the same project. Query and history must
use the same embedding model/revision and dimensions. Refresh the snapshot after
approved changes. Retrieval returns candidates; it never declares a match or
`no_match`.

For classification, supply a `ClassificationInput` containing:

- The candidate and its `RetrievalResult`.
- Stored `EvidenceTurn` records with project, meeting, speaker and original text.
  Candidate offsets are start-inclusive/end-exclusive Python string positions.
- One `CurrentHead` per returned family, with authoritative version and state.
  A later proposed version must not automatically displace confirmed scope.
- The candidate act's speaker label, present in its source evidence.

After the shared logged model caller returns valid raw content:

```python
from src.classify.output import assess_classification, decode_output
from src.classify.request import prepare_request

request = prepare_request(inputs)
# The agreed A/C caller supplies raw_model_content and logs every model attempt.
classification = decode_output(raw_model_content, request)
verdict = assess_classification(
    inputs,
    classification,
    speaker_can_confirm_scope=configured_authority,
    replacement_stated=evidence_rule_result,
)
```

`allowed` is a validation outcome, not approval or persistence. Pass the result
to Track C's confirmation and write service. Authority comes from configuration;
the explicit replacement guard must not be inferred merely from a supersession
label. This example is an integration sketch, not an executable cloud caller.

## Decisions before live integration

1. Ben/A/C: `docs/09-model-deployment.md`, `src/llm/config.py` and
   `src/logging/calls.py` now define the proposed deployment/caller. Verify actual
   access and settings, per-attempt failure logging and budget before live use.
   No credentials are committed in this branch.
2. Lucas: agree the history/current-head adapter and embedding metadata storage.
   This branch defines neither a new database schema nor a register write service.
3. Team: settle same-family replacement versus a new replacement family, and
   delayed confirmation separately from a restatement label. D2 remains a draft
   until these are settled and the dialogue is reviewed.

Next independent Track B work is E3 historical-ID/no-match/relationship scoring.
The current scorer reports retrieval recall only. After live LLM-2 works on final
dev candidates, compare top-k with full-history context and pair with Ben on the
strong baseline. No holdout gold was inspected or used in prompts.
