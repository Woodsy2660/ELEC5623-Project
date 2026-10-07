"""Fixture routes. Nothing here reads or writes a database.

A decision is committed only after ``apply_decision`` accepts it. That function
calls the state engine. A refused decision is a 409 whose body is the reason.
"""

import json
from collections.abc import Iterator

from fastapi import APIRouter, Response
from fastapi.responses import JSONResponse, StreamingResponse

from src.api.decisions import apply_decision
from src.api.evidence import quote_unhighlighted
from src.api.fixtures import StoredTurn
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
    StreamTurn,
)
from src.api.store import get_store

router = APIRouter()


def _missing(reason: str) -> JSONResponse:
    return JSONResponse(status_code=404, content=ReasonBody(reason=reason).model_dump())


def _conflict(reason: str) -> JSONResponse:
    return JSONResponse(status_code=409, content=DecisionConflict(reason=reason).model_dump())


def _known_speaker_keys(settings: ProjectSettings) -> set[str]:
    keys: set[str] = set()
    for speaker in settings.speakers:
        keys.add(speaker.speaker_label.lower())
        keys.add(speaker.display_name.lower())
        keys.add(speaker.name.lower())
    return keys


@router.get("/projects", response_model=list[ProjectOut])
def list_projects() -> list[ProjectOut]:
    return list(get_store().projects.values())


@router.get(
    "/projects/{project_id}/requirements",
    response_model=list[RegisterRow],
    responses={404: {"model": ReasonBody}},
)
def list_requirements(project_id: str) -> list[RegisterRow] | JSONResponse:
    store = get_store()
    if project_id not in store.projects:
        return _missing(f"Unknown project {project_id}")
    return store.register[project_id]


@router.get(
    "/projects/{project_id}/requirements/{requirement_id}",
    response_model=RequirementDetail,
    responses={404: {"model": ReasonBody}},
)
def get_requirement(project_id: str, requirement_id: str) -> RequirementDetail | JSONResponse:
    store = get_store()
    if project_id not in store.projects:
        return _missing(f"Unknown project {project_id}")
    detail = store.details[project_id].get(requirement_id)
    if detail is None:
        return _missing(f"Unknown requirement {requirement_id}")
    return detail


@router.get(
    "/projects/{project_id}/proposals",
    response_model=ProposalList,
    responses={404: {"model": ReasonBody}},
)
def list_proposals(project_id: str) -> ProposalList | JSONResponse:
    store = get_store()
    if project_id not in store.projects:
        return _missing(f"Unknown project {project_id}")
    queue_label, scope_label, discarded = store.proposal_list_meta[project_id]
    proposals = store.proposals[project_id]
    meeting_id = proposals[0].meeting_id if proposals else None
    return ProposalList(
        project_id=project_id,
        meeting_id=meeting_id,
        queue_label=queue_label,
        scope_count_label=scope_label,
        discarded_candidates=discarded,
        proposals=proposals,
    )


@router.post(
    "/proposals/{proposal_id}/decision",
    response_model=CommittedEvent,
    responses={404: {"model": ReasonBody}, 409: {"model": DecisionConflict}},
)
def decide(proposal_id: str, body: DecisionRequest) -> CommittedEvent | JSONResponse:
    store = get_store()
    proposal = next(
        (
            item
            for proposals in store.proposals.values()
            for item in proposals
            if item.id == proposal_id
        ),
        None,
    )
    if proposal is None:
        return _missing(f"Unknown proposal {proposal_id}")
    result = apply_decision(proposal, body, event_id=store.next_event_id())
    if isinstance(result, DecisionConflict):
        return JSONResponse(status_code=409, content=result.model_dump(mode="json"))
    proposal.decision = result
    return result


@router.get(
    "/projects/{project_id}/meetings",
    response_model=list[MeetingOut],
    responses={404: {"model": ReasonBody}},
)
def list_meetings(project_id: str) -> list[MeetingOut] | JSONResponse:
    store = get_store()
    if project_id not in store.projects:
        return _missing(f"Unknown project {project_id}")
    return store.meetings[project_id]


