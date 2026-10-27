"""Main pipeline execution entry point for evaluation runs.

Gold and extracted candidates meet at the same loop. Gold supplies statement
text and evidence only. Relation and requirement ids are not read here.
"""

import argparse
import hashlib
import json
import os
from datetime import UTC, datetime
from pathlib import Path
from typing import Any
from uuid import uuid4

import yaml
from openai import AzureOpenAI
from sqlalchemy.orm import Session, sessionmaker

from src.classify.classify import ClassificationOutcome, classify_candidate
from src.classify.output import assess_classification
from src.classify.request import PROMPT_PATH as CLASSIFY_PROMPT_PATH
from src.classify.schemas import ClassificationInput
from src.engine.proposal_rules import Verdict
from src.engine.state_machine import EventType
from src.eval.gold_candidates import gold_candidate_from_event
from src.extract.extractor import PROMPT_PATH as EXTRACT_PROMPT_PATH
from src.extract.schemas import Candidate
from src.ingest import import_meeting, load_scenario
from src.llm.config import get_deployment_config
from src.logging.calls import CallLogger
from src.persist.database import create_database_engine
from src.persist.models import (
    Base,
    Candidate as CandidateRow,
    Meeting,
    ModelCall,
    Proposal,
    Requirement,
    RequirementCurrent,
    RequirementVersion,
    Run,
    Speaker,
    Turn,
)
from src.persist.register import confirm_current, next_requirement_id, write_version
from src.retrieve.embedder import Embedder, get_embedder
from src.retrieve.embeddings import EmbeddingCall
from src.retrieve.hybrid import retrieve
from src.retrieve.schemas import RequirementVersion as RetrievalVersion
from src.retrieve.schemas import RetrievalRequest
from src.classify.schemas import CurrentHead, EvidenceTurn
from src.engine.state_machine import State
from src.validate.schemas import EvidenceSpan


def load_dotenv(path: Path = Path(".env")) -> None:
    """Load a local env file without overriding variables already set. Never prints values."""
    if not path.is_file():
        return
    for raw in path.read_text(encoding="utf-8").splitlines():
        line = raw.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        key = key.strip()
        value = value.strip().strip('"').strip("'")
        if key and key not in os.environ:
            os.environ[key] = value


def _compute_prompt_hashes() -> str:
    """Compute combined hash of all prompt files."""
    hashes = []
    for path in (EXTRACT_PROMPT_PATH, CLASSIFY_PROMPT_PATH):
        if path.exists():
            content = path.read_bytes()
            blob_hash = hashlib.sha1(f"blob {len(content)}\0".encode() + content).hexdigest()
            hashes.append(f"{path.name}:{blob_hash}")
    return ";".join(sorted(hashes))


def _load_gold_events(scenario_dir: Path) -> list[dict[str, Any]]:
    """Load gold events. Callers may use statement, evidence, and event_action only."""
    gold_path = scenario_dir / "gold.yaml"
    if not gold_path.exists():
        return []
    with open(gold_path, encoding="utf-8") as handle:
        data = yaml.safe_load(handle)
    return data.get("events", [])


def _get_corpus_versions(session: Session, project_id: str) -> list[RetrievalVersion]:
    """All retained versions that carry an encoder identity. Rows without one are skipped."""
    versions = (
        session.query(RequirementVersion)
        .join(Requirement)
        .filter(Requirement.project_id == project_id)
        .order_by(RequirementVersion.requirement_id, RequirementVersion.version)
        .all()
    )
    corpus = []
    for ver in versions:
        evidence = []
        if ver.evidence_json:
            for item in json.loads(ver.evidence_json):
                evidence.append(
                    EvidenceSpan(turn_id=item["turn_id"], start=item["start"], end=item["end"])
                )
        if not ver.embedding_blob:
            continue
        if ver.embedding_model is None or ver.embedding_version is None or ver.embedding_dim is None:
            raise ValueError(f"Requirement version {ver.id} has an embedding without encoder identity")
        embedding = tuple(json.loads(ver.embedding_blob.decode("utf-8")))
        if len(embedding) != ver.embedding_dim:
            raise ValueError(
                f"Requirement version {ver.id} declares dim {ver.embedding_dim} "
                f"but stored {len(embedding)} values"
            )
        corpus.append(
            RetrievalVersion(
                project_id=project_id,
                requirement_id=ver.requirement_id,
                version=ver.version,
                text=ver.text,
                state=State(ver.state),
                evidence=tuple(evidence),
                embedding_model=ver.embedding_model,
                embedding_version=ver.embedding_version,
                embedding_dim=ver.embedding_dim,
                embedding=embedding,
            )
        )
    return corpus


