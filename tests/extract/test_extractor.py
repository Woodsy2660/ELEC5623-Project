"""Tests for src/extract/extractor.py - FR05 candidate extraction.

Uses a fake client returning canned responses - no network calls.
"""

import json
import tempfile
from pathlib import Path
from typing import Any
from unittest.mock import MagicMock

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from src.extract import extractor
from src.extract.extractor import (
    ExtractionError,
    _render_prompt,
    _turn_windows,
    extract_candidates,
)
from src.persist.models import Base, Candidate, Meeting, ModelCall, Project, Run, Turn


class FakeUsage:
    """Fake usage object for mocking."""

    def __init__(self, prompt_tokens: int = 100, completion_tokens: int = 50):
        self.prompt_tokens = prompt_tokens
        self.completion_tokens = completion_tokens


class FakeMessage:
    """Fake message object for mocking."""

    def __init__(self, content: str):
        self.content = content


class FakeChoice:
    """Fake choice object for mocking."""

    def __init__(self, content: str):
        self.message = FakeMessage(content)


class FakeCompletion:
    """Fake ChatCompletion object for mocking."""

    def __init__(self, content: str):
        self.choices = [FakeChoice(content)]
        self.model = "gpt-4o-mini-2024-07-18"
        self.usage = FakeUsage()

    def model_dump(self) -> dict[str, Any]:
        """Return dict representation for JSON serialization."""
        return {
            "choices": [{"message": {"content": self.choices[0].message.content}}],
            "model": self.model,
            "usage": {
                "prompt_tokens": self.usage.prompt_tokens,
                "completion_tokens": self.usage.completion_tokens,
            },
        }


@pytest.fixture
def db_session():
    """Create an in-memory database session with test data."""
    from datetime import UTC, datetime

    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)
    SessionLocal = sessionmaker(bind=engine)
    session = SessionLocal()

    # Create a project
    project = Project(id="proj-001", name="Test Project", created_at=datetime.now(UTC))
    session.add(project)

    # Create a run
    run = Run(
        id="run-001",
        mode="extract",
        candidate_source="model",
        repeat_index=0,
        prompt_hash="abc123",
        model_deployment="gpt-4o-mini",
        temp=0.0,
        started_at=datetime.now(UTC),
    )
    session.add(run)

    # Create a meeting
    meeting = Meeting(
        id="meet-001",
        project_id="proj-001",
        ordinal=1,
        source_hash="abc123",
        imported_at=datetime.now(UTC),
    )
    session.add(meeting)

    # Create turns with specific text for testing evidence resolution
    turns = [
        Turn(
            id="turn-001",
            meeting_id="meet-001",
            turn_index=0,
            speaker="Alice",
            text="We need the system to support SSO authentication for enterprise users.",
        ),
        Turn(
            id="turn-002",
            meeting_id="meet-001",
            turn_index=1,
            speaker="Bob",
            text="Yes, and sessions should timeout after 30 minutes of inactivity.",
        ),
        Turn(
            id="turn-003",
            meeting_id="meet-001",
            turn_index=2,
            speaker="Alice",
            text="The password must be at least 12 characters long.",
        ),
    ]
    for turn in turns:
        session.add(turn)

    session.commit()
    yield session
    session.close()


@pytest.fixture
def temp_runs_dir():
    """Create a temporary directory for raw response files."""
    with tempfile.TemporaryDirectory() as tmpdir:
        yield Path(tmpdir)


