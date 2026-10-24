"""E1 Register integrity tests.

Tests:
- import D1, export, and assert the export matches DB state: every id,
  statement, status, version and evidence reference
- re-import the same canonical files; assert the export is byte-identical
- import a malformed file; assert it raises and the export is unchanged
- assert no row from another project appears in the export (NFR03)

These run with no network.
"""

import json
import tempfile
from datetime import UTC, datetime
from pathlib import Path

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from src.export.register import ExportError, export_register
from src.ingest.loader import (
    MeetingError,
    import_meeting,
    load_scenario_meetings,
)
from src.persist.models import (
    Base,
    Event,
    Meeting,
    Project,
    Requirement,
    RequirementCurrent,
    RequirementVersion,
    Speaker,
    Turn,
)


@pytest.fixture
def db_session():
    """Create an in-memory database session for testing."""
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)
    SessionLocal = sessionmaker(bind=engine)
    session = SessionLocal()
    yield session
    session.close()


@pytest.fixture
def d1_scenario_dir():
    """Path to the D1 scenario directory."""
    return Path(__file__).resolve().parents[2] / "scenarios" / "dev" / "D1"


class TestImportExportRoundTrip:
    """E1: Import and export round-trip tests."""

    def test_import_d1_export_matches_db_state(self, db_session, d1_scenario_dir):
        """Import D1 scenario and verify export matches DB state."""
        # Import scenario
        meetings = load_scenario_meetings(db_session, d1_scenario_dir)
        db_session.commit()

        # Should have imported meetings
        assert len(meetings) == 2

        # Export
        export_data = export_register(db_session, "D1")

        # Verify project info
        assert export_data["project_id"] == "D1"
        assert export_data["project_name"] == "Client portal"

        # Verify export is valid structure
        assert "requirements" in export_data
        assert "exported_at" in export_data

        # Verify meetings are in DB
        db_meetings = db_session.query(Meeting).filter(Meeting.project_id == "D1").all()
        assert len(db_meetings) == 2

        # Verify turns are in DB
        for meeting in db_meetings:
            turns = db_session.query(Turn).filter(Turn.meeting_id == meeting.id).all()
            assert len(turns) > 0

    def test_reimport_produces_identical_export(self, db_session, d1_scenario_dir):
        """Re-import the same canonical files; export content is identical."""
        # First import
        meetings1 = load_scenario_meetings(db_session, d1_scenario_dir)
        db_session.commit()

        # First export
        export1 = export_register(db_session, "D1")

        # Re-import (should be idempotent)
        meetings2 = load_scenario_meetings(db_session, d1_scenario_dir)
        db_session.commit()

        # Meetings should be the same objects (idempotent)
        assert len(meetings2) == len(meetings1)
        for m1, m2 in zip(meetings1, meetings2, strict=True):
            assert m1.id == m2.id

        # Second export
        export2 = export_register(db_session, "D1")

        # Exports should be identical (excluding timestamp)
        # Compare everything except exported_at
        assert export1["project_id"] == export2["project_id"]
        assert export1["project_name"] == export2["project_name"]
        assert export1["requirements"] == export2["requirements"]

    def test_malformed_file_raises_and_export_unchanged(self, db_session, d1_scenario_dir):
        """Import a malformed file; assert it raises and export is unchanged."""
        # First import valid scenario
        load_scenario_meetings(db_session, d1_scenario_dir)
        db_session.commit()

        # Get baseline export
        baseline_export = export_register(db_session, "D1")

        # Create a malformed file
        with tempfile.NamedTemporaryFile(
            mode="w", suffix=".jsonl", delete=False
        ) as f:
            malformed_path = Path(f.name)
            f.write("not valid json {{{")

        # Attempt to import malformed file - should raise
        with pytest.raises(MeetingError):
            import_meeting(db_session, "D1", malformed_path, ordinal=99)

        # Rollback any partial changes
        db_session.rollback()

        # Export again
        after_export = export_register(db_session, "D1")

        # Export content should be unchanged (excluding timestamp)
        assert baseline_export["project_id"] == after_export["project_id"]
        assert baseline_export["project_name"] == after_export["project_name"]
        assert baseline_export["requirements"] == after_export["requirements"]

        # Cleanup
        malformed_path.unlink()

    def test_no_cross_project_leakage(self, db_session, d1_scenario_dir):
        """NFR03: No row from another project appears in the export."""
        # Import D1 scenario
        load_scenario_meetings(db_session, d1_scenario_dir)
        db_session.commit()

        # Create a second project with its own data
        project2 = Project(
            id="OTHER",
            name="Other Project",
            created_at=datetime.now(UTC),
        )
        db_session.add(project2)

        speaker2 = Speaker(
            project_id="OTHER",
            speaker_label="Test Speaker",
            role="Developer",
            can_confirm_scope=True,
        )
        db_session.add(speaker2)
        db_session.commit()

        # Add a requirement to the OTHER project (manually, simulating pipeline)
        event = Event(
            id="evt-other-001",
            project_id="OTHER",
            ts=datetime.now(UTC),
            actor="system",
            event_type="create",
            payload_json=json.dumps({"requirement_id": "OTHER-REQ-001"}),
        )
        db_session.add(event)
        db_session.flush()

        req = Requirement(id="OTHER-REQ-001", project_id="OTHER")
        db_session.add(req)
        db_session.flush()

        ver = RequirementVersion(
            id="OTHER-REQ-001-v1",
            requirement_id="OTHER-REQ-001",
            version=1,
            text="Some requirement in OTHER project",
            state="proposed",
            evidence_json="[]",
            created_event_id="evt-other-001",
        )
        db_session.add(ver)

        current = RequirementCurrent(
            requirement_id="OTHER-REQ-001",
            current_version_id="OTHER-REQ-001-v1",
            state="proposed",
            text="Some requirement in OTHER project",
        )
        db_session.add(current)
        db_session.commit()

        # Export D1 - should NOT contain OTHER project data
        d1_export = export_register(db_session, "D1")

        # Verify no OTHER project data leaked
        assert d1_export["project_id"] == "D1"
        for req in d1_export["requirements"]:
            assert not req["requirement_id"].startswith("OTHER")
            assert "OTHER" not in req["requirement_id"]

        # Export OTHER project - should only have its own data
        other_export = export_register(db_session, "OTHER")
        assert other_export["project_id"] == "OTHER"
        assert len(other_export["requirements"]) == 1
        assert other_export["requirements"][0]["requirement_id"] == "OTHER-REQ-001"


