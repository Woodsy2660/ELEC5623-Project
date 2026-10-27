"""Baseline: one prompt, the full register, no retrieval and no transition check.

Same ingest, store, logger, model settings and eval confirm policy as the pipeline.
The two differences are the missing retriever and ``enforce=False`` on the write.
Do not filter its proposals through the rule table.
"""

import argparse
import hashlib
import json
import os
from datetime import UTC, datetime
from pathlib import Path
from uuid import uuid4

import yaml
from openai import AzureOpenAI
from pydantic import BaseModel, ConfigDict, Field, ValidationError
from sqlalchemy.orm import sessionmaker

from src.engine.state_machine import EventType, State
from src.eval.gold_candidates import decision_action
from src.eval.run_pipeline import load_dotenv
from src.extract.schemas import Candidate
from src.ingest import import_meeting, load_scenario
from src.llm.config import get_deployment_config
from src.logging.calls import CallLogger, ModelCallError
from src.persist.database import create_database_engine
from src.persist.models import (
    Base,
    Proposal,
    Requirement,
    RequirementCurrent,
    RequirementVersion,
    Run,
    Speaker,
    Turn,
)
from src.persist.models import (
    Candidate as CandidateRow,
)
from src.persist.register import confirm_current, next_requirement_id, write_version
from src.validate.resolve import QuoteAmbiguous, QuoteNotFound, resolve_quote
from src.validate.schemas import EvidenceSpan

PROMPT_PATH = Path(__file__).resolve().parents[2] / "prompts" / "baseline_v1.txt"

_WRITE = {
    "new": (EventType.CREATE, State.PROPOSED),
    "refinement": (EventType.REFINE, State.CONFIRMED),
    "contradiction": (EventType.CONTRADICT, State.CONTRADICTED),
    "supersession": (EventType.SUPERSEDE, State.SUPERSEDED),
}


class _EvidenceItem(BaseModel):
    model_config = ConfigDict(extra="forbid")
    turn_id: str = Field(min_length=1)
    quote: str = Field(min_length=1)


class _Change(BaseModel):
    model_config = ConfigDict(extra="forbid")
    statement: str = Field(min_length=1)
    evidence: list[_EvidenceItem] = Field(min_length=1)
    requirement_id: str | None = None
    relation: str


class _BaselineResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")
    changes: list[_Change]


def _schema() -> dict:
    return {
        "type": "json_schema",
        "json_schema": {
            "name": "baseline_register_update",
            "strict": True,
            "schema": {
                "type": "object",
                "properties": {
                    "changes": {
                        "type": "array",
                        "items": {
                            "type": "object",
                            "properties": {
                                "statement": {"type": "string"},
                                "evidence": {
                                    "type": "array",
                                    "items": {
                                        "type": "object",
                                        "properties": {
                                            "turn_id": {"type": "string"},
                                            "quote": {"type": "string"},
                                        },
                                        "required": ["turn_id", "quote"],
                                        "additionalProperties": False,
                                    },
                                },
                                "requirement_id": {"type": ["string", "null"]},
                                "relation": {
                                    "type": "string",
                                    "enum": ["new", "refinement", "contradiction", "supersession"],
                                },
                            },
                            "required": ["statement", "evidence", "requirement_id", "relation"],
                            "additionalProperties": False,
                        },
                    }
                },
                "required": ["changes"],
                "additionalProperties": False,
            },
        },
    }


def _prompt_hash() -> str:
    content = PROMPT_PATH.read_bytes()
    return hashlib.sha1(f"blob {len(content)}\0".encode() + content).hexdigest()


