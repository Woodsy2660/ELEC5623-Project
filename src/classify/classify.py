"""FR07/FR08 caller. One logged classify call, one retry, then a recorded failure.

The model proposes a relation. This module does not confirm scope and does not
write the register. A supersession that says no replacement was stated is
downgraded to contradiction before the rule table sees it: a wrong contradiction
leaves agreed scope in place for a person to review, and a wrong supersession
would replace it.
"""

from dataclasses import dataclass
from pathlib import Path

from src.classify.output import ClassificationOutputError, decode_output
from src.classify.request import PROMPT_PATH, prepare_request
from src.classify.schemas import Classification, ClassificationInput, Relation
from src.logging.calls import CallLogger, ModelCallError, ParsedResponse


@dataclass(frozen=True)
class ClassificationOutcome:
    """Parsed proposal, the ids actually offered, and whether a soft downgrade fired."""

    retrieved_ids: tuple[str, ...]
    classification: Classification | None
    downgraded: bool
    model_relation: str | None
    error: str | None
    call_ids: tuple[str, ...]


def apply_soft_downgrade(classification: Classification) -> tuple[Classification, bool]:
    """Downgrade a self-contradicting supersession. Never repair any other violation."""
    if (
        classification.relation == Relation.SUPERSESSION
        and classification.replacement_stated is False
    ):
        return (
            classification.model_copy(update={"relation": Relation.CONTRADICTION}),
            True,
        )
    return classification, False


def _failure(
    retrieved_ids: tuple[str, ...],
    call_ids: tuple[str, ...],
    error: str,
) -> ClassificationOutcome:
    return ClassificationOutcome(
        retrieved_ids=retrieved_ids,
        classification=None,
        downgraded=False,
        model_relation=None,
        error=error,
        call_ids=call_ids,
    )


def classify_candidate(
    client,
    *,
    session,
    run_id: str,
    inputs: ClassificationInput,
    deployment_name: str,
    temperature: float = 0.0,
    seed: int | None = 42,
    runs_dir: Path = Path("runs"),
    logger: CallLogger | None = None,
) -> ClassificationOutcome:
    """Classify one candidate against the families retrieval actually returned.

    ``inputs.speaker_label`` is a label. Authority is not an argument here.
    Hard schema or consistency failures are retried once, then returned as an
    error outcome. The response is not rewritten into a legal prediction.
    """
    prepared = prepare_request(inputs)
    retrieved_ids = tuple(prepared.retrieved_ids)
    if logger is None:
        logger = CallLogger(
            session,
            client,
            deployment_name=deployment_name,
            temperature=temperature,
            seed=seed,
            runs_dir=runs_dir,
        )
    messages = [
        {"role": "system", "content": prepared.system_message},
        {"role": "user", "content": prepared.user_message},
    ]
    response_format = {
        "type": "json_schema",
        "json_schema": {
            "name": "classification_result",
            "strict": True,
            "schema": prepared.output_schema,
        },
    }
    call_ids: list[str] = []
    last_error = "classification failed"
    for attempt in range(2):
        try:
            parsed: ParsedResponse = logger.call(
                run_id=run_id,
                stage="classify",
                prompt_path=PROMPT_PATH,
                messages=messages,
                response_format=response_format,
            )
        except ModelCallError as exc:
            # call_model has already retried the transport failure once.
            return _failure(retrieved_ids, tuple(call_ids), f"model call failed: {exc}")
        call_ids.append(parsed.call_id)
        try:
            decoded = decode_output(parsed.content, prepared)
        except ClassificationOutputError as exc:
            last_error = str(exc)
            if attempt == 0:
                continue
            return _failure(retrieved_ids, tuple(call_ids), last_error)
        downgraded_from = decoded.relation.value
        classification, downgraded = apply_soft_downgrade(decoded)
        return ClassificationOutcome(
            retrieved_ids=retrieved_ids,
            classification=classification,
            downgraded=downgraded,
            model_relation=downgraded_from,
            error=None,
            call_ids=tuple(call_ids),
        )
    return _failure(retrieved_ids, tuple(call_ids), last_error)
