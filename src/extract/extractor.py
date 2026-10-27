"""FR05: Candidate extraction from meeting transcripts.

The model returns quotes, NOT offsets. Language models cannot reliably count
characters. The model copies the exact substring; deterministic code finds it.
This is also why gold authoring works the same way - both sides resolve through
the same function.
"""

import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from jinja2 import Template
from openai import AzureOpenAI
from pydantic import BaseModel, ConfigDict, Field, ValidationError
from sqlalchemy.orm import Session

from src.extract.schemas import Candidate
from src.logging.calls import CallLogger, ModelCallError
from src.persist.models import Candidate as CandidateModel
from src.persist.models import Meeting, Turn
from src.validate.resolve import QuoteAmbiguous, QuoteNotFound, resolve_quote
from src.validate.schemas import EvidenceSpan

PROMPT_PATH = Path(__file__).resolve().parents[2] / "prompts" / "extract_v1.jinja"


class ExtractionError(Exception):
    """Error during candidate extraction."""

    pass


class _EvidenceItem(BaseModel):
    """Evidence quote from the model response."""

    model_config = ConfigDict(extra="forbid")

    turn_id: str = Field(min_length=1)
    quote: str = Field(min_length=1)


class _CandidateItem(BaseModel):
    """Candidate from the model response."""

    model_config = ConfigDict(extra="forbid")

    statement: str = Field(min_length=1)
    evidence: list[_EvidenceItem] = Field(min_length=1)


class _ExtractionResponse(BaseModel):
    """Expected response structure from the model."""

    model_config = ConfigDict(extra="forbid")

    candidates: list[_CandidateItem]


@dataclass
class ExtractionResult:
    """Result of extracting candidates from a meeting."""

    candidates: list[Candidate]
    returned: int = 0
    accepted: int = 0
    rejected_unresolvable: int = 0
    parse_failures: int = 0
    call_id: str | None = None


def _render_prompt(turns: list[dict[str, str]]) -> str:
    """Render the extraction prompt with the meeting turns."""
    template_content = PROMPT_PATH.read_text(encoding="utf-8")
    template = Template(template_content)
    return template.render(turns=turns)


def _build_schema() -> dict[str, Any]:
    """Build the JSON schema for extraction response."""
    return {
        "type": "json_schema",
        "json_schema": {
            "name": "extraction_result",
            "strict": True,
            "schema": {
                "type": "object",
                "properties": {
                    "candidates": {
                        "type": "array",
                        "items": {
                            "type": "object",
                            "properties": {
                                "statement": {"type": "string"},
                                "evidence": {
                                    "type": "array",
                                    "items": {
                                        "type": "object",
                                        "properties": {
                                            "turn_id": {"type": "string"},
                                            "quote": {"type": "string"},
                                        },
                                        "required": ["turn_id", "quote"],
                                        "additionalProperties": False,
                                    },
                                },
                            },
                            "required": ["statement", "evidence"],
                            "additionalProperties": False,
                        },
                    },
                },
                "required": ["candidates"],
                "additionalProperties": False,
            },
        },
    }


def _resolve_evidence(
    evidence_items: list[_EvidenceItem],
    turns_text: dict[str, str],
    meeting_id: str,
) -> tuple[list[EvidenceSpan], list[str]]:
    """Resolve evidence quotes to spans.

    Returns:
        Tuple of (resolved_spans, error_messages).
    """
    spans: list[EvidenceSpan] = []
    errors: list[str] = []

    for item in evidence_items:
        turn_id = item.turn_id
        quote = item.quote

        if turn_id not in turns_text:
            errors.append(f"Unknown turn_id: {turn_id}")
            continue

        turn_text = turns_text[turn_id]

        try:
            start, end = resolve_quote(turn_text, quote)
            spans.append(EvidenceSpan(turn_id=turn_id, start=start, end=end))
        except QuoteNotFound:
            errors.append(f"Quote not found in {turn_id}: {quote!r}")
        except QuoteAmbiguous:
            errors.append(f"Quote ambiguous in {turn_id}: {quote!r}")

    return spans, errors


def extract_candidates(
    session: Session,
    client: AzureOpenAI,
    *,
    run_id: str,
    meeting_id: str,
    deployment_name: str,
    temperature: float = 0.0,
    seed: int | None = 42,
    runs_dir: Path = Path("runs"),
) -> ExtractionResult:
    """Extract candidates from a meeting transcript.

    Args:
        session: Database session.
        client: Azure OpenAI client.
        run_id: Run ID for logging.
        meeting_id: Meeting to extract from.
        deployment_name: Model deployment name.
        temperature: Temperature setting.
        seed: Random seed.
        runs_dir: Directory for raw response files.

    Returns:
        ExtractionResult with candidates and counts.

    Raises:
        ExtractionError: If the meeting doesn't exist or extraction fails.
    """
    # Load meeting and verify it exists
    meeting = session.get(Meeting, meeting_id)
    if meeting is None:
        raise ExtractionError(f"Meeting not found: {meeting_id}")

    project_id = meeting.project_id

    # Load turns in order, scoped to the meeting
    turns = (
        session.query(Turn).filter(Turn.meeting_id == meeting_id).order_by(Turn.turn_index).all()
    )

    if not turns:
        raise ExtractionError(f"No turns found for meeting: {meeting_id}")

    # Build turns data for the prompt
    turns_data = [
        {"turn_id": turn.id, "speaker": turn.speaker, "text": turn.text} for turn in turns
    ]

    # Build turns lookup for resolution
    turns_text = {turn.id: turn.text for turn in turns}

    # Render prompt
    prompt_content = _render_prompt(turns_data)

    # Build messages
    messages = [
        {"role": "user", "content": prompt_content},
    ]

    # Make the model call
    result = ExtractionResult(candidates=[])

    with CallLogger(
        session,
        client,
        deployment_name=deployment_name,
        temperature=temperature,
        seed=seed,
        runs_dir=runs_dir,
    ) as logger:
        try:
            response = logger.call(
                run_id=run_id,
                stage="extract",
                prompt_path=PROMPT_PATH,
                messages=messages,
                response_format=_build_schema(),
            )
            result.call_id = response.call_id
        except ModelCallError:
            result.parse_failures = 1
            return result

    # Parse the response
    try:
        data = json.loads(response.content)
        extraction = _ExtractionResponse.model_validate(data)
    except (json.JSONDecodeError, ValidationError):
        result.parse_failures = 1
        return result

    result.returned = len(extraction.candidates)

    # Process each candidate
    for idx, item in enumerate(extraction.candidates):
        candidate_id = f"{meeting_id}-C{idx:04d}"

        # Resolve evidence quotes to spans
        spans, errors = _resolve_evidence(item.evidence, turns_text, meeting_id)

        if errors or not spans:
            # Candidate rejected - evidence doesn't resolve
            result.rejected_unresolvable += 1
            continue

        # Create candidate
        candidate = Candidate(
            candidate_id=candidate_id,
            project_id=project_id,
            meeting_id=meeting_id,
            text_norm=item.statement,
            evidence=spans,
            atomic=True,
        )

        # Persist to database
        evidence_json = json.dumps(
            [{"turn_id": s.turn_id, "start": s.start, "end": s.end} for s in spans]
        )

        db_candidate = CandidateModel(
            id=candidate_id,
            meeting_id=meeting_id,
            run_id=run_id,
            text_norm=item.statement,
            evidence_json=evidence_json,
            extract_call_id=response.call_id,
        )
        session.add(db_candidate)

        result.candidates.append(candidate)
        result.accepted += 1

    session.flush()
    return result
