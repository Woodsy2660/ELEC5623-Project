"""FR02/FR09/FR11: stage proposals, validate again, then atomically commit review.

No model or gold decisions are made here. Callers supply an authenticated human
decision and own the transaction. SQLite writers acquire BEGIN IMMEDIATE before
reading so a second reviewer cannot commit against the same historical head.
"""

import json
import re
from collections.abc import Callable
from datetime import UTC, datetime
from typing import Literal
from uuid import uuid4

from pydantic import BaseModel, Field, TypeAdapter
from sqlalchemy import select
from sqlalchemy.orm import Session

from src.classify.schemas import Classification
from src.engine.proposal_rules import RuleVerdict, Verdict, assess_proposal
from src.engine.state_machine import EventType, State, validate_transition
from src.persist.models import (
    Candidate,
    Event,
    Meeting,
    Proposal,
    ProposalReview,
    Requirement,
    RequirementCurrent,
    RequirementVersion,
    Speaker,
    Turn,
)
from src.retrieve.schemas import VectorRecord
from src.validate.resolve import validate_candidate
from src.validate.schemas import EvidenceSpan

EmbedText = Callable[[str], VectorRecord]
_SPANS = TypeAdapter(list[EvidenceSpan])
_IDS = TypeAdapter(list[str])


class ReviewConflict(ValueError):
    """A rejected/unresolved input. Never repair or substitute a prediction."""


class ReviewDecision(BaseModel):
    action: Literal["confirm", "reject", "edit"]
    actor: str = Field(min_length=1)
    edited_text: str | None = None


class ReviewResult(BaseModel):
    id: str
    project_id: str
    proposal_id: str
    action: Literal["confirm", "reject", "edit"]
    event_type: EventType | None
    from_state: State | None
    to_state: State | None
    register_changed: bool
    edited_text: str | None = None
    reason: str


def candidate_evidence(
    session: Session,
    candidate: Candidate,
) -> tuple[Meeting, list[EvidenceSpan], dict[str, Turn]]:
    """Resolve every span against this candidate's stored meeting, without repair."""
    meeting = session.get(Meeting, candidate.meeting_id)
    if meeting is None:
        raise ReviewConflict("Candidate meeting is missing")
    try:
        spans = _SPANS.validate_json(candidate.evidence_json, strict=True)
    except ValueError as exc:
        raise ReviewConflict("Invalid stored evidence") from exc
    turns = {t.id: t for t in session.scalars(select(Turn).where(Turn.meeting_id == meeting.id))}
    result = validate_candidate({key: turn.text for key, turn in turns.items()}, spans)
    if not result.ok:
        raise ReviewConflict(result.reason or "Invalid evidence")
    if len({(s.turn_id, s.start, s.end) for s in spans}) != len(spans):
        raise ReviewConflict("Duplicate evidence spans")
    if any(not turns[s.turn_id].text[s.start : s.end].strip() for s in spans):
        raise ReviewConflict("Evidence must contain text")
    if not candidate.text_norm.strip():
        raise ReviewConflict("Candidate statement is blank")
    return meeting, spans, turns


def explicit_replacement(quotes: list[str]) -> bool:
    """Conservative English rule on quoted evidence, never the classifier label.

    Unrecognised wording remains unresolved for review. This is a declared MVP
    rule, not a general natural-language entailment test.
    """
    text = " ".join(quotes).lower()
    if re.search(r"\b(if|maybe|perhaps|could|might|would|should|not|never|no)\b|n't|[?]", text):
        return False
    return any(
        re.search(pattern, text)
        for pattern in (
            r"\bwe (?:will|have decided to) (?:use|adopt)\b[^.!?]+\binstead\b",
            r"\bwe (?:will|have decided to) replace\b[^.!?]+\bwith\b[^.!?]+",
        )
    )


