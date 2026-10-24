"""Tests for transcript ingest (FR04).

These tests verify:
- importing D1-M01 twice produces one meeting and 19 turns, not two or 38
- a JSONL file with a gap in turn_index is rejected and writes nothing
- a scenario.yaml with a speaker missing from the manifest is rejected
- cross-project query attempts return nothing

No network, no API key. These run in CI.
"""

import json
import tempfile
from pathlib import Path

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import Session

from src.ingest.loader import (
    MeetingError,
    ScenarioError,
    import_meeting,
    load_scenario,
    load_scenario_meetings,
)
from src.persist.database import initialize_database
from src.persist.models import Base, Meeting, Project, Speaker, Turn


@pytest.fixture
def db_session():
    """Create a fresh in-memory database session for each test."""
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)
    initialize_database(engine)

    with Session(engine) as session:
        yield session
        session.rollback()


@pytest.fixture
def d1_scenario_dir() -> Path:
    """Path to D1 scenario directory."""
    return Path(__file__).parents[2] / "scenarios" / "dev" / "D1"


class TestLoadScenario:
    """Tests for load_scenario function."""

    def test_loads_project_and_speakers(self, db_session: Session, d1_scenario_dir: Path):
        """load_scenario creates project and speakers."""
        project = load_scenario(db_session, d1_scenario_dir)

        assert project.id == "D1"
        assert project.name == "Client portal"

        # Check speakers
        speakers = db_session.query(Speaker).filter(Speaker.project_id == "D1").all()
        assert len(speakers) == 3

        speaker_labels = {s.speaker_label for s in speakers}
        assert speaker_labels == {"Sarah Chen", "Mike Torres", "Jordan Kim"}

        # Check can_confirm_scope
        sarah = next(s for s in speakers if s.speaker_label == "Sarah Chen")
        assert sarah.can_confirm_scope is True

        mike = next(s for s in speakers if s.speaker_label == "Mike Torres")
        assert mike.can_confirm_scope is False

    def test_idempotent_load(self, db_session: Session, d1_scenario_dir: Path):
        """Loading the same scenario twice returns the same project."""
        project1 = load_scenario(db_session, d1_scenario_dir)
        db_session.commit()

        project2 = load_scenario(db_session, d1_scenario_dir)

        assert project1.id == project2.id

        # Only one project should exist
        projects = db_session.query(Project).all()
        assert len(projects) == 1

    def test_missing_manifest_raises(self, db_session: Session, tmp_path: Path):
        """Missing scenario.yaml raises ScenarioError."""
        with pytest.raises(ScenarioError, match="not found"):
            load_scenario(db_session, tmp_path)

    def test_missing_speakers_raises(self, db_session: Session, tmp_path: Path):
        """Scenario without speakers raises ScenarioError."""
        manifest = tmp_path / "scenario.yaml"
        manifest.write_text("id: test\nname: Test\n")

        with pytest.raises(ScenarioError, match="speakers"):
            load_scenario(db_session, tmp_path)