class TestExtractCandidates:
    """Tests for the extract_candidates function."""

    def test_candidate_with_verbatim_quote_is_accepted(self, db_session, temp_runs_dir):
        """A candidate whose quote appears verbatim is accepted with correct offsets."""
        # Model returns a candidate with an exact quote from turn-001
        model_response = {
            "candidates": [
                {
                    "statement": "The system shall support SSO authentication for enterprise users.",
                    "evidence": [
                        {
                            "turn_id": "turn-001",
                            "quote": "support SSO authentication for enterprise users",
                        }
                    ],
                }
            ]
        }

        client = MagicMock()
        client.chat.completions.create.return_value = FakeCompletion(
            content=json.dumps(model_response)
        )

        result = extract_candidates(
            db_session,
            client,
            run_id="run-001",
            meeting_id="meet-001",
            deployment_name="gpt-4o-mini",
            runs_dir=temp_runs_dir,
        )

        # Verify result
        assert result.returned == 1
        assert result.accepted == 1
        assert result.rejected_unresolvable == 0
        assert result.parse_failures == 0
        assert len(result.candidates) == 1

        # Verify candidate
        candidate = result.candidates[0]
        assert candidate.candidate_id == "meet-001-C0000"
        assert candidate.project_id == "proj-001"
        assert candidate.meeting_id == "meet-001"
        assert (
            candidate.text_norm
            == "The system shall support SSO authentication for enterprise users."
        )

        # Verify evidence span offsets are correct
        assert len(candidate.evidence) == 1
        span = candidate.evidence[0]
        assert span.turn_id == "turn-001"
        # "support SSO authentication for enterprise users" starts at position 22
        # in "We need the system to support SSO authentication for enterprise users."
        # "We need the system to " = 22 characters
        assert span.start == 22
        assert span.end == 69

        # Verify candidate was persisted to database
        db_candidates = db_session.query(Candidate).all()
        assert len(db_candidates) == 1
        assert db_candidates[0].id == "meet-001-C0000"

    def test_candidate_with_nonexistent_quote_is_rejected(self, db_session, temp_runs_dir):
        """A candidate whose quote does not appear is rejected and counted in rejected_unresolvable."""
        # Model returns a candidate with a quote that doesn't exist in any turn
        model_response = {
            "candidates": [
                {
                    "statement": "The system shall use biometric authentication.",
                    "evidence": [
                        {
                            "turn_id": "turn-001",
                            "quote": "biometric authentication is required",  # Not in transcript
                        }
                    ],
                }
            ]
        }

        client = MagicMock()
        client.chat.completions.create.return_value = FakeCompletion(
            content=json.dumps(model_response)
        )

        result = extract_candidates(
            db_session,
            client,
            run_id="run-001",
            meeting_id="meet-001",
            deployment_name="gpt-4o-mini",
            runs_dir=temp_runs_dir,
        )

        # Verify result
        assert result.returned == 1
        assert result.accepted == 0
        assert result.rejected_unresolvable == 1
        assert len(result.candidates) == 0

        # Verify NO candidate was persisted to database
        db_candidates = db_session.query(Candidate).all()
        assert len(db_candidates) == 0

    def test_candidate_with_unknown_turn_id_is_rejected(self, db_session, temp_runs_dir):
        """A candidate referencing an unknown turn_id is rejected."""
        model_response = {
            "candidates": [
                {
                    "statement": "The system shall log all access attempts.",
                    "evidence": [
                        {
                            "turn_id": "turn-999",  # Doesn't exist
                            "quote": "log all access",
                        }
                    ],
                }
            ]
        }

        client = MagicMock()
        client.chat.completions.create.return_value = FakeCompletion(
            content=json.dumps(model_response)
        )

        result = extract_candidates(
            db_session,
            client,
            run_id="run-001",
            meeting_id="meet-001",
            deployment_name="gpt-4o-mini",
            runs_dir=temp_runs_dir,
        )

        assert result.returned == 1
        assert result.accepted == 0
        assert result.rejected_unresolvable == 1

    def test_multiple_candidates_mixed_acceptance(self, db_session, temp_runs_dir):
        """Multiple candidates can have mixed acceptance - some valid, some rejected."""
        model_response = {
            "candidates": [
                {
                    # Valid - quote exists
                    "statement": "Sessions shall timeout after 30 minutes.",
                    "evidence": [
                        {
                            "turn_id": "turn-002",
                            "quote": "sessions should timeout after 30 minutes",
                        }
                    ],
                },
                {
                    # Invalid - quote doesn't exist
                    "statement": "The system shall use OAuth.",
                    "evidence": [
                        {
                            "turn_id": "turn-001",
                            "quote": "we must use OAuth",
                        }
                    ],
                },
                {
                    # Valid - quote exists
                    "statement": "Password must be at least 12 characters.",
                    "evidence": [
                        {
                            "turn_id": "turn-003",
                            "quote": "password must be at least 12 characters",
                        }
                    ],
                },
            ]
        }

        client = MagicMock()
        client.chat.completions.create.return_value = FakeCompletion(
            content=json.dumps(model_response)
        )

        result = extract_candidates(
            db_session,
            client,
            run_id="run-001",
            meeting_id="meet-001",
            deployment_name="gpt-4o-mini",
            runs_dir=temp_runs_dir,
        )

        assert result.returned == 3
        assert result.accepted == 2
        assert result.rejected_unresolvable == 1
        assert len(result.candidates) == 2

        # Verify only valid candidates were persisted
        db_candidates = db_session.query(Candidate).all()
        assert len(db_candidates) == 2

    def test_candidate_with_multiple_evidence_spans(self, db_session, temp_runs_dir):
        """A candidate with multiple evidence quotes has all spans resolved."""
        model_response = {
            "candidates": [
                {
                    "statement": "The system shall support SSO with 30 minute session timeout.",
                    "evidence": [
                        {
                            "turn_id": "turn-001",
                            "quote": "support SSO authentication",
                        },
                        {
                            "turn_id": "turn-002",
                            "quote": "timeout after 30 minutes",
                        },
                    ],
                }
            ]
        }

        client = MagicMock()
        client.chat.completions.create.return_value = FakeCompletion(
            content=json.dumps(model_response)
        )

        result = extract_candidates(
            db_session,
            client,
            run_id="run-001",
            meeting_id="meet-001",
            deployment_name="gpt-4o-mini",
            runs_dir=temp_runs_dir,
        )

        assert result.accepted == 1
        assert len(result.candidates) == 1
        assert len(result.candidates[0].evidence) == 2

    def test_meeting_not_found_raises_error(self, db_session, temp_runs_dir):
        """Extracting from a non-existent meeting raises ExtractionError."""
        client = MagicMock()

        with pytest.raises(ExtractionError) as exc_info:
            extract_candidates(
                db_session,
                client,
                run_id="run-001",
                meeting_id="meet-nonexistent",
                deployment_name="gpt-4o-mini",
                runs_dir=temp_runs_dir,
            )

        assert "not found" in str(exc_info.value)

    def test_empty_response_returns_empty_result(self, db_session, temp_runs_dir):
        """An empty response from the model returns zero candidates."""
        model_response = {"candidates": []}

        client = MagicMock()
        client.chat.completions.create.return_value = FakeCompletion(
            content=json.dumps(model_response)
        )

        result = extract_candidates(
            db_session,
            client,
            run_id="run-001",
            meeting_id="meet-001",
            deployment_name="gpt-4o-mini",
            runs_dir=temp_runs_dir,
        )

        assert result.returned == 0
        assert result.accepted == 0
        assert result.rejected_unresolvable == 0
        assert len(result.candidates) == 0

    def test_invalid_json_response_counts_as_parse_failure(self, db_session, temp_runs_dir):
        """Invalid JSON in model response counts as parse failure."""
        client = MagicMock()
        client.chat.completions.create.return_value = FakeCompletion(content="not valid json {{")

        result = extract_candidates(
            db_session,
            client,
            run_id="run-001",
            meeting_id="meet-001",
            deployment_name="gpt-4o-mini",
            runs_dir=temp_runs_dir,
        )

        assert result.parse_failures == 1
        assert result.accepted == 0

    def test_call_id_is_recorded_in_result(self, db_session, temp_runs_dir):
        """The call_id from the model call is recorded in the result."""
        model_response = {"candidates": []}

        client = MagicMock()
        client.chat.completions.create.return_value = FakeCompletion(
            content=json.dumps(model_response)
        )

        result = extract_candidates(
            db_session,
            client,
            run_id="run-001",
            meeting_id="meet-001",
            deployment_name="gpt-4o-mini",
            runs_dir=temp_runs_dir,
        )

        assert result.call_id is not None
        assert len(result.call_id) == 36  # UUID format


