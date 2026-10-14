# Track B — local retrieval milestone (FR10 / E3)

For the current teammate-facing summary, setup commands and integration inputs,
start with [Track B handoff](10-track-b-handoff.md). This document retains the
local implementation history and its verification limits.

## Implemented

- `src/retrieve/schemas.py`: typed query, retained-version and result contracts.
- `src/retrieve/hybrid.py`: project-scoped BM25 and dense cosine ranking, collapse to
  stable requirement families before RRF (constant 60), default top-k = 5.
- Every returned family includes all supplied historical versions, text, state and evidence.
  Superseded, contradicted and withdrawn versions remain searchable.
- Separate full BM25, dense and fused family rankings are returned for E3 diagnostics.
- Stable tie-breaking; duplicate versions, invalid vectors, model/revision mismatches and
  dimension mismatches raise errors instead of triggering a fallback.

The ranking core uses the existing Pydantic dependency and the Python standard library.
BM25 uses fixed k1=1.5 and b=0.75, case-folded word tokens, and no stop-word list or stemming.
No relevance threshold is introduced: even zero lexical overlap can yield candidates.
The classifier must still support `no_match`; retrieval never decides the relationship.

## Run locally

From the repository root:

```bash
.venv/bin/python -m src.retrieve.demo
.venv/bin/python -m pytest tests/test_retrieval.py
.venv/bin/python -m pytest src/engine tests --ignore=tests/live
.venv/bin/ruff check src tests
.venv/bin/ruff format --check src tests
```

The demo's vectors are **hand-authored unit fixtures**, not semantic model outputs.
They demonstrate historical lookup and ranking mechanics only. Neither the demo nor these
tests establishes recall or semantic quality on the course evaluation corpus.

Local verification on 7 October 2026: 31 new retrieval cases passed; the full default
suite passed all 42 cases (including one pre-existing placeholder). Ruff lint and format
checks passed. No hosted model was called and no dependency was added.

## Integration contract

The caller passes a `RetrievalRequest` containing the validated extracted candidate and
its vector, plus `RequirementVersion` objects supplied through a persistence adapter.
Query and version vectors must use the same pinned embedding model/revision and dimensions.
Store the vector model/revision alongside persisted embeddings when the adapter is added.

Supply only versions available at the point of the sequential run being evaluated;
the retriever cannot infer meeting cutoffs from this contract. Refresh the snapshot after
approved updates. Future meetings must never enter the corpus for an earlier query.

Pass `result.families` to the classifier and retain `result.retrieved_ids` on the proposal.
The result contains no match decision, state mutation, gold data or confirmation decision.
An empty project returns an empty family list. Invalid inputs remain explicit errors.

## Real local encoder (7 October 2026)

The first local encoder is now implemented and smoke-tested:

- Model: `sentence-transformers/all-MiniLM-L6-v2`.
- Revision: `1110a243fdf4706b3f48f1d95db1a4f5529b4d41`, pinned in
  `src/retrieve/model_config.json`; CPU inference with 384-dimensional normalised vectors.
- Optional packages are pinned in `requirements-retrieval.txt`; the base requirements and
  default CI do not download weights or require the optional encoder dependencies.
- Weights and tokenizer are cached under `.venv/embedding-cache` and ignored by Git.
  Runtime loading is local-only, uses safe weights, and disables remote custom code.
- Each encode attempt is recorded through an explicit trace sink. The smoke adapter uses
  the existing `runs` and `model_calls` schema in a separate `runs/<uuid>/trace.sqlite`.
  It does not create or change register tables, or replace the A/C shared logger interface.
- Raw vectors, input text, timing, input-token count and error status are stored locally.
  Generated-token count and API cost are zero. For embeddings, `prompt_hash` records the
  Git blob hash of the encoder configuration: there is no generative prompt.
- Empty input fails before encoding. Text exceeding 256 tokens fails explicitly, rather
  than silently truncating. Model dimension and token-limit mismatches are errors.

