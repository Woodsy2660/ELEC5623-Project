# 11 — Remaining Implementation

This document tracks what remains to be implemented and provides step-by-step guidance for each task.

## Overview

The system has complete implementations for:
- Ingestion, extraction, validation (Track A)
- Retrieval, classification schemas (Track B)
- State engine, persistence, logging (Track C)
- React frontend with all screens

**The critical gap is connecting the working backend pipeline to the API layer.** The API currently serves hardcoded fixtures instead of reading from the SQLite database.

---

## 1. Wire API to Database

**Priority:** HIGH
**Effort:** Medium
**Blocks:** All other API features

### Current State
- `src/api/router.py` calls `get_store()` which returns fixtures from `src/api/fixtures.py`
- `src/eval/run_pipeline.py` writes to SQLite via `src/persist/models.py`
- The two systems don't talk to each other

### Implementation Steps

1. **Create database session dependency in `src/api/app.py`:**
   ```python
   from sqlalchemy import create_engine
   from sqlalchemy.orm import sessionmaker, Session
   from src.persist.models import Base

   DATABASE_URL = os.environ.get("DATABASE_URL", "sqlite:///pipeline.db")
   engine = create_engine(DATABASE_URL)
   SessionLocal = sessionmaker(bind=engine)

   def get_db() -> Generator[Session, None, None]:
       db = SessionLocal()
       try:
           yield db
       finally:
           db.close()
   ```

2. **Create `src/api/queries.py` with database queries:**
   ```python
   def get_projects(db: Session) -> list[ProjectOut]:
       """Query projects with computed counts."""
       # Query Project table, join with Requirement for counts
       ...

   def get_register(db: Session, project_id: str) -> list[RegisterRow]:
       """Query requirement versions for register display."""
       # Query RequirementVersion, RequirementCurrent
       ...

   def get_proposals(db: Session, project_id: str) -> ProposalList:
       """Query pending proposals for review."""
       # Query Proposal table where decision is NULL
       ...
   ```

3. **Update `src/api/router.py` routes to use database:**
   ```python
   @router.get("/projects")
   def list_projects(db: Session = Depends(get_db)) -> list[ProjectOut]:
       return queries.get_projects(db)
   ```

4. **Keep fixtures as fallback for demo mode:**
   ```python
   USE_FIXTURES = os.environ.get("USE_FIXTURES", "false").lower() == "true"
   ```

### Files to Modify
- `src/api/app.py` — Add database engine and session
- `src/api/router.py` — Replace fixture calls with queries
- Create `src/api/queries.py` — Database query functions

### Testing
```bash
# Run pipeline to populate database
python3 -m src.eval.run_pipeline --scenario scenarios/dev/D1 --mode eval --candidate-source gold --repeat 1

# Start API and verify it reads from DB
python3 -m src.api

# Check projects endpoint returns pipeline data
curl http://127.0.0.1:8000/projects
```

---

## 2. Import Endpoint

