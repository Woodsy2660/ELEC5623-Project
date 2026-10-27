"""Scoring module for E2, E3, E5 and related metrics.

This is the only module permitted to read gold_events.
"""

import argparse
import hashlib
import json
from pathlib import Path
from typing import Any, Literal

import yaml
from pydantic import BaseModel, ConfigDict, Field, model_validator
from sqlalchemy.orm import sessionmaker

from src.eval.metrics import (
    DRIVING_LABELS,
    NULL_RESULT_PROTOCOL,
    SIX_LABELS,
    _relation_pairs,
    align_by_span,
    e8_from_calls,
    extraction_report,
    false_supersession,
    historical_id_accuracy,
    illegal_transition_rate,
    invented_id_rate,
    joint_accuracy,
    map_created_ids,
    no_match_rates,
    register_accuracy,
    relation_report,
    retrieval_recall,
)
from src.eval.retrieval_schemas import RetrievalObservation
from src.persist.database import create_database_engine
from src.persist.models import (
    Candidate,
    Event,
    Meeting,
    ModelCall,
    Proposal,
    Requirement,
    RequirementVersion,
    Run,
)


class RetrievalGoldCase(BaseModel):
    """Dev match label; never supplied to a retrieval or embedding call."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    case_id: str = Field(min_length=1)
    expected_requirement_id: str | None = Field(..., min_length=1)


class RetrievalGold(BaseModel):
    """Only this scoring module opens retrieval labels."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    schema_version: Literal[1] = 1
    split: Literal["dev"]
    cases: tuple[RetrievalGoldCase, ...] = Field(min_length=1)

    @model_validator(mode="after")
    def unique_cases(self) -> "RetrievalGold":
        ids = [case.case_id for case in self.cases]
        if len(ids) != len(set(ids)):
            raise ValueError("Duplicate gold case ID")
        return self


def score_retrieval(
    observations: tuple[RetrievalObservation, ...],
    gold_path: Path,
) -> dict[str, object]:
    """E3 recall@3/5/8. Failed/missing matchable cases stay in the denominator."""
    if any("holdout" in part.casefold() for part in gold_path.resolve().parts):
        raise ValueError("This development scorer does not open holdout files")
    gold_bytes = gold_path.read_bytes()
    gold = RetrievalGold.model_validate_json(gold_bytes)
    observed = {item.case_id: item for item in observations}
    if len(observed) != len(observations):
        raise ValueError("Duplicate observed case ID")
    unknown = set(observed) - {case.case_id for case in gold.cases}
    if unknown:
        raise ValueError(f"Observed cases missing from gold: {sorted(unknown)}")
    channels = ("bm25", "dense", "fused")
    cutoffs = (3, 5, 8)
    counts = {channel: {str(k): 0 for k in cutoffs} for channel in channels}
    matchable = sum(case.expected_requirement_id is not None for case in gold.cases)
    errors = 0
    valid = 0
    cases = []
    for case in gold.cases:
        item = observed.get(case.case_id)
        error = "missing output" if item is None else item.error
        if item is not None and item.result is not None:
            rankings = {
                "bm25": item.result.bm25_family_ids,
                "dense": item.result.dense_family_ids,
                "fused": item.result.fused_family_ids,
            }
            if any(len(ids) != len(set(ids)) for ids in rankings.values()):
                error = "invalid output: duplicate ranked family ID"
            elif any(set(ids) != set(rankings["fused"]) for ids in rankings.values()):
                error = "invalid output: channel family sets disagree"
        else:
            rankings = {channel: () for channel in channels}
        if error is not None:
            errors += 1
        else:
            valid += 1
        ranks = {}
        for channel, ids in rankings.items():
            rank = (
                ids.index(case.expected_requirement_id) + 1
                if error is None and case.expected_requirement_id in ids
                else None
            )
            ranks[channel] = rank
            if case.expected_requirement_id is not None:
                for k in cutoffs:
                    counts[channel][str(k)] += int(rank is not None and rank <= k)
        cases.append(
            {
                "case_id": case.case_id,
                "expected_requirement_id": case.expected_requirement_id,
                "ranks": ranks,
                "error": error,
            }
        )
    return {
        "kind": "dev-retrieval-only",
        "gold_sha256": hashlib.sha256(gold_bytes).hexdigest(),
        "total_cases": len(gold.cases),
        "matchable_cases": matchable,
        "no_match_cases": len(gold.cases) - matchable,
        "valid_outputs": valid,
        "error_or_missing_outputs": errors,
        "coverage": valid / len(gold.cases),
        "recall_at_k": {
            channel: {k: hits / matchable if matchable else None for k, hits in values.items()}
            for channel, values in counts.items()
        },
        "no_match_accuracy": None,
        "notes": "No-match accuracy requires a classifier. No-match cases are not recall successes.",
        "cases": cases,
    }


