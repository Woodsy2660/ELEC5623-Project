# Track C persisted review

**Date:** 2026-10-27  
**Scope:** FR01–FR04, FR09, FR11, FR12; E4 groundwork.  
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
- The decision service re-reads the candidate and transcript, checks exact evidence
  offsets against the source turn, confirms the evidence belongs to the same project
  and meeting, reads configured speaker authority, verifies every offered ID belongs
  to that project, and checks the matched ID was actually offered. It snapshots and
  rechecks the current version of every offered family, so a no-match decision also
  expires when its retrieval context changes. It then calls the standard-library `assess_proposal` rules and
  lifecycle engine again while holding the SQLite write lock.
- Confirm, reject and text edit decisions append a review audit. A confirmed state
  change, new version, current-row pointer and review record commit in one transaction.
  A failed embedding or write leaves the register unchanged; invalid decisions return
  409 and append a blocked-review audit.
- A new requirement writes Create then Confirm. A supersession preserves the old text
  and history, marks its family Superseded, creates a new replacement family as
  Proposed then Confirmed, and records both family IDs on the related events. No-op
  and reject decisions create an audit event without changing requirements.
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
Proposals lacking this review context stay visible but cannot be confirmed. B may pass
the candidate's validated `VectorRecord` to `stage_proposal` so a reviewer can reuse
it without another model call. Edited text uses the local pinned embedder and its trace
adapter. Embedding weights must already be cached; review never downloads a model or
calls Azure. Invalid, missing or inconsistent vectors fail closed.

## Local startup

From the repository root, install `requirements.txt` into this repository's virtual
environment. `.env` is not loaded automatically; set the variables in the process
environment:

```powershell
$env:DATABASE_URL = "sqlite:///consulting_intelligence.db"
$env:REVIEWER_TOKEN = "set-a-local-demo-token"
python -m src.persist
python -m src.eval.ingest_scenario --scenario scenarios/dev/D1
python -m src.api
```

In another terminal, run `npm --prefix web run dev`. Browse to the Vite address and
enter the same token under **Reviewer access** before saving decisions. The front end
keeps it in memory for that tab. Do not put it in `VITE_*`, source control, or a hosted
build.

`ingest_scenario` imports only scenario metadata and canonical transcript files. It
does not read or seed `gold.yaml` or `gold.src.yaml`. The sample D1 files are authored
project inputs, not predicted model results. If the local embedding model is not
already cached, register writes that need a new embedding return a conflict and leave
the transaction unchanged.

## Validation and limits

The persistent-review tests use temporary SQLite databases, synthetic calls and
injected vectors. They do not call a provider or report classification accuracy. The
verified run before the final replay-call correction collected 286 tests: 285 passed;
the one failure exposed positional arguments in the new replay check. The arguments
now use the helper's named parameters, but that full suite has not been rerun in this
turn. The frontend TypeScript/Vite production build passed. Earlier focused lint on
the API, persistence, engine and review test files passed; the scenario CLI and replay
format check still need a fresh lint pass.

The following remain open: integrating a real logged A/B proposal producer into
`stage_proposal`, the extracted-candidate full pipeline, parity baseline, complete
run/metric harness, test-set results, project-scoped identity and read permissions,
project deletion, integration settings beyond speaker roles, and E1/E4/E7/E8
acceptance. The reviewer token is one local shared write credential; it is not a
multi-user access-control system. The hosted preview still serves fixtures.

`create_all` adds `proposal_reviews` when needed and never alters existing columns.
Existing rows in `consulting_intelligence.db` are not cleared or migrated. Make an
explicit migration before any future change to an existing table.
