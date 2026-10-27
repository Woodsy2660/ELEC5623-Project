"""FR01/FR03: project-scoped SQLite reads using the existing HTTP contract."""

import json

from sqlalchemy import select
from sqlalchemy.orm import Session

from src.api.evidence import quote_from_span, quote_unhighlighted
from src.api.schemas import (
    AuditBlock,
    CommittedEvent,
    MeetingOut,
    ProjectOut,
    ProposalList,
    ProposalOut,
    RegisterRow,
    RequirementDetail,
    RetrievedAlternative,
    StateCount,
    StreamTurn,
    TimelineEntry,
)
from src.classify.schemas import Classification
from src.engine.proposal_rules import Verdict
from src.engine.state_machine import State
from src.persist.models import (
    Candidate,
    Event,
    Meeting,
    Project,
    Proposal,
    ProposalReview,
    Requirement,
    RequirementCurrent,
    RequirementVersion,
    Run,
    Speaker,
    Turn,
)
from src.persist.review import ReviewConflict, assess_stored_proposal, candidate_evidence
from src.validate.schemas import EvidenceSpan


def require_project(session: Session, project_id: str) -> Project:
    project = session.get(Project, project_id)
    if project is None:
        raise LookupError(f"Unknown project {project_id}")
    return project


def register_rows(session: Session, project_id: str) -> list[RegisterRow]:
    require_project(session, project_id)
    rows = session.execute(
        select(RequirementCurrent, RequirementVersion, Event)
        .join(Requirement, Requirement.id == RequirementCurrent.requirement_id)
        .join(RequirementVersion, RequirementVersion.id == RequirementCurrent.current_version_id)
        .join(Event, Event.id == RequirementVersion.created_event_id)
        .where(Requirement.project_id == project_id)
        .order_by(Requirement.id)
    )
    return [
        RegisterRow(
            requirement_id=head.requirement_id,
            version=version.version,
            version_label=f"v{version.version}",
            text=head.text,
            state=State(head.state),
            changed_label=event.ts.isoformat(),
        )
        for head, version, event in rows
    ]


def meetings(session: Session, project_id: str) -> list[MeetingOut]:
    require_project(session, project_id)
    result = []
    imports = {
        payload["meeting_id"]: payload
        for event in session.scalars(
            select(Event).where(
                Event.project_id == project_id, Event.event_type == "meeting_imported"
            )
        )
        if (payload := json.loads(event.payload_json))
    }
    for meeting in session.scalars(
        select(Meeting).where(Meeting.project_id == project_id).order_by(Meeting.ordinal)
    ):
        count = len(list(session.scalars(select(Turn.id).where(Turn.meeting_id == meeting.id))))
        metadata = imports.get(meeting.id, {})
        result.append(
            MeetingOut(
                id=meeting.id,
                project_id=project_id,
                ordinal=meeting.ordinal,
                title=metadata.get("title", f"Meeting {meeting.ordinal}"),
                source_name=metadata.get("source_name"),
                when_label=meeting.imported_at.isoformat(),
                status="past",
                turn_count=count,
            )
        )
    return result


def proposal_out(session: Session, proposal: Proposal) -> ProposalOut:
    candidate = session.get(Candidate, proposal.candidate_id)
    meeting = session.get(Meeting, candidate.meeting_id)
    context = session.get(ProposalReview, proposal.id)
    can_confirm, reason, verdict = False, "", None
    try:
        verdict = assess_stored_proposal(session, proposal)
        can_confirm = verdict.verdict in (Verdict.ALLOWED, Verdict.NO_OP)
        reason = "" if can_confirm else verdict.reason
    except ReviewConflict as exc:
        reason = str(exc)
    evidence = []
    try:
        _, spans, turns = candidate_evidence(session, candidate)
        evidence = [
            quote_from_span(speaker=turns[s.turn_id].speaker, text=turns[s.turn_id].text, span=s)
            for s in spans
        ]
    except ReviewConflict as exc:
        can_confirm, reason = False, str(exc)
    ids = json.loads(proposal.retrieved_ids_json)
    retrieved = []
    for rank, rid in enumerate(ids, 1):
        family = session.get(Requirement, rid)
        head = session.get(RequirementCurrent, rid)
        if family and family.project_id == meeting.project_id and head:
            retrieved.append(
                RetrievedAlternative(
                    rank=rank,
                    requirement_id=rid,
                    text=head.text,
                    state=State(head.state),
                    chosen=rid == proposal.predicted_id,
                )
            )
    chosen = next((r for r in retrieved if r.chosen), None)
    label = context.speaker_label if context else ""
    speaker = session.get(Speaker, (meeting.project_id, label)) if label else None
    decision = None
    if context and context.decision_event_id:
        event = session.get(Event, context.decision_event_id)
        decision = CommittedEvent.model_validate_json(event.payload_json)
    return ProposalOut(
        id=proposal.id,
        project_id=meeting.project_id,
        meeting_id=meeting.id,
        requirement_id=proposal.predicted_id,
        queue_text="Awaiting review" if decision is None else "Reviewed",
        statement=candidate.text_norm,
        classification=Classification(
            matched_requirement_id=proposal.predicted_id,
            relation=proposal.predicted_relation,
            rationale=context.rationale if context else "Review metadata unavailable",
            retrieved_ids=ids,
            replacement_stated=(
                context.classifier_replacement_stated is True if context else False
            ),
        ),
        proposed_event=verdict.proposed_event if verdict else None,
        from_state=chosen.state if chosen else None,
        to_state=verdict.resulting_state if verdict else None,
        can_confirm=can_confirm,
        can_confirm_reason=reason,
        unresolved=not can_confirm and decision is None,
        evidence=evidence,
        retrieved=retrieved,
        speaker_label=label,
        speaker_name=label,
        speaker_role=speaker.role if speaker else "Unconfigured",
        speaker_can_confirm=speaker.can_confirm_scope if speaker else False,
        decision=decision,
    )


