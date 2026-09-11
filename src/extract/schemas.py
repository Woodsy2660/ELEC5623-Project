"""Candidate schema for extraction stage boundary."""

from pydantic import BaseModel

from src.validate.schemas import EvidenceSpan


class Candidate(BaseModel):
    """An extracted candidate requirement statement."""

    candidate_id: str
    project_id: str
    meeting_id: str
    text_norm: str
    evidence: list[EvidenceSpan]
    atomic: bool = True
