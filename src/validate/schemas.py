"""Evidence span schema for stage boundaries."""

from pydantic import BaseModel


class EvidenceSpan(BaseModel):
    """A reference to a span of text within a transcript turn."""

    turn_id: str  # "{meeting_id}:{turn_index}"
    start: int
    end: int