class TestImportMeeting:
    """Tests for import_meeting function."""

    def test_imports_meeting_and_turns(self, db_session: Session, d1_scenario_dir: Path):
        """import_meeting creates meeting and all turns."""
        # First load the scenario to get speakers
        load_scenario(db_session, d1_scenario_dir)
        db_session.commit()

        canonical_path = d1_scenario_dir / "canonical" / "M01.jsonl"
        meeting = import_meeting(db_session, "D1", canonical_path, ordinal=1)
        db_session.commit()

        assert meeting.id == "D1-M01"
        assert meeting.project_id == "D1"
        assert meeting.ordinal == 1

        # Check turns
        turns = db_session.query(Turn).filter(Turn.meeting_id == "D1-M01").all()
        assert len(turns) == 19

    def test_idempotent_import_produces_one_meeting(
        self, db_session: Session, d1_scenario_dir: Path
    ):
        """Importing D1-M01 twice produces one meeting and 19 turns, not two or 38."""
        load_scenario(db_session, d1_scenario_dir)
        db_session.commit()

        canonical_path = d1_scenario_dir / "canonical" / "M01.jsonl"

        # First import
        meeting1 = import_meeting(db_session, "D1", canonical_path, ordinal=1)
        db_session.commit()

        # Second import - should return same meeting
        meeting2 = import_meeting(db_session, "D1", canonical_path, ordinal=1)
        db_session.commit()

        # Same meeting
        assert meeting1.id == meeting2.id

        # Only one meeting
        meetings = db_session.query(Meeting).filter(Meeting.project_id == "D1").all()
        assert len(meetings) == 1

        # Exactly 19 turns, not 38
        turns = db_session.query(Turn).filter(Turn.meeting_id == "D1-M01").all()
        assert len(turns) == 19

        # Verify turn IDs are correct
        turn_ids = {t.id for t in turns}
        expected_ids = {f"D1-M01:{i:04d}" for i in range(19)}
        assert turn_ids == expected_ids

    def test_gap_in_turn_index_is_rejected(self, db_session: Session, tmp_path: Path):
        """A JSONL file with a gap in turn_index is rejected and writes nothing."""
        # Create a minimal scenario
        scenario_dir = tmp_path / "test_scenario"
        scenario_dir.mkdir()
        (scenario_dir / "canonical").mkdir()

        # Write scenario.yaml
        manifest = {
            "id": "TEST",
            "name": "Test",
            "speakers": [
                {"label": "Speaker1", "role": "Role1", "can_confirm_scope": True}
            ],
        }
        (scenario_dir / "scenario.yaml").write_text(
            f"id: {manifest['id']}\nname: {manifest['name']}\n"
            f"speakers:\n  - label: Speaker1\n    role: Role1\n    can_confirm_scope: true\n"
        )

        load_scenario(db_session, scenario_dir)
        db_session.commit()

        # Create JSONL with gap (0, 1, 3 - missing 2)
        jsonl_path = scenario_dir / "canonical" / "M01.jsonl"
        lines = [
            json.dumps({"turn_index": 0, "turn_id": "TEST-M01:0000", "speaker": "Speaker1", "text": "First"}),
            json.dumps({"turn_index": 1, "turn_id": "TEST-M01:0001", "speaker": "Speaker1", "text": "Second"}),
            json.dumps({"turn_index": 3, "turn_id": "TEST-M01:0003", "speaker": "Speaker1", "text": "Fourth"}),
        ]
        jsonl_path.write_text("\n".join(lines))

        # Count initial state
        initial_meetings = db_session.query(Meeting).count()
        initial_turns = db_session.query(Turn).count()

        # Import should fail
        with pytest.raises(MeetingError, match="Non-contiguous"):
            import_meeting(db_session, "TEST", jsonl_path, ordinal=1)

        # Rollback and verify nothing was written
        db_session.rollback()

        assert db_session.query(Meeting).count() == initial_meetings
        assert db_session.query(Turn).count() == initial_turns

    def test_unknown_speaker_is_rejected(self, db_session: Session, tmp_path: Path):
        """A meeting with an unknown speaker is rejected."""
        # Create a minimal scenario
        scenario_dir = tmp_path / "test_scenario"
        scenario_dir.mkdir()
        (scenario_dir / "canonical").mkdir()

        (scenario_dir / "scenario.yaml").write_text(
            "id: TEST\nname: Test\n"
            "speakers:\n  - label: Speaker1\n    role: Role1\n    can_confirm_scope: true\n"
        )

        load_scenario(db_session, scenario_dir)
        db_session.commit()

        # Create JSONL with unknown speaker
        jsonl_path = scenario_dir / "canonical" / "M01.jsonl"
        lines = [
            json.dumps({"turn_index": 0, "turn_id": "TEST-M01:0000", "speaker": "Unknown", "text": "Hello"}),
        ]
        jsonl_path.write_text("\n".join(lines))

        with pytest.raises(MeetingError, match="Unknown speaker"):
            import_meeting(db_session, "TEST", jsonl_path, ordinal=1)

    def test_malformed_json_is_rejected(self, db_session: Session, tmp_path: Path):
        """Malformed JSON is rejected and writes nothing."""
        scenario_dir = tmp_path / "test_scenario"
        scenario_dir.mkdir()
        (scenario_dir / "canonical").mkdir()

        (scenario_dir / "scenario.yaml").write_text(
            "id: TEST\nname: Test\n"
            "speakers:\n  - label: Speaker1\n    role: Role1\n    can_confirm_scope: true\n"
        )

        load_scenario(db_session, scenario_dir)
        db_session.commit()

        jsonl_path = scenario_dir / "canonical" / "M01.jsonl"
        jsonl_path.write_text("not valid json")

        initial_meetings = db_session.query(Meeting).count()

        with pytest.raises(MeetingError, match="Invalid JSON"):
            import_meeting(db_session, "TEST", jsonl_path, ordinal=1)

        db_session.rollback()
        assert db_session.query(Meeting).count() == initial_meetings