def _read_observations(items: list[dict[str, object]]) -> tuple[RetrievalObservation, ...]:
    """Malformed outputs with a known case ID become explicit failures, not repairs."""
    observations = []
    for item in items:
        case_id = item.get("case_id")
        if not isinstance(case_id, str) or not case_id:
            raise ValueError("Cannot associate an output without a valid case ID")
        try:
            observations.append(RetrievalObservation.model_validate(item))
        except ValueError as exc:
            observations.append(
                RetrievalObservation(case_id=case_id, error=f"invalid output: {exc}")
            )
    return tuple(observations)


def _load_scenario_gold(scenario_dir: Path) -> list[dict[str, Any]]:
    """Open gold.yaml. This is the only scoring entry that reads relation labels."""
    gold_path = scenario_dir / "gold.yaml"
    if any("holdout" in part.casefold() for part in gold_path.resolve().parts):
        raise ValueError("This development scorer does not open holdout files")
    data = yaml.safe_load(gold_path.read_text(encoding="utf-8")) or {}
    events = list(data.get("events") or [])
    return sorted(
        events, key=lambda event: (event.get("meeting_ordinal", 0), event.get("event_index", 0))
    )


def _prediction_records(
    session, run_id: str
) -> tuple[list[dict[str, Any]], list[dict[str, Any]], dict[int, dict[str, dict[str, Any]]]]:
    proposals = session.query(Proposal).filter(Proposal.run_id == run_id).all()
    candidate_ids = [row.candidate_id for row in proposals]
    candidates = (
        {
            row.id: row
            for row in session.query(Candidate).filter(Candidate.id.in_(candidate_ids)).all()
        }
        if candidate_ids
        else {}
    )
    meetings = {row.id: row for row in session.query(Meeting).all()}
    events = session.query(Event).filter(Event.run_id == run_id).order_by(Event.ts).all()
    created_by_candidate: dict[str, str] = {}
    event_rows = []
    version_events: dict[str, dict[str, Any]] = {}
    for event in events:
        payload = json.loads(event.payload_json) if event.payload_json else {}
        event_rows.append(
            {
                "event_type": event.event_type,
                "requirement_id": payload.get("requirement_id"),
                "seq": payload.get("seq"),
                "ts": event.ts.isoformat() if event.ts else "",
                "meeting_ordinal": payload.get("meeting_ordinal"),
            }
        )
        if (
            event.event_type == "create"
            and payload.get("candidate_id")
            and payload.get("requirement_id")
        ):
            created_by_candidate.setdefault(payload["candidate_id"], payload["requirement_id"])
        version_events[event.id] = payload
    predictions = []
    for proposal in proposals:
        candidate = candidates.get(proposal.candidate_id)
        evidence = (
            json.loads(candidate.evidence_json) if candidate and candidate.evidence_json else []
        )
        rankings = json.loads(proposal.rankings_json) if proposal.rankings_json else {}
        meeting = meetings.get(candidate.meeting_id) if candidate else None
        predictions.append(
            {
                "candidate_id": proposal.candidate_id,
                "evidence": evidence,
                "predicted_id": proposal.predicted_id,
                "predicted_relation": proposal.predicted_relation,
                "rankings": rankings,
                "decision": proposal.decision,
                "engine_verdict": proposal.engine_verdict,
                "downgraded": bool(proposal.downgraded),
                "created_requirement_id": created_by_candidate.get(proposal.candidate_id),
                "meeting_ordinal": meeting.ordinal if meeting else None,
                "aligned_relation": None,
            }
        )
    versions = (
        session.query(RequirementVersion)
        .join(Requirement, Requirement.id == RequirementVersion.requirement_id)
        .all()
    )
    ordinals = sorted(
        {
            row["meeting_ordinal"]
            for row in event_rows
            if isinstance(row.get("meeting_ordinal"), int)
        }
    )
    actual_at: dict[int, dict[str, dict[str, Any]]] = {}
    for ordinal in ordinals:
        chosen: dict[str, dict[str, Any]] = {}
        for version in versions:
            payload = version_events.get(version.created_event_id) or {}
            version_ordinal = payload.get("meeting_ordinal")
            if not isinstance(version_ordinal, int) or version_ordinal > ordinal:
                continue
            current = chosen.get(version.requirement_id)
            if current is None or version.version >= current["version"]:
                chosen[version.requirement_id] = {
                    "state": version.state,
                    "version": version.version,
                }
        actual_at[ordinal] = chosen
    return predictions, event_rows, actual_at


