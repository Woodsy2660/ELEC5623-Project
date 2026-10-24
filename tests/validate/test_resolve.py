"""Tests for evidence span resolution (FR06).

These tests verify:
- resolve_quote finds a unique quote and returns correct offsets
- zero matches raises QuoteNotFound
- a quote appearing twice in one turn raises QuoteAmbiguous
- a quote differing only by whitespace or case does NOT match
- every one of D1's 14 gold evidence spans resolves against the canonical files
"""

import json
from pathlib import Path

import pytest
import yaml

from src.validate.resolve import (
    QuoteAmbiguous,
    QuoteNotFound,
    ValidationResult,
    extract_quote,
    resolve_quote,
    validate_candidate,
    validate_span,
)
from src.validate.schemas import EvidenceSpan


class TestResolveQuote:
    """Tests for resolve_quote function."""

    def test_finds_unique_quote_returns_correct_offsets(self):
        """resolve_quote finds a unique quote and returns correct offsets."""
        turn_text = "The quick brown fox jumps over the lazy dog."
        quote = "brown fox"

        start, end = resolve_quote(turn_text, quote)

        assert start == 10
        assert end == 19
        assert turn_text[start:end] == quote

    def test_quote_at_start(self):
        """Quote at the beginning of the turn."""
        turn_text = "Hello world, how are you?"
        quote = "Hello"

        start, end = resolve_quote(turn_text, quote)

        assert start == 0
        assert end == 5
        assert turn_text[start:end] == quote

    def test_quote_at_end(self):
        """Quote at the end of the turn."""
        turn_text = "This is a test."
        quote = "a test."

        start, end = resolve_quote(turn_text, quote)

        assert start == 8
        assert end == 15
        assert turn_text[start:end] == quote

    def test_zero_matches_raises_quote_not_found(self):
        """Zero matches raises QuoteNotFound."""
        turn_text = "The quick brown fox jumps over the lazy dog."
        quote = "purple elephant"

        with pytest.raises(QuoteNotFound):
            resolve_quote(turn_text, quote)

    def test_empty_quote_raises_quote_not_found(self):
        """Empty quote raises QuoteNotFound."""
        turn_text = "Some text here."

        with pytest.raises(QuoteNotFound):
            resolve_quote(turn_text, "")

    def test_quote_appearing_twice_raises_quote_ambiguous(self):
        """A quote appearing twice in one turn raises QuoteAmbiguous."""
        turn_text = "The cat sat on the mat. The cat was happy."
        quote = "The cat"

        with pytest.raises(QuoteAmbiguous):
            resolve_quote(turn_text, quote)

    def test_whitespace_difference_does_not_match(self):
        """A quote differing only by whitespace does NOT match."""
        turn_text = "Users must log in using email."
        # Extra space in quote
        quote = "Users  must"

        with pytest.raises(QuoteNotFound):
            resolve_quote(turn_text, quote)

    def test_leading_trailing_whitespace_does_not_match(self):
        """A quote with leading/trailing whitespace does NOT match."""
        turn_text = "Users must log in using email."
        quote = " Users must"

        with pytest.raises(QuoteNotFound):
            resolve_quote(turn_text, quote)

    def test_case_difference_does_not_match(self):
        """A quote differing only by case does NOT match."""
        turn_text = "Users must log in using email."
        quote = "users must"  # lowercase

        with pytest.raises(QuoteNotFound):
            resolve_quote(turn_text, quote)

    def test_punctuation_difference_does_not_match(self):
        """A quote differing only by punctuation does NOT match."""
        turn_text = "Hello, world!"
        quote = "Hello world"  # missing comma

        with pytest.raises(QuoteNotFound):
            resolve_quote(turn_text, quote)


class TestValidateSpan:
    """Tests for validate_span function."""

    def test_valid_span(self):
        """Valid span returns True."""
        turn_text = "Hello world"
        assert validate_span(turn_text, 0, 5) is True
        assert validate_span(turn_text, 6, 11) is True
        assert validate_span(turn_text, 0, 11) is True

    def test_negative_start(self):
        """Negative start returns False."""
        turn_text = "Hello world"
        assert validate_span(turn_text, -1, 5) is False

    def test_start_equals_end(self):
        """start == end (empty span) returns False."""
        turn_text = "Hello world"
        assert validate_span(turn_text, 5, 5) is False

    def test_start_greater_than_end(self):
        """start > end returns False."""
        turn_text = "Hello world"
        assert validate_span(turn_text, 6, 5) is False

    def test_end_exceeds_length(self):
        """end > len(turn_text) returns False."""
        turn_text = "Hello world"  # len=11
        assert validate_span(turn_text, 0, 12) is False

    def test_start_equals_length(self):
        """start == len(turn_text) returns False (no valid end)."""
        turn_text = "Hello"  # len=5
        assert validate_span(turn_text, 5, 6) is False


