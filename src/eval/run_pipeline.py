"""Main pipeline execution entry point for evaluation runs.

Implements the nine-step DAG:
1. Open a run with all configuration
2. Load the scenario (project, speakers)
3. For each meeting in ordinal order:
   a. Import canonical file (idempotent)
   b. Obtain candidates (gold or extracted)
   c. For each candidate: retrieve, classify, validate, persist
4. Close the run
"""

import argparse
import hashlib
import json
from datetime import UTC, datetime
from pathlib import Path
from typing import Any
from uuid import uuid4

import yaml
from openai import AzureOpenAI
from sqlalchemy import create_engine
from sqlalchemy.orm import Session, sessionmaker

from src.classify.request import PROMPT_PATH as CLASSIFY_PROMPT_PATH
from src.classify.schemas import (
    Classification,
    CurrentHead,
    EvidenceTurn,
    Relation,
)
from src.engine.proposal_rules import Verdict
from src.engine.state_machine import EventType, State
from src.extract import Candidate, ExtractionError, extract_candidates
from src.extract.extractor import PROMPT_PATH as EXTRACT_PROMPT_PATH
from src.ingest import load_scenario
from src.llm.config import get_deployment_config
from src.persist.models import (
    Base,
    Event,
    Meeting,
    Proposal,
    Requirement,
    RequirementCurrent,
    RequirementVersion,
    Run,
    Speaker,
    Turn,
)
from src.retrieve.schemas import RequirementVersion as RetrievalVersion
from src.validate.schemas import EvidenceSpan


def _compute_prompt_hashes() -> str:
    """Compute combined hash of all prompt files."""
    prompts = [EXTRACT_PROMPT_PATH, CLASSIFY_PROMPT_PATH]
    hashes = []
    for path in prompts:
        if path.exists():
            content = path.read_bytes()
            blob_hash = hashlib.sha1(f"blob {len(content)}\0".encode() + content).hexdigest()
            hashes.append(f"{path.name}:{blob_hash}")
    return ";".join(sorted(hashes))


def _load_gold_events(scenario_dir: Path) -> list[dict[str, Any]]:
    """Load gold events from gold.yaml."""
    gold_path = scenario_dir / "gold.yaml"
    if not gold_path.exists():
        return []
    with open(gold_path, encoding="utf-8") as f:
        data = yaml.safe_load(f)
    return data.get("events", [])


def _gold_events_for_meeting(gold_events: list[dict], meeting_ordinal: int) -> list[dict]:
    """Filter gold events for a specific meeting."""
    return [e for e in gold_events if e.get("meeting_ordinal") == meeting_ordinal]


def _build_gold_candidate(
    gold_event: dict,
    project_id: str,
    meeting_id: str,
    candidate_index: int,
) -> Candidate:
    """Construct a Candidate from a gold event."""
    # Build evidence spans from gold evidence
    evidence = []
    for ev in gold_event.get("evidence", []):
        evidence.append(EvidenceSpan(
            turn_id=ev["turn_id"],
            start=ev["start"],
            end=ev["end"],
        ))

    # For gold candidates, we use the evidence quote as the normalized text
    # or construct from evidence
    first_evidence = gold_event.get("evidence", [{}])[0]
    text_norm = first_evidence.get("quote", f"Gold event {gold_event['event_index']}")

    return Candidate(
        candidate_id=f"{meeting_id}-G{candidate_index:04d}",
        project_id=project_id,
        meeting_id=meeting_id,
        text_norm=text_norm,
        evidence=evidence,
        atomic=True,
    )