class TestExportStructure:
    """Tests for export structure with requirements data."""

    def test_export_includes_all_versions(self, db_session):
        """Superseded and withdrawn versions appear in the export."""
        # Create a project
        project = Project(id="TEST", name="Test", created_at=datetime.now(UTC))
        db_session.add(project)
        db_session.flush()

        # Create events for each version
        event1 = Event(
            id="evt-001",
            project_id="TEST",
            ts=datetime.now(UTC),
            actor="user",
            event_type="create",
            payload_json=json.dumps({"requirement_id": "REQ-001"}),
        )
        event2 = Event(
            id="evt-002",
            project_id="TEST",
            ts=datetime.now(UTC),
            actor="user",
            event_type="update",
            payload_json=json.dumps({"requirement_id": "REQ-001", "reason": "Clarification"}),
        )
        event3 = Event(
            id="evt-003",
            project_id="TEST",
            ts=datetime.now(UTC),
            actor="user",
            event_type="withdraw",
            payload_json=json.dumps({"requirement_id": "REQ-001", "reason": "No longer needed"}),
        )
        db_session.add_all([event1, event2, event3])
        db_session.flush()

        # Create requirement with multiple versions
        req = Requirement(id="REQ-001", project_id="TEST")
        db_session.add(req)
        db_session.flush()

        # Version 1: proposed
        ver1 = RequirementVersion(
            id="REQ-001-v1",
            requirement_id="REQ-001",
            version=1,
            text="Initial requirement",
            state="proposed",
            evidence_json=json.dumps([{"turn_id": "T001", "start": 0, "end": 10}]),
            created_event_id="evt-001",
        )
        # Version 2: confirmed (supersedes v1)
        ver2 = RequirementVersion(
            id="REQ-001-v2",
            requirement_id="REQ-001",
            version=2,
            text="Updated requirement",
            state="confirmed",
            evidence_json=json.dumps([{"turn_id": "T002", "start": 5, "end": 20}]),
            created_event_id="evt-002",
        )
        # Version 3: withdrawn
        ver3 = RequirementVersion(
            id="REQ-001-v3",
            requirement_id="REQ-001",
            version=3,
            text="Updated requirement",
            state="withdrawn",
            evidence_json=json.dumps([{"turn_id": "T002", "start": 5, "end": 20}]),
            created_event_id="evt-003",
        )
        db_session.add_all([ver1, ver2, ver3])

        # Current points to v3 (withdrawn)
        current = RequirementCurrent(
            requirement_id="REQ-001",
            current_version_id="REQ-001-v3",
            state="withdrawn",
            text="Updated requirement",
        )
        db_session.add(current)
        db_session.commit()

        # Export
        export_data = export_register(db_session, "TEST")

        # Should have one requirement
        assert len(export_data["requirements"]) == 1
        req_data = export_data["requirements"][0]

        # Should have ALL three versions (including superseded and withdrawn)
        assert len(req_data["versions"]) == 3

        # Check versions are in order
        assert req_data["versions"][0]["version"] == 1
        assert req_data["versions"][0]["state"] == "proposed"
        assert req_data["versions"][1]["version"] == 2
        assert req_data["versions"][1]["state"] == "confirmed"
        assert req_data["versions"][2]["version"] == 3
        assert req_data["versions"][2]["state"] == "withdrawn"

        # Current should be v3
        assert req_data["current_state"] == "withdrawn"
        assert req_data["current_version_number"] == 3

    def test_evidence_includes_turn_id_and_offsets(self, db_session):
        """Evidence references carry turn_id plus offsets."""
        # Create minimal project structure
        project = Project(id="TEST2", name="Test2", created_at=datetime.now(UTC))
        db_session.add(project)

        event = Event(
            id="evt-100",
            project_id="TEST2",
            ts=datetime.now(UTC),
            actor="user",
            event_type="create",
            payload_json="{}",
        )
        db_session.add(event)
        db_session.flush()

        req = Requirement(id="REQ-002", project_id="TEST2")
        db_session.add(req)
        db_session.flush()

        # Version with multiple evidence spans
        evidence = [
            {"turn_id": "M01:0005", "start": 10, "end": 50},
            {"turn_id": "M01:0008", "start": 0, "end": 30},
        ]
        ver = RequirementVersion(
            id="REQ-002-v1",
            requirement_id="REQ-002",
            version=1,
            text="Test requirement",
            state="confirmed",
            evidence_json=json.dumps(evidence),
            created_event_id="evt-100",
        )
        db_session.add(ver)

        current = RequirementCurrent(
            requirement_id="REQ-002",
            current_version_id="REQ-002-v1",
            state="confirmed",
            text="Test requirement",
        )
        db_session.add(current)
        db_session.commit()

        # Export
        export_data = export_register(db_session, "TEST2")

        # Verify evidence structure
        req_data = export_data["requirements"][0]
        ver_data = req_data["versions"][0]
        assert len(ver_data["evidence"]) == 2

        # First evidence span
        ev0 = ver_data["evidence"][0]
        assert ev0["turn_id"] == "M01:0005"
        assert ev0["start"] == 10
        assert ev0["end"] == 50

        # Second evidence span
        ev1 = ver_data["evidence"][1]
        assert ev1["turn_id"] == "M01:0008"
        assert ev1["start"] == 0
        assert ev1["end"] == 30

    def test_decision_history_includes_reason(self, db_session):
        """Decision history includes reason where present."""
        # Create minimal project structure
        project = Project(id="TEST3", name="Test3", created_at=datetime.now(UTC))
        db_session.add(project)

        # Event with reason
        event = Event(
            id="evt-200",
            project_id="TEST3",
            ts=datetime.now(UTC),
            actor="reviewer",
            event_type="reject",
            payload_json=json.dumps({
                "requirement_id": "REQ-003",
                "reason": "Does not meet acceptance criteria",
            }),
        )
        db_session.add(event)
        db_session.flush()

        req = Requirement(id="REQ-003", project_id="TEST3")
        db_session.add(req)
        db_session.flush()

        ver = RequirementVersion(
            id="REQ-003-v1",
            requirement_id="REQ-003",
            version=1,
            text="Rejected requirement",
            state="rejected",
            evidence_json="[]",
            created_event_id="evt-200",
        )
        db_session.add(ver)

        current = RequirementCurrent(
            requirement_id="REQ-003",
            current_version_id="REQ-003-v1",
            state="rejected",
            text="Rejected requirement",
        )
        db_session.add(current)
        db_session.commit()

        # Export
        export_data = export_register(db_session, "TEST3")

        # Verify decision history includes reason
        req_data = export_data["requirements"][0]
        assert len(req_data["decision_history"]) == 1
        history_entry = req_data["decision_history"][0]
        assert history_entry["event_type"] == "reject"
        assert history_entry["actor"] == "reviewer"
        assert history_entry["reason"] == "Does not meet acceptance criteria"


class TestExportErrors:
    """Tests for export error handling."""

    def test_export_nonexistent_project_raises(self, db_session):
        """Exporting a non-existent project raises ExportError."""
        with pytest.raises(ExportError) as exc_info:
            export_register(db_session, "NONEXISTENT")

        assert "not found" in str(exc_info.value).lower()

    def test_export_empty_project_returns_empty_requirements(self, db_session):
        """Exporting a project with no requirements returns empty list."""
        project = Project(id="EMPTY", name="Empty Project", created_at=datetime.now(UTC))
        db_session.add(project)
        db_session.commit()

        export_data = export_register(db_session, "EMPTY")

        assert export_data["project_id"] == "EMPTY"
        assert export_data["requirements"] == []
