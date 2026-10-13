"""E3 development retrieval contracts. Inference inputs have no expected-match labels."""

from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator

from src.engine.state_machine import State
from src.extract.schemas import Candidate
from src.retrieve.schemas import RetrievalResult
from src.validate.schemas import EvidenceSpan


class HistoryVersion(BaseModel):
    """Caller-supplied snapshot: text/state/evidence must be correct at history_cutoff."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    project_id: str = Field(min_length=1)
    requirement_id: str = Field(min_length=1)
    version: int = Field(ge=1)
    text: str = Field(min_length=1)
    state: State
    available_after_meeting: int = Field(ge=1)
    evidence: tuple[EvidenceSpan, ...] = ()


class RetrievalCase(BaseModel):
    """Retrieval at a meeting's start, using retained history visible before that meeting."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    case_id: str = Field(min_length=1)
    meeting_ordinal: int = Field(ge=1)
    history_cutoff: int = Field(ge=0)
    candidate: Candidate
    history: tuple[HistoryVersion, ...]

    @model_validator(mode="after")
    def valid_cutoff(self) -> "RetrievalCase":
        if self.history_cutoff >= self.meeting_ordinal:
            raise ValueError("History cutoff must precede the candidate meeting")
        keys = [(v.project_id, v.requirement_id, v.version) for v in self.history]
        if len(keys) != len(set(keys)):
            raise ValueError("Duplicate history version")
        return self


class RetrievalDataset(BaseModel):
    """Dev only. This is not the final transcript/gold-event scenario format."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    schema_version: Literal[1] = 1
    split: Literal["dev"]
    cases: tuple[RetrievalCase, ...] = Field(min_length=1)

    @model_validator(mode="after")
    def unique_cases(self) -> "RetrievalDataset":
        ids = [case.case_id for case in self.cases]
        if len(ids) != len(set(ids)):
            raise ValueError("Duplicate case ID")
        return self


class RetrievalObservation(BaseModel):
    """One output or one explicit error; failures never disappear from the run."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    case_id: str
    result: RetrievalResult | None = None
    error: str | None = None

    @model_validator(mode="after")
    def output_or_error(self) -> "RetrievalObservation":
        if (self.result is None) == (self.error is None):
            raise ValueError("Provide exactly one retrieval result or error")
        return self