def _get_current_heads(session: Session, requirement_ids: list[str]) -> list[CurrentHead]:
    heads = []
    for req_id in requirement_ids:
        current = session.get(RequirementCurrent, req_id)
        if current is None:
            continue
        version = session.get(RequirementVersion, current.current_version_id)
        if version is None:
            continue
        heads.append(
            CurrentHead(requirement_id=req_id, version=version.version, state=State(current.state))
        )
    return heads


def _get_evidence_turns(session: Session, candidate: Candidate) -> list[EvidenceTurn]:
    turns = []
    seen: set[str] = set()
    for span in candidate.evidence:
        if span.turn_id in seen:
            continue
        seen.add(span.turn_id)
        turn = session.get(Turn, span.turn_id)
        if turn is None:
            continue
        meeting = session.get(Meeting, turn.meeting_id)
        if meeting is None:
            continue
        turns.append(
            EvidenceTurn(
                project_id=meeting.project_id,
                meeting_id=turn.meeting_id,
                turn_id=turn.id,
                speaker_label=turn.speaker,
                text=turn.text,
            )
        )
    return turns


def _get_speaker_can_confirm(session: Session, project_id: str, speaker_label: str) -> bool:
    """Authority comes from the speakers table. An unmapped speaker cannot confirm."""
    speaker = (
        session.query(Speaker)
        .filter(Speaker.project_id == project_id, Speaker.speaker_label == speaker_label)
        .first()
    )
    return bool(speaker.can_confirm_scope) if speaker is not None else False


def _human_decision(mode: str, event_action: str | None, verdict: Verdict, proposed: EventType | None) -> str:
    """Eval confirms an allowed proposal unless the gold file says reject.

    The action is confirm or reject only. A lifecycle name in that field is ignored
    by the caller before it arrives here.
    """
    if mode != "eval":
        return "pending"
    if event_action == "reject":
        return "reject"
    if verdict == Verdict.ALLOWED and proposed is not None and event_action in {None, "confirm"}:
        return "confirm"
    return "reject"


def _insert_candidate(
    session: Session,
    *,
    run_id: str,
    candidate: Candidate,
    extract_call_id: str | None,
) -> None:
    session.add(
        CandidateRow(
            id=candidate.candidate_id,
            meeting_id=candidate.meeting_id,
            run_id=run_id,
            text_norm=candidate.text_norm,
            evidence_json=json.dumps(
                [
                    {"turn_id": span.turn_id, "start": span.start, "end": span.end}
                    for span in candidate.evidence
                ]
            ),
            extract_call_id=extract_call_id,
        )
    )


def _log_local_embedding(
    session: Session,
    run_id: str,
    call: EmbeddingCall,
    runs_dir: Path,
) -> None:
    """Record a local encode in model_calls. Failures here must not hide an encode error."""
    try:
        call_id = str(uuid4())
        run_dir = runs_dir / run_id
        run_dir.mkdir(parents=True, exist_ok=True)
        raw_path = run_dir / f"{call_id}.json"
        raw_path.write_text(
            json.dumps(
                {
                    "model_id": call.model_id,
                    "config_hash": call.config_hash,
                    "input_tokens": call.input_tokens,
                    "latency_ms": call.latency_ms,
                    "error": call.error,
                    "text_count": len(call.texts),
                }
            ),
            encoding="utf-8",
        )
        session.add(
            ModelCall(
                id=call_id,
                run_id=run_id,
                stage="embed",
                deployment_name=call.model_id,
                served_model=call.model_id,
                prompt_hash=call.config_hash,
                temperature=0.0,
                seed=None,
                input_tokens=call.input_tokens,
                output_tokens=0,
                latency_ms=call.latency_ms,
                retries=0,
                cost=0.0,
                raw_json_path=str(raw_path),
            )
        )
        session.flush()
    except Exception:
        return


