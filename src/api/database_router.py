"""Existing UI contract backed by SQLite; no fixture fallback in database mode."""

import json
import secrets
from collections.abc import Iterator
from datetime import UTC, datetime
from pathlib import Path
from tempfile import TemporaryDirectory
from typing import Annotated
from uuid import uuid4

from fastapi import APIRouter, Depends, Header, HTTPException, Response
from fastapi.responses import JSONResponse, StreamingResponse
from sqlalchemy import Engine, select
from sqlalchemy.exc import OperationalError
from sqlalchemy.orm import Session

from src.api import queries
from src.api.schemas import (
    CommittedEvent,
    DecisionConflict,
    DecisionRequest,
    MeetingCreate,
    MeetingOut,
    ProjectOut,
    ProjectSettings,
    ProposalList,
    ReasonBody,
    RegisterRow,
    RequirementDetail,
    SpeakerSetting,
    StreamTurn,
)
from src.export.register import export_register
from src.ingest.loader import MeetingError, import_meeting
from src.persist.database import initialize_database, review_transaction
from src.persist.models import Candidate, Event, Meeting, Proposal, Run, Speaker
from src.persist.review import EmbedText, ReviewConflict, ReviewDecision, commit_decision


def build_database_router(
    engine: Engine, *, reviewer_token: str | None, embed_text: EmbedText
) -> APIRouter:
    router = APIRouter()
    ready = False

    def database() -> Iterator[Session]:
        nonlocal ready
        if not ready:
            initialize_database(engine)
            ready = True
        with Session(engine) as session:
            yield session

    def reviewer(authorization: str | None = Header(default=None)) -> str:
        if not reviewer_token:
            raise HTTPException(503, "Review access is not configured on this server")
        if authorization is None or not secrets.compare_digest(
            authorization, f"Bearer {reviewer_token}"
        ):
            raise HTTPException(401, "Enter the reviewer access token to save changes")
        return "human-reviewer"

    Database = Annotated[Session, Depends(database)]
    Reviewer = Annotated[str, Depends(reviewer)]

    @router.get("/projects", response_model=list[ProjectOut])
    def list_projects(db: Database) -> list[ProjectOut]:
        return queries.projects(db)

    @router.get("/projects/{project_id}/requirements", response_model=list[RegisterRow])
    def register(project_id: str, db: Database) -> list[RegisterRow]:
        return queries.register_rows(db, project_id)

    @router.get(
        "/projects/{project_id}/requirements/{requirement_id}", response_model=RequirementDetail
    )
    def detail(project_id: str, requirement_id: str, db: Database) -> RequirementDetail:
        return queries.requirement_detail(db, project_id, requirement_id)

    @router.get("/projects/{project_id}/proposals", response_model=ProposalList)
    def list_proposals(project_id: str, db: Database) -> ProposalList:
        return queries.proposals(db, project_id)

    @router.post(
        "/proposals/{proposal_id}/decision",
        response_model=CommittedEvent,
        responses={409: {"model": DecisionConflict}, 404: {"model": ReasonBody}},
    )
    def decide(
        proposal_id: str, body: DecisionRequest, actor: Reviewer, db: Database
    ) -> CommittedEvent | JSONResponse:
        # The read dependency initializes the schema, but decision reads use the locked session.
        try:
            with review_transaction(engine) as locked:
                proposal = locked.get(Proposal, proposal_id)
                if proposal is None:
                    raise LookupError(f"Unknown proposal {proposal_id}")
                try:
                    with locked.begin_nested():
                        result = commit_decision(
                            locked,
                            proposal_id=proposal_id,
                            decision=ReviewDecision(
                                action=body.action, edited_text=body.edited_text, actor=actor
                            ),
                            embed_text=embed_text,
                            project_snapshot_token=body.project_snapshot_token,
                        )
                    return CommittedEvent(**result.model_dump())
                except ReviewConflict as exc:
                    candidate = locked.get(Candidate, proposal.candidate_id)
                    meeting = locked.get(Meeting, candidate.meeting_id)
                    locked.add(
                        Event(
                            id=str(uuid4()),
                            project_id=meeting.project_id,
                            ts=datetime.now(UTC),
                            actor=actor,
                            event_type="review_blocked",
                            run_id=proposal.run_id,
                            payload_json=json.dumps(
                                {"proposal_id": proposal.id, "reason": str(exc)}
                            ),
                        )
                    )
                    return JSONResponse(status_code=409, content={"reason": str(exc)})
        except OperationalError:
            return JSONResponse(
                status_code=409, content={"reason": "Database is busy; reload and retry"}
            )

    @router.get("/projects/{project_id}/meetings", response_model=list[MeetingOut])
    def meetings(project_id: str, db: Database) -> list[MeetingOut]:
        return queries.meetings(db, project_id)

    @router.post("/projects/{project_id}/meetings", response_model=MeetingOut, status_code=201)
    def create_meeting(
        project_id: str, body: MeetingCreate, response: Response, actor: Reviewer, db: Database
    ) -> MeetingOut:
        if body.ordinal < 1 or not body.turns:
            raise ReviewConflict("Provide a positive meeting order and at least one turn")
        if any(not t.speaker.strip() or not t.text.strip() for t in body.turns):
            raise ReviewConflict("Speaker labels and turn text must not be blank")
        with review_transaction(engine) as locked:
            queries.require_project(locked, project_id)
            meeting_id = f"{project_id}-M{body.ordinal:02d}"
            content = "".join(
                json.dumps(
                    {
                        "turn_id": f"{meeting_id}:{i:04d}",
                        "turn_index": i,
                        "speaker": t.speaker,
                        "text": t.text,
                    },
                    ensure_ascii=False,
                )
                + "\n"
                for i, t in enumerate(body.turns)
            )
            previous = locked.get(Meeting, meeting_id)
            if previous:
                import hashlib

                if (
                    previous.project_id != project_id
                    or previous.source_hash != hashlib.sha256(content.encode()).hexdigest()
                ):
                    raise ReviewConflict("Meeting order already exists with different content")
                response.status_code = 200
            try:
                with TemporaryDirectory() as directory:
                    path = Path(directory) / "transcript.jsonl"
                    path.write_text(content, encoding="utf-8", newline="")
                    meeting = import_meeting(locked, project_id, path, body.ordinal)
            except MeetingError as exc:
                raise ReviewConflict(str(exc)) from exc
            if not previous:
                locked.add(
                    Event(
                        id=str(uuid4()),
                        project_id=project_id,
                        ts=datetime.now(UTC),
                        actor=actor,
                        event_type="meeting_imported",
                        run_id=None,
                        payload_json=json.dumps(
                            {
                                "meeting_id": meeting.id,
                                "title": body.title,
                                "source_name": body.source_name,
                            }
                        ),
                    )
                )
                locked.flush()
            return next(
                item for item in queries.meetings(locked, project_id) if item.id == meeting.id
            )

    @router.get("/meetings/{meeting_id}/turns", response_model=list[StreamTurn])
    def turns(meeting_id: str, db: Database) -> list[StreamTurn]:
        return queries.turns(db, meeting_id)

    @router.get("/meetings/{meeting_id}/stream", response_model=None)
    def stream(meeting_id: str, db: Database) -> StreamingResponse:
        items = queries.turns(db, meeting_id)
        return StreamingResponse(
            (f"event: turn\ndata: {t.model_dump_json()}\n\n" for t in items),
            media_type="text/event-stream",
        )

    @router.get("/projects/{project_id}/export")
    def export(project_id: str, db: Database) -> JSONResponse:
        queries.require_project(db, project_id)
        return JSONResponse(
            export_register(db, project_id),
            headers={
                "Content-Disposition": 'attachment; filename="register.json"',
            },
        )

    def settings(project_id: str, db: Session) -> ProjectSettings:
        queries.require_project(db, project_id)
        speakers = db.scalars(
            select(Speaker).where(Speaker.project_id == project_id).order_by(Speaker.speaker_label)
        )
        run = db.scalars(
            select(Run)
            .join(Candidate, Candidate.run_id == Run.id)
            .join(Meeting, Meeting.id == Candidate.meeting_id)
            .where(Meeting.project_id == project_id)
            .order_by(Run.started_at.desc())
        ).first()
        return ProjectSettings(
            project_id=project_id,
            connections=[],
            capture_default="ask",
            speakers=[
                SpeakerSetting(
                    speaker_label=s.speaker_label,
                    name=s.speaker_label,
                    display_name=s.speaker_label,
                    role=s.role,
                    can_confirm_scope=s.can_confirm_scope,
                )
                for s in speakers
            ],
            deployment=run.model_deployment if run else "Not configured",
            temperature=run.temp if run else 0,
            retrieval_k=5,
            extract_prompt="extract_v1.jinja",
            classify_prompt="classify_v1.txt",
            prompt_status="See run records",
            project_isolation=True,
            provider_retention_note="Verify retention against the configured deployment before uploading transcripts.",
        )

    @router.get("/projects/{project_id}/settings", response_model=ProjectSettings)
    def get_settings(project_id: str, db: Database) -> ProjectSettings:
        return settings(project_id, db)

    @router.put("/projects/{project_id}/settings", response_model=ProjectSettings)
    def put_settings(
        project_id: str, body: ProjectSettings, actor: Reviewer, db: Database
    ) -> ProjectSettings:
        with review_transaction(engine) as locked:
            current = settings(project_id, locked)
            if body.model_dump(exclude={"speakers"}) != current.model_dump(exclude={"speakers"}):
                raise ReviewConflict("Only project speaker roles can be changed here")
            labels = [s.speaker_label for s in body.speakers]
            if len(labels) != len(set(labels)) or any(not label.strip() for label in labels):
                raise ReviewConflict("Speaker labels must be nonblank and unique")
            existing = {s.speaker_label for s in current.speakers}
            if not existing.issubset(labels):
                raise ReviewConflict("Existing speaker labels cannot be removed")
            for item in body.speakers:
                if not item.role.strip():
                    raise ReviewConflict("Speaker role must not be blank")
                locked.merge(
                    Speaker(
                        project_id=project_id,
                        speaker_label=item.speaker_label,
                        role=item.role,
                        can_confirm_scope=item.can_confirm_scope,
                    )
                )
            locked.flush()
            return settings(project_id, locked)

    return router
