# 07 — Repo layout and conventions

## Layout

```
/src
  /ingest          transcript parsing, turn IDs, idempotent import   FR04
  /extract         LLM-1 call + schemas                              FR05
  /validate        evidence span resolution                          FR06
  /retrieve        BM25, embeddings, family collapse, RRF            FR10
  /classify        LLM-2 call + enum construction                    FR07/08
  /engine          PURE. stdlib only. no I/O. state machine          FR11
  /persist         SQLAlchemy models, transactional writes           FR09
  /review_ui       React/Vite in /web                                FR01/02/03
  /export          register + history serialisation                  FR12
  /logging         model_calls wrapper, runs table
  /eval            harness scripts, scoring
  /baseline        comparison system
/prompts           versioned .txt or .jinja, one file per stage
/scenarios
  /dev             D1–D3 + gold
  /holdout         H1–H5 + gold
  /dev-adversarial
  /holdout-adversarial   NOT OPENED until final scoring
/tests
/docs
/web               Vite + React review UI. The state engine stays in Python.
  /src/components  one component per designed class
  /src/routes      one route per exported screen
  /src/styles      copies of design/styles/tokens.css and app.css, plus screens.css
  /src/api         typed client. schema.d.ts is generated
```

`src/engine/` must import successfully and pass its tests with no `.env`, no network and no database.
This is checked in CI. It is the reason the contribution is independently testable.

## Web

The proposal named a Streamlit review UI. The screens are now the React app in `/web`, because
`design/` is the screen specification. Lifecycle transitions stay in `src/engine/`; the UI renders
`can_confirm`, `can_confirm_reason`, and a 409 reason. See `docs/02-architecture.md`.

- `web/src/api/schema.d.ts` is generated. From `web/`, run `npm run gen:api`. Do not edit it by hand.
- `web/src/styles/tokens.css` and `web/src/styles/app.css` are copies of `design/styles/`. Run
  `npm run sync:ds` to refresh them. `npm run check:ds` fails if they differ. Do not hand-edit the copies.
- Page classes that exist only in an exported screen's `<style>` block live in `web/src/styles/screens.css`.

### Shared preview on Vercel

Import this repository with the Vercel root set to the repository root, not `web/`.
The entrypoint is `src/api/hosted.py`. The build installs and builds `/web` into
`web/dist`, and that app serves the screens. Fixture routes are under `/api` so
they do not collide with the React routes. No environment variable is required.

Vercel provides Python 3.12, 3.13, and 3.14. `.python-version` is `3.12` for that
preview. Local development stays on the 3.11 virtualenv. Runtime pins live in
`pyproject.toml` and `uv.lock`; `requirements.txt` remains the local install list.

`npm run dev` in `/web` still uses `http://127.0.0.1:8000`. A hosted page calls
`/api` on its own origin.

The store is the in-memory fixture. Confirm, reject, edit, and settings changes
last only for the life of that running instance.

## Python

- Python 3.11+, one virtualenv, `requirements.txt` pinned with exact versions.
- Type hints on all public functions. Pydantic models for anything crossing a stage boundary.
- `ruff` for lint and format. No debate about style.
- No module in `src/` may import from `src/eval/` or `src/baseline/`.

## Data contracts

Every stage boundary is a Pydantic model, defined once in `src/<stage>/schemas.py` and imported by
consumers. Stages communicate by these objects only — never by loose dicts, never by reading each
other's database tables directly.

Representative:

```python
class EvidenceSpan(BaseModel):
    turn_id: str          # "{meeting_id}:{turn_index}"
    start: int
    end: int

class Candidate(BaseModel):
    candidate_id: str
    project_id: str
    meeting_id: str
    text_norm: str
    evidence: list[EvidenceSpan]
    atomic: bool = True

class Classification(BaseModel):
    matched_requirement_id: str | None   # None == no_match
    relation: Relation                   # six-value enum
    rationale: str
    retrieved_ids: list[str]             # what was actually offered
```