def _register_payload(session, project_id: str) -> tuple[list[dict], str]:
    versions = (
        session.query(RequirementVersion)
        .join(Requirement)
        .filter(Requirement.project_id == project_id)
        .order_by(RequirementVersion.requirement_id, RequirementVersion.version)
        .all()
    )
    currents = {
        row.requirement_id: row
        for row in session.query(RequirementCurrent)
        .join(Requirement)
        .filter(Requirement.project_id == project_id)
        .all()
    }
    families: dict[str, list[dict]] = {}
    for version in versions:
        families.setdefault(version.requirement_id, []).append(
            {"version": version.version, "state": version.state, "text": version.text}
        )
    payload = []
    for requirement_id, history in families.items():
        current = currents.get(requirement_id)
        payload.append(
            {
                "requirement_id": requirement_id,
                "current_state": current.state if current else None,
                "current_text": current.text if current else None,
                "versions": history,
            }
        )
    return payload, next_requirement_id(session, project_id)


def _speakers(session, project_id: str) -> list[dict]:
    rows = session.query(Speaker).filter(Speaker.project_id == project_id).all()
    return [
        {
            "speaker_label": row.speaker_label,
            "role": row.role,
            "can_confirm_scope": bool(row.can_confirm_scope),
        }
        for row in rows
    ]


def _offered_ids(session, project_id: str) -> list[str]:
    rows = session.query(Requirement.id).filter(Requirement.project_id == project_id).all()
    return sorted(requirement_id for (requirement_id,) in rows)


def _resolve(
    change: _Change, turns: dict[str, str], meeting_id: str
) -> tuple[list[EvidenceSpan], str | None]:
    spans = []
    for item in change.evidence:
        text = turns.get(item.turn_id)
        if text is None or not item.turn_id.startswith(meeting_id):
            return [], f"unknown turn {item.turn_id}"
        try:
            start, end = resolve_quote(text, item.quote)
        except (QuoteNotFound, QuoteAmbiguous) as exc:
            return [], str(exc)
        spans.append(EvidenceSpan(turn_id=item.turn_id, start=start, end=end))
    return spans, None


def _add_proposal(session, **kwargs) -> None:
    session.add(Proposal(id=str(uuid4()), **kwargs))