class TestValidateCandidate:
    """Tests for validate_candidate function."""

    def test_all_spans_valid(self):
        """All valid spans returns ok=True."""
        turns = {
            "M01:0000": "Users must log in using email.",
            "M01:0001": "Passwords must be strong.",
        }
        evidence = [
            EvidenceSpan(turn_id="M01:0000", start=0, end=10),
            EvidenceSpan(turn_id="M01:0001", start=0, end=9),
        ]

        result = validate_candidate(turns, evidence)

        assert result.ok is True
        assert result.reason is None

    def test_empty_evidence_rejected(self):
        """Empty evidence list returns ok=False."""
        turns = {"M01:0000": "Some text."}

        result = validate_candidate(turns, [])

        assert result.ok is False
        assert "No evidence spans" in result.reason

    def test_unknown_turn_id_rejected(self):
        """Unknown turn_id returns ok=False."""
        turns = {"M01:0000": "Some text."}
        evidence = [EvidenceSpan(turn_id="M01:9999", start=0, end=5)]

        result = validate_candidate(turns, evidence)

        assert result.ok is False
        assert "Unknown turn_id" in result.reason

    def test_invalid_bounds_rejected(self):
        """Invalid span bounds returns ok=False."""
        turns = {"M01:0000": "Hello"}  # len=5
        evidence = [EvidenceSpan(turn_id="M01:0000", start=0, end=10)]

        result = validate_candidate(turns, evidence)

        assert result.ok is False
        assert "Invalid span bounds" in result.reason

    def test_empty_span_rejected(self):
        """Empty span (start==end) returns ok=False."""
        turns = {"M01:0000": "Hello"}
        evidence = [EvidenceSpan(turn_id="M01:0000", start=3, end=3)]

        result = validate_candidate(turns, evidence)

        assert result.ok is False
        # Empty spans fail bounds validation (start < end required)
        assert "Invalid span bounds" in result.reason or "Empty span" in result.reason


class TestExtractQuote:
    """Tests for extract_quote function."""

    def test_extracts_correct_substring(self):
        """Extracts the correct substring."""
        turn_text = "The quick brown fox."
        quote = extract_quote(turn_text, 4, 9)
        assert quote == "quick"

    def test_invalid_bounds_raises(self):
        """Invalid bounds raises ValueError."""
        turn_text = "Hello"
        with pytest.raises(ValueError):
            extract_quote(turn_text, 0, 10)


class TestD1GoldSpans:
    """Tests that all D1 gold evidence spans resolve correctly."""

    @pytest.fixture
    def d1_scenario_dir(self) -> Path:
        """Path to D1 scenario directory."""
        return Path(__file__).parents[2] / "scenarios" / "dev" / "D1"

    @pytest.fixture
    def d1_turns(self, d1_scenario_dir: Path) -> dict[str, str]:
        """Load all turns from D1 canonical files."""
        turns = {}
        canonical_dir = d1_scenario_dir / "canonical"

        for jsonl_path in sorted(canonical_dir.glob("*.jsonl")):
            with open(jsonl_path, encoding="utf-8") as f:
                for line in f:
                    if line.strip():
                        record = json.loads(line)
                        turns[record["turn_id"]] = record["text"]

        return turns

    @pytest.fixture
    def d1_gold_events(self, d1_scenario_dir: Path) -> list[dict]:
        """Load gold events from D1."""
        gold_path = d1_scenario_dir / "gold.yaml"
        with open(gold_path, encoding="utf-8") as f:
            gold_data = yaml.safe_load(f)
        return gold_data.get("events", [])

    def test_d1_scenario_exists(self, d1_scenario_dir: Path):
        """D1 scenario directory exists with required files."""
        assert d1_scenario_dir.exists()
        assert (d1_scenario_dir / "scenario.yaml").exists()
        assert (d1_scenario_dir / "gold.yaml").exists()
        assert (d1_scenario_dir / "canonical" / "M01.jsonl").exists()
        assert (d1_scenario_dir / "canonical" / "M02.jsonl").exists()

    def test_d1_has_14_gold_evidence_spans(self, d1_gold_events: list[dict]):
        """D1 has exactly 14 gold evidence spans."""
        total_spans = sum(
            len(event.get("evidence", [])) for event in d1_gold_events
        )
        assert total_spans == 14

    def test_all_d1_gold_spans_resolve(
        self, d1_turns: dict[str, str], d1_gold_events: list[dict]
    ):
        """Every one of D1's 14 gold evidence spans resolves against canonical files."""
        for event in d1_gold_events:
            for evidence in event.get("evidence", []):
                turn_id = evidence["turn_id"]
                quote = evidence["quote"]
                expected_start = evidence["start"]
                expected_end = evidence["end"]

                # Turn must exist
                assert turn_id in d1_turns, f"Unknown turn_id: {turn_id}"
                turn_text = d1_turns[turn_id]

                # Quote must resolve to exact offsets
                actual_start, actual_end = resolve_quote(turn_text, quote)
                assert actual_start == expected_start, (
                    f"Start mismatch for {turn_id}: "
                    f"expected {expected_start}, got {actual_start}"
                )
                assert actual_end == expected_end, (
                    f"End mismatch for {turn_id}: "
                    f"expected {expected_end}, got {actual_end}"
                )

                # Resolved text must equal the authored quote exactly
                resolved_text = turn_text[actual_start:actual_end]
                assert resolved_text == quote, (
                    f"Text mismatch for {turn_id}: "
                    f"expected {quote!r}, got {resolved_text!r}"
                )