def _add_proposal(
    session: Session,
    *,
    run_id: str,
    candidate_id: str,
    retrieved_ids: list[str],
    rankings: dict[str, Any],
    predicted_id: str | None,
    predicted_relation: str,
    proposed_event: str,
    engine_verdict: str,
    decision: str,
    downgraded: bool,
) -> None:
    session.add(
        Proposal(
            id=str(uuid4()),
            run_id=run_id,
            candidate_id=candidate_id,
            retrieved_ids_json=json.dumps(retrieved_ids),
            predicted_id=predicted_id,
            predicted_relation=predicted_relation,
            proposed_event=proposed_event,
            engine_verdict=engine_verdict,
            rankings_json=json.dumps(rankings),
            decision=decision,
            downgraded=downgraded,
        )
    )


def _process_candidate(
    session: Session,
    *,
    run_id: str,
    project_id: str,
    meeting_ordinal: int,
    candidate: Candidate,
    event_action: str | None,
    mode: str,
    embedder: Embedder,
    classifier,
    client,
    config,
    runs_dir: Path,
    seq: dict[str, int],
    stats: dict[str, Any],
) -> None:
    """Retrieve, classify, assess, and maybe commit. Identical for both candidate sources."""
    retrieved_ids: list[str] = []
    rankings: dict[str, Any] = {"bm25": [], "dense": [], "fused": [], "offered": [], "error": None}
    try:
        vector = embedder.encode([candidate.text_norm])[0]
        corpus = _get_corpus_versions(session, project_id)
        retrieval = retrieve(
            RetrievalRequest(
                candidate=candidate,
                embedding_model=embedder.model,
                embedding_version=embedder.version,
                embedding_dim=embedder.dim,
                embedding=tuple(vector),
            ),
            corpus,
        )
        retrieved_ids = list(retrieval.retrieved_ids)
        rankings = {
            "bm25": list(retrieval.bm25_family_ids),
            "dense": list(retrieval.dense_family_ids),
            "fused": list(retrieval.fused_family_ids),
            "offered": retrieved_ids,
            "downgraded_from": None,
            "error": None,
        }
        turns = _get_evidence_turns(session, candidate)
        if not candidate.evidence:
            raise ValueError(f"No evidence spans for {candidate.candidate_id}")
        by_id = {turn.turn_id: turn for turn in turns}
        missing = [span.turn_id for span in candidate.evidence if span.turn_id not in by_id]
        if missing:
            raise ValueError(f"No stored turn for evidence {missing[0]}")
        speaker_label = by_id[candidate.evidence[0].turn_id].speaker_label
        unique_turns = []
        seen_turns: set[str] = set()
        for span in candidate.evidence:
            if span.turn_id in seen_turns:
                continue
            seen_turns.add(span.turn_id)
            unique_turns.append(by_id[span.turn_id])
        inputs = ClassificationInput(
            candidate=candidate,
            retrieval=retrieval,
            evidence_turns=tuple(unique_turns),
            current_heads=tuple(_get_current_heads(session, retrieved_ids)),
            speaker_label=speaker_label,
        )
        outcome: ClassificationOutcome = classifier(
            client,
            session=session,
            run_id=run_id,
            inputs=inputs,
            deployment_name=config.deployment_name if config else "none",
            temperature=config.temperature if config else 0.0,
            seed=config.seed if config else 42,
            runs_dir=runs_dir,
        )
        session.commit()
    except Exception as exc:
        session.rollback()
        stats["errors"].append(f"{candidate.candidate_id}: {type(exc).__name__}: {exc}")
        rankings["error"] = f"{type(exc).__name__}: {exc}"
        try:
            _add_proposal(
                session,
                run_id=run_id,
                candidate_id=candidate.candidate_id,
                retrieved_ids=retrieved_ids,
                rankings=rankings,
                predicted_id=None,
                predicted_relation="error",
                proposed_event="none",
                engine_verdict="error",
                decision="error",
                downgraded=False,
            )
            session.commit()
            stats["proposals_created"] += 1
        except Exception as inner:
            session.rollback()
            stats["errors"].append(f"{candidate.candidate_id}: proposal row failed: {inner}")
        return

    rankings["downgraded_from"] = outcome.model_relation if outcome.downgraded else None
    rankings["error"] = outcome.error
    if outcome.error or outcome.classification is None:
        stats["errors"].append(f"{candidate.candidate_id}: {outcome.error}")
        stats["classify_errors"] += 1
        _add_proposal(
            session,
            run_id=run_id,
            candidate_id=candidate.candidate_id,
            retrieved_ids=list(outcome.retrieved_ids),
            rankings=rankings,
            predicted_id=None,
            predicted_relation="error",
            proposed_event="none",
            engine_verdict="error",
            decision="error",
            downgraded=False,
        )
        session.commit()
        stats["proposals_created"] += 1
        return

    if outcome.downgraded:
        stats["downgrades"] += 1
    classification = outcome.classification
    can_confirm = _get_speaker_can_confirm(session, project_id, inputs.speaker_label)
    verdict = assess_classification(
        inputs,
        classification,
        speaker_can_confirm_scope=can_confirm,
        replacement_stated=classification.replacement_stated,
    )
    decision = _human_decision(mode, event_action, verdict.verdict, verdict.proposed_event)
    try:
        if (
            decision == "confirm"
            and verdict.verdict == Verdict.ALLOWED
            and verdict.proposed_event is not None
            and verdict.resulting_state is not None
        ):
            if classification.relation.value == "new":
                requirement_id = next_requirement_id(session, project_id)
            else:
                if classification.matched_requirement_id is None:
                    raise ValueError("Historical relation confirmed without a matched id")
                requirement_id = classification.matched_requirement_id
            seq["n"] += 1
            write_version(
                session,
                project_id=project_id,
                run_id=run_id,
                requirement_id=requirement_id,
                event_type=verdict.proposed_event,
                resulting_state=verdict.resulting_state,
                candidate=candidate,
                classification=classification,
                meeting_ordinal=meeting_ordinal,
                seq=seq["n"],
                embedding=tuple(vector),
                embedding_model=embedder.model,
                embedding_version=embedder.version,
                embedding_dim=embedder.dim,
                actor="pipeline",
                enforce=True,
            )
            stats["events_applied"] += 1
            if verdict.proposed_event == EventType.CREATE:
                seq["n"] += 1
                confirm_current(
                    session,
                    project_id=project_id,
                    run_id=run_id,
                    requirement_id=requirement_id,
                    candidate=candidate,
                    classification=classification,
                    meeting_ordinal=meeting_ordinal,
                    seq=seq["n"],
                    actor="pipeline",
                    enforce=True,
                )
                stats["events_applied"] += 1
        _add_proposal(
            session,
            run_id=run_id,
            candidate_id=candidate.candidate_id,
            retrieved_ids=list(classification.retrieved_ids),
            rankings=rankings,
            predicted_id=classification.matched_requirement_id,
            predicted_relation=classification.relation.value,
            proposed_event=verdict.proposed_event.value if verdict.proposed_event else "none",
            engine_verdict=verdict.verdict.value,
            decision=decision,
            downgraded=outcome.downgraded,
        )
        session.commit()
        stats["proposals_created"] += 1
    except Exception as exc:
        session.rollback()
        stats["errors"].append(f"{candidate.candidate_id}: {type(exc).__name__}: {exc}")
        try:
            rankings["error"] = f"{type(exc).__name__}: {exc}"
            _add_proposal(
                session,
                run_id=run_id,
                candidate_id=candidate.candidate_id,
                retrieved_ids=retrieved_ids,
                rankings=rankings,
                predicted_id=classification.matched_requirement_id,
                predicted_relation=classification.relation.value,
                proposed_event="none",
                engine_verdict="error",
                decision="error",
                downgraded=outcome.downgraded,
            )
            session.commit()
            stats["proposals_created"] += 1
        except Exception as inner:
            session.rollback()
            stats["errors"].append(f"{candidate.candidate_id}: proposal row failed: {inner}")