def run_baseline(
    scenario_dir: Path,
    mode: str,
    repeat_index: int,
    db_url: str = "sqlite:///baseline.db",
    runs_dir: Path = Path("runs"),
    *,
    client=None,
    config=None,
    responder=None,
) -> dict:
    """Run the baseline. Schema-valid changes are written even when the transition is illegal."""
    engine = create_database_engine(db_url)
    Base.metadata.create_all(engine)
    session = sessionmaker(bind=engine)()
    if config is None and responder is None:
        config = get_deployment_config()
    if client is None and responder is None:
        client = AzureOpenAI(
            azure_endpoint=config.endpoint,
            api_key=config.api_key,
            api_version=config.api_version,
        )
    run_id = str(uuid4())
    try:
        scenario_note = scenario_dir.resolve().relative_to(Path.cwd().resolve()).as_posix()
    except ValueError:
        scenario_note = scenario_dir.as_posix()
    notes = {
        "scenario": scenario_note,
        "split": "dev" if "dev" in Path(scenario_note).parts else "unspecified",
        "system": "baseline",
        "extraction": {
            "returned": 0,
            "accepted": 0,
            "rejected_unresolvable": 0,
            "parse_failures": 0,
        },
    }
    session.add(
        Run(
            id=run_id,
            mode=mode,
            candidate_source="baseline",
            repeat_index=repeat_index,
            prompt_hash=_prompt_hash(),
            model_deployment=config.deployment_name if config else "none",
            temp=config.temperature if config else 0.0,
            started_at=datetime.now(UTC),
            notes=json.dumps(notes),
        )
    )
    session.commit()
    project = load_scenario(session, scenario_dir)
    session.commit()
    project_id = project.id
    with open(scenario_dir / "scenario.yaml", encoding="utf-8") as handle:
        manifest = yaml.safe_load(handle)
    gold_events = []
    gold_path = scenario_dir / "gold.yaml"
    if gold_path.exists():
        gold_events = (yaml.safe_load(gold_path.read_text(encoding="utf-8")) or {}).get(
            "events"
        ) or []
    logger = None
    if responder is None:
        logger = CallLogger(
            session,
            client,
            deployment_name=config.deployment_name,
            temperature=config.temperature,
            seed=config.seed,
            runs_dir=runs_dir,
        )
    stats = {
        "run_id": run_id,
        "meetings_processed": 0,
        "changes_accepted": 0,
        "events_applied": 0,
        "errors": [],
    }
    seq = {"n": 0}
    system_prompt = PROMPT_PATH.read_text(encoding="utf-8")
    for meeting_info in sorted(manifest.get("meetings", []), key=lambda item: item["ordinal"]):
        ordinal = meeting_info["ordinal"]
        meeting = import_meeting(
            session, project_id, scenario_dir / meeting_info["canonical"], ordinal
        )
        session.commit()
        meeting_id = meeting.id
        stats["meetings_processed"] += 1
        turns = (
            session.query(Turn)
            .filter(Turn.meeting_id == meeting_id)
            .order_by(Turn.turn_index)
            .all()
        )
        register, announced_next = _register_payload(session, project_id)
        user = {
            "project_id": project_id,
            "meeting_id": meeting_id,
            "next_requirement_id": announced_next,
            "speakers": _speakers(session, project_id),
            "register": register,
            "turns": [
                {"turn_id": turn.id, "speaker": turn.speaker, "text": turn.text} for turn in turns
            ],
        }
        messages = [
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": json.dumps(user, ensure_ascii=False)},
        ]
        parsed = None
        call_id = None
        last_error = "baseline response invalid"
        for attempt in range(2):
            try:
                if responder is None:
                    response = logger.call(
                        run_id=run_id,
                        stage="baseline",
                        prompt_path=PROMPT_PATH,
                        messages=messages,
                        response_format=_schema(),
                    )
                    content = response.content
                    call_id = response.call_id
                else:
                    content = responder(user)
            except ModelCallError as exc:
                last_error = str(exc)
                break
            try:
                parsed = _BaselineResponse.model_validate(json.loads(content))
                break
            except (json.JSONDecodeError, ValidationError) as exc:
                last_error = str(exc)
                parsed = None
                if attempt == 0 and responder is None:
                    continue
                break
        session.commit()
        if parsed is None:
            stats["errors"].append(f"meeting {ordinal}: {last_error}")
            notes["extraction"]["parse_failures"] += 1
            continue
        notes["extraction"]["returned"] += len(parsed.changes)
        turn_text = {turn.id: turn.text for turn in turns}
        actions = [
            decision_action(event)
            for event in gold_events
            if event.get("meeting_ordinal") == ordinal
        ]
        align_actions = len(actions) == len(parsed.changes)
        for index, change in enumerate(parsed.changes):
            spans, error = _resolve(change, turn_text, meeting_id)
            candidate_id = f"{meeting_id}-{run_id[:8]}-B{index:04d}"
            if error or not spans:
                notes["extraction"]["rejected_unresolvable"] += 1
                stats["errors"].append(f"{candidate_id}: {error or 'no evidence'}")
                continue
            if change.relation not in _WRITE:
                stats["errors"].append(
                    f"{candidate_id}: relation {change.relation} is not a driving label"
                )
                continue
            candidate = Candidate(
                candidate_id=candidate_id,
                project_id=project_id,
                meeting_id=meeting_id,
                text_norm=change.statement.strip(),
                evidence=spans,
            )
            session.add(
                CandidateRow(
                    id=candidate.candidate_id,
                    meeting_id=meeting_id,
                    run_id=run_id,
                    text_norm=candidate.text_norm,
                    evidence_json=json.dumps(
                        [
                            {"turn_id": span.turn_id, "start": span.start, "end": span.end}
                            for span in spans
                        ]
                    ),
                    extract_call_id=call_id,
                )
            )
            session.flush()
            offered = _offered_ids(session, project_id)
            action = actions[index] if align_actions else None
            decision = "pending"
            if mode == "eval":
                decision = "reject" if action == "reject" else "confirm"
            event_type, resulting = _WRITE[change.relation]
            rankings = {"bm25": [], "dense": [], "fused": [], "offered": offered, "error": None}
            if decision != "confirm":
                _add_proposal(
                    session,
                    run_id=run_id,
                    candidate_id=candidate_id,
                    retrieved_ids_json=json.dumps(offered),
                    predicted_id=change.requirement_id,
                    predicted_relation=change.relation,
                    proposed_event=event_type.value,
                    engine_verdict="unvalidated",
                    rankings_json=json.dumps(rankings),
                    decision=decision,
                    downgraded=False,
                )
                session.commit()
                continue
            requirement_id = change.requirement_id
            if change.relation == "new" and not requirement_id:
                requirement_id = next_requirement_id(session, project_id)
            if not requirement_id:
                rankings["error"] = "historical relation without an id"
                stats["errors"].append(f"{candidate_id}: historical relation without an id")
                _add_proposal(
                    session,
                    run_id=run_id,
                    candidate_id=candidate_id,
                    retrieved_ids_json=json.dumps(offered),
                    predicted_id=None,
                    predicted_relation=change.relation,
                    proposed_event=event_type.value,
                    engine_verdict="error",
                    rankings_json=json.dumps(rankings),
                    decision="error",
                    downgraded=False,
                )
                session.commit()
                continue
            seq["n"] += 1
            write_version(
                session,
                project_id=project_id,
                run_id=run_id,
                requirement_id=requirement_id,
                event_type=event_type,
                resulting_state=resulting,
                candidate=candidate,
                classification=None,
                meeting_ordinal=ordinal,
                seq=seq["n"],
                embedding=None,
                embedding_model=None,
                embedding_version=None,
                embedding_dim=None,
                actor="baseline",
                enforce=False,
            )
            stats["events_applied"] += 1
            if change.relation == "new":
                seq["n"] += 1
                confirm_current(
                    session,
                    project_id=project_id,
                    run_id=run_id,
                    requirement_id=requirement_id,
                    candidate=candidate,
                    classification=None,
                    meeting_ordinal=ordinal,
                    seq=seq["n"],
                    actor="baseline",
                    enforce=False,
                )
                stats["events_applied"] += 1
            _add_proposal(
                session,
                run_id=run_id,
                candidate_id=candidate_id,
                retrieved_ids_json=json.dumps(offered),
                predicted_id=None if change.relation == "new" else requirement_id,
                predicted_relation=change.relation,
                proposed_event=event_type.value,
                engine_verdict="unvalidated",
                rankings_json=json.dumps(rankings),
                decision=decision,
                downgraded=False,
            )
            notes["extraction"]["accepted"] += 1
            stats["changes_accepted"] += 1
            session.commit()
    run = session.get(Run, run_id)
    run.notes = json.dumps(notes)
    session.commit()
    session.close()
    engine.dispose()
    return stats


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Run the baseline system (no retrieval, no state engine)."
    )
    parser.add_argument("--scenario", type=str, required=True)
    parser.add_argument("--mode", type=str, choices=["demo", "eval"], required=True)
    parser.add_argument("--repeat", type=int, choices=[1, 2, 3], required=True)
    parser.add_argument("--db", type=str, default="sqlite:///baseline.db")
    args = parser.parse_args()
    load_dotenv()
    scenario_dir = Path(args.scenario)
    if not scenario_dir.exists():
        print(f"Error: Scenario directory not found: {scenario_dir}")
        return
    if not os.environ.get("AZURE_OPENAI_ENDPOINT") or not os.environ.get("AZURE_OPENAI_API_KEY"):
        print("Error: AZURE_OPENAI_ENDPOINT and AZURE_OPENAI_API_KEY are required")
        return
    stats = run_baseline(scenario_dir, args.mode, args.repeat, db_url=args.db)
    print(f"Run ID: {stats['run_id']}")
    print(f"Meetings: {stats['meetings_processed']}")
    print(f"Changes accepted: {stats['changes_accepted']}")
    print(f"Events applied: {stats['events_applied']}")
    for error in stats["errors"][:10]:
        print(f"  - {error}")


if __name__ == "__main__":
    main()
