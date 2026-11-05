"""FR02/FR09/FR11: stage proposals, validate again, then atomically commit review.

No model or gold decisions are made here. Callers supply an authenticated human
decision and own the transaction. SQLite writers acquire BEGIN IMMEDIATE before
reading so a second reviewer cannot commit against the same historical head.
"""

import hashlib
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
from src.engine.state_machine import EventType, State
from src.extract.schemas import Candidate as CandidateData
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
from src.persist.register import confirm_current, write_supersession_replacement, write_version
from src.persist.retrieval import vector_record_from_version
from src.retrieve.schemas import VectorRecord
from src.validate.resolve import validate_candidate
from src.validate.schemas import EvidenceSpan

EmbedText = Callable[[str], VectorRecord]
_SPANS = TypeAdapter(list[EvidenceSpan])
_IDS = TypeAdapter(list[str])


class ReviewConflict(ValueError):
    """A rejected/unresolved input. Never repair or substitute a prediction."""


class ProjectSnapshotConflict(ReviewConflict):
    """The project changed, while the proposal's own retrieved heads may still match."""


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


class MeetingGate(BaseModel):
    meeting_id: str
    ordinal: int
    generated: bool
    can_generate: bool
    reason: str = ""


def meeting_has_candidates(session: Session, meeting_id: str) -> bool:
    return (
        session.scalar(select(Candidate.id).where(Candidate.meeting_id == meeting_id).limit(1))
        is not None
    )


def pending_review_count(session: Session, project_id: str) -> int:
    """Proposals in this project that no reviewer has confirmed, edited or rejected."""
    return len(
        session.scalars(
            select(Proposal.id)
            .join(Candidate, Candidate.id == Proposal.candidate_id)
            .join(Meeting, Meeting.id == Candidate.meeting_id)
            .where(Meeting.project_id == project_id, Proposal.decision.is_(None))
        ).all()
    )


def meeting_gates(session: Session, project_id: str) -> list[MeetingGate]:
    """Demo order from docs/02: the reviewed register feeds the next meeting.

    Only the earliest unprocessed meeting can be generated, and only once every
    earlier proposal in the project has a human decision.
    """
    pending = pending_review_count(session, project_id)
    gates: list[MeetingGate] = []
    first_open: int | None = None
    for meeting in session.scalars(
        select(Meeting).where(Meeting.project_id == project_id).order_by(Meeting.ordinal)
    ):
        if meeting_has_candidates(session, meeting.id):
            gates.append(
                MeetingGate(
                    meeting_id=meeting.id,
                    ordinal=meeting.ordinal,
                    generated=True,
                    can_generate=False,
                )
            )
            continue
        if first_open is not None:
            reason = f"Generate meeting {first_open} first"
        elif pending:
            reason = f"Decide the {pending} pending proposals from earlier meetings first"
        else:
            reason = ""
        gates.append(
            MeetingGate(
                meeting_id=meeting.id,
                ordinal=meeting.ordinal,
                generated=False,
                can_generate=not reason,
                reason=reason,
            )
        )
        if first_open is None:
            first_open = meeting.ordinal
    return gates


def evidence_sentence(text: str, start: int, end: int) -> str:
    """Widen a quoted span to the whole sentence it sits in.

    The extractor may quote "reset links should be sent by SMS instead of email"
    and drop the "From now on" or "If legal agrees," that decides the meaning.
    """
    left = max(text.rfind(mark, 0, start) for mark in ".!?") + 1
    if end > start and text[end - 1] in ".!?":
        right = end
    else:
        stops = [i for i in (text.find(mark, end) for mark in ".!?") if i >= 0]
        right = min(stops) + 1 if stops else len(text)
    return text[left:right].strip()


def hedged_statement(quotes: list[str]) -> bool:
    """True when the evidence is a question, a condition or a possibility.

    Negation is not a hedge here: "the receipt emails can't happen as agreed" is how
    a contradiction is stated.
    """
    text = " ".join(quotes).lower().replace("’", "'")
    return bool(
        re.search(
            r"\b(if|unless|maybe|perhaps|possibly|probably|may|might|could|would)\b|[?]",
            text,
        )
    )