def proposals(session: Session, project_id: str) -> ProposalList:
    require_project(session, project_id)
    rows = session.scalars(
        select(Proposal)
        .join(Candidate, Candidate.id == Proposal.candidate_id)
        .join(Meeting, Meeting.id == Candidate.meeting_id)
        .outerjoin(ProposalReview, ProposalReview.proposal_id == Proposal.id)
        .where(
            Meeting.project_id == project_id,
            Proposal.decision.is_(None),
            ProposalReview.decision_event_id.is_(None),
            Proposal.predicted_relation != "error",
        )
        .order_by(Meeting.ordinal, Proposal.id)
    )
    items = [proposal_out(session, row) for row in rows]
    discarded_candidates = 0
    for run in session.scalars(select(Run).where(Run.candidate_source == "extracted")):
        try:
            run_notes = json.loads(run.notes or "{}")
        except (TypeError, ValueError) as exc:
            raise ValueError(f"Run {run.id} has invalid notes") from exc
        if not isinstance(run_notes, dict):
            raise ValueError(f"Run {run.id} has invalid notes")
        if run_notes.get("project_id") != project_id:
            continue
        extraction = run_notes.get("extraction", {})
        if not isinstance(extraction, dict):
            raise ValueError(f"Run {run.id} has invalid extraction metrics")
        rejected = extraction.get("rejected_unresolvable", 0)
        if isinstance(rejected, bool) or not isinstance(rejected, int) or rejected < 0:
            raise ValueError(f"Run {run.id} has an invalid rejected-evidence count")
        discarded_candidates += rejected
    return ProposalList(
        project_id=project_id,
        meeting_id=items[0].meeting_id if items else None,
        queue_label=f"{len(items)} pending proposals",
        scope_count_label=f"{len(register_rows(session, project_id))} requirements",
        discarded_candidates=discarded_candidates,
        proposals=items,
    )


def projects(session: Session) -> list[ProjectOut]:
    result = []
    for project in session.scalars(select(Project).order_by(Project.id)):
        rows = register_rows(session, project.id)
        pending = sum(p.decision is None for p in proposals(session, project.id).proposals)
        result.append(
            ProjectOut(
                id=project.id,
                name=project.name,
                client="",
                meeting_count=len(meetings(session, project.id)),
                requirement_count=len(rows),
                state_counts=[
                    StateCount(state=s, count=sum(r.state == s for r in rows)) for s in State
                ],
                empty=not rows,
                proposal_count=pending,
                review_note=f"{pending} pending review",
            )
        )
    return result


def requirement_detail(session: Session, project_id: str, requirement_id: str) -> RequirementDetail:
    require_project(session, project_id)
    family = session.get(Requirement, requirement_id)
    head = session.get(RequirementCurrent, requirement_id)
    if family is None or family.project_id != project_id or head is None:
        raise LookupError(f"Unknown requirement {requirement_id}")
    current = session.get(RequirementVersion, head.current_version_id)
    entries, event_labels = [], []
    versions = list(
        session.scalars(
            select(RequirementVersion)
            .where(RequirementVersion.requirement_id == requirement_id)
            .order_by(RequirementVersion.version)
        )
    )
    first_event = None
    run = None
    for version in versions:
        event = session.get(Event, version.created_event_id)
        first_event = first_event or event
        run = session.get(Run, event.run_id) if event.run_id else None
        quotes = []
        for raw in json.loads(version.evidence_json):
            span = EvidenceSpan.model_validate(raw)
            turn = session.get(Turn, span.turn_id)
            meeting = session.get(Meeting, turn.meeting_id) if turn else None
            if not meeting or meeting.project_id != project_id:
                raise ReviewConflict("Version evidence is missing or outside this project")
            quotes.append(quote_from_span(speaker=turn.speaker, text=turn.text, span=span))
        entries.append(
            TimelineEntry(
                version=version.version,
                state=State(version.state),
                when_label=event.ts.isoformat(),
                text=version.text,
                historical=version.id != head.current_version_id,
                struck=version.state in ("superseded", "withdrawn"),
                evidence=quotes,
            )
        )
        event_labels.append(f"{event.ts.isoformat()} {event.event_type} ({event.actor})")
    return RequirementDetail(
        id=requirement_id,
        project_id=project_id,
        title=None,
        current_state=State(head.state),
        current_text=head.text,
        current_version=current.version,
        summary="Persisted requirement history",
        timeline=entries,
        audit=AuditBlock(
            family_created=first_event.ts.isoformat(),
            events=event_labels,
            prompt_version=run.prompt_hash if run else "Unavailable",
            model=run.model_deployment if run else "Unavailable",
            rejected_proposals="See project review decisions",
        ),
    )


def turns(session: Session, meeting_id: str) -> list[StreamTurn]:
    if session.get(Meeting, meeting_id) is None:
        raise LookupError(f"Unknown meeting {meeting_id}")
    return [
        StreamTurn(**quote_unhighlighted(turn_id=t.id, speaker=t.speaker, text=t.text).model_dump())
        for t in session.scalars(
            select(Turn).where(Turn.meeting_id == meeting_id).order_by(Turn.turn_index)
        )
    ]
