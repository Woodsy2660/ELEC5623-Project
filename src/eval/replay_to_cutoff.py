"""Rebuild expected vs actual state from events up to a meeting cutoff.

This tool:
1. Loads run's events up to and including the cutoff meeting
2. Replays them in chronological order to produce actual state map
3. Computes expected state from gold.yaml up to the same meeting
4. Prints a diff: which requirement states differ
"""

import argparse
import json
from collections import defaultdict
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import yaml
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from src.engine.state_machine import EventType, State, validate_transition
from src.persist.models import (
    Base,
    Event,
    Meeting,
    Requirement,
    RequirementCurrent,
    RequirementVersion,
    Run,
)


@dataclass
class RequirementState:
    """State of a requirement at a point in time."""

    requirement_id: str
    state: State
    version: int
    text: str | None = None


def _load_gold_events(scenario_dir: Path) -> list[dict[str, Any]]:
    """Load gold events from gold.yaml."""
    gold_path = scenario_dir / "gold.yaml"
    if not gold_path.exists():
        return []
    with open(gold_path, encoding="utf-8") as f:
        data = yaml.safe_load(f)
    return data.get("events", [])


def _compute_gold_expected_state(
    gold_events: list[dict[str, Any]],
    after_meeting: int,
) -> dict[str, RequirementState]:
    """Compute expected state from gold events up to a meeting ordinal.

    For each requirement, track:
    - State: proposed -> confirmed (after NEW + CONFIRM)
    - Version: increments with refinements
    - Supersession: old req becomes superseded, new version created

    Gold events use relations: new, refinement, supersession, contradiction, restatement
    """
    # Track state for each requirement
    state_map: dict[str, RequirementState] = {}
    version_counters: dict[str, int] = defaultdict(int)

    for event in gold_events:
        meeting_ordinal = event.get("meeting_ordinal", 0)
        if meeting_ordinal > after_meeting:
            break

        req_id = event.get("requirement_id")
        relation = event.get("relation", "new")
        evidence = event.get("evidence", [])
        text = evidence[0].get("quote", "") if evidence else ""

        if relation == "new":
            # New requirement: starts as confirmed in eval mode
            version_counters[req_id] = 1
            state_map[req_id] = RequirementState(
                requirement_id=req_id,
                state=State.CONFIRMED,
                version=1,
                text=text,
            )
        elif relation == "refinement":
            # Refinement: increment version, stays confirmed
            version_counters[req_id] += 1
            if req_id in state_map:
                state_map[req_id] = RequirementState(
                    requirement_id=req_id,
                    state=State.CONFIRMED,
                    version=version_counters[req_id],
                    text=text,
                )
        elif relation == "supersession":
            # Supersession: old req becomes superseded
            if req_id in state_map:
                state_map[req_id] = RequirementState(
                    requirement_id=req_id,
                    state=State.SUPERSEDED,
                    version=state_map[req_id].version + 1,
                    text=text,
                )
        elif relation == "contradiction":
            # Contradiction: req becomes contradicted
            if req_id in state_map:
                state_map[req_id] = RequirementState(
                    requirement_id=req_id,
                    state=State.CONTRADICTED,
                    version=state_map[req_id].version + 1,
                    text=text,
                )

    return state_map