def _get_corpus_versions(
    session: Session,
    project_id: str,
    embedding_model: str,
) -> list[RetrievalVersion]:
    """Build corpus of all retained versions for retrieval.

    Includes ALL states: proposed, confirmed, contradicted, superseded, withdrawn.
    """
    versions = (
        session.query(RequirementVersion)
        .join(Requirement)
        .filter(Requirement.project_id == project_id)
        .order_by(RequirementVersion.requirement_id, RequirementVersion.version)
        .all()
    )

    corpus = []
    for ver in versions:
        # Parse evidence
        evidence = []
        if ver.evidence_json:
            for ev in json.loads(ver.evidence_json):
                evidence.append(EvidenceSpan(
                    turn_id=ev["turn_id"],
                    start=ev["start"],
                    end=ev["end"],
                ))

        # Parse embedding
        if ver.embedding_blob:
            # Assume embedding is stored as JSON blob
            embedding = tuple(json.loads(ver.embedding_blob.decode("utf-8")))
        else:
            # No embedding yet - skip this version for retrieval
            continue

        corpus.append(RetrievalVersion(
            project_id=project_id,
            requirement_id=ver.requirement_id,
            version=ver.version,
            text=ver.text,
            state=State(ver.state),
            evidence=tuple(evidence),
            embedding_model=embedding_model,
            embedding=embedding,
        ))

    return corpus


def _get_current_heads(
    session: Session,
    requirement_ids: list[str],
) -> list[CurrentHead]:
    """Get current head versions for the specified requirements."""
    heads = []
    for req_id in requirement_ids:
        current = (
            session.query(RequirementCurrent)
            .filter(RequirementCurrent.requirement_id == req_id)
            .first()
        )
        if current:
            version = (
                session.query(RequirementVersion)
                .filter(RequirementVersion.id == current.current_version_id)
                .first()
            )
            if version:
                heads.append(CurrentHead(
                    requirement_id=req_id,
                    version=version.version,
                    state=State(current.state),
                ))
    return heads


def _get_evidence_turns(
    session: Session,
    candidate: Candidate,
) -> list[EvidenceTurn]:
    """Get turn data for candidate's evidence."""
    turns = []
    turn_ids = {span.turn_id for span in candidate.evidence}
    for turn_id in turn_ids:
        turn = session.get(Turn, turn_id)
        if turn:
            meeting = session.get(Meeting, turn.meeting_id)
            if meeting:
                turns.append(EvidenceTurn(
                    project_id=meeting.project_id,
                    meeting_id=turn.meeting_id,
                    turn_id=turn.id,
                    speaker_label=turn.speaker,
                    text=turn.text,
                ))
    return turns


def _get_speaker_can_confirm(
    session: Session,
    project_id: str,
    speaker_label: str,
) -> bool:
    """Check if speaker has authority to confirm scope."""
    speaker = (
        session.query(Speaker)
        .filter(
            Speaker.project_id == project_id,
            Speaker.speaker_label == speaker_label,
        )
        .first()
    )
    return speaker.can_confirm_scope if speaker else False


