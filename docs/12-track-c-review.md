# Track C persisted review

**Date:** 2026-10-28<br>
**Scope:** FR01–FR04, FR09, FR11, FR12; E4 groundwork.<br>
**Team decision:** confirming a supersession retires the old family and creates a
separate, confirmed family for its replacement.

This implements the first database-backed review slice on
`codex/track-c-persistence-review`. It follows the local main-branch proposal in
`docs/11-remaining-implementation.md`, and uses the transcript and classification
contracts already present in Tracks A and B.

## Behavior now wired

- Local `src.api.app:app` reads from SQLite by default. Set `USE_FIXTURES=true` to
  use the old fixture API. `src.api.hosted:app` explicitly keeps fixture mode for
  the published preview, so preview decisions are still temporary.
- `src/api/database_router.py` preserves the existing HTTP response shapes for project,
  register, requirement history, proposal, meeting, speaker settings, transcript and
  event export reads. Evidence quotes are split in Python before they reach the UI.
- `POST /projects/{id}/meetings` stores byte-faithful turns through the existing A
  importer. It rejects unmapped speakers and a second version of the same meeting
  order; submitting the same ordinal and content again is idempotent.
- `GET /projects/{id}/export` calls the existing FR12 serializer and includes every
  retained version and decision event.
- `stage_proposal` is the A/B adapter boundary. It persists the candidate, offered
  requirement IDs, prediction, rationale, speaker and the expected current version.
  It does not create or update a requirement.
- `run_pipeline --mode demo --candidate-source extracted` uses Track B retrieval and
  classification, then stages each valid result through `stage_proposal`. The review
  API can read that same SQLite database. Demo mode rejects `gold` as its candidate
  source. Eval mode remains separate; see the open decision-gate issue below before
  using it for measurements.
- The database review queue reports A's `rejected_unresolvable` count from runs with
  a recorded project ID. Older run notes have no project ID, so their extraction
  rejects cannot be attributed safely.
- The decision service re-reads the candidate and transcript, checks exact evidence
  offsets against the source turn, confirms the evidence belongs to the same project
  and meeting, reads configured speaker authority, verifies every offered ID belongs
  to that project, and checks the matched ID was actually offered. It snapshots the
  full project register as well as every offered family. If another decision changes
  the register, the review card keeps the proposal visible and shows added, changed or
  removed current entries. Confirming against that displayed snapshot checks a snapshot
  fingerprint, re-runs the standard-library `assess_proposal` rules and lifecycle engine,
  and commits under the SQLite write lock. A changed offered or matched family still
  blocks the proposal. The reviewer must compare broad project changes with the evidence;
  the model is not silently re-run. Revalidation is recorded as an audit event without a
  requirement ID or evaluation-run ID, so it does not enter lifecycle replay or run scoring.
- Confirm, reject and text edit decisions append a review audit. A confirmed state
  change, version row, current-row pointer and review record commit in one transaction.
  A failed embedding or write leaves the register unchanged; invalid decisions return
  409 and append a blocked-review audit.
- A new requirement writes Create then Confirm events against one version row; Confirm
  updates that version's state in place, matching Track B's register writer. A
  supersession preserves the old text and history, marks its family Superseded, creates
  a separate replacement family through Create then Confirm events, and records both
  family IDs on the related events. No-op and reject decisions create an audit event
  without changing requirements.
- The existing cutoff replay reads these versioned events and validates their state
  and version sequence. Legacy unversioned events retain their old replay path.
- The lifecycle transition test oracle is now an independent table copied from the
  architecture document. The Hypothesis sequence check does not import the production
  transition table as its expected answer.

## Replacement guard and vector contract

The classifier's `supersession` label does not authorize a state change. A scope owner
must be configured for the exact speaker on the source evidence, and the quoted text
must match the conservative English rule in `explicit_replacement`. It recognises
explicit wording such as “we will use SSO instead” and “we have decided to replace A
with B”. Hedges, questions, conditionals, negation and unrecognized wording stay
unresolved. This small rule is a safety filter; it does not claim general natural
language understanding.