@router.post(
    "/projects/{project_id}/meetings",
    response_model=MeetingOut,
    status_code=201,
    responses={404: {"model": ReasonBody}, 409: {"model": DecisionConflict}},
)
def create_meeting(
    project_id: str, body: MeetingCreate, response: Response
) -> MeetingOut | JSONResponse:
    store = get_store()
    if project_id not in store.projects:
        return _missing(f"Unknown project {project_id}")
    existing = next(
        (
            meeting
            for meeting in store.meetings[project_id]
            if meeting.source_name == body.source_name
        ),
        None,
    )
    if existing is not None:
        response.status_code = 200
        return existing

    known = _known_speaker_keys(store.settings[project_id])
    unknown = [turn.speaker for turn in body.turns if turn.speaker.lower() not in known]
    if unknown:
        return _conflict("Blocked: one speaker has no role")

    meeting_id = f"{project_id}-M{body.ordinal:02d}"
    if any(meeting.id == meeting_id for meeting in store.meetings[project_id]):
        return _conflict(f"Meeting {meeting_id} already exists")

    for index, turn in enumerate(body.turns, start=1):
        store.add_turn(
            StoredTurn(
                meeting_id=meeting_id,
                turn_index=index,
                speaker=turn.speaker,
                text=turn.text,
                quote=quote_unhighlighted(
                    turn_id=f"{meeting_id}:{index:04d}",
                    speaker=turn.speaker,
                    text=turn.text,
                ),
            )
        )

    meeting = MeetingOut(
        id=meeting_id,
        project_id=project_id,
        ordinal=body.ordinal,
        title=body.title,
        when_label="Imported",
        status="past",
        turn_count=len(body.turns),
        source_name=body.source_name,
    )
    store.meetings[project_id].append(meeting)
    return meeting


@router.get(
    "/meetings/{meeting_id}/turns",
    response_model=list[StreamTurn],
    responses={404: {"model": ReasonBody}},
)
def list_turns(meeting_id: str) -> list[StreamTurn] | JSONResponse:
    store = get_store()
    if not _meeting_exists(meeting_id):
        return _missing(f"Unknown meeting {meeting_id}")
    return [_stream_turn(turn, partial=False) for turn in store.turns.get(meeting_id, [])]


@router.get(
    "/meetings/{meeting_id}/stream",
    response_model=None,
    responses={
        200: {
            "description": "Server-sent events. Each event is one StreamTurn.",
            "content": {
                "text/event-stream": {"schema": {"$ref": "#/components/schemas/StreamTurn"}}
            },
        },
        404: {"model": ReasonBody},
    },
)
def stream_meeting(meeting_id: str) -> StreamingResponse | JSONResponse:
    """Replay stored turns. The last turn of the live meeting is still partial."""
    if not _meeting_exists(meeting_id):
        return _missing(f"Unknown meeting {meeting_id}")
    return StreamingResponse(_events(meeting_id), media_type="text/event-stream")


@router.get(
    "/projects/{project_id}/settings",
    response_model=ProjectSettings,
    responses={404: {"model": ReasonBody}},
)
def get_settings(project_id: str) -> ProjectSettings | JSONResponse:
    store = get_store()
    if project_id not in store.projects:
        return _missing(f"Unknown project {project_id}")
    return store.settings[project_id]


@router.put(
    "/projects/{project_id}/settings",
    response_model=ProjectSettings,
    responses={404: {"model": ReasonBody}, 409: {"model": DecisionConflict}},
)
def put_settings(project_id: str, body: ProjectSettings) -> ProjectSettings | JSONResponse:
    store = get_store()
    if project_id not in store.projects:
        return _missing(f"Unknown project {project_id}")
    if body.project_id != project_id:
        return _conflict("Settings project_id does not match the path")
    store.settings[project_id] = body
    return body


def _meeting_exists(meeting_id: str) -> bool:
    store = get_store()
    return any(
        meeting.id == meeting_id for meetings in store.meetings.values() for meeting in meetings
    )


def _stream_turn(turn: StoredTurn, *, partial: bool) -> StreamTurn:
    quote = turn.quote
    return StreamTurn(
        turn_id=quote.turn_id,
        speaker=quote.speaker,
        before=quote.before,
        span=quote.span,
        after=quote.after,
        partial=partial,
    )


def _events(meeting_id: str) -> Iterator[str]:
    turns = get_store().turns.get(meeting_id, [])
    last = len(turns) - 1
    for index, turn in enumerate(turns):
        partial = meeting_id == "D1-M03" and index == last
        payload = _stream_turn(turn, partial=partial).model_dump()
        yield f"event: turn\ndata: {json.dumps(payload)}\n\n"
