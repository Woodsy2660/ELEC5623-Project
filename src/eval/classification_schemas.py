"""Label-free saved predictions for development E3-oracle scoring; no model calls."""

from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator


class CaseIdentity(BaseModel):
    """Candidate alignment is supplied by the caller, scoped to a project."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    project_id: str = Field(min_length=1, strict=True)
    case_id: str = Field(min_length=1, strict=True)

    @model_validator(mode="after")
    def nonblank_identity(self) -> "CaseIdentity":
        if not self.project_id.strip() or not self.case_id.strip():
            raise ValueError("Project and case IDs must not be blank")
        return self


class ClassificationObservation(CaseIdentity):
    """One final raw prediction or explicit failure, before human correction.

    Offered IDs are request provenance, never copied from model-generated fields.
    None means unavailable, not an empty retrieval result.
    """

    status: Literal["ok", "error", "unresolved"]
    offered_ids: tuple[str, ...] | None = None
    raw_content: str | None = Field(default=None, strict=True)
    error: str | None = Field(default=None, min_length=1, strict=True)

    @model_validator(mode="after")
    def valid_observation(self) -> "ClassificationObservation":
        if self.status == "ok" and (self.raw_content is None or self.error is not None):
            raise ValueError("An ok observation requires raw_content and no error")
        if self.status != "ok" and (self.error is None or not self.error.strip()):
            raise ValueError("A failure requires an explicit nonblank error")
        if self.offered_ids is not None:
            if any(not isinstance(value, str) or not value.strip() for value in self.offered_ids):
                raise ValueError("Offered IDs must be nonblank strings")
            if len(self.offered_ids) != len(set(self.offered_ids)):
                raise ValueError("Duplicate offered ID")
        return self


class ClassificationRun(BaseModel):
    """Dev-only E3-oracle manifest. Malformed identifiable cases are scored as errors.

    This file contains predictions and run provenance, never expected labels.
    It is not an extraction aligner, live runner or database/harness contract.
    """

    model_config = ConfigDict(extra="forbid", frozen=True)

    schema_version: Literal[1] = 1
    kind: Literal["dev-e3-oracle"]
    split: Literal["dev"]
    method: Literal["pipeline", "full_history", "baseline"]
    run_id: str = Field(min_length=1, strict=True)
    repeat_index: int = Field(ge=1, le=3, strict=True)
    model: str = Field(min_length=1, strict=True)
    prompt_hash: str = Field(pattern=r"^[0-9a-f]{40}$", strict=True)
    inputs_sha256: str = Field(pattern=r"^[0-9a-f]{64}$", strict=True)
    cases: tuple[dict[str, Any], ...]

    @model_validator(mode="after")
    def nonblank_metadata(self) -> "ClassificationRun":
        if not self.run_id.strip() or not self.model.strip():
            raise ValueError("Run ID and model must not be blank")
        return self
