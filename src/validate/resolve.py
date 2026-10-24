"""FR06: Evidence span resolution and validation.

This module provides EXACT substring matching for evidence validation.
No regex, no normalisation, no case folding, no whitespace tolerance, no fuzzy matching.

The canonical file was normalised once at authoring time and is frozen.
Any tolerance here silently accepts evidence that does not exist in the transcript.
"""

from dataclasses import dataclass

from src.validate.schemas import EvidenceSpan


class QuoteNotFound(Exception):
    """Raised when a quote does not appear in the turn text."""

    pass


class QuoteAmbiguous(Exception):
    """Raised when a quote appears more than once in the turn text."""

    pass


def resolve_quote(turn_text: str, quote: str) -> tuple[int, int]:
    """Find the exact position of a quote within turn text.

    Args:
        turn_text: The full text of the turn.
        quote: The exact substring to find.

    Returns:
        (start, end) character offsets of the quote within turn_text.

    Raises:
        QuoteNotFound: If the quote does not appear in turn_text.
        QuoteAmbiguous: If the quote appears more than once.

    Note:
        This is EXACT substring matching. No .strip(), .lower(), regex, or difflib.
        The quote must match the turn text byte-for-byte.
    """
    if not quote:
        raise QuoteNotFound("Empty quote")

    first_pos = turn_text.find(quote)
    if first_pos == -1:
        raise QuoteNotFound(f"Quote not found in turn text: {quote!r}")

    # Check for ambiguity: is there another occurrence?
    second_pos = turn_text.find(quote, first_pos + 1)
    if second_pos != -1:
        raise QuoteAmbiguous(f"Quote appears multiple times in turn text: {quote!r}")

    return (first_pos, first_pos + len(quote))


def validate_span(turn_text: str, start: int, end: int) -> bool:
    """Validate that span offsets are within bounds.

    Args:
        turn_text: The full text of the turn.
        start: Start offset (inclusive).
        end: End offset (exclusive).

    Returns:
        True if 0 <= start < end <= len(turn_text), False otherwise.
    """
    return 0 <= start < end <= len(turn_text)


@dataclass(frozen=True)
class ValidationResult:
    """Result of validating a candidate's evidence spans."""

    ok: bool
    reason: str | None = None


def validate_candidate(
    turns: dict[str, str],
    evidence: list[EvidenceSpan],
) -> ValidationResult:
    """Validate all evidence spans for a candidate.

    Args:
        turns: Mapping of turn_id to turn text.
        evidence: List of evidence spans to validate.

    Returns:
        ValidationResult with ok=True if all spans resolve, or ok=False with reason.

    Note:
        A candidate with any unresolvable span is rejected whole.
        Never partially accepted, never repaired.
    """
    if not evidence:
        return ValidationResult(ok=False, reason="No evidence spans provided")

    for span in evidence:
        # Check turn exists
        if span.turn_id not in turns:
            return ValidationResult(ok=False, reason=f"Unknown turn_id: {span.turn_id}")

        turn_text = turns[span.turn_id]

        # Validate bounds
        if not validate_span(turn_text, span.start, span.end):
            return ValidationResult(
                ok=False,
                reason=f"Invalid span bounds for {span.turn_id}: "
                f"start={span.start}, end={span.end}, len={len(turn_text)}",
            )

        # Verify the span actually contains text (not empty)
        if span.start == span.end:
            return ValidationResult(
                ok=False,
                reason=f"Empty span for {span.turn_id}: start=end={span.start}",
            )

    return ValidationResult(ok=True)


def extract_quote(turn_text: str, start: int, end: int) -> str:
    """Extract the quoted text from a turn given offsets.

    Args:
        turn_text: The full text of the turn.
        start: Start offset (inclusive).
        end: End offset (exclusive).

    Returns:
        The substring turn_text[start:end].

    Raises:
        ValueError: If offsets are invalid.
    """
    if not validate_span(turn_text, start, end):
        raise ValueError(f"Invalid span: start={start}, end={end}, len={len(turn_text)}")
    return turn_text[start:end]