class TestCrossProjectIsolation:
    """Tests for cross-project query isolation (NFR03)."""

    def test_turns_isolated_by_project(self, db_session: Session, tmp_path: Path):
        """Turns from different projects are isolated."""
        # Create two scenarios
        for project_id in ["PROJ_A", "PROJ_B"]:
            scenario_dir = tmp_path / project_id
            scenario_dir.mkdir()
            (scenario_dir / "canonical").mkdir()

            (scenario_dir / "scenario.yaml").write_text(
                f"id: {project_id}\nname: Test {project_id}\n"
                f"speakers:\n  - label: Speaker1\n    role: Role1\n    can_confirm_scope: true\n"
            )

            jsonl_path = scenario_dir / "canonical" / "M01.jsonl"
            lines = [
                json.dumps({
                    "turn_index": 0,
                    "turn_id": f"{project_id}-M01:0000",
                    "speaker": "Speaker1",
                    "text": f"Text for {project_id}"
                }),
            ]
            jsonl_path.write_text("\n".join(lines))

            load_scenario(db_session, scenario_dir)
            import_meeting(db_session, project_id, jsonl_path, ordinal=1)

        db_session.commit()

        # Query turns for PROJ_A only
        proj_a_turns = (
            db_session.query(Turn)
            .join(Meeting)
            .filter(Meeting.project_id == "PROJ_A")
            .all()
        )
        assert len(proj_a_turns) == 1
        assert "PROJ_A" in proj_a_turns[0].id

        # Query turns for PROJ_B only
        proj_b_turns = (
            db_session.query(Turn)
            .join(Meeting)
            .filter(Meeting.project_id == "PROJ_B")
            .all()
        )
        assert len(proj_b_turns) == 1
        assert "PROJ_B" in proj_b_turns[0].id


class TestLoadScenarioMeetings:
    """Tests for load_scenario_meetings function."""

    def test_loads_all_meetings(self, db_session: Session, d1_scenario_dir: Path):
        """load_scenario_meetings loads all meetings in the manifest."""
        meetings = load_scenario_meetings(db_session, d1_scenario_dir)
        db_session.commit()

        assert len(meetings) == 2
        assert meetings[0].id == "D1-M01"
        assert meetings[1].id == "D1-M02"

        # Verify turn counts
        m01_turns = db_session.query(Turn).filter(Turn.meeting_id == "D1-M01").count()
        m02_turns = db_session.query(Turn).filter(Turn.meeting_id == "D1-M02").count()

        assert m01_turns == 19
        assert m02_turns == 20


class TestTextPreservation:
    """Tests that text is preserved byte-faithfully."""

    def test_text_not_modified_on_import(self, db_session: Session, tmp_path: Path):
        """Text is not modified during import - no normalisation."""
        scenario_dir = tmp_path / "test_scenario"
        scenario_dir.mkdir()
        (scenario_dir / "canonical").mkdir()

        (scenario_dir / "scenario.yaml").write_text(
            "id: TEST\nname: Test\n"
            "speakers:\n  - label: Speaker1\n    role: Role1\n    can_confirm_scope: true\n"
        )

        load_scenario(db_session, scenario_dir)
        db_session.commit()

        # Text with special characters, multiple spaces, etc.
        original_text = "Hello   world!  This has   multiple   spaces."

        jsonl_path = scenario_dir / "canonical" / "M01.jsonl"
        lines = [
            json.dumps({
                "turn_index": 0,
                "turn_id": "TEST-M01:0000",
                "speaker": "Speaker1",
                "text": original_text
            }),
        ]
        jsonl_path.write_text("\n".join(lines))

        import_meeting(db_session, "TEST", jsonl_path, ordinal=1)
        db_session.commit()

        # Retrieve and verify text is unchanged
        turn = db_session.query(Turn).filter(Turn.id == "TEST-M01:0000").one()
        assert turn.text == original_text