The `proposal_reviews` table is additive and never backfills earlier proposal rows.
Old pending proposals without the new full-project snapshot stay visible but cannot be
confirmed; stage them again against the current register. Old completed decisions are
recognized through `decision_event_id` and stay out of the pending queue. B passes the
candidate's validated `VectorRecord` to `stage_proposal` so a reviewer can reuse it
without another model call. Edited text uses the local pinned embedder and its trace
adapter. Embedding weights must already be cached; review never downloads a model or
calls Azure. An edit is blocked if its encoder identity differs from B's proposal
vector or any retained project vector.

Track B stores vectors as JSON arrays and records `embedding_model`,
`embedding_version` and `embedding_dim` in columns. Initialization adds the missing
columns to existing SQLite tables. A legacy full `VectorRecord` blob is converted
only when its model identity validates; a bare vector without provenance remains
unverified and blocks retrieval or writes until explicitly migrated.

Pipeline-local embedding calls are written to the same run's `model_calls` table in
their own transaction, so a later candidate failure cannot roll back their trace.
Text edits made in the review API use Track B's isolated local trace database.

## Local demo on Windows PowerShell

### Prerequisites

- Windows PowerShell, Python 3.11 or newer, and Node.js/npm. The checked-in Vite lock
  requires Node `^20.19.0` or `>=22.12.0`.
- Internet access for the first dependency install and one-time download of the pinned
  Hugging Face embedding model. Later local review uses the cached model.
- An Azure OpenAI chat key and an available `cia-chat` deployment to generate a fresh
  D1 queue. Azure usage may incur cost under the project's subscription.

### Data and credentials

- A fresh clone has no project data because SQLite files are ignored by Git. Run the
  D1 demo pipeline once to create meetings, candidates and proposals in the local DB.
- The pipeline's extraction and classification calls need an Azure OpenAI chat key.
  Browsing or reviewing records already in the DB does not call Azure; the review API
  uses the local embedding model for an edited/new requirement.
- `REVIEWER_TOKEN` is checked by the local API on every confirm, reject or edit. Enter
  the same value under **Reviewer access** in the app and press **Apply**. The browser
  keeps it only in the current tab's memory, so enter it again after a full page reload.
  This is one shared local-demo write token, not per-user authentication.
- The Azure key is only for the Python pipeline. Never enter it in the browser or set it
  as a `VITE_*` variable. Keep the API on localhost and do not expose this demo token or
  API publicly.

Run these commands from the repository root. `requirements-retrieval.txt` includes
the pinned Python dependencies and the local embedding runtime. The embedding weights
download once from Hugging Face and are then loaded from the local cache. The demo uses
Azure `cia-chat` for extraction and classification; it does not call the `cia-embed`
deployment. Azure chat usage may incur project costs.

```powershell
if (-not (Test-Path .venv\Scripts\python.exe)) { py -3 -m venv .venv }
& .\.venv\Scripts\python.exe -m pip install -r requirements-retrieval.txt
npm.cmd --prefix web ci
& .\.venv\Scripts\python.exe -m src.retrieve.prepare_model

# Use a fresh demo DB so it stays separate from any existing project database.
$env:DATABASE_URL = "sqlite:///track-c-demo.db"
$env:REVIEWER_TOKEN = "local-demo-token-change-me"
$env:AZURE_OPENAI_ENDPOINT = "https://consulting-agent-system.openai.azure.com/"
$env:AZURE_OPENAI_DEPLOYMENT = "cia-chat"
$env:AZURE_OPENAI_API_VERSION = "2024-10-21"

# Run this line by itself. At the hidden prompt, paste Key 1 and press Enter.
$secureKey = Read-Host "Azure OpenAI API key" -AsSecureString; $keyPointer = [Runtime.InteropServices.Marshal]::SecureStringToBSTR($secureKey); try { $env:AZURE_OPENAI_API_KEY = [Runtime.InteropServices.Marshal]::PtrToStringBSTR($keyPointer) } finally { [Runtime.InteropServices.Marshal]::ZeroFreeBSTR($keyPointer) }

# These commands must run in the same PowerShell window as the key prompt above.
& .\.venv\Scripts\python.exe -m src.persist --database-url $env:DATABASE_URL
& .\.venv\Scripts\python.exe -m src.eval.run_pipeline --scenario scenarios/dev/D1 --mode demo --candidate-source extracted --repeat 1 --db "sqlite:///track-c-demo.db"
& .\.venv\Scripts\python.exe -m src.api
```

