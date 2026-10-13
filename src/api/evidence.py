"""Turn a stored transcript span into the pre-split evidence shape.

Character offsets are an input. They are not returned, and they are not part
of the HTTP schema. The frontend receives the three strings and concatenates
them.
"""

from src.api.schemas import EvidenceQuote
from src.validate.schemas import EvidenceSpan


def quote_from_span(*, speaker: str, text: str, span: EvidenceSpan) -> EvidenceQuote:
    """Slice ``text`` in Python and return the three visible pieces."""
    if span.start < 0 or span.end > len(text) or span.start > span.end:
        raise ValueError(f"span {span.start}:{span.end} is outside turn {span.turn_id}")
    return EvidenceQuote(
        turn_id=span.turn_id,
        speaker=speaker,
        before=text[: span.start],
        span=text[span.start : span.end],
        after=text[span.end :],
    )


def quote_unhighlighted(*, turn_id: str, speaker: str, text: str) -> EvidenceQuote:
    """A transcript turn with no evidence highlight."""
    return EvidenceQuote(turn_id=turn_id, speaker=speaker, before=text, span="", after="")