def _apply_event_to_register(
    session: Session,
    project_id: str,
    run_id: str,
    requirement_id: str,
    event_type: EventType,
    candidate: Candidate,
    classification: Classification | None,
    resulting_state: State,
    embedding: tuple[float, ...] | None,
    embedding_model: str | None,
) -> str:
    """Apply an event to the register in one transaction.

    Creates/updates: event, requirement, version, current row.
    Returns the event ID.
    """
    event_id = str(uuid4())
    now = datetime.now(UTC)

    # Build payload
    payload = {
        "requirement_id": requirement_id,
        "candidate_id": candidate.candidate_id,
        "text": candidate.text_norm,
        "evidence": [
            {"turn_id": s.turn_id, "start": s.start, "end": s.end}
            for s in candidate.evidence
        ],
    }
    if classification:
        payload["relation"] = classification.relation.value
        payload["rationale"] = classification.rationale
        payload["retrieved_ids"] = classification.retrieved_ids

    # Create event
    event = Event(
        id=event_id,
        project_id=project_id,
        ts=now,
        actor="pipeline",
        event_type=event_type.value,
        payload_json=json.dumps(payload),
        run_id=run_id,
    )
    session.add(event)

    # Get or create requirement
    requirement = session.get(Requirement, requirement_id)
    if requirement is None:
        requirement = Requirement(id=requirement_id, project_id=project_id)
        session.add(requirement)
        session.flush()

    # Get current version number
    max_version = (
        session.query(RequirementVersion.version)
        .filter(RequirementVersion.requirement_id == requirement_id)
        .order_by(RequirementVersion.version.desc())
        .first()
    )
    new_version_num = (max_version[0] + 1) if max_version else 1

    # Create new version
    version_id = f"{requirement_id}-v{new_version_num}"
    evidence_json = json.dumps([
        {"turn_id": s.turn_id, "start": s.start, "end": s.end}
        for s in candidate.evidence
    ])

    # Encode embedding as JSON blob if present
    embedding_blob = None
    if embedding:
        embedding_blob = json.dumps(list(embedding)).encode("utf-8")

    version = RequirementVersion(
        id=version_id,
        requirement_id=requirement_id,
        version=new_version_num,
        text=candidate.text_norm,
        state=resulting_state.value,
        evidence_json=evidence_json,
        embedding_blob=embedding_blob,
        created_event_id=event_id,
    )
    session.add(version)

    # Update current pointer
    current = (
        session.query(RequirementCurrent)
        .filter(RequirementCurrent.requirement_id == requirement_id)
        .first()
    )
    if current:
        current.current_version_id = version_id
        current.state = resulting_state.value
        current.text = candidate.text_norm
    else:
        current = RequirementCurrent(
            requirement_id=requirement_id,
            current_version_id=version_id,
            state=resulting_state.value,
            text=candidate.text_norm,
        )
        session.add(current)

    session.flush()
    return event_id


def _generate_requirement_id(project_id: str, index: int) -> str:
    """Generate a new requirement ID."""
    return f"R{index + 1:02d}"


