"""Classification schema and Relation enum for stage boundary."""

from enum import Enum
from typing import Any

from pydantic import BaseModel, ConfigDict, Field, model_validator

from src.engine.state_machine import State
from src.extract.schemas import Candidate
from src.retrieve.schemas import RetrievalResult


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
    # The model's own claim. A soft downgrade may change relation and leave this false.
    replacement_stated: bool = False


class EvidenceTurn(BaseModel):
    """Stored source text supplied by ingestion, not invented by a model."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    project_id: str = Field(min_length=1, strict=True)
    meeting_id: str = Field(min_length=1, strict=True)
    turn_id: str = Field(min_length=1, strict=True)
    speaker_label: str = Field(min_length=1, strict=True)
    text: str = Field(min_length=1, strict=True)


class CurrentHead(BaseModel):
    """Authoritative current pointer from persistence; never infer it from max(version)."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    requirement_id: str = Field(min_length=1, strict=True)
    version: int = Field(ge=1, strict=True)
    state: State


class ClassificationInput(BaseModel):
    """FR07/FR08 inputs after evidence validation and project-scoped retrieval."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    candidate: Candidate
    retrieval: RetrievalResult
    evidence_turns: tuple[EvidenceTurn, ...]
    current_heads: tuple[CurrentHead, ...]
    speaker_label: str = Field(min_length=1, strict=True)

    @model_validator(mode="after")
    def consistent_context(self) -> "ClassificationInput":
        candidate, retrieval = self.candidate, self.retrieval
        if not candidate.atomic or not candidate.text_norm.strip():
            raise ValueError("Classification requires a nonblank atomic candidate")
        if retrieval.candidate_id != candidate.candidate_id:
            raise ValueError("Retrieval belongs to a different candidate")
        if retrieval.project_id != candidate.project_id:
            raise ValueError("Retrieval belongs to a different project")
        if not candidate.evidence:
            raise ValueError("Classification requires source evidence")
        turns = {turn.turn_id: turn for turn in self.evidence_turns}
        if len(turns) != len(self.evidence_turns):
            raise ValueError("Duplicate evidence turn ID")
        if set(turns) != {span.turn_id for span in candidate.evidence}:
            raise ValueError("Supply exactly the source turns referenced by the candidate")
        if any(
            turn.project_id != candidate.project_id or turn.meeting_id != candidate.meeting_id
            for turn in turns.values()
        ):
            raise ValueError("Evidence belongs to a different project or meeting")
        if self.speaker_label not in {turn.speaker_label for turn in turns.values()}:
            raise ValueError("Candidate speaker is absent from source evidence")
        spans = set()
        for span in candidate.evidence:
            key = (span.turn_id, span.start, span.end)
            if key in spans:
                raise ValueError("Duplicate evidence span")
            spans.add(key)
            text = turns[span.turn_id].text
            if not 0 <= span.start < span.end <= len(text):
                raise ValueError("Evidence offsets do not resolve to a stored turn")
            if not text[span.start : span.end].strip():
                raise ValueError("Evidence span must contain text")
        families = {family.requirement_id: family for family in retrieval.families}
        if len(families) != len(retrieval.families):
            raise ValueError("Duplicate retrieved family ID")
        for family in families.values():
            if not family.versions:
                raise ValueError("Retrieved family has no versions")
            if len({v.version for v in family.versions}) != len(family.versions):
                raise ValueError("Duplicate historical version")
            if any(
                v.project_id != candidate.project_id or v.requirement_id != family.requirement_id
                for v in family.versions
            ):
                raise ValueError("Historical version belongs to a different project or family")
        heads = {head.requirement_id: head for head in self.current_heads}
        if len(heads) != len(self.current_heads) or set(heads) != set(families):
            raise ValueError("Supply one authoritative current head per retrieved family")
        for family_id, head in heads.items():
            version = next(
                (v for v in families[family_id].versions if v.version == head.version), None
            )
            if version is None or version.state != head.state:
                raise ValueError("Current head disagrees with supplied history")
        return self


class PreparedClassificationRequest(BaseModel):
    """Local request preparation only. A shared logged model caller consumes this."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    candidate_id: str
    project_id: str
    prompt_hash: str
    retrieved_ids: tuple[str, ...]
    system_message: str
    user_message: str
    output_schema: dict[str, Any]