def current_head(session: Session, project_id: str, requirement_id: str) -> RequirementCurrent:
    family = session.get(Requirement, requirement_id)
    head = session.get(RequirementCurrent, requirement_id)
    if family is None or family.project_id != project_id or head is None:
        raise ReviewConflict("Historical requirement is missing or outside this project")
    version = session.get(RequirementVersion, head.current_version_id)
    if (
        version is None
        or version.requirement_id != requirement_id
        or version.state != head.state
        or version.text != head.text
    ):
        raise ReviewConflict("Current pointer disagrees with requirement history")
    return head


def require_project_embedding_contract(
    session: Session, project_id: str, vector: VectorRecord
) -> None:
    """Keep retained versions retrieval-compatible; fail closed on legacy blobs."""
    rows = session.scalars(
        select(RequirementVersion)
        .join(Requirement, Requirement.id == RequirementVersion.requirement_id)
        .where(Requirement.project_id == project_id)
    )
    for version in rows:
        try:
            previous = VectorRecord.model_validate_json(version.embedding_blob)
        except (ValueError, TypeError) as exc:
            raise ReviewConflict(
                f"Version {version.id} has no verifiable embedding metadata; migrate it before writing"
            ) from exc
        if previous.embedding_model != vector.embedding_model or len(previous.embedding) != len(
            vector.embedding
        ):
            raise ReviewConflict(
                "New vector does not match this project's retrieval model and dimensions"
            )


def assess_stored_proposal(session: Session, proposal: Proposal) -> RuleVerdict:
    candidate = session.get(Candidate, proposal.candidate_id)
    if candidate is None or candidate.run_id != proposal.run_id:
        raise ReviewConflict("Proposal and candidate run disagree")
    meeting, spans, turns = candidate_evidence(session, candidate)
    context = session.get(ProposalReview, proposal.id)
    if context is None:
        raise ReviewConflict(
            "Proposal has no review snapshot; regenerate it through stage_proposal"
        )
    if context.decision_event_id:
        raise ReviewConflict("Proposal already decided")
    evidence_speakers = {turns[s.turn_id].speaker for s in spans}
    if evidence_speakers != {context.speaker_label}:
        raise ReviewConflict("Evidence must identify one configured proposal speaker")
    speaker = session.get(Speaker, (meeting.project_id, context.speaker_label))
    if speaker is None:
        raise ReviewConflict("Evidence speaker has no project role")
    try:
        ids = _IDS.validate_json(proposal.retrieved_ids_json, strict=True)
    except ValueError as exc:
        raise ReviewConflict("Invalid retrieved IDs") from exc
    if len(ids) != len(set(ids)):
        raise ReviewConflict("Duplicate retrieved IDs")
    heads = {rid: current_head(session, meeting.project_id, rid).current_version_id for rid in ids}
    try:
        expected_heads = json.loads(context.expected_retrieval_heads_json or "null")
    except (TypeError, ValueError) as exc:
        raise ReviewConflict("Proposal has invalid retrieval snapshot") from exc
    if expected_heads is None or expected_heads != heads:
        raise ReviewConflict("Retrieved requirements changed since this proposal; regenerate it")
    head = None
    if proposal.predicted_id is not None:
        head = current_head(session, meeting.project_id, proposal.predicted_id)
    if context.expected_version_id != (head.current_version_id if head else None):
        raise ReviewConflict("Requirement changed since this proposal; regenerate it before review")
    return assess_proposal(
        relation=proposal.predicted_relation,
        matched_requirement_id=proposal.predicted_id,
        retrieved_ids=ids,
        current_state=State(head.state) if head else None,
        speaker_can_confirm_scope=speaker.can_confirm_scope,
        replacement_stated=explicit_replacement(
            [turns[s.turn_id].text[s.start : s.end] for s in spans]
        ),
    )