def test_prompt_keeps_turn_text_byte_exact() -> None:
    """Quotes must match stored text, so the prompt cannot escape its characters."""
    text = """Let's add "SSO" & <MFA> — it's required"""

    prompt = _render_prompt([{"turn_id": "t-1", "speaker": "Sam", "text": text}])

    assert json.dumps(text, ensure_ascii=False) in prompt
    assert "\\u0027" not in prompt


def test_turn_windows_split_long_meetings_without_breaking_turns(monkeypatch):
    monkeypatch.setattr(extractor, "MAX_TURN_CHARS_PER_CALL", 10)
    turns = [
        {"turn_id": str(i), "speaker": "A", "text": "x" * n} for i, n in enumerate([4, 5, 3, 12, 1])
    ]
    windows = _turn_windows(turns)
    assert [[t["turn_id"] for t in w] for w in windows] == [["0", "1"], ["2"], ["3"], ["4"]]
    assert [t for w in windows for t in w] == turns


def test_short_meeting_is_one_window():
    turns = [{"turn_id": "0", "speaker": "A", "text": "short"}]
    assert _turn_windows(turns) == [turns]


def test_long_meeting_is_extracted_per_window_and_a_failed_window_is_logged(
    db_session, temp_runs_dir, monkeypatch
):
    """Each window is its own logged call; a failed window does not drop the others."""
    from src.logging import calls

    monkeypatch.setattr(calls, "_sleep", lambda s: None)
    # Each fixture turn is under 80 characters, so a 60-character limit gives three windows.
    monkeypatch.setattr(extractor, "MAX_TURN_CHARS_PER_CALL", 60)
    first = {
        "candidates": [
            {
                "statement": "The system shall support SSO authentication.",
                "evidence": [{"turn_id": "turn-001", "quote": "support SSO authentication"}],
            }
        ]
    }
    third = {
        "candidates": [
            {
                "statement": "Passwords must be at least 12 characters.",
                "evidence": [{"turn_id": "turn-003", "quote": "at least 12 characters long"}],
            }
        ]
    }
    client = MagicMock()
    client.chat.completions.create.side_effect = [
        FakeCompletion(content=json.dumps(first)),
        Exception("window two fails"),
        Exception("window two fails again"),
        FakeCompletion(content=json.dumps(third)),
    ]
    result = extract_candidates(
        db_session,
        client,
        run_id="run-001",
        meeting_id="meet-001",
        deployment_name="gpt-4o-mini",
        runs_dir=temp_runs_dir,
    )
    assert result.accepted == 2
    assert result.parse_failures == 1
    assert [c.candidate_id for c in result.candidates] == ["meet-001-C0000", "meet-001-C0001"]
    rows = db_session.query(ModelCall).filter(ModelCall.stage == "extract").all()
    assert len(rows) == 3
    assert sorted(r.input_tokens for r in rows) == [0, 100, 100]
