"""FR04: Transcript ingest with stable turn identifiers.

This module loads scenarios and imports meetings into the database.
Ingest is idempotent: (project_id, source_hash) short-circuits re-import.

READ THE TEXT BYTE-FAITHFULLY. Do not strip, collapse whitespace, normalise
unicode, fold punctuation or alter the text in any way on import. That
normalisation happened exactly once, in normalise.py, when the authored draft
became the canonical file.
"""

import hashlib
import json
from datetime import UTC, datetime
from pathlib import Path

import yaml
from sqlalchemy.orm import Session

from src.persist.models import Meeting, Project, Speaker, Turn


class ScenarioError(Exception):
    """Raised when a scenario manifest is invalid."""

    pass


class MeetingError(Exception):
    """Raised when a meeting file is malformed."""

    pass


def load_scenario(session: Session, scenario_dir: Path) -> Project:
    """Load a scenario manifest and create the project with speakers.

    Args:
        session: Database session.
        scenario_dir: Path to scenario directory containing scenario.yaml.

    Returns:
        The created or existing Project.

    Raises:
        ScenarioError: If the manifest is invalid or a speaker is missing.
    """
    manifest_path = scenario_dir / "scenario.yaml"
    if not manifest_path.exists():
        raise ScenarioError(f"Scenario manifest not found: {manifest_path}")

    with open(manifest_path, encoding="utf-8") as f:
        manifest = yaml.safe_load(f)

    project_id = manifest.get("id")
    if not project_id:
        raise ScenarioError("Scenario manifest missing 'id' field")

    # Check if project already exists
    existing = session.get(Project, project_id)
    if existing is not None:
        return existing

    # Validate speakers
    speakers_data = manifest.get("speakers", [])
    if not speakers_data:
        raise ScenarioError("Scenario manifest missing 'speakers' field")

    # Create project
    project = Project(
        id=project_id,
        name=manifest.get("name", project_id),
        created_at=datetime.now(UTC),
    )
    session.add(project)

    # Create speakers
    for speaker_data in speakers_data:
        label = speaker_data.get("label")
        if not label:
            raise ScenarioError("Speaker missing 'label' field")

        role = speaker_data.get("role")
        if not role:
            raise ScenarioError(f"Speaker '{label}' missing 'role' field")

        can_confirm = speaker_data.get("can_confirm_scope")
        if can_confirm is None:
            raise ScenarioError(f"Speaker '{label}' missing 'can_confirm_scope' field")

        speaker = Speaker(
            project_id=project_id,
            speaker_label=label,
            role=role,
            can_confirm_scope=can_confirm,
        )
        session.add(speaker)

    session.flush()
    return project


