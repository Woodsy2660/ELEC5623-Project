"""The only register write path. The model proposes; the engine decides.

Eval mode and the review API both call these functions. Transition legality is
``validate_transition`` in ``src.engine``. This module does not keep a second table.
``enforce=False`` is the baseline: it records the model's change without that check.
"""

import json
from datetime import UTC, datetime
from uuid import uuid4

from sqlalchemy.orm import Session

from src.classify.schemas import Classification
from src.engine.state_machine import EventType, State, validate_transition
from src.extract.schemas import Candidate
from src.persist.models import Event, Requirement, RequirementCurrent, RequirementVersion
from src.persist.retrieval import vector_record_from_version


def next_requirement_id(session: Session, project_id: str) -> str:
    """Allocate the next R01-style id from rows already stored for this project."""
    rows = session.query(Requirement.id).filter(Requirement.project_id == project_id).all()
    highest = 0
    for (requirement_id,) in rows:
        if requirement_id.startswith("R") and requirement_id[1:].isdigit():
            highest = max(highest, int(requirement_id[1:]))
    return f"R{highest + 1:02d}"


def _evidence_payload(candidate: Candidate) -> list[dict[str, object]]:
    return [
        {"turn_id": span.turn_id, "start": span.start, "end": span.end}
        for span in candidate.evidence
    ]


def _add_event(
    session: Session,
    *,
    project_id: str,
    run_id: str,
    event_type: EventType,
    requirement_id: str,
    candidate: Candidate,
    classification: Classification | None,
    resulting_state: State,
    meeting_ordinal: int,
    seq: int,
    actor: str,
    event_links: dict[str, str] | None,
) -> str:
    event_id = str(uuid4())
    payload: dict[str, object] = {
        "requirement_id": requirement_id,
        "candidate_id": candidate.candidate_id,
        "text": candidate.text_norm,
        "evidence": _evidence_payload(candidate),
        "meeting_ordinal": meeting_ordinal,
        "resulting_state": resulting_state.value,
        "seq": seq,
    }
    if classification is not None:
        payload["relation"] = classification.relation.value
        payload["rationale"] = classification.rationale
        payload["retrieved_ids"] = list(classification.retrieved_ids)
        payload["replacement_stated"] = classification.replacement_stated
    if event_links:
        payload.update(event_links)
    session.add(
        Event(
            id=event_id,
            project_id=project_id,
            ts=datetime.now(UTC),
            actor=actor,
            event_type=event_type.value,
            payload_json=json.dumps(payload),
            run_id=run_id,
        )
    )
    session.flush()
    return event_id


def _current_state(session: Session, requirement_id: str) -> State | None:
    current = session.get(RequirementCurrent, requirement_id)
    if current is None:
        return None
    return State(current.state)


def write_version(
    session: Session,
    *,
    project_id: str,
    run_id: str,
    requirement_id: str,
    event_type: EventType,
    resulting_state: State,
    candidate: Candidate,
    classification: Classification | None,
    meeting_ordinal: int,
    seq: int,
    embedding: tuple[float, ...] | None,
    embedding_model: str | None,
    embedding_version: str | None,
    embedding_dim: int | None,
    actor: str = "pipeline",
    enforce: bool = True,
    event_links: dict[str, str] | None = None,
) -> str:
    """Append one version and point the current row at it.

    When ``enforce`` is true the engine must agree, and an embedding is required
    so later retrieval does not skip the row. The baseline passes ``enforce=False``
    and may omit the vector: that is the missing validator, not a forgotten column.
    """
    from_state = _current_state(session, requirement_id)
    existing = session.get(Requirement, requirement_id)
    if existing is not None and existing.project_id != project_id:
        raise ValueError(f"Requirement {requirement_id} belongs to a different project")
    if enforce:
        legal = validate_transition(from_state, event_type)
        if legal is None:
            source = from_state.value if from_state is not None else "none"
            raise ValueError(f"illegal transition {event_type.value} from {source}")
        if legal != resulting_state:
            raise ValueError(
                f"resulting state {resulting_state.value} disagrees with the engine "
                f"({legal.value})"
            )
        if (
            embedding is None
            or embedding_model is None
            or embedding_version is None
            or embedding_dim is None
        ):
            raise ValueError(
                "Register writes that feed retrieval require embedding_model, "
                "embedding_version, embedding_dim, and a vector"
            )
    event_id = _add_event(
        session,
        project_id=project_id,
        run_id=run_id,
        event_type=event_type,
        requirement_id=requirement_id,
        candidate=candidate,
        classification=classification,
        resulting_state=resulting_state,
        meeting_ordinal=meeting_ordinal,
        seq=seq,
        actor=actor,
        event_links=event_links,
    )
    requirement = session.get(Requirement, requirement_id)
    if requirement is None:
        session.add(Requirement(id=requirement_id, project_id=project_id))
        session.flush()
    max_version = (
        session.query(RequirementVersion.version)
        .filter(RequirementVersion.requirement_id == requirement_id)
        .order_by(RequirementVersion.version.desc())
        .first()
    )
    new_version_num = (max_version[0] + 1) if max_version else 1
    embedding_blob = None
    stored_model = None
    stored_version = None
    stored_dim = None
    if embedding is not None:
        if embedding_model is None or embedding_version is None or embedding_dim is None:
            raise ValueError(
                "Writing an embedding requires embedding_model, embedding_version, and embedding_dim"
            )
        if len(embedding) != embedding_dim:
            raise ValueError(
                f"Refusing to store {embedding_model} version {embedding_version}: "
                f"declared dim {embedding_dim} but vector length is {len(embedding)}"
            )
        embedding_blob = json.dumps(list(embedding)).encode("utf-8")
        stored_model = embedding_model
        stored_version = embedding_version
        stored_dim = embedding_dim
    version_id = f"{requirement_id}-v{new_version_num}"
    session.add(
        RequirementVersion(
            id=version_id,
            requirement_id=requirement_id,
            version=new_version_num,
            text=candidate.text_norm,
            state=resulting_state.value,
            evidence_json=json.dumps(_evidence_payload(candidate)),
            embedding_blob=embedding_blob,
            embedding_model=stored_model,
            embedding_version=stored_version,
            embedding_dim=stored_dim,
            created_event_id=event_id,
        )
    )
    session.flush()
    current = session.get(RequirementCurrent, requirement_id)
    if current is None:
        session.add(
            RequirementCurrent(
                requirement_id=requirement_id,
                current_version_id=version_id,
                state=resulting_state.value,
                text=candidate.text_norm,
            )
        )
    else:
        current.current_version_id = version_id
        current.state = resulting_state.value
        current.text = candidate.text_norm
    session.flush()
    return event_id


