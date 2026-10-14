"""FR10 stage contracts; vectors must come from the same pinned embedding model."""

import math

from pydantic import BaseModel, ConfigDict, Field, field_validator

from src.engine.state_machine import State
from src.extract.schemas import Candidate
from src.validate.schemas import EvidenceSpan


class VectorRecord(BaseModel):
    """A nonzero embedding with an explicit model/revision identifier."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    embedding_model: str = Field(min_length=1)
    embedding: tuple[float, ...] = Field(min_length=1)

    @field_validator("embedding")
    @classmethod
    def valid_vector(cls, value: tuple[float, ...]) -> tuple[float, ...]:
        """Invalid vectors are errors; never substitute zeros or another channel."""
        if not all(math.isfinite(component) for component in value):
            raise ValueError("Embedding components must be finite")
        if not any(value):
            raise ValueError("Embedding must be nonzero")
        return value


class RequirementVersion(VectorRecord):
    """A retained version supplied by the persistence layer, not read from its tables."""

    project_id: str = Field(min_length=1)
    requirement_id: str = Field(min_length=1)
    version: int = Field(ge=1)
    text: str = Field(min_length=1)
    state: State
    evidence: tuple[EvidenceSpan, ...] = ()


class RetrievalRequest(VectorRecord):
    """Candidate plus its embedding. Evidence validation happens upstream."""

    candidate: Candidate
    top_k: int = Field(default=5, gt=0)


class RetrievedFamily(BaseModel):
    """One stable family, including all retained versions for the classifier."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    requirement_id: str
    versions: tuple[RequirementVersion, ...]
    bm25_rank: int
    dense_rank: int
    rrf_score: float


class RetrievalResult(BaseModel):
    """Separate family rankings support E3 recall@3/@5/@8 in the evaluator."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    candidate_id: str
    project_id: str
    embedding_model: str
    families: tuple[RetrievedFamily, ...]
    bm25_family_ids: tuple[str, ...]
    dense_family_ids: tuple[str, ...]
    fused_family_ids: tuple[str, ...]

    @property
    def retrieved_ids(self) -> list[str]:
        """IDs offered to the next stage; this is not a match or a relation prediction."""
        return [family.requirement_id for family in self.families]