**Priority:** HIGH
**Effort:** Medium
**Depends on:** Database wiring (#1)

### Current State
- UI has file drop zone at `/projects/:id/import`
- No backend endpoint exists
- `src/ingest/loader.py` has `import_meeting()` function ready

### Implementation Steps

1. **Add import endpoint to `src/api/router.py`:**
   ```python
   from fastapi import UploadFile, File
   from src.ingest import import_meeting
   from src.ingest.normalise import parse_transcript

   @router.post("/projects/{project_id}/import")
   async def import_transcript(
       project_id: str,
       file: UploadFile = File(...),
       ordinal: int = Query(...),
       db: Session = Depends(get_db),
   ) -> MeetingOut:
       content = await file.read()
       text = content.decode("utf-8")

       # Parse transcript into turns
       turns = parse_transcript(text, file.filename)

       # Write to temp file for import_meeting
       # Or refactor import_meeting to accept turns directly

       meeting = import_meeting(db, project_id, temp_path, ordinal)
       db.commit()

       return MeetingOut(...)
   ```

2. **Implement `src/ingest/normalise.py:parse_transcript()`:**
   ```python
   def parse_transcript(content: str, filename: str) -> list[dict]:
       """Parse transcript text into turn records.

       Supports:
       - Plain text with "SPEAKER: text" format
       - JSON/JSONL exports from meeting tools
       """
       if filename.endswith(".jsonl"):
           return _parse_jsonl(content)
       elif filename.endswith(".json"):
           return _parse_json(content)
       else:
           return _parse_plain_text(content)
   ```

3. **Add speaker validation:**
   ```python
   def validate_speakers(db: Session, project_id: str, turns: list[dict]) -> list[str]:
       """Return list of unknown speakers that need mapping."""
       known = {s.speaker_label for s in db.query(Speaker).filter_by(project_id=project_id)}
       found = {t["speaker"] for t in turns}
       return list(found - known)
   ```

4. **Wire frontend `Import.tsx`:**
   ```typescript
   const handleUpload = async (file: File) => {
     const formData = new FormData()
     formData.append('file', file)
     formData.append('ordinal', meetingOrder)

     const response = await fetch(`/projects/${projectId}/import`, {
       method: 'POST',
       body: formData,
     })
     // Handle response, refresh meetings
   }
   ```

### Files to Modify
- `src/api/router.py` — Add POST endpoint
- `src/ingest/normalise.py` — Add transcript parsing
- `web/src/routes/Import.tsx` — Wire upload handler

---

## 3. Export Endpoint

**Priority:** MEDIUM
**Effort:** Low
**Depends on:** Database wiring (#1)

### Current State
- `src/export/register.py` has working `export_register()` and `write_export()`
- No API route to trigger export
- UI "Export" button has no handler

### Implementation Steps

1. **Add export endpoint to `src/api/router.py`:**
   ```python
   from fastapi.responses import StreamingResponse
   from src.export import export_register, write_export
   import io

   @router.get("/projects/{project_id}/export")
   def export_project(
       project_id: str,
       format: str = Query("json", regex="^(json|csv)$"),
       db: Session = Depends(get_db),
   ) -> StreamingResponse:
       data = export_register(db, project_id)

       if format == "csv":
           content = write_export_csv(data)
           media_type = "text/csv"
           filename = f"{project_id}-register.csv"
       else:
           content = write_export(data)
           media_type = "application/json"
           filename = f"{project_id}-register.json"

       return StreamingResponse(
           io.BytesIO(content),
           media_type=media_type,
           headers={"Content-Disposition": f"attachment; filename={filename}"}
       )
   ```

2. **Wire frontend button in `Register.tsx`:**
   ```typescript
   const handleExport = () => {
     window.location.href = `/projects/${projectId}/export?format=json`
   }

   <button onClick={handleExport} className="cia-btn">Export</button>
   ```

### Files to Modify
- `src/api/router.py` — Add GET export endpoint
- `web/src/routes/Register.tsx` — Wire export button

---

## 4. Extracted Candidates Pipeline

**Priority:** HIGH
**Effort:** High
**Depends on:** Azure OpenAI credentials

### Current State
- `run_pipeline.py` handles gold candidates fully
- Lines 586–592 have TODO for extracted candidates
- All required modules exist: `src/extract/`, `src/retrieve/`, `src/classify/`

### Implementation Steps

1. **Complete the extracted candidate path in `run_pipeline.py`:**
   ```python
   else:
       # Full pipeline: retrieve, classify, validate, apply

       # 1. Get embedding for candidate
       embedding_result = embedder.encode([candidate.text_norm])[0]

       # 2. Build retrieval corpus
       corpus = _get_corpus_versions(session, project.id, embedding_result.embedding_model)

       # 3. Retrieve similar requirements
       retrieval_result = retrieve(
           RetrievalRequest(
               candidate=candidate,
               embedding_model=embedding_result.embedding_model,
               embedding=embedding_result.embedding,
               top_k=5,
           ),
           corpus,
       )

       # 4. Prepare classification input
       current_heads = _get_current_heads(session, retrieval_result.fused_family_ids)
       classification_input = ClassificationInput(
           candidate=candidate,
           evidence_turns=evidence_turns,
           retrieved=retrieval_result.families,
           current_heads=current_heads,
       )

       # 5. Call LLM-2 for classification
       classification = classify_candidate(
           client, run_id, classification_input,
           deployment_name, temperature, seed, runs_dir
       )

       # 6. Validate and apply
       verdict = assess_classification(classification, current_heads, speaker_can_confirm)
       if verdict == Verdict.ALLOWED:
           _apply_event_to_register(...)
   ```

2. **Create `src/classify/classify.py` (the actual LLM call):**
   ```python
   def classify_candidate(
       client: AzureOpenAI,
       run_id: str,
       input: ClassificationInput,
       deployment_name: str,
       temperature: float,
       seed: int,
       runs_dir: Path,
   ) -> Classification:
       """Call LLM-2 to classify a candidate."""
       request = prepare_request(input)

       raw_response = call_model(
           client, run_id, "classify",
           deployment_name, temperature, seed,
           request.messages, runs_dir,
       )

       return decode_output(raw_response, input)
   ```

3. **Wire embeddings generation:**
   ```python
   from src.retrieve.embeddings import LocalEmbedder
   from src.retrieve.local_trace import LocalTrace

   trace = LocalTrace(runs_dir, model_id, config_hash)
   embedder = LocalEmbedder(trace.record)
   ```

### Files to Modify
- `src/eval/run_pipeline.py` — Complete extracted path
- Create `src/classify/classify.py` — LLM-2 call wrapper

### Testing
```bash
# Set Azure credentials
export AZURE_OPENAI_ENDPOINT=...
export AZURE_OPENAI_API_KEY=...

# Run with extracted candidates
python3 -m src.eval.run_pipeline --scenario scenarios/dev/D1 --mode eval --candidate-source extracted --repeat 1
```

---

## 5. Speaker Assignment Modal

**Priority:** MEDIUM
**Effort:** Low

### Current State
- Import page shows "New speaker — assign a role before importing"
- "Assign" button exists but no modal

### Implementation Steps

1. **Add modal state to `Import.tsx`:**
   ```typescript
   const [assignModal, setAssignModal] = useState<{speaker: string} | null>(null)

   // In render:
   {assignModal && (
     <SpeakerAssignModal
       speaker={assignModal.speaker}
       onSave={(name, role, canConfirm) => {
         // POST to settings endpoint
         setAssignModal(null)
       }}
       onClose={() => setAssignModal(null)}
     />
   )}
   ```

2. **Create `SpeakerAssignModal` component**

3. **Add speaker to settings via existing `PUT /projects/:id/settings`**

---

## 6. Delete Project

**Priority:** LOW
**Effort:** Low

### Implementation Steps

1. **Add delete endpoint:**
   ```python
   @router.delete("/projects/{project_id}")
   def delete_project(project_id: str, db: Session = Depends(get_db)):
       # Delete in order: events, versions, requirements, meetings, turns, speakers, project
       db.query(Event).filter_by(project_id=project_id).delete()
       # ... cascade deletes
       db.commit()
       return {"deleted": project_id}
   ```

2. **Add confirmation in Settings.tsx**

---

## 7. Calendar Integration

**Priority:** LOW (per build plan, cut list item)
**Effort:** High

This is listed in the cut list (docs/06-build-plan.md) as deferrable. Current state:
- UI shows "Connect" buttons
- No OAuth flow implemented
- No calendar API integration

If implementing:
1. Add OAuth routes for Google Calendar / Microsoft Graph
2. Store tokens in database
3. Poll for upcoming meetings
4. Create meetings automatically

---

## Implementation Order

| Order | Task | Blocks |
|-------|------|--------|
| 1 | Wire API to Database | Everything else |
| 2 | Import Endpoint | Full workflow |
| 3 | Extracted Candidates Pipeline | Evaluation runs |
| 4 | Export Endpoint | E1 verification |
| 5 | Speaker Assignment | Import workflow |
| 6 | Delete Project | Cleanup |
| 7 | Calendar Integration | (Optional) |

---

## Verification Checklist

After implementation, verify:

- [ ] `GET /projects` returns data from database, not fixtures
- [ ] `POST /projects/:id/import` accepts transcript file and creates meeting
- [ ] `GET /projects/:id/export` returns JSON/CSV download
- [ ] `run_pipeline.py --candidate-source extracted` completes without errors
- [ ] Review queue shows proposals from extracted candidates
- [ ] Confirm/reject actions persist to database
- [ ] Register reflects confirmed changes
- [ ] E1 round-trip test passes with real data