def import_meeting(
    session: Session,
    project_id: str,
    canonical_path: Path,
    ordinal: int,
) -> Meeting:
    """Import a canonical JSONL meeting transcript.

    Args:
        session: Database session.
        project_id: The project to import into.
        canonical_path: Path to the canonical JSONL file.
        ordinal: Meeting ordinal number.

    Returns:
        The created or existing Meeting.

    Raises:
        MeetingError: If the file is malformed or validation fails.

    Note:
        If (project_id, source_hash) already exists, returns the existing Meeting
        and writes NOTHING. Re-import must be idempotent (E1).
    """
    if not canonical_path.exists():
        raise MeetingError(f"Canonical file not found: {canonical_path}")

    # Read file as bytes and compute hash
    file_bytes = canonical_path.read_bytes()
    source_hash = hashlib.sha256(file_bytes).hexdigest()

    # Check for existing meeting with same source hash
    existing = (
        session.query(Meeting)
        .filter(Meeting.project_id == project_id, Meeting.source_hash == source_hash)
        .first()
    )
    if existing is not None:
        return existing

    # Parse and validate JSONL
    content = file_bytes.decode("utf-8")
    lines = content.strip().split("\n")

    if not lines or not lines[0].strip():
        raise MeetingError(f"Empty canonical file: {canonical_path}")

    turns_data: list[dict] = []
    for line_num, line in enumerate(lines, start=1):
        if not line.strip():
            continue
        try:
            record = json.loads(line)
        except json.JSONDecodeError as e:
            raise MeetingError(f"Invalid JSON on line {line_num}: {e}") from e
        turns_data.append(record)

    # Validate turns
    _validate_turns(turns_data, project_id, canonical_path)

    # Get meeting_id from first turn
    if not turns_data:
        raise MeetingError(f"No turns in canonical file: {canonical_path}")

    first_turn_id = turns_data[0].get("turn_id", "")
    # Extract meeting_id from turn_id (format: "{meeting_id}:{turn_index:04d}")
    if ":" not in first_turn_id:
        raise MeetingError(f"Invalid turn_id format: {first_turn_id}")
    meeting_id = first_turn_id.rsplit(":", 1)[0]

    # Verify project_id is part of meeting_id
    if not meeting_id.startswith(project_id):
        raise MeetingError(
            f"Meeting ID '{meeting_id}' does not match project '{project_id}'"
        )

    # Check speaker labels exist in project
    project_speakers = {
        s.speaker_label
        for s in session.query(Speaker).filter(Speaker.project_id == project_id)
    }

    for record in turns_data:
        speaker = record.get("speaker")
        if speaker not in project_speakers:
            raise MeetingError(
                f"Unknown speaker '{speaker}' in meeting. "
                f"Valid speakers: {sorted(project_speakers)}"
            )

    # Create meeting
    meeting = Meeting(
        id=meeting_id,
        project_id=project_id,
        ordinal=ordinal,
        source_hash=source_hash,
        imported_at=datetime.now(UTC),
    )
    session.add(meeting)

    # Create turns - NO TEXT TRANSFORMATION
    for record in turns_data:
        turn = Turn(
            id=record["turn_id"],
            meeting_id=meeting_id,
            turn_index=record["turn_index"],
            speaker=record["speaker"],
            text=record["text"],  # Byte-faithful, no normalisation
        )
        session.add(turn)

    session.flush()
    return meeting


def _validate_turns(turns_data: list[dict], project_id: str, path: Path) -> None:
    """Validate turn records from a canonical file.

    Raises:
        MeetingError: If validation fails.
    """
    if not turns_data:
        raise MeetingError(f"No turns in canonical file: {path}")

    required_keys = {"turn_index", "turn_id", "speaker", "text"}

    for idx, record in enumerate(turns_data):
        # Check required keys
        missing = required_keys - record.keys()
        if missing:
            raise MeetingError(
                f"Turn {idx} missing required keys: {sorted(missing)} in {path}"
            )

        # Validate turn_index is contiguous from 0
        expected_index = idx
        actual_index = record.get("turn_index")
        if actual_index != expected_index:
            raise MeetingError(
                f"Non-contiguous turn_index: expected {expected_index}, "
                f"got {actual_index} in {path}"
            )

        # Validate turn_id format
        turn_id = record.get("turn_id", "")
        if ":" not in turn_id:
            raise MeetingError(f"Invalid turn_id format (no colon): {turn_id}")

        meeting_part, index_part = turn_id.rsplit(":", 1)
        try:
            parsed_index = int(index_part)
        except ValueError as e:
            raise MeetingError(f"Invalid turn_id index part: {turn_id}") from e

        if parsed_index != expected_index:
            raise MeetingError(
                f"turn_id index mismatch: turn_id says {parsed_index}, "
                f"but turn_index is {expected_index}"
            )

        # Validate turn_id format matches expected pattern
        expected_turn_id = f"{meeting_part}:{expected_index:04d}"
        if turn_id != expected_turn_id:
            raise MeetingError(
                f"turn_id format error: expected {expected_turn_id}, got {turn_id}"
            )


def load_scenario_meetings(session: Session, scenario_dir: Path) -> list[Meeting]:
    """Load a scenario and all its meetings.

    Args:
        session: Database session.
        scenario_dir: Path to scenario directory.

    Returns:
        List of imported meetings.
    """
    # Load scenario manifest
    manifest_path = scenario_dir / "scenario.yaml"
    with open(manifest_path, encoding="utf-8") as f:
        manifest = yaml.safe_load(f)

    project = load_scenario(session, scenario_dir)

    meetings = []
    for meeting_info in manifest.get("meetings", []):
        ordinal = meeting_info["ordinal"]
        canonical_rel = meeting_info["canonical"]
        canonical_path = scenario_dir / canonical_rel

        meeting = import_meeting(session, project.id, canonical_path, ordinal)
        meetings.append(meeting)

    return meetings