def run_pipeline(
    scenario_dir: Path,
    mode: str,
    candidate_source: str,
    repeat_index: int,
    db_url: str = "sqlite:///pipeline.db",
    runs_dir: Path = Path("runs"),
    *,
    client=None,
    config=None,
    embedder: Embedder | None = None,
    classifier=None,
) -> dict[str, Any]:
    """Run retrieval, classification, and the engine. Gold does not supply labels."""
    engine = create_database_engine(db_url)
    Base.metadata.create_all(engine)
    session = sessionmaker(bind=engine)()
    if classifier is None:
        classifier = classify_candidate
    if config is None:
        try:
            config = get_deployment_config()
        except ValueError:
            config = None
    needs_client = candidate_source == "extracted" or classifier is classify_candidate
    if client is None and config is not None and needs_client:
        client = AzureOpenAI(
            azure_endpoint=config.endpoint,
            api_key=config.api_key,
            api_version=config.api_version,
        )

    run_id = str(uuid4())
    run = Run(
        id=run_id,
        mode=mode,
        candidate_source=candidate_source,
        repeat_index=repeat_index,
        prompt_hash=_compute_prompt_hashes(),
        model_deployment=config.deployment_name if config else "none",
        temp=config.temperature if config else 0.0,
        started_at=datetime.now(UTC),
        notes="{}",
    )
    session.add(run)
    session.commit()

    project = load_scenario(session, scenario_dir)
    session.commit()
    project_id = project.id

    if embedder is None:
        logger = None
        if client is not None and config is not None:
            logger = CallLogger(
                session,
                client,
                deployment_name=config.deployment_name,
                temperature=config.temperature,
                seed=config.seed,
                runs_dir=runs_dir,
            )

        def _record(call: EmbeddingCall) -> None:
            _log_local_embedding(session, run_id, call, runs_dir)

        embedder = get_embedder(record_local=_record, azure_logger=logger, run_id=run_id)

    try:
        scenario_note = scenario_dir.resolve().relative_to(Path.cwd().resolve()).as_posix()
    except ValueError:
        scenario_note = scenario_dir.as_posix()
    split = "dev" if "dev" in Path(scenario_note).parts else "unspecified"
    notes = {
        "scenario": scenario_note,
        "split": split,
        "system": "pipeline",
        "encoder_model": embedder.model,
        "encoder_version": embedder.version,
        "encoder_dim": embedder.dim,
        "encoder_fingerprint": embedder.fingerprint(),
        "extraction": {
            "returned": 0,
            "accepted": 0,
            "rejected_unresolvable": 0,
            "parse_failures": 0,
        },
    }
    run = session.get(Run, run_id)
    run.notes = json.dumps(notes)
    session.commit()

    stats: dict[str, Any] = {
        "run_id": run_id,
        "project_id": project_id,
        "mode": mode,
        "candidate_source": candidate_source,
        "meetings_processed": 0,
        "candidates_total": 0,
        "candidates_accepted": 0,
        "proposals_created": 0,
        "events_applied": 0,
        "downgrades": 0,
        "classify_errors": 0,
        "errors": [],
    }
    if needs_client and client is None:
        stats["errors"].append("No Azure config for classification")
        session.close()
        return stats

    gold_events = _load_gold_events(scenario_dir) if candidate_source == "gold" else []
    manifest_path = scenario_dir / "scenario.yaml"
    with open(manifest_path, encoding="utf-8") as handle:
        manifest = yaml.safe_load(handle)
    seq = {"n": 0}

    for meeting_info in sorted(manifest.get("meetings", []), key=lambda item: item["ordinal"]):
        ordinal = meeting_info["ordinal"]
        meeting = import_meeting(session, project_id, scenario_dir / meeting_info["canonical"], ordinal)
        session.commit()
        meeting_id = meeting.id
        stats["meetings_processed"] += 1

        prepared: list[tuple[Candidate, str | None]] = []
        if candidate_source == "gold":
            meeting_gold = [
                event for event in gold_events if event.get("meeting_ordinal") == ordinal
            ]
            meeting_gold.sort(key=lambda event: event.get("event_index", 0))
            for index, event in enumerate(meeting_gold):
                built = gold_candidate_from_event(
                    event,
                    project_id=project_id,
                    meeting_id=meeting_id,
                    candidate_index=index,
                    run_id=run_id,
                )
                _insert_candidate(
                    session,
                    run_id=run_id,
                    candidate=built.candidate,
                    extract_call_id=None,
                )
                prepared.append((built.candidate, built.event_action))
            session.commit()
            stats["candidates_accepted"] += len(prepared)
        elif candidate_source == "extracted":
            from src.extract import ExtractionError, extract_candidates

            try:
                result = extract_candidates(
                    session,
                    client,
                    run_id=run_id,
                    meeting_id=meeting_id,
                    deployment_name=config.deployment_name,
                    temperature=config.temperature,
                    seed=config.seed,
                    runs_dir=runs_dir,
                )
            except ExtractionError as exc:
                stats["errors"].append(f"Extraction error: {exc}")
                continue
            session.commit()
            notes["extraction"]["returned"] += result.returned
            notes["extraction"]["accepted"] += result.accepted
            notes["extraction"]["rejected_unresolvable"] += result.rejected_unresolvable
            notes["extraction"]["parse_failures"] += result.parse_failures
            run = session.get(Run, run_id)
            run.notes = json.dumps(notes)
            session.commit()
            stats["candidates_accepted"] += result.accepted
            prepared = [(candidate, None) for candidate in result.candidates]
        else:
            stats["errors"].append(f"Unknown candidate source: {candidate_source}")
            continue

        stats["candidates_total"] += len(prepared)
        for candidate, event_action in prepared:
            _process_candidate(
                session,
                run_id=run_id,
                project_id=project_id,
                meeting_ordinal=ordinal,
                candidate=candidate,
                event_action=event_action,
                mode=mode,
                embedder=embedder,
                classifier=classifier,
                client=client,
                config=config,
                runs_dir=runs_dir,
                seq=seq,
                stats=stats,
            )

    session.close()
    engine.dispose()
    return stats


def main() -> None:
    parser = argparse.ArgumentParser(description="Run the pipeline in evaluation mode.")
    parser.add_argument("--scenario", type=str, required=True)
    parser.add_argument("--mode", type=str, choices=["demo", "eval"], required=True)
    parser.add_argument(
        "--candidate-source",
        type=str,
        choices=["gold", "extracted"],
        required=True,
    )
    parser.add_argument("--repeat", type=int, choices=[1, 2, 3], required=True)
    parser.add_argument("--db", type=str, default="sqlite:///pipeline.db")
    args = parser.parse_args()

    load_dotenv()
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
    print(f"  Downgrades: {stats['downgrades']}")
    print(f"  Classify errors: {stats['classify_errors']}")
    if stats["errors"]:
        print(f"\nErrors ({len(stats['errors'])}):")
        for error in stats["errors"][:10]:
            print(f"  - {error}")
        if len(stats["errors"]) > 10:
            print(f"  ... and {len(stats['errors']) - 10} more")


if __name__ == "__main__":
    main()