Leave that terminal running. In another PowerShell terminal, start the UI:

```powershell
cd "D:\Git Repo\ELEC5623-Project"
npm.cmd --prefix web run dev -- --host 127.0.0.1
```

Open `http://localhost:5173/`, choose project **D1**, then open **Review queue**.
At the top of the review panel, expand **Reviewer access**, enter the same local token,
and save it for this browser tab. Review the transcript evidence and retrieved alternatives before deciding. If an
earlier confirmation changed the register, the queue remains available and affected
cards show the current entries. Compare them with the proposal before using Confirm;
the server rechecks that exact register snapshot and the deterministic rules in the
same transaction. A change to a matched or retrieved family remains blocked and needs
fresh classification. A rejection only records the decision. Editing text reuses the
local embedding model.

The CLI imports D1 from its authored transcripts and speaker settings; it does not
seed gold labels. The runner also imports the meetings itself, so the explicit
`ingest_scenario` command is optional. Check the CLI's `Errors` section if the queue is
empty. Run the demo once per database: each run creates a new set of proposals, so a
repeat in the same database can add duplicate pending items. Use a new database
filename for a clean repeat.

The eval CLI loads `.env`, but the database initializer and API read process
environment variables. The commands above set those variables in the PowerShell
session so all three tools use the same database and reviewer token. Never put the
Azure key in `VITE_*`, source control, or a hosted build.

For a review-only setup using a database file supplied separately, skip the model
pipeline and start the API with `DATABASE_URL` pointing at that file and
`REVIEWER_TOKEN` set in the same PowerShell process. Then start the UI as above. The
database file is not part of a normal checkout, so this path is available only if you
have been given a populated DB.

### Troubleshooting

| What you see | What to check |
|---|---|
| Browser cannot connect or reports `Failed to fetch` | Keep the API terminal running; verify it uses the same `DATABASE_URL` as the pipeline. Keep the Vite terminal running too. |
| Review queue is empty after a fresh clone | Run the D1 demo pipeline once, check its `Results` and `Errors`, and make sure the API points to `sqlite:///track-c-demo.db`. |
| Saving returns `503` | Stop and restart the API after setting `REVIEWER_TOKEN` in that PowerShell process. |
| Saving returns `401` | In **Reviewer access**, enter the exact same token as the API and press **Apply**. |
| Saving returns `409` | The server rejected a stale or invalid decision. Reload the queue, inspect the register changes and evidence, and do not retry blindly. |

`ingest_scenario` imports only scenario metadata and canonical transcript files. It
does not read or seed `gold.yaml` or `gold.src.yaml`. The sample D1 files are authored
project inputs, not predicted model results. If the local embedding model is not
already cached, register writes that need a new embedding return a conflict and leave
the transaction unchanged.

## Validation and limits

The focused database, evaluation and pipeline checks use temporary SQLite databases,
synthetic model outputs and injected embeddings. They do not call a provider or report
classification accuracy. The full Track C tests that start FastAPI's `TestClient` could
not be completed in this Windows sandbox: its asyncio test server blocks while opening
a local socket pair. Direct persistence, replay, state-gate and demo-pipeline checks
are run separately. The hosted preview still serves fixtures, and the reviewer token
is one local shared write credential rather than a multi-user access-control system.

Project-scoped identity/read permissions, project deletion, integration settings
beyond speaker roles, and E1/E4/E7/E8 acceptance remain open. Calendar and live meeting
integration remain deferred by the build-plan cut list.

The current eval runner auto-confirms an engine-allowed proposal when its gold input
has no explicit `event_action`; D1 currently has no such action fields. This conflicts
with `AGENTS.md`'s gold-decision gate. The team needs an explicit decision file and
aligned runner behavior before eval writes can be considered compliant. The shared
model logger also misses a database row when both attempts of an Azure call fail.

Database initialization preserves rows and applies the additive SQLite migration
needed for Track B's vector metadata and proposal fields. It does not infer metadata
for legacy bare vectors. Keep a backup before running the local app against an older
database.