def _compute_actual_state(
    session,
    run_id: str,
    project_id: str,
    after_meeting: int,
) -> dict[str, RequirementState]:
    """Compute actual state from DB events up to a meeting ordinal."""
    # Get meeting IDs up to and including after_meeting
    meetings = (
        session.query(Meeting)
        .filter(
            Meeting.project_id == project_id,
            Meeting.ordinal <= after_meeting,
        )
        .all()
    )
    meeting_ids = {m.id for m in meetings}

    # Get events for this run
    events = (
        session.query(Event)
        .filter(
            Event.run_id == run_id,
            Event.project_id == project_id,
        )
        .order_by(Event.ts)
        .all()
    )

    # Build state from events
    state_map: dict[str, RequirementState] = {}
    version_counters: dict[str, int] = defaultdict(int)

    for event in events:
        payload = json.loads(event.payload_json) if event.payload_json else {}
        req_id = payload.get("requirement_id")

        # Track C review events carry the actual meeting ID and immutable version
        # number. Do not infer a cutoff from a display-name suffix.
        if "meeting_id" in payload and payload["meeting_id"] not in meeting_ids:
            continue

        # Check if this event's evidence is from meetings we're considering
        evidence = payload.get("evidence", [])
        if evidence:
            turn_id = evidence[0].get("turn_id", "")
            # Parse meeting ID from turn_id (format: D1-M01:0001)
            # The meeting_id format is like "D1-M01"
            if ":" in turn_id:
                turn_meeting_part = turn_id.split(":")[0]  # e.g., "D1-M01"
                # Extract meeting ordinal from turn_meeting_part (last 2 digits)
                try:
                    turn_meeting_ordinal = int(turn_meeting_part[-2:])
                    if turn_meeting_ordinal > after_meeting:
                        continue
                except (ValueError, IndexError):
                    # Can't parse - check by meeting_id directly
                    if turn_meeting_part not in meeting_ids:
                        continue

        if not req_id:
            continue

        event_type = event.event_type
        text = payload.get("text", "")

        if "version" in payload:
            previous = state_map.get(req_id)
            from_state = previous.state if previous else None
            state = validate_transition(from_state, EventType(event_type))
            number = (previous.version if previous else 0) + 1
            if (
                state is None
                or payload["version"] != number
                or payload.get("from_state") != (from_state.value if from_state else None)
                or payload.get("to_state") != state.value
            ):
                raise ValueError(f"Invalid lifecycle snapshot in event {event.id}")
            state_map[req_id] = RequirementState(req_id, state, number, text)
            version_counters[req_id] = number
            continue

        if event_type == "create":
            version_counters[req_id] = 1
            state_map[req_id] = RequirementState(
                requirement_id=req_id,
                state=State.PROPOSED,
                version=1,
                text=text,
            )
        elif event_type == "confirm":
            if req_id in state_map:
                state_map[req_id] = RequirementState(
                    requirement_id=req_id,
                    state=State.CONFIRMED,
                    version=state_map[req_id].version,
                    text=text or state_map[req_id].text,
                )
        elif event_type == "refine":
            version_counters[req_id] += 1
            if req_id in state_map:
                state_map[req_id] = RequirementState(
                    requirement_id=req_id,
                    state=State.CONFIRMED,
                    version=version_counters[req_id],
                    text=text,
                )
        elif event_type == "supersede":
            if req_id in state_map:
                state_map[req_id] = RequirementState(
                    requirement_id=req_id,
                    state=State.SUPERSEDED,
                    version=state_map[req_id].version + 1,
                    text=text,
                )
        elif event_type == "contradict":
            if req_id in state_map:
                state_map[req_id] = RequirementState(
                    requirement_id=req_id,
                    state=State.CONTRADICTED,
                    version=state_map[req_id].version + 1,
                    text=text,
                )

    return state_map


def _load_current_state_from_db(
    session,
    project_id: str,
) -> dict[str, RequirementState]:
    """Load current state directly from RequirementCurrent table."""
    currents = (
        session.query(RequirementCurrent)
        .join(Requirement, RequirementCurrent.requirement_id == Requirement.id)
        .filter(Requirement.project_id == project_id)
        .all()
    )

    state_map: dict[str, RequirementState] = {}
    for current in currents:
        # Get version number from the version table
        version = session.get(RequirementVersion, current.current_version_id)
        version_num = version.version if version else 0

        state_map[current.requirement_id] = RequirementState(
            requirement_id=current.requirement_id,
            state=State(current.state),
            version=version_num,
            text=current.text,
        )

    return state_map


