"""Classification schema and Relation enum for stage boundary."""

from enum import Enum

from pydantic import BaseModel


class Relation(str, Enum):
    """Six-value relation classification."""

    NEW = "new"
    REFINEMENT = "refinement"
    CONTRADICTION = "contradiction"
    SUPERSESSION = "supersession"
    RESTATEMENT = "restatement"
    NOT_REQUIREMENT = "not_requirement"


class Classification(BaseModel):
    """Classification result from LLM-2."""

    matched_requirement_id: str | None  # None == no_match
    relation: Relation
    rationale: str
    retrieved_ids: list[str]  # what was actually offered