def stage_proposal(
    session: Session,
    *,
    candidate_id: str,
    classification: Classification,
    speaker_label: str,
    embedding: VectorRecord | None = None,
) -> Proposal:
    """A/B integration entry point. Staging never creates a register row or event.

    Invalid/unresolved proposals are retained, not dropped. Their original IDs and
    relation remain available to scoring; confirmation recomputes the verdict.
    """
    candidate = session.get(Candidate, candidate_id)
    if candidate is None:
        raise ReviewConflict("Unknown candidate")
    meeting, _, _ = candidate_evidence(session, candidate)
    heads = {
        rid: current_head(session, meeting.project_id, rid).current_version_id
        for rid in classification.retrieved_ids
    }
    expected = None
    if classification.matched_requirement_id:
        expected = current_head(session, meeting.project_id, classification.matched_requirement_id)
    proposal = Proposal(
        id=str(uuid4()),
        run_id=candidate.run_id,
        candidate_id=candidate.id,
        retrieved_ids_json=json.dumps(classification.retrieved_ids),
        predicted_id=classification.matched_requirement_id,
        predicted_relation=classification.relation.value,
        proposed_event="none",
        engine_verdict=Verdict.REJECTED.value,
    )
    session.add(proposal)
    session.flush()
    session.add(
        ProposalReview(
            proposal_id=proposal.id,
            expected_version_id=expected.current_version_id if expected else None,
            expected_retrieval_heads_json=json.dumps(heads, sort_keys=True),
            speaker_label=speaker_label,
            rationale=classification.rationale,
            embedding_json=embedding.model_dump_json() if embedding is not None else None,
        )
    )
    session.flush()
    try:
        verdict = assess_stored_proposal(session, proposal)
        proposal.engine_verdict = verdict.verdict.value
        proposal.proposed_event = verdict.proposed_event.value if verdict.proposed_event else "none"
    except ReviewConflict:
        # Keep malformed classifications visible as errors. Never manufacture a fallback.
        proposal.engine_verdict = Verdict.REJECTED.value
    session.flush()
    return proposal


def _append_version(
    session: Session,
    *,
    proposal: Proposal,
    project_id: str,
    requirement_id: str,
    event_type: EventType,
    text: str,
    evidence: list[EvidenceSpan],
    vector: VectorRecord,
    actor: str,
    links: dict[str, str] | None = None,
) -> Event:
    head = session.get(RequirementCurrent, requirement_id)
    from_state = State(head.state) if head else None
    state = validate_transition(from_state, event_type)
    if state is None:
        raise ReviewConflict(f"Illegal transition from {from_state} via {event_type.value}")
    if head:
        current_head(session, project_id, requirement_id)
    else:
        if session.get(Requirement, requirement_id):
            raise ReviewConflict("Requirement has no current pointer")
        session.add(Requirement(id=requirement_id, project_id=project_id))
        session.flush()
    previous = session.get(RequirementVersion, head.current_version_id) if head else None
    number = previous.version + 1 if previous else 1
    event = Event(
        id=str(uuid4()),
        project_id=project_id,
        ts=datetime.now(UTC),
        actor=actor,
        event_type=event_type.value,
        run_id=proposal.run_id,
        payload_json=json.dumps(
            {
                "requirement_id": requirement_id,
                "proposal_id": proposal.id,
                "candidate_id": proposal.candidate_id,
                "meeting_id": session.get(Candidate, proposal.candidate_id).meeting_id,
                "text": text,
                "version": number,
                "from_state": from_state.value if from_state else None,
                "to_state": state.value,
                "evidence": [s.model_dump() for s in evidence],
                "relation": proposal.predicted_relation,
                **(links or {}),
            }
        ),
    )
    session.add(event)
    session.flush()
    version = RequirementVersion(
        id=str(uuid4()),
        requirement_id=requirement_id,
        version=number,
        text=text,
        state=state.value,
        evidence_json=json.dumps([s.model_dump() for s in evidence]),
        embedding_blob=vector.model_dump_json().encode(),
        created_event_id=event.id,
    )
    session.add(version)
    session.flush()
    if head is None:
        session.add(
            RequirementCurrent(
                requirement_id=requirement_id,
                current_version_id=version.id,
                state=state.value,
                text=text,
            )
        )
    else:
        head.current_version_id, head.state, head.text = version.id, state.value, text
    session.flush()
    return event