Sources: [model card](https://huggingface.co/sentence-transformers/all-MiniLM-L6-v2),
[SentenceTransformer API](https://www.sbert.net/docs/package_reference/sentence_transformer/model.html).
This is an initial development choice, not a claim that this model is optimal for the corpus.

### Start on this laptop

The dependencies and model are already installed. From the repository root:

```bash
.venv/bin/python -m src.retrieve.semantic_demo
.venv/bin/python -m src.retrieve.semantic_demo --query "Staff must authenticate via the corporate identity provider." --top-k 2
.venv/bin/python -m src.retrieve.semantic_demo --query "Please email customers their proof of payment." --top-k 2
```

Inspect `bm25`, `dense` and `fused` in the output, then inspect the returned versions.
These are ranked candidates, not confirmed matches or approved changes. In particular,
zero-overlap BM25 results remain tied; stable-ID ordering can promote irrelevant candidates.
RRF is not a calibrated probability and does not remove the classifier's `no_match` task.

The real offline runs placed LOGIN first for the corporate-identity-provider query,
even when BM25 had no shared terms. RECEIPT came first for the proof-of-payment query.
These are hand-written illustrative inputs, **not held-out examples or an E3 accuracy result**.
They do not justify changing retrieval settings or claiming measurable improvement.

Verification: 51 default tests passed (40 retrieval/encoder cases, 10 engine cases, one
pre-existing placeholder); Ruff lint/format and dependency compatibility checks passed.
The real model also ran successfully with both Hugging Face and Transformers offline flags.

### Set up another laptop

```bash
python3.11 -m venv .venv
.venv/bin/python -m pip install -r requirements-retrieval.txt
.venv/bin/python -m src.retrieve.prepare_model
.venv/bin/python -m src.retrieve.semantic_demo
```

Only `prepare_model` downloads the fixed public model. Encode calls keep text on the laptop.
Default tests remain download-free; the model smoke demo is a separate manual command.

## Still required before Stage 4 can be considered complete

1. Integrate the implemented local encoder with persisted version embeddings.
2. Connect the persistence adapter with Lucas (Track C), including model/revision metadata
   and snapshots limited to the history visible at each meeting.
3. Obtain the team-authored dev scenarios D1–D3. Fixtures are not replacements for them.
4. In the evaluation layer, measure BM25-only, dense-only and fused recall@3/@5/@8 on
   matchable dev candidates; report no-match cases separately. Keep gold labels there.
5. Use the measured failures to decide whether any retrieval change is justified.

## Development retrieval evaluation entry point (E3)

`src/eval/run_retrieval.py` now runs label-free retrieval inputs, records every local
encoder batch, and saves `rankings.json` in an isolated run directory. `src/eval/score.py`
alone reads the separate dev labels and computes BM25, dense and fused recall@3/@5/@8.
This evaluates the retrieval component only, not full E3-oracle classification or E5 state.
The existing `score.py --run` full-pipeline entry point remains a scaffold.

Failed, malformed and missing outputs stay in the matchable-case denominator. No-match
cases are counted separately and do not inflate recall. No-match accuracy is left unset
until a classifier is implemented. Zero matchable support yields null recall, not 100%.
Input and gold-file SHA-256 hashes identify the dataset versions used in scoring.

The runner filters out versions from other projects and versions becoming available after
`history_cutoff` **before encoding**. Require `history_cutoff < meeting_ordinal`. This is a
meeting-start retrieval snapshot, not a sequential state-engine replay. Authors must
supply text and states correct as of that cutoff; a timestamp filter cannot repair a
snapshot whose old text/state was already overwritten by a later change.

### Prepare files after the team authors the dev scenarios

The lightweight JSON contract is an adapter for component evaluation, not a replacement
for the ordered transcript/gold-event corpus. Derive two files from the approved dev data:

1. `retrieval_inputs.json`: candidate text/evidence and the known historical snapshot.
   No expected ID or relationship labels are allowed in the case structure.
2. `retrieval_labels.json`: case IDs and their independently authored expected family IDs,
   or null for no-match. Only the scoring module opens this file.

Input shape (illustrative format, **not authored D1 data**):

```json
{
  "schema_version": 1,
  "split": "dev",
  "cases": [{
    "case_id": "D1-M2-C1",
    "meeting_ordinal": 2,
    "history_cutoff": 1,
    "candidate": {
      "candidate_id": "C1", "project_id": "D1", "meeting_id": "D1-M2",
      "text_norm": "Employees sign in using company single sign-on.",
      "evidence": []
    },
    "history": [{
      "project_id": "D1", "requirement_id": "R01", "version": 1,
      "text": "Employees log in with email and password.",
      "state": "confirmed", "available_after_meeting": 1,
      "evidence": []
    }]
  }]
}
```

Label shape for that illustrative example:

```json
{
  "schema_version": 1,
  "split": "dev",
  "cases": [{"case_id": "D1-M2-C1", "expected_requirement_id": "R01"}]
}
```

Real candidates should retain their actual evidence spans; the empty lists above are
format placeholders. Evidence support is evaluated separately by E2, not this runner.
Ensure there are enough distinct families to make recall@3/@5/@8 informative. A corpus
with fewer than k families trivially contains every family in its top-k and cannot
establish meaningful top-k quality. Include near-duplicates, back-references and no-match.

Once those real files exist, run from the repo root (paths below are examples):

```bash
.venv/bin/python -m src.eval.run_retrieval --inputs scenarios/dev/retrieval_inputs.json --repeat 1
.venv/bin/python -m src.eval.score --rankings runs/<run-id>/rankings.json --gold scenarios/dev/retrieval_labels.json --output runs/<run-id>/metrics.json
```

Repeat with indexes 2 and 3, retaining all three run directories. Inspect per-case rank
and errors before changing model, top-k or prompts. This dev-only entry point rejects
holdout split declarations and paths; a later frozen evaluation harness will handle holdout.

Verification: all 66 default tests pass, including 15 evaluation cases. Real cached-model
CLI integration was checked over three repeats on one **unit fixture** kept in temporary
storage. Those mechanics checks are not a measured result on team scenarios.
At the retrieval milestone, no final team-authored D1–D3 files were available.

## D2 authoring draft (7 October 2026)

`scenarios/dev/D2/README.md` and `gold-sequence.draft.json` now contain an
AI-assisted initial plan for Danyang's review and Lucas's dialogue authoring.
The draft has three meetings and 18 content events around three distinct
email-related obligations, with refinements, replacements, an unresolved conflict,
delayed approval, questions and references to historical versions.

Event order, individual state steps, retained versions and meeting-end snapshots
were checked locally. Complete replacement transactions and the separation of a
restatement label from a delayed Confirm decision still need team alignment.
No transcript or evidence offsets exist yet. The draft is not runnable gold,
is not a retrieval-runner input, and has not been used for model evaluation.
Three families also make top-k recall uninformative once all are available.

## LLM-2 request and output contracts (13 October 2026)

Implemented locally, without calling a cloud model:

- `prompts/classify_v1.txt`: a versioned zero-shot prompt for the six documented
  relationships. Source and history text are treated as data, not instructions;
  the rationale is a short evidence-based explanation, not hidden reasoning steps.
- `src/classify/schemas.py`: additional input/request models; the existing
  `Classification` fields and API wire contract are unchanged. Inputs require
  source turns, candidate evidence, retrieved histories and authoritative current
  version pointers. Project/candidate identity, span bounds, source speaker and
  family/version consistency are checked before request preparation. These checks
  do not replace Track A's extraction/evidence stage or prove semantic support.
- `src/classify/request.py`: packages source quotes and all supplied retained
  versions as JSON user data, keeping them out of the system message. Records
  the exact prompt's Git blob hash. The per-request JSON Schema allows only
  offered family IDs or null for `no_match`, and the six relationship labels.
  Embeddings and gold labels are not part of the model input.
- `src/classify/output.py`: rejects malformed JSON, duplicate fields, extra fields,
  invented IDs, invalid ID/relationship pairs and blank rationales without repairs
  or default answers. Adds `retrieved_ids` from the request, never model output.
  Its adapter passes a decoded result to Lucas's existing `assess_proposal`.

The current pointer must come from persistence. Do not guess it from the largest
version number: a newer proposal can coexist with an earlier confirmed version.
The adapter requires explicit configured authority and `replacement_stated`
booleans; it does not derive either from an LLM label, confirm a proposal, or
perform any register write. The team's evidence rule for `replacement_stated`
remains unsettled in the Track C handoff.

The request's `output_schema` is provider-neutral. For Azure Chat Completions,
the future logged caller puts it in `response_format.json_schema.schema`, with
`type=json_schema` and `strict=true`. For the Responses API it belongs in
`text.format.schema`. All three output fields are required and extra properties
are disallowed. This is a supported-schema design, **not** a successful provider
call or proof that the team's eventual deployed model supports it.
See [Microsoft's structured-output documentation](https://learn.microsoft.com/azure/ai-services/openai/how-to/structured-outputs).

Targeted verification: 50 new offline tests pass for request provenance, exact
source offsets, current-head handling, raw-output rejection and the Track C
adapter. Invalid synthetic predictions test the contract, not model accuracy.
Keeping untrusted content in a user data record is not proof that all prompt
injection cases are blocked. No holdout data was inspected.
After this slice, the combined default suite passes all 158 test items, including
the upstream API, engine and database tests. Ruff lint passes across `src` and
`tests`, and the new classifier files pass the format check. The existing API
test dependency deprecation warning remains; it does not fail the tests.

## Next Track B work

Connect these contracts to the team's **shared logged model caller**, after
confirming the actual Foundry model deployment/version, model or Agent endpoint,
API path, authentication, supported settings and budget. The local `.env` currently
has no Azure endpoint, deployment or credential values. Do not introduce a second
formal logger or perform unlogged hosted calls. The shared wrapper must record
every attempt, including the one permitted schema retry; a second invalid response,
provider refusal or truncated response is an explicit error, not a repaired label.

Then build E3-oracle ID/relationship scoring on final dev data, pair with Ben on
the strong baseline, and run the full-register ablation. The standalone retrieval
scorer still measures recall only; classification accuracy and macro-F1 are not
implemented or measured by this local slice.

Shared corpus obligations also remain: Track B writes D2's gold sequence and D1's dialogue,
with the other authors following the rotation in `docs/05-annotation-and-corpus.md`.
Do not use or inspect holdout gold during prompt development.