def run_pipeline(
    scenario_dir: Path,
    mode: str,
    candidate_source: str,
    repeat_index: int,
    db_url: str = "sqlite:///pipeline.db",
    runs_dir: Path = Path("runs"),
) -> dict[str, Any]:
    """Run the full pipeline on a scenario.

    Args:
        scenario_dir: Path to scenario directory.
        mode: 'demo' or 'eval'.
        candidate_source: 'gold' or 'extracted'.
        repeat_index: Repeat number (1, 2, or 3).
        db_url: Database URL.
        runs_dir: Directory for raw model responses.

    Returns:
        Summary dict with counts and any errors.
    """
    # Create database
    engine = create_engine(db_url)
    Base.metadata.create_all(engine)
    SessionLocal = sessionmaker(bind=engine)
    session = SessionLocal()

    # Load gold events
    gold_events = _load_gold_events(scenario_dir)

    # Get deployment config
    try:
        config = get_deployment_config()
        client = AzureOpenAI(
            azure_endpoint=config.endpoint,
            api_key=config.api_key,
            api_version=config.api_version,
        )
    except ValueError:
        # No Azure config - can't do extraction or classification
        client = None
        config = None

    # Create run record
    run_id = str(uuid4())
    prompt_hash = _compute_prompt_hashes()

    run = Run(
        id=run_id,
        mode=mode,
        candidate_source=candidate_source,
        repeat_index=repeat_index,
        prompt_hash=prompt_hash,
        model_deployment=config.deployment_name if config else "none",
        temp=config.temperature if config else 0.0,
        started_at=datetime.now(UTC),
    )
    session.add(run)
    session.commit()

    # Load scenario
    project = load_scenario(session, scenario_dir)
    session.commit()

    # Load scenario manifest for meeting order
    manifest_path = scenario_dir / "scenario.yaml"
    with open(manifest_path, encoding="utf-8") as f:
        manifest = yaml.safe_load(f)

    # Track stats
    stats = {
        "run_id": run_id,
        "project_id": project.id,
        "mode": mode,
        "candidate_source": candidate_source,
        "meetings_processed": 0,
        "candidates_total": 0,
        "candidates_accepted": 0,
        "proposals_created": 0,
        "events_applied": 0,
        "errors": [],
    }

    # Process meetings in ordinal order
    for meeting_info in sorted(manifest.get("meetings", []), key=lambda m: m["ordinal"]):
        ordinal = meeting_info["ordinal"]
        canonical_rel = meeting_info["canonical"]
        canonical_path = scenario_dir / canonical_rel

        # Import meeting (idempotent)
        from src.ingest import import_meeting
        meeting = import_meeting(session, project.id, canonical_path, ordinal)
        session.commit()

        stats["meetings_processed"] += 1

        # Get candidates
        candidates: list[Candidate] = []

        if candidate_source == "gold":
            # Build candidates from gold events for this meeting
            meeting_gold = _gold_events_for_meeting(gold_events, ordinal)
            for idx, gold_event in enumerate(meeting_gold):
                candidate = _build_gold_candidate(
                    gold_event,
                    project.id,
                    meeting.id,
                    idx,
                )
                candidates.append(candidate)
                # Store gold event metadata for later matching
                candidate._gold_event = gold_event  # type: ignore

        elif candidate_source == "extracted":
            # Extract candidates using LLM-1
            if client is None or config is None:
                stats["errors"].append("No Azure config for extraction")
                continue

            try:
                result = extract_candidates(
                    session,
                    client,
                    run_id=run_id,
                    meeting_id=meeting.id,
                    deployment_name=config.deployment_name,
                    temperature=config.temperature,
                    seed=config.seed,
                    runs_dir=runs_dir,
                )
                candidates = result.candidates
                stats["candidates_accepted"] += result.accepted
            except ExtractionError as e:
                stats["errors"].append(f"Extraction error: {e}")
                continue

        stats["candidates_total"] += len(candidates)

        # Process each candidate
        for candidate in candidates:
            try:
                # Get evidence turns
                evidence_turns = _get_evidence_turns(session, candidate)
                if not evidence_turns:
                    stats["errors"].append(f"No evidence turns for {candidate.candidate_id}")
                    continue

                # Determine speaker (from first evidence turn)
                speaker_label = evidence_turns[0].speaker_label

                # Check speaker authority (used for extracted candidates)
                _speaker_can_confirm = _get_speaker_can_confirm(
                    session, project.id, speaker_label
                )

                # For gold candidates, we know the relation and requirement_id
                if candidate_source == "gold" and hasattr(candidate, "_gold_event"):
                    gold_event = candidate._gold_event
                    relation_str = gold_event.get("relation", "new")
                    gold_req_id = gold_event.get("requirement_id")

                    # Map gold relation to Classification
                    relation = Relation(relation_str)
                    matched_id = gold_req_id if relation != Relation.NEW else None

                    classification = Classification(
                        matched_requirement_id=matched_id,
                        relation=relation,
                        rationale="Gold event",
                        retrieved_ids=[gold_req_id] if gold_req_id else [],
                    )

                    # For gold events, get or create requirement
                    if relation == Relation.NEW:
                        requirement_id = gold_req_id
                    else:
                        requirement_id = matched_id

                    # Determine current state
                    current_row = (
                        session.query(RequirementCurrent)
                        .filter(RequirementCurrent.requirement_id == requirement_id)
                        .first()
                    )
                    _current_state = State(current_row.state) if current_row else None

                    # Determine event type
                    if relation == Relation.NEW:
                        event_type = EventType.CREATE
                        resulting_state = State.PROPOSED
                    elif relation == Relation.REFINEMENT:
                        event_type = EventType.REFINE
                        resulting_state = State.CONFIRMED
                    elif relation == Relation.SUPERSESSION:
                        event_type = EventType.SUPERSEDE
                        resulting_state = State.SUPERSEDED
                    elif relation == Relation.CONTRADICTION:
                        event_type = EventType.CONTRADICT
                        resulting_state = State.CONTRADICTED
                    else:
                        # Restatement or not_requirement - no state change
                        continue

                    # For new requirements, confirm them immediately in eval mode
                    if relation == Relation.NEW and mode == "eval":
                        # First create as proposed
                        _apply_event_to_register(
                            session, project.id, run_id, requirement_id,
                            EventType.CREATE, candidate, classification,
                            State.PROPOSED, None, None,
                        )
                        # Then confirm
                        _apply_event_to_register(
                            session, project.id, run_id, requirement_id,
                            EventType.CONFIRM, candidate, classification,
                            State.CONFIRMED, None, None,
                        )
                        stats["events_applied"] += 2
                    else:
                        # Apply the event directly
                        _apply_event_to_register(
                            session, project.id, run_id, requirement_id,
                            event_type, candidate, classification,
                            resulting_state, None, None,
                        )
                        stats["events_applied"] += 1

                    # Create proposal record
                    proposal = Proposal(
                        id=str(uuid4()),
                        run_id=run_id,
                        candidate_id=candidate.candidate_id,
                        retrieved_ids_json=json.dumps([gold_req_id] if gold_req_id else []),
                        predicted_id=matched_id,
                        predicted_relation=relation.value,
                        proposed_event=event_type.value if event_type else "none",
                        engine_verdict=Verdict.ALLOWED.value,
                    )
                    session.add(proposal)
                    stats["proposals_created"] += 1

                else:
                    # Full pipeline: retrieve, classify, validate, apply
                    # This requires embeddings and the full model pipeline
                    # For now, just log that we'd process this candidate
                    stats["errors"].append(
                        f"Extracted candidate processing not fully implemented: {candidate.candidate_id}"
                    )

                session.commit()

            except Exception as e:
                session.rollback()
                stats["errors"].append(f"Error processing {candidate.candidate_id}: {e}")

    session.close()
    return stats