def cancellation_stated(quotes: list[str]) -> bool:
    """True when the evidence withdraws something: the content test for a contradiction.

    A contradiction makes an earlier statement false with no replacement (docs/05), so
    its evidence must carry a refusal or withdrawal. A plain requirement sentence ("Record
    the parcels delivered to each household") or a reaffirmation ("still required") does
    not. "cancel" is left out because it is often the subject matter, not the decision.
    """
    text = " ".join(quotes).lower().replace("’", "'")
    return bool(
        re.search(
            r"\b(?:cannot|can't|won't|will not|must not|shall not|no longer|not part of"
            r"|not (?:needed|required|necessary|going ahead|go ahead|happen(?:ing)?)"
            r"|(?:don't|doesn't|do not|does not) need"
            r"|drop(?:s|ped)?|remove[sd]?|withdraw(?:n|s)?|scrap(?:s|ped)?|abandon(?:s|ed)?)\b",
            text,
        )
    )


def explicit_replacement(quotes: list[str]) -> bool:
    """Conservative English rule on quoted evidence, never the classifier label.

    Unrecognised wording remains unresolved for review. This is a declared MVP
    rule, not a general natural-language entailment test.
    """
    text = " ".join(quotes).lower().replace("’", "'")
    # "no longer" retires the outgoing option ("telephone booking is no longer part of
    # this service"); it does not refuse the replacement, so it is not a negation here.
    if re.search(
        r"\b(if|unless|maybe|perhaps|possibly|probably|may|could|might|would|not|never|no)\b"
        r"|n't|[?]",
        re.sub(r"\bno longer\b", "", text),
    ):
        return False
    # A dated commitment plus a named alternative is a replacement even without "we'll":
    # "from now on reset links should be sent by SMS instead of email". Normative
    # "should" is accepted only in this frame; elsewhere it stays a recommendation.
    commitment = r"(?:from now on|going forward|from today|as of today|starting (?:today|now))"
    alternative = r"(?:instead of|rather than)"
    if re.search(
        rf"\b{commitment}\b[^.!?]*\b{alternative}\b|\b{alternative}\b[^.!?]*\b{commitment}\b",
        text,
    ):
        return True
    if re.search(r"\bshould\b", text):
        return False
    # An unhedged instruction names the replacement directly: "Replace X with Y",
    # "Switch X to Y", "Send it by SMS instead of email".
    if re.search(
        r"(?:^|[.;:!]\s*)(?:replace\b[^.!?]+\bwith\b|(?:switch|change|move)\b[^.!?]*\bto\b)", text
    ):
        return True
    if re.search(r"\b(?:instead of|rather than)\b", text):
        return True
    decision = r"(?:we will|we'll|we are going to|we're going to|we (?:have |'ve )?decided to|let's|let us)"
    return any(
        re.search(pattern, text)
        for pattern in (
            rf"\b{decision} (?:use|adopt|go with)\b[^.!?]+\binstead\b",
            rf"\b{decision} replace\b[^.!?]+\bwith\b[^.!?]+",
            rf"\b{decision} (?:change|switch|move)\b[^.!?]*\bto\b[^.!?]+",
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


ProjectHeadSnapshot = dict[str, dict[str, str | int]]


def project_head_snapshot(session: Session, project_id: str) -> ProjectHeadSnapshot:
    """Capture version and state for every family so later proposals detect all changes."""
    rows = session.execute(
        select(
            Requirement.id,
            RequirementCurrent.current_version_id,
            RequirementCurrent.state,
            RequirementCurrent.text,
            RequirementVersion.version,
            RequirementVersion.state,
            RequirementVersion.text,
        )
        .outerjoin(RequirementCurrent, RequirementCurrent.requirement_id == Requirement.id)
        .outerjoin(
            RequirementVersion,
            RequirementVersion.id == RequirementCurrent.current_version_id,
        )
        .where(Requirement.project_id == project_id)
        .order_by(Requirement.id)
    )
    snapshot = {}
    for family_id, version_id, head_state, head_text, version, version_state, version_text in rows:
        if (
            version_id is None
            or version is None
            or head_state != version_state
            or head_text != version_text
        ):
            raise ReviewConflict(f"Requirement {family_id} has an invalid current pointer")
        snapshot[family_id] = {
            "version_id": version_id,
            "version": version,
            "state": head_state,
        }
    return snapshot


def project_snapshot_fingerprint(snapshot: ProjectHeadSnapshot) -> str:
    """Stable token proving which current register snapshot the reviewer saw."""
    canonical = json.dumps(snapshot, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()


def require_project_embedding_contract(
    session: Session, project_id: str, vector: VectorRecord
) -> None:
    """Keep every retained version aligned with B's model/version/dimension contract."""
    rows = session.scalars(
        select(RequirementVersion)
        .join(Requirement, Requirement.id == RequirementVersion.requirement_id)
        .where(Requirement.project_id == project_id)
    )
    for version in rows:
        try:
            previous = vector_record_from_version(version)
        except ValueError as exc:
            raise ReviewConflict(
                f"Version {version.id} has no verifiable embedding metadata; migrate it before writing"
            ) from exc
        if (
            previous.embedding_model != vector.embedding_model
            or previous.embedding_version != vector.embedding_version
            or previous.embedding_dim != vector.embedding_dim
        ):
            raise ReviewConflict(
                "New vector does not match this project's retrieval model, version, and dimensions"
            )


def _next_event_seq(session: Session, run_id: str) -> int:
    """Allocate the next replay order for events written after a proposal is reviewed."""
    largest = 0
    for event in session.scalars(select(Event).where(Event.run_id == run_id)):
        try:
            payload = json.loads(event.payload_json)
        except (TypeError, ValueError):
            continue
        value = payload.get("seq")
        if isinstance(value, int) and value > largest:
            largest = value
    return largest + 1


def assess_stored_proposal(
    session: Session, proposal: Proposal, *, allow_project_changes: bool = False
) -> RuleVerdict:
    candidate = session.get(Candidate, proposal.candidate_id)
    if candidate is None or candidate.run_id != proposal.run_id:
        raise ReviewConflict("Proposal and candidate run disagree")
    meeting, spans, turns = candidate_evidence(session, candidate)
    context = session.get(ProposalReview, proposal.id)
    if context is None:
        raise ReviewConflict(
            "Proposal has no review snapshot; regenerate it through stage_proposal"
        )
    if context.decision_event_id or proposal.decision is not None:
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
    if context.expected_project_heads_json is None:
        raise ReviewConflict("Proposal has no project snapshot; regenerate it before review")
    try:
        expected_project_heads = json.loads(context.expected_project_heads_json)
    except (TypeError, ValueError) as exc:
        raise ReviewConflict("Proposal has an invalid project snapshot") from exc
    if expected_project_heads != project_head_snapshot(session, meeting.project_id):
        if not allow_project_changes:
            raise ProjectSnapshotConflict(
                "Project requirements or states changed since this proposal"
            )
    head = None
    if proposal.predicted_id is not None:
        head = current_head(session, meeting.project_id, proposal.predicted_id)
    if context.expected_version_id != (head.current_version_id if head else None):
        raise ReviewConflict("Requirement changed since this proposal; regenerate it before review")
    sentences = [evidence_sentence(turns[s.turn_id].text, s.start, s.end) for s in spans]
    return assess_proposal(
        relation=proposal.predicted_relation,
        matched_requirement_id=proposal.predicted_id,
        retrieved_ids=ids,
        current_state=State(head.state) if head else None,
        speaker_can_confirm_scope=speaker.can_confirm_scope,
        replacement_stated=explicit_replacement(sentences),
        hedged=hedged_statement(sentences),
        cancellation_stated=cancellation_stated(sentences),
    )


def stage_proposal(
    session: Session,
    *,
    candidate_id: str,
    classification: Classification,
    speaker_label: str,
    embedding: VectorRecord | None = None,
    rankings: dict[str, object] | None = None,
    downgraded: bool = False,
    expected_project_heads: ProjectHeadSnapshot | None = None,
) -> Proposal:
    """A/B integration entry point. Staging never creates a register row or event.

    Invalid/unresolved proposals are retained, not dropped. Their original IDs and
    relation remain available to scoring; confirmation recomputes the verdict.
    """
    candidate = session.get(Candidate, candidate_id)
    if candidate is None:
        raise ReviewConflict("Unknown candidate")
    meeting, _, _ = candidate_evidence(session, candidate)
    project_heads = (
        expected_project_heads
        if expected_project_heads is not None
        else project_head_snapshot(session, meeting.project_id)
    )
    heads = {}
    for rid in classification.retrieved_ids:
        snapshot = project_heads.get(rid)
        if snapshot is None or not isinstance(snapshot.get("version_id"), str):
            raise ReviewConflict(
                f"Retrieved requirement {rid} is missing from the project snapshot"
            )
        heads[rid] = snapshot["version_id"]
    expected = None
    if classification.matched_requirement_id:
        expected = project_heads.get(classification.matched_requirement_id)
        if expected is None or not isinstance(expected.get("version_id"), str):
            raise ReviewConflict("Matched requirement is missing from the project snapshot")
    proposal = Proposal(
        id=str(uuid4()),
        run_id=candidate.run_id,
        candidate_id=candidate.id,
        retrieved_ids_json=json.dumps(classification.retrieved_ids),
        predicted_id=classification.matched_requirement_id,
        predicted_relation=classification.relation.value,
        proposed_event="none",
        engine_verdict=Verdict.REJECTED.value,
        rankings_json=json.dumps(rankings) if rankings is not None else None,
        decision=None,
        downgraded=downgraded,
    )
    session.add(proposal)
    session.flush()
    session.add(
        ProposalReview(
            proposal_id=proposal.id,
            expected_version_id=expected["version_id"] if expected else None,
            expected_retrieval_heads_json=json.dumps(heads, sort_keys=True),
            expected_project_heads_json=json.dumps(project_heads, sort_keys=True),
            speaker_label=speaker_label,
            rationale=classification.rationale,
            embedding_json=embedding.model_dump_json() if embedding is not None else None,
            classifier_replacement_stated=classification.replacement_stated,
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


def commit_decision(
    session: Session,
    *,
    proposal_id: str,
    decision: ReviewDecision,
    embed_text: EmbedText,
    project_snapshot_token: str | None = None,
) -> ReviewResult:
    """Apply one human decision inside the caller's locked transaction.

    Edit changes normalized text only; evidence and classifier prediction remain
    immutable, and evidence, authority, head and transition are all revalidated.
    """
    proposal = session.get(Proposal, proposal_id)
    if proposal is None:
        raise ReviewConflict("Unknown proposal")
    candidate = session.get(Candidate, proposal.candidate_id)
    if candidate is None:
        raise ReviewConflict("Proposal candidate is missing")
    meeting = session.get(Meeting, candidate.meeting_id)
    if meeting is None:
        raise ReviewConflict("Proposal meeting is missing")
    context = session.get(ProposalReview, proposal.id)
    if context is None:
        raise ReviewConflict(
            "Proposal has no review snapshot; regenerate it through stage_proposal"
        )
    if context.decision_event_id or proposal.decision is not None:
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
        try:
            verdict = assess_stored_proposal(session, proposal)
        except ProjectSnapshotConflict:
            current_snapshot = project_head_snapshot(session, meeting.project_id)
            if project_snapshot_token != project_snapshot_fingerprint(current_snapshot):
                raise ReviewConflict(
                    "Project requirements or states changed since this proposal was loaded; "
                    "reload and review the current entries"
                ) from None
            previous_snapshot = json.loads(context.expected_project_heads_json or "null")
            verdict = assess_stored_proposal(session, proposal, allow_project_changes=True)
            if verdict.verdict not in (Verdict.ALLOWED, Verdict.NO_OP):
                raise ReviewConflict(verdict.reason) from None
            context.expected_project_heads_json = json.dumps(current_snapshot, sort_keys=True)
            session.add(
                Event(
                    id=str(uuid4()),
                    project_id=meeting.project_id,
                    ts=datetime.now(UTC),
                    actor=decision.actor,
                    event_type="proposal_revalidated",
                    run_id=None,
                    payload_json=json.dumps(
                        {
                            "proposal_id": proposal.id,
                            "previous_project_heads": previous_snapshot,
                            "current_project_heads": current_snapshot,
                        },
                        sort_keys=True,
                    ),
                )
            )
        if verdict.verdict not in (Verdict.ALLOWED, Verdict.NO_OP):
            raise ReviewConflict(verdict.reason)
        if decision.action == "edit" and verdict.verdict == Verdict.NO_OP:
            raise ReviewConflict("A no-op cannot change requirement text")
        if verdict.verdict == Verdict.ALLOWED:
            _, spans, _ = candidate_evidence(session, candidate)
            proposal_vector = None
            if context.embedding_json is not None:
                try:
                    proposal_vector = VectorRecord.model_validate_json(context.embedding_json)
                except (TypeError, ValueError) as exc:
                    raise ReviewConflict("Proposal embedding is invalid") from exc
            vector = (
                proposal_vector
                if proposal_vector is not None and text == candidate.text_norm
                else embed_text(text)
            )
            if not isinstance(vector, VectorRecord):
                raise ReviewConflict("Embedding provider must return a validated VectorRecord")
            if proposal_vector is not None and text != candidate.text_norm:
                if (
                    vector.embedding_model != proposal_vector.embedding_model
                    or vector.embedding_version != proposal_vector.embedding_version
                    or vector.embedding_dim != proposal_vector.embedding_dim
                ):
                    raise ReviewConflict(
                        "Edited text embedding does not match the Track B proposal encoder"
                    )
            require_project_embedding_contract(session, meeting.project_id, vector)
            event_type = verdict.proposed_event
            rid = proposal.predicted_id or str(uuid4())
            classification = Classification(
                matched_requirement_id=proposal.predicted_id,
                relation=proposal.predicted_relation,
                rationale=context.rationale,
                retrieved_ids=_IDS.validate_json(proposal.retrieved_ids_json, strict=True),
                replacement_stated=context.classifier_replacement_stated is True,
            )
            candidate_data = CandidateData(
                candidate_id=candidate.id,
                project_id=meeting.project_id,
                meeting_id=meeting.id,
                text_norm=text,
                evidence=spans,
                atomic=True,
            )
            seq = _next_event_seq(session, proposal.run_id)
            if event_type == EventType.SUPERSEDE:
                replacement_id = str(uuid4())
                write_supersession_replacement(
                    session,
                    project_id=meeting.project_id,
                    run_id=proposal.run_id,
                    requirement_id=rid,
                    replacement_requirement_id=replacement_id,
                    candidate=candidate_data,
                    classification=classification,
                    meeting_ordinal=meeting.ordinal,
                    seq=seq,
                    embedding=vector.embedding,
                    embedding_model=vector.embedding_model,
                    embedding_version=vector.embedding_version,
                    embedding_dim=vector.embedding_dim,
                    actor=decision.actor,
                    proposal_id=proposal.id,
                )
                final_state = State.SUPERSEDED
            else:
                event_links = {"proposal_id": proposal.id}
                write_version(
                    session,
                    project_id=meeting.project_id,
                    run_id=proposal.run_id,
                    requirement_id=rid,
                    event_type=event_type,
                    resulting_state=verdict.resulting_state,
                    candidate=candidate_data,
                    classification=classification,
                    meeting_ordinal=meeting.ordinal,
                    seq=seq,
                    embedding=vector.embedding,
                    embedding_model=vector.embedding_model,
                    embedding_version=vector.embedding_version,
                    embedding_dim=vector.embedding_dim,
                    actor=decision.actor,
                    event_links=event_links,
                )
                final_state = verdict.resulting_state
                if event_type == EventType.CREATE:
                    confirm_current(
                        session,
                        project_id=meeting.project_id,
                        run_id=proposal.run_id,
                        requirement_id=rid,
                        candidate=candidate_data,
                        classification=classification,
                        meeting_ordinal=meeting.ordinal,
                        seq=seq + 1,
                        actor=decision.actor,
                        event_links=event_links,
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
    proposal.decision = decision.action
    context.decision_event_id = result.id
    session.flush()
    return result