def compare_states(
    expected: dict[str, RequirementState],
    actual: dict[str, RequirementState],
) -> list[str]:
    """Compare expected vs actual states and return diff lines."""
    diffs = []

    # All requirement IDs
    all_ids = sorted(set(expected.keys()) | set(actual.keys()))

    for req_id in all_ids:
        exp = expected.get(req_id)
        act = actual.get(req_id)

        if exp is None:
            diffs.append(f"+ {req_id}: unexpected (actual: {act.state.value})")
        elif act is None:
            diffs.append(f"- {req_id}: missing (expected: {exp.state.value})")
        elif exp.state != act.state:
            diffs.append(
                f"! {req_id}: state mismatch "
                f"(expected: {exp.state.value}, actual: {act.state.value})"
            )
        elif exp.version != act.version:
            diffs.append(
                f"~ {req_id}: version mismatch "
                f"(expected: v{exp.version}, actual: v{act.version})"
            )

    return diffs


def replay_to_cutoff(
    run_id: str,
    after_meeting: int,
    scenario_dir: Path,
    db_url: str = "sqlite:///pipeline.db",
) -> dict[str, Any]:
    """Replay events to cutoff and compare with gold.

    Args:
        run_id: The run ID to analyze.
        after_meeting: Meeting ordinal to cutoff at.
        scenario_dir: Path to scenario directory.
        db_url: Database URL.

    Returns:
        Summary dict with expected, actual, and diffs.
    """
    # Create database session
    engine = create_engine(db_url)
    Base.metadata.create_all(engine)
    SessionLocal = sessionmaker(bind=engine)
    session = SessionLocal()

    # Load run
    run = session.get(Run, run_id)
    if run is None:
        session.close()
        raise ValueError(f"Run not found: {run_id}")

    # Get project ID from first event
    first_event = session.query(Event).filter(Event.run_id == run_id).order_by(Event.ts).first()
    if first_event is None:
        session.close()
        raise ValueError(f"No events found for run: {run_id}")

    project_id = first_event.project_id

    # Load gold events
    gold_events = _load_gold_events(scenario_dir)

    # Compute expected state from gold
    expected = _compute_gold_expected_state(gold_events, after_meeting)

    # Compute actual state from DB
    actual = _compute_actual_state(session, run_id, project_id, after_meeting)

    # Alternative: load current state directly
    db_current = _load_current_state_from_db(session, project_id)

    # Compare
    diffs = compare_states(expected, actual)
    db_diffs = compare_states(expected, db_current)

    session.close()

    return {
        "run_id": run_id,
        "after_meeting": after_meeting,
        "expected": {k: v.state.value for k, v in expected.items()},
        "actual_replayed": {k: v.state.value for k, v in actual.items()},
        "actual_db": {k: v.state.value for k, v in db_current.items()},
        "diffs_replayed": diffs,
        "diffs_db": db_diffs,
    }


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Replay events to rebuild state after a specific meeting."
    )
    parser.add_argument(
        "--run",
        type=str,
        required=True,
        help="Run ID to analyze",
    )
    parser.add_argument(
        "--after-meeting",
        type=int,
        required=True,
        help="Meeting ordinal after which to compare state (e.g., 1, 2, 3)",
    )
    parser.add_argument(
        "--scenario",
        type=str,
        required=True,
        help="Path to scenario directory (for gold.yaml)",
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

    print("Replaying events:")
    print(f"  Run ID: {args.run}")
    print(f"  After meeting: {args.after_meeting}")
    print(f"  Scenario: {scenario_dir}")
    print()

    try:
        result = replay_to_cutoff(
            run_id=args.run,
            after_meeting=args.after_meeting,
            scenario_dir=scenario_dir,
            db_url=args.db,
        )
    except ValueError as e:
        print(f"Error: {e}")
        return

    print("Expected state (from gold):")
    for req_id, state in sorted(result["expected"].items()):
        print(f"  {req_id}: {state}")
    print()

    print("Actual state (replayed to cutoff):")
    for req_id, state in sorted(result["actual_replayed"].items()):
        print(f"  {req_id}: {state}")
    print()

    if result["diffs_replayed"]:
        print(f"Differences ({len(result['diffs_replayed'])}):")
        for diff in result["diffs_replayed"]:
            print(f"  {diff}")
    else:
        print("No differences - states match!")


if __name__ == "__main__":
    main()