def main() -> None:
    parser = argparse.ArgumentParser(description="Run the pipeline in evaluation mode.")
    parser.add_argument(
        "--scenario",
        type=str,
        required=True,
        help="Path to scenario directory (e.g., scenarios/dev/D1)",
    )
    parser.add_argument(
        "--mode",
        type=str,
        choices=["demo", "eval"],
        required=True,
        help="Run mode: demo (human confirmation) or eval (gold decisions)",
    )
    parser.add_argument(
        "--candidate-source",
        type=str,
        choices=["gold", "extracted"],
        required=True,
        help="Source of candidates: gold (injected) or extracted (LLM-1)",
    )
    parser.add_argument(
        "--repeat",
        type=int,
        choices=[1, 2, 3],
        required=True,
        help="Repeat index for variance measurement (1, 2, or 3)",
    )
    parser.add_argument(
        "--db",
        type=str,
        default="sqlite:///pipeline.db",
        help="Database URL (default: sqlite:///pipeline.db)",
    )
    args = parser.parse_args()

    scenario_dir = Path(args.scenario)
    if not scenario_dir.exists():
        print(f"Error: Scenario directory not found: {scenario_dir}")
        return

    print("Running pipeline:")
    print(f"  Scenario: {scenario_dir}")
    print(f"  Mode: {args.mode}")
    print(f"  Candidate source: {args.candidate_source}")
    print(f"  Repeat: {args.repeat}")
    print()

    stats = run_pipeline(
        scenario_dir=scenario_dir,
        mode=args.mode,
        candidate_source=args.candidate_source,
        repeat_index=args.repeat,
        db_url=args.db,
    )

    print("Results:")
    print(f"  Run ID: {stats['run_id']}")
    print(f"  Meetings processed: {stats['meetings_processed']}")
    print(f"  Candidates total: {stats['candidates_total']}")
    print(f"  Proposals created: {stats['proposals_created']}")
    print(f"  Events applied: {stats['events_applied']}")

    if stats["errors"]:
        print(f"\nErrors ({len(stats['errors'])}):")
        for error in stats["errors"][:10]:
            print(f"  - {error}")
        if len(stats["errors"]) > 10:
            print(f"  ... and {len(stats['errors']) - 10} more")


if __name__ == "__main__":
    main()
