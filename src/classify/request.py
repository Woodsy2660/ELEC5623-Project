"""FR07/FR08: prepare prompt data and a per-request ID enum; no inference or writes."""

import hashlib
import json
from pathlib import Path

from src.classify.schemas import (
    ClassificationInput,
    PreparedClassificationRequest,
    Relation,
)

PROMPT_PATH = Path(__file__).resolve().parents[2] / "prompts" / "classify_v1.txt"


def prepare_request(
    inputs: ClassificationInput,
    *,
    prompt_path: Path = PROMPT_PATH,
) -> PreparedClassificationRequest:
    """Read the versioned prompt; keep all transcript/history text in user data.

    The caller supplies an as-of-now history and authoritative current pointers.
    This function cannot infer meeting cutoffs or retrieve database state.
    """
    # Nested upstream models are mutable. Recheck them immediately before preparation.
    inputs = ClassificationInput.model_validate(inputs.model_dump())
    prompt_bytes = prompt_path.read_bytes()
    prompt = prompt_bytes.decode("utf-8")
    if not prompt.strip():
        raise ValueError("Classification prompt must not be empty")
    prompt_hash = hashlib.sha1(f"blob {len(prompt_bytes)}\0".encode() + prompt_bytes).hexdigest()
    heads = {head.requirement_id: head for head in inputs.current_heads}
    turns = {turn.turn_id: turn for turn in inputs.evidence_turns}
    payload = {
        "project_id": inputs.candidate.project_id,
        "candidate_id": inputs.candidate.candidate_id,
        "meeting_id": inputs.candidate.meeting_id,
        "candidate_text": inputs.candidate.text_norm,
        "speaker_label": inputs.speaker_label,
        "evidence": [
            {
                "turn_id": span.turn_id,
                "speaker_label": turns[span.turn_id].speaker_label,
                "start": span.start,
                "end": span.end,
                "quote": turns[span.turn_id].text[span.start : span.end],
                "turn_text": turns[span.turn_id].text,
            }
            for span in inputs.candidate.evidence
        ],
        "retrieved_families": [
            {
                "requirement_id": family.requirement_id,
                "current_version": heads[family.requirement_id].version,
                "current_state": heads[family.requirement_id].state.value,
                "versions": [
                    {
                        "version": version.version,
                        "text": version.text,
                        "state": version.state.value,
                    }
                    for version in sorted(family.versions, key=lambda v: v.version)
                ],
            }
            for family in inputs.retrieval.families
        ],
    }
    schema = {
        "type": "object",
        "properties": {
            "matched_requirement_id": {
                "type": ["string", "null"],
                "enum": [*inputs.retrieval.retrieved_ids, None],
            },
            "relation": {"type": "string", "enum": [relation.value for relation in Relation]},
            "rationale": {"type": "string"},
            "replacement_stated": {"type": "boolean"},
        },
        "required": [
            "matched_requirement_id",
            "relation",
            "rationale",
            "replacement_stated",
        ],
        "additionalProperties": False,
    }
    return PreparedClassificationRequest(
        candidate_id=inputs.candidate.candidate_id,
        project_id=inputs.candidate.project_id,
        prompt_hash=prompt_hash,
        retrieved_ids=tuple(inputs.retrieval.retrieved_ids),
        system_message=prompt,
        user_message=json.dumps(payload, ensure_ascii=False),
        output_schema=schema,
    )
