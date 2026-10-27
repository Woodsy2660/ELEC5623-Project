"""FR07/FR08: strict response checks and an adapter to Lucas's pure proposal rules."""

import json

from pydantic import BaseModel, ConfigDict, Field, ValidationError

from src.classify.schemas import (
    Classification,
    ClassificationInput,
    PreparedClassificationRequest,
    Relation,
)
from src.engine.proposal_rules import RuleVerdict, assess_proposal


class ClassificationOutputError(ValueError):
    """Invalid raw prediction. Count it as an error; never repair or default it."""


class _Prediction(BaseModel):
    model_config = ConfigDict(extra="forbid")

    matched_requirement_id: str | None = Field(..., min_length=1, strict=True)
    relation: Relation
    rationale: str = Field(min_length=1, strict=True)
    # Absent only for fixtures written before the field existed. The live schema requires it.
    replacement_stated: bool = Field(default=False, strict=True)


def _unique_keys(pairs: list[tuple[str, object]]) -> dict[str, object]:
    result = {}
    for key, value in pairs:
        if key in result:
            raise ClassificationOutputError("Duplicate JSON field")
        result[key] = value
    return result


def _reject_constant(value: str) -> None:
    raise ClassificationOutputError(f"Non-JSON constant: {value}")


def decode_output(
    content: str,
    request: PreparedClassificationRequest,
) -> Classification:
    """Validate the raw JSON content; provenance comes from the request, not the model.

    Refusal/truncation envelopes and retries belong to the future shared logged
    caller. A refusal must not be passed here as a substituted prediction.
    """
    try:
        data = json.loads(content, object_pairs_hook=_unique_keys, parse_constant=_reject_constant)
        prediction = _Prediction.model_validate(data)
    except (json.JSONDecodeError, ValidationError, TypeError) as exc:
        raise ClassificationOutputError("Invalid classification JSON or fields") from exc
    matched, relation = prediction.matched_requirement_id, prediction.relation
    if matched is not None and matched not in request.retrieved_ids:
        raise ClassificationOutputError("Model selected an ID outside the offered list")
    if relation == Relation.NEW and matched is not None:
        raise ClassificationOutputError("New requirement must use null for no_match")
    if relation not in {Relation.NEW, Relation.NOT_REQUIREMENT} and matched is None:
        raise ClassificationOutputError("Historical relationship requires an offered ID")
    if not prediction.rationale.strip():
        raise ClassificationOutputError("Rationale must not be blank")
    return Classification(
        matched_requirement_id=matched,
        relation=relation,
        rationale=prediction.rationale,
        retrieved_ids=list(request.retrieved_ids),
        replacement_stated=prediction.replacement_stated,
    )


def assess_classification(
    inputs: ClassificationInput,
    classification: Classification,
    *,
    speaker_can_confirm_scope: bool,
    replacement_stated: bool,
) -> RuleVerdict:
    """Assess an already decoded prediction. Does not confirm, persist or derive guards.

    Authority is project configuration. Explicit replacement must be established
    from validated evidence by the agreed integration rule, not the LLM label.
    """
    inputs = ClassificationInput.model_validate(inputs.model_dump())
    if classification.retrieved_ids != inputs.retrieval.retrieved_ids:
        raise ClassificationOutputError("Classification retrieval provenance does not match inputs")
    if type(speaker_can_confirm_scope) is not bool or type(replacement_stated) is not bool:
        raise ValueError("Authority and replacement guards must be explicit booleans")
    heads = {head.requirement_id: head for head in inputs.current_heads}
    matched = classification.matched_requirement_id
    return assess_proposal(
        relation=classification.relation.value,
        matched_requirement_id=matched,
        retrieved_ids=classification.retrieved_ids,
        current_state=heads[matched].state if matched in heads else None,
        speaker_can_confirm_scope=speaker_can_confirm_scope,
        replacement_stated=replacement_stated,
    )