def confirm_current(
    session: Session,
    *,
    project_id: str,
    run_id: str,
    requirement_id: str,
    candidate: Candidate,
    classification: Classification | None,
    meeting_ordinal: int,
    seq: int,
    actor: str = "pipeline",
    enforce: bool = True,
    event_links: dict[str, str] | None = None,
) -> str:
    """Confirm the current version in place. Does not write a second embedding."""
    current = session.get(RequirementCurrent, requirement_id)
    if current is None:
        raise ValueError(f"Cannot confirm unknown requirement {requirement_id}")
    version = session.get(RequirementVersion, current.current_version_id)
    if version is None:
        raise ValueError(f"Cannot confirm {requirement_id}: current version row is missing")
    resulting = validate_transition(State(version.state), EventType.CONFIRM)
    if enforce and resulting is None:
        raise ValueError(f"illegal transition confirm from {version.state}")
    if resulting is None:
        # Baseline already wrote an illegal predecessor. Record the confirm anyway.
        resulting = State.CONFIRMED
    event_id = _add_event(
        session,
        project_id=project_id,
        run_id=run_id,
        event_type=EventType.CONFIRM,
        requirement_id=requirement_id,
        candidate=candidate,
        classification=classification,
        resulting_state=resulting,
        meeting_ordinal=meeting_ordinal,
        seq=seq,
        actor=actor,
        event_links=event_links,
    )
    version.state = resulting.value
    current.state = resulting.value
    session.flush()
    return event_id


def write_supersession_replacement(
    session: Session,
    *,
    project_id: str,
    run_id: str,
    requirement_id: str,
    replacement_requirement_id: str,
    candidate: Candidate,
    classification: Classification,
    meeting_ordinal: int,
    seq: int,
    embedding: tuple[float, ...],
    embedding_model: str,
    embedding_version: str,
    embedding_dim: int,
    actor: str,
    proposal_id: str | None = None,
    enforce: bool = True,
) -> tuple[str, str, str]:
    """Supersede an old family and create a confirmed replacement family atomically.

    The old family's text and vector remain intact in its new Superseded version.
    The replacement has its own family ID and a single Confirmed version.
    """
    if replacement_requirement_id == requirement_id:
        raise ValueError("A replacement must use a separate requirement family")
    head = session.get(RequirementCurrent, requirement_id)
    family = session.get(Requirement, requirement_id)
    if head is None or family is None or family.project_id != project_id:
        raise ValueError("Supersession requires a current requirement in this project")
    old_version = session.get(RequirementVersion, head.current_version_id)
    if old_version is None:
        raise ValueError("Supersession source has no current version")
    old_vector = vector_record_from_version(old_version)
    links = {"replacement_requirement_id": replacement_requirement_id}
    if proposal_id is not None:
        links["proposal_id"] = proposal_id
    superseded_candidate = candidate.model_copy(update={"text_norm": head.text})
    superseded_event_id = write_version(
        session,
        project_id=project_id,
        run_id=run_id,
        requirement_id=requirement_id,
        event_type=EventType.SUPERSEDE,
        resulting_state=State.SUPERSEDED,
        candidate=superseded_candidate,
        classification=classification,
        meeting_ordinal=meeting_ordinal,
        seq=seq,
        embedding=old_vector.embedding,
        embedding_model=old_vector.embedding_model,
        embedding_version=old_vector.embedding_version,
        embedding_dim=old_vector.embedding_dim,
        actor=actor,
        enforce=enforce,
        event_links=links,
    )
    replacement_links = {"replaces_requirement_id": requirement_id}
    if proposal_id is not None:
        replacement_links["proposal_id"] = proposal_id
    create_event_id = write_version(
        session,
        project_id=project_id,
        run_id=run_id,
        requirement_id=replacement_requirement_id,
        event_type=EventType.CREATE,
        resulting_state=State.PROPOSED,
        candidate=candidate,
        classification=classification,
        meeting_ordinal=meeting_ordinal,
        seq=seq + 1,
        embedding=embedding,
        embedding_model=embedding_model,
        embedding_version=embedding_version,
        embedding_dim=embedding_dim,
        actor=actor,
        enforce=enforce,
        event_links=replacement_links,
    )
    confirm_event_id = confirm_current(
        session,
        project_id=project_id,
        run_id=run_id,
        requirement_id=replacement_requirement_id,
        candidate=candidate,
        classification=classification,
        meeting_ordinal=meeting_ordinal,
        seq=seq + 2,
        actor=actor,
        enforce=enforce,
        event_links=replacement_links,
    )
    return superseded_event_id, create_event_id, confirm_event_id