def commit_decision(
    session: Session,
    *,
    proposal_id: str,
    decision: ReviewDecision,
    embed_text: EmbedText,
) -> ReviewResult:
    """Apply one human decision inside the caller's locked transaction.

    Edit changes normalized text only; evidence and classifier prediction remain
    immutable, and evidence, authority, head and transition are all revalidated.
    """
    proposal = session.get(Proposal, proposal_id)
    if proposal is None:
        raise ReviewConflict("Unknown proposal")
    candidate = session.get(Candidate, proposal.candidate_id)
    meeting = session.get(Meeting, candidate.meeting_id)
    context = session.get(ProposalReview, proposal.id)
    if context is None:
        raise ReviewConflict(
            "Proposal has no review snapshot; regenerate it through stage_proposal"
        )
    if context.decision_event_id:
        raise ReviewConflict("Proposal already decided")
    head = None
    if proposal.predicted_id:
        head = current_head(session, meeting.project_id, proposal.predicted_id)
    source_state = State(head.state) if head else None
    final_state, event_type = source_state, None
    changed = False
    text = candidate.text_norm
    if decision.action == "edit":
        if not decision.edited_text or not decision.edited_text.strip():
            raise ReviewConflict("Edit requires replacement text")
        text = decision.edited_text
    if decision.action != "reject":
        verdict = assess_stored_proposal(session, proposal)
        if verdict.verdict not in (Verdict.ALLOWED, Verdict.NO_OP):
            raise ReviewConflict(verdict.reason)
        if decision.action == "edit" and verdict.verdict == Verdict.NO_OP:
            raise ReviewConflict("A no-op cannot change requirement text")
        if verdict.verdict == Verdict.ALLOWED:
            _, spans, _ = candidate_evidence(session, candidate)
            vector = (
                VectorRecord.model_validate_json(context.embedding_json)
                if context.embedding_json is not None and text == candidate.text_norm
                else embed_text(text)
            )
            if not isinstance(vector, VectorRecord):
                raise ReviewConflict("Embedding provider must return a validated VectorRecord")
            require_project_embedding_contract(session, meeting.project_id, vector)
            event_type = verdict.proposed_event
            rid = proposal.predicted_id or str(uuid4())
            args = dict(
                session=session,
                proposal=proposal,
                project_id=meeting.project_id,
                evidence=spans,
                actor=decision.actor,
            )
            if event_type == EventType.SUPERSEDE:
                replacement_id = str(uuid4())
                # Preserve the old statement; the new statement belongs to the replacement family.
                old_vector = embed_text(head.text)
                _append_version(
                    **args,
                    requirement_id=rid,
                    event_type=event_type,
                    text=head.text,
                    vector=old_vector,
                    links={"replacement_requirement_id": replacement_id},
                )
                for transition in (EventType.CREATE, EventType.CONFIRM):
                    _append_version(
                        **args,
                        requirement_id=replacement_id,
                        event_type=transition,
                        text=text,
                        vector=vector,
                        links={"replaces_requirement_id": rid},
                    )
                final_state = State.SUPERSEDED
            else:
                _append_version(
                    **args, requirement_id=rid, event_type=event_type, text=text, vector=vector
                )
                final_state = verdict.resulting_state
                if event_type == EventType.CREATE:
                    _append_version(
                        **args,
                        requirement_id=rid,
                        event_type=EventType.CONFIRM,
                        text=text,
                        vector=vector,
                    )
                    event_type, final_state = EventType.CONFIRM, State.CONFIRMED
            changed = True
    reason = "Committed" if changed else "Decision recorded; register unchanged"
    result = ReviewResult(
        id=str(uuid4()),
        project_id=meeting.project_id,
        proposal_id=proposal.id,
        action=decision.action,
        event_type=event_type,
        from_state=source_state,
        to_state=final_state,
        register_changed=changed,
        edited_text=text if decision.action == "edit" else None,
        reason=reason,
    )
    session.add(
        Event(
            id=result.id,
            project_id=meeting.project_id,
            ts=datetime.now(UTC),
            actor=decision.actor,
            event_type="review_decision",
            run_id=proposal.run_id,
            payload_json=result.model_dump_json(),
        )
    )
    session.flush()
    context.decision_event_id = result.id
    session.flush()
    return result