def score_run(
    run_id: str,
    *,
    db_url: str = "sqlite:///pipeline.db",
    scenario_dir: Path | None = None,
) -> dict[str, Any]:
    """Score one finished run. Labels are read here and nowhere in the pipeline."""
    engine = create_database_engine(db_url)
    session = sessionmaker(bind=engine)()
    try:
        run = session.get(Run, run_id)
        if run is None:
            raise ValueError(f"Run not found: {run_id}")
        notes = json.loads(run.notes) if run.notes else {}
        candidate_source = run.candidate_source
        repeat_index = run.repeat_index
        if scenario_dir is None:
            scenario_note = notes.get("scenario")
            if not scenario_note:
                raise ValueError("Pass --scenario; this run row does not record one")
            scenario_dir = Path(str(scenario_note))
        gold_events = _load_scenario_gold(scenario_dir)
        predictions, event_rows, actual_at = _prediction_records(session, run_id)
        calls = [
            {
                "stage": row.stage,
                "input_tokens": row.input_tokens,
                "output_tokens": row.output_tokens,
                "retries": row.retries,
                "cost": row.cost,
                "latency_ms": row.latency_ms,
            }
            for row in session.query(ModelCall).filter(ModelCall.run_id == run_id).all()
        ]
    finally:
        session.close()
        engine.dispose()

    aligned, spurious = align_by_span(gold_events, predictions)
    for gold, prediction in aligned:
        if prediction is not None:
            prediction["aligned_relation"] = gold.get("relation")
    mapping = map_created_ids(aligned)
    pairs = _relation_pairs(aligned, spurious)
    column = {"gold": "oracle", "extracted": "pipeline"}.get(candidate_source, candidate_source)
    split = notes.get("split") or ("dev" if "dev" in scenario_dir.parts else "unspecified")
    e3 = {
        "column": column,
        "retrieval_recall": retrieval_recall(aligned, mapping),
        "historical_id_accuracy": historical_id_accuracy(aligned, mapping),
        "no_match": no_match_rates(aligned, predictions),
        "relation_four_class": relation_report(pairs, DRIVING_LABELS),
        "relation_six_class": relation_report(pairs, SIX_LABELS),
        "joint_correct_id_and_label": joint_accuracy(aligned, mapping),
        "id_map_gold_to_system": mapping,
    }
    report = {
        "split": split,
        "run_id": run_id,
        "system": notes.get("system", "pipeline"),
        "candidate_source": candidate_source,
        "column": column,
        "repeat_index": repeat_index,
        "headline": "four-class macro-F1 over new, refinement, contradiction, supersession",
        "four_class_macro_f1": e3["relation_four_class"]["macro_f1"],
        "four_class_support": {
            label: e3["relation_four_class"]["per_class"][label]["support"]
            for label in DRIVING_LABELS
        },
        "four_class_excluded_zero_support": e3["relation_four_class"]["excluded_zero_support"],
        "six_class_macro_f1": e3["relation_six_class"]["macro_f1"],
        "e2": extraction_report(aligned, spurious, notes.get("extraction"))
        if candidate_source == "extracted"
        else {"skipped": "E2 is scored on extracted runs only"},
        "e3": e3,
        "e4_illegal_transition_rate": illegal_transition_rate(event_rows),
        "e5": {
            **register_accuracy(gold_events, actual_at, mapping),
            "false_supersession": false_supersession(aligned),
        },
        "e8": e8_from_calls(calls),
        "invented_id_rate": invented_id_rate(predictions),
        "coverage": {
            "gold_events": len(gold_events),
            "predictions": len(predictions),
            "aligned": sum(prediction is not None for _, prediction in aligned),
            "classify_errors": sum(
                item.get("predicted_relation") == "error" for item in predictions
            ),
        },
        "null_result_protocol": NULL_RESULT_PROTOCOL,
        "notes": (
            "Dev-split figures. Per-class support is beside every F1. "
            "Zero-support classes are excluded from the macro mean and named. "
            "D1 has no expected_state_after column; E5 replays gold relations through the engine. "
            "Meeting 2 of D1 does not supersede R01."
        ),
    }
    return report