`retrieved_ids` is stored on the proposal so E3 can distinguish "retrieval missed it" from "classifier
picked wrong from a correct list". Do not drop it.

## Prompts

- One file per stage in `/prompts`, e.g. `extract_v1.jinja`, `classify_v1.jinja`.
- Never a string literal in Python.
- The call site records `prompt_hash` = git blob hash of the prompt file, on every call.
- Prompt changes after the Week 11 freeze require a team decision recorded in the PR.
- Few-shot examples come from the **dev split only**, and are part of the prompt file so they are
  hashed with it.

## Logging

Every model call, including retries and baseline calls, writes one `model_calls` row:

```
run_id, stage, prompt_hash, input_tokens, output_tokens,
latency_ms, retries, cost, raw_json_path
```

Raw responses go to `runs/<run_id>/<call_id>.json` on disk; the table stores the path. Do not put raw
JSON in SQLite.

Cost is computed at log time from the recorded rates for the pinned deployment. Record the rates in
`docs/` when the model is selected; do not hardcode them in code.

### Failed attempts and E8 accounting (29 October 2026)

The shared SQL row shape and successful `CallLogger.call` / `embed` returns are
unchanged. Each provider attempt now gets its own ID, raw JSON and committed
`model_calls` row, including the failed attempt before a retry. Chat retries once;
embedding retains its existing no-retry policy. SDK-internal retries are disabled
so they cannot issue invisible requests. Schema-validation retries at the stage
level remain separate calls. `retries` is the transport attempt index (0 or 1).

The raw payload adds `_call_trace`: `outcome` (provider success/failure),
`usage_known`, `attempt_index`, `logical_call_id` and a safe error summary. Provider
success does not imply schema-valid, evidence-supported or correct output. Error
summaries retain exception type, HTTP status and machine error code, without
exception text, request headers, credentials, URLs or request bodies. A failed
extraction returns diagnostic call IDs; the pipeline exposes it in `errors` and
run notes instead of reporting an apparently successful empty meeting.

The existing SQL numeric columns remain non-null for compatibility. On attempts
without provider usage, their zeros are **unknown placeholders, not free usage**.
E8 reads the raw flags: if any usage is unknown, total `cost`, `input_tokens` and
`output_tokens` are null. `recorded_cost` and recorded token subtotals cover only
known usage; `unknown_usage_calls`, `failed_calls` and `usage_complete` expose the
limit, also by stage. Do not sum SQL `cost` directly and describe it as total cost.
Missing raw records also make usage unknown. Legacy successful raw responses and
local encoder traces remain readable; earlier missing requests cannot be recovered.

Audit rows commit in a separate transaction, like local embedding traces, so a
later candidate/register rollback does not erase a paid attempt. The run must be
committed first and the caller must not hold a SQLite write lock during inference.
The logger does not commit pending business writes. An audit storage error stops
processing without making another provider request.

This fixes the logging and error-reporting defect found in the full AMI smoke run;
it does not repair its historical records, rerun that corpus, fix API/canonical
import deduplication, change prompts, or establish evaluation accuracy.

## Secrets

Credentials in `.env`, never committed. `.env.example` lists the variable names only. Nothing in
`/prompts`, `/scenarios`, `/docs` or any notebook output may contain a key. This is a course
requirement, not just good practice.

## Git

- Branch per stage: `stage-4-retrieval`, `stage-7-engine-wiring`.
- Commit messages reference the FR or E ID where applicable.
- Tag the prompt freeze commit `prompt-freeze-week11`. All holdout results must be reproducible from
  that tag.

## Testing

- `pytest`. Engine tests use Hypothesis for property-based coverage: no event sequence deletes a
  version, no unlisted transition succeeds, confirmed scope never changes without a confirmation event.
- Deterministic tests (E1, E4, E7) run in CI. Model-dependent tests do not — they run manually and cost
  money.
- A test that needs an API key belongs in `/tests/live/` and is excluded from the default run.
