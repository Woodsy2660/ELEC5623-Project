"""Tests for src/logging/calls.py - shared model call logger.

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

from src.logging.calls import CallLogger, ModelCallError, call_model
from src.persist.models import Base, ModelCall, Run


class FakeUsage:
    """Fake usage object for mocking."""

    def __init__(self, prompt_tokens: int, completion_tokens: int):
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

    def __init__(
        self,
        content: str,
        model: str = "gpt-4o-mini-2024-07-18",
        prompt_tokens: int = 100,
        completion_tokens: int = 50,
    ):
        self.choices = [FakeChoice(content)]
        self.model = model
        self.usage = FakeUsage(prompt_tokens, completion_tokens)

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
    """Create an in-memory database session for testing."""
    from datetime import UTC, datetime

    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)
    SessionLocal = sessionmaker(bind=engine)
    session = SessionLocal()

    # Create a run for foreign key constraint
    run = Run(
        id="test-run-001",
        mode="extract",
        candidate_source="model",
        repeat_index=0,
        prompt_hash="abc123",
        model_deployment="gpt-4o-mini",
        temp=0.0,
        started_at=datetime.now(UTC),
    )
    session.add(run)
    session.commit()

    yield session
    session.close()


@pytest.fixture
def temp_runs_dir():
    """Create a temporary directory for raw response files."""
    with tempfile.TemporaryDirectory() as tmpdir:
        yield Path(tmpdir)


@pytest.fixture
def prompt_file(temp_runs_dir):
    """Create a temporary prompt file for testing."""
    prompt_path = temp_runs_dir / "test_prompt.jinja"
    prompt_path.write_text("Test prompt content", encoding="utf-8")
    return prompt_path


class TestCallModel:
    """Tests for the call_model function."""

    def test_successful_call_returns_parsed_response(self, temp_runs_dir, prompt_file):
        """A successful call returns ParsedResponse with all fields populated."""
        # Create fake client
        client = MagicMock()
        response_content = json.dumps({"candidates": []})
        client.chat.completions.create.return_value = FakeCompletion(
            content=response_content,
            model="gpt-4o-mini-2024-07-18",
            prompt_tokens=150,
            completion_tokens=75,
        )

        # Make the call
        parsed, row_data = call_model(
            client,
            run_id="test-run-001",
            stage="extract",
            prompt_path=prompt_file,
            messages=[{"role": "user", "content": "Test message"}],
            deployment_name="gpt-4o-mini",
            temperature=0.0,
            seed=42,
            runs_dir=temp_runs_dir,
        )

        # Verify ParsedResponse fields
        assert parsed.call_id is not None
        assert len(parsed.call_id) == 36  # UUID format
        assert parsed.content == response_content
        assert parsed.input_tokens == 150
        assert parsed.output_tokens == 75
        assert parsed.served_model == "gpt-4o-mini-2024-07-18"
        assert parsed.latency_ms >= 0
        assert parsed.retries == 0

    def test_successful_call_writes_raw_json_file(self, temp_runs_dir, prompt_file):
        """A successful call writes raw JSON to disk at the recorded path."""
        client = MagicMock()
        response_content = json.dumps({"candidates": []})
        client.chat.completions.create.return_value = FakeCompletion(content=response_content)

        parsed, row_data = call_model(
            client,
            run_id="test-run-001",
            stage="extract",
            prompt_path=prompt_file,
            messages=[{"role": "user", "content": "Test"}],
            deployment_name="gpt-4o-mini",
            runs_dir=temp_runs_dir,
        )

        # Verify raw JSON file exists at recorded path
        raw_path = Path(row_data["raw_json_path"])
        assert raw_path.exists()

        # Verify contents are valid JSON
        raw_data = json.loads(raw_path.read_text(encoding="utf-8"))
        assert "choices" in raw_data
        assert "model" in raw_data

    def test_row_data_has_all_fields(self, temp_runs_dir, prompt_file):
        """Row data dict contains all required fields for model_calls table."""
        client = MagicMock()
        client.chat.completions.create.return_value = FakeCompletion(
            content='{"candidates": []}',
            model="gpt-4o-mini-2024-07-18",
            prompt_tokens=100,
            completion_tokens=50,
        )

        parsed, row_data = call_model(
            client,
            run_id="test-run-001",
            stage="extract",
            prompt_path=prompt_file,
            messages=[{"role": "user", "content": "Test"}],
            deployment_name="gpt-4o-mini",
            temperature=0.5,
            seed=123,
            runs_dir=temp_runs_dir,
        )

        # Verify all required fields
        assert row_data["id"] == parsed.call_id
        assert row_data["run_id"] == "test-run-001"
        assert row_data["stage"] == "extract"
        assert row_data["deployment_name"] == "gpt-4o-mini"
        assert row_data["served_model"] == "gpt-4o-mini-2024-07-18"
        assert row_data["prompt_hash"] is not None
        assert len(row_data["prompt_hash"]) == 40  # SHA-1 hex
        assert row_data["temperature"] == 0.5
        assert row_data["seed"] == 123
        assert row_data["input_tokens"] == 100
        assert row_data["output_tokens"] == 50
        assert row_data["latency_ms"] >= 0
        assert row_data["retries"] == 0
        assert row_data["cost"] >= 0
        assert row_data["raw_json_path"] is not None

    def test_schema_failure_retries_once(self, temp_runs_dir, prompt_file):
        """A schema failure retries once, logs retries=1, and raises on second failure."""
        client = MagicMock()
        # First call fails, second call also fails
        client.chat.completions.create.side_effect = Exception("Schema validation failed")

        with pytest.raises(ModelCallError) as exc_info:
            call_model(
                client,
                run_id="test-run-001",
                stage="extract",
                prompt_path=prompt_file,
                messages=[{"role": "user", "content": "Test"}],
                deployment_name="gpt-4o-mini",
                runs_dir=temp_runs_dir,
            )

        # Verify the client was called twice (initial + 1 retry)
        assert client.chat.completions.create.call_count == 2
        assert "after retry" in str(exc_info.value)

    def test_schema_failure_succeeds_on_retry(self, temp_runs_dir, prompt_file):
        """A schema failure that succeeds on retry logs retries=1."""
        client = MagicMock()
        # First call fails, second succeeds
        client.chat.completions.create.side_effect = [
            Exception("Schema validation failed"),
            FakeCompletion(content='{"candidates": []}'),
        ]

        parsed, row_data = call_model(
            client,
            run_id="test-run-001",
            stage="extract",
            prompt_path=prompt_file,
            messages=[{"role": "user", "content": "Test"}],
            deployment_name="gpt-4o-mini",
            runs_dir=temp_runs_dir,
        )

        # Verify retry count
        assert parsed.retries == 1
        assert row_data["retries"] == 1

    def test_latency_is_populated_and_plausible(self, temp_runs_dir, prompt_file):
        """Latency_ms is populated and has a plausible value (>= 0)."""
        client = MagicMock()
        client.chat.completions.create.return_value = FakeCompletion(content='{"candidates": []}')

        parsed, row_data = call_model(
            client,
            run_id="test-run-001",
            stage="extract",
            prompt_path=prompt_file,
            messages=[{"role": "user", "content": "Test"}],
            deployment_name="gpt-4o-mini",
            runs_dir=temp_runs_dir,
        )

        # Latency should be non-negative (could be 0 for very fast fake calls)
        assert parsed.latency_ms >= 0
        assert row_data["latency_ms"] >= 0
        # Should be less than 10 seconds for a fake call
        assert parsed.latency_ms < 10000


class TestCallLogger:
    """Tests for the CallLogger context manager."""

    def test_successful_call_writes_model_calls_row(self, db_session, temp_runs_dir, prompt_file):
        """A successful call writes exactly one model_calls row with all fields."""
        client = MagicMock()
        client.chat.completions.create.return_value = FakeCompletion(
            content='{"candidates": []}',
            model="gpt-4o-mini-2024-07-18",
            prompt_tokens=100,
            completion_tokens=50,
        )

        with CallLogger(
            db_session,
            client,
            deployment_name="gpt-4o-mini",
            temperature=0.0,
            seed=42,
            runs_dir=temp_runs_dir,
        ) as logger:
            response = logger.call(
                run_id="test-run-001",
                stage="extract",
                prompt_path=prompt_file,
                messages=[{"role": "user", "content": "Test"}],
            )

        # Verify exactly one row was inserted
        rows = db_session.query(ModelCall).all()
        assert len(rows) == 1

        row = rows[0]
        assert row.id == response.call_id
        assert row.run_id == "test-run-001"
        assert row.stage == "extract"
        assert row.deployment_name == "gpt-4o-mini"
        assert row.served_model == "gpt-4o-mini-2024-07-18"
        assert row.prompt_hash is not None
        assert row.temperature == 0.0
        assert row.seed == 42
        assert row.input_tokens == 100
        assert row.output_tokens == 50
        assert row.latency_ms >= 0
        assert row.retries == 0
        assert row.cost >= 0
        assert row.raw_json_path is not None

        # Verify raw JSON file exists
        assert Path(row.raw_json_path).exists()

    def test_logger_raises_on_failure(self, db_session, temp_runs_dir, prompt_file):
        """CallLogger raises ModelCallError on failure after retry."""
        client = MagicMock()
        client.chat.completions.create.side_effect = Exception("API error")

        with pytest.raises(ModelCallError):
            with CallLogger(
                db_session,
                client,
                deployment_name="gpt-4o-mini",
                runs_dir=temp_runs_dir,
            ) as logger:
                logger.call(
                    run_id="test-run-001",
                    stage="extract",
                    prompt_path=prompt_file,
                    messages=[{"role": "user", "content": "Test"}],
                )

        # Verify no row was inserted on failure
        rows = db_session.query(ModelCall).all()
        assert len(rows) == 0