def _print_summary(report: dict[str, Any]) -> None:
    four = report["e3"]["relation_four_class"]
    print(f"Split: {report['split']}. System: {report['system']}. Column: {report['column']}.")
    print(f"Run: {report['run_id']}")
    print(f"Headline four-class macro-F1: {report['four_class_macro_f1']}")
    for label, scores in four["per_class"].items():
        print(f"  {label}: F1={scores['f1']} support={scores['support']}")
    if four["excluded_zero_support"]:
        print(f"  Excluded from the mean (support 0): {', '.join(four['excluded_zero_support'])}")
    print(f"Six-class macro-F1: {report['six_class_macro_f1']}")
    recall = report["e3"]["retrieval_recall"]
    print(f"Retrieval recall support={recall['support']}")
    for channel, values in recall["recall_at_k"].items():
        print(f"  {channel}: {values}")
    print(f"Historical-id accuracy: {report['e3']['historical_id_accuracy']}")
    print(f"No-match: {report['e3']['no_match']}")
    print(f"Joint id and label: {report['e3']['joint_correct_id_and_label']}")
    print(
        f"E4 illegal-transition rate: {report['e4_illegal_transition_rate']['rate']} "
        f"({report['e4_illegal_transition_rate']['illegal']}/{report['e4_illegal_transition_rate']['events']})"
    )
    e5 = report["e5"]
    for ordinal, meeting in e5["per_meeting"].items():
        print(f"E5 meeting {ordinal}: accuracy={meeting['accuracy']} support={meeting['support']}")
    print(
        f"E5 reversal final-state accuracy: {e5['reversal_final_state_accuracy']} "
        f"support={e5['reversal_support']}"
    )
    print(f"False supersession: {e5['false_supersession']}")
    print(f"Invented-id rate: {report['invented_id_rate']}")
    print(f"E8 calls: {report['e8']['calls']} cost={report['e8']['cost']}")
    print(report["null_result_protocol"])


def main() -> None:
    parser = argparse.ArgumentParser(description="Score a completed run against gold data.")
    source = parser.add_mutually_exclusive_group(required=True)
    source.add_argument(
        "--run",
        type=str,
        help="Run ID to score",
    )
    source.add_argument("--rankings", type=Path, help="Retrieval-only rankings.json")
    parser.add_argument("--gold", type=Path, help="Dev-only retrieval match labels")
    parser.add_argument(
        "--scenario", type=Path, help="Scenario directory; gold.yaml is read only here"
    )
    parser.add_argument("--db", type=str, default="sqlite:///pipeline.db")
    parser.add_argument("--output", type=Path, help="Optional metrics JSON output")
    args = parser.parse_args()
    if args.rankings is not None:
        if args.gold is None:
            parser.error("--rankings requires --gold")
        report = json.loads(args.rankings.read_text())
        if report.get("kind") != "dev-retrieval-only" or report.get("split") != "dev":
            parser.error("Expected dev-retrieval-only rankings")
        observations = _read_observations(report["observations"])
        metrics = score_retrieval(observations, args.gold)
        metrics["run_id"] = report["run_id"]
        metrics["repeat_index"] = report["repeat_index"]
        metrics["inputs_sha256"] = report["inputs_sha256"]
        text = json.dumps(metrics, indent=2)
        if args.output is not None:
            args.output.write_text(text)
        print(text)
    else:
        report = score_run(args.run, db_url=args.db, scenario_dir=args.scenario)
        text = json.dumps(report, indent=2)
        destination = Path("runs") / args.run / "score.json"
        destination.parent.mkdir(parents=True, exist_ok=True)
        destination.write_text(text, encoding="utf-8")
        if args.output is not None:
            args.output.write_text(text, encoding="utf-8")
        _print_summary(report)
        print(f"Wrote {destination.as_posix()}")


if __name__ == "__main__":
    main()
