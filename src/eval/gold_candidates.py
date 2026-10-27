"""Gold file entries as candidates. Labels stay out of this module.

The file is opened by the runners. Only statement text, evidence spans, and an
optional confirm/reject action are copied. Ground-truth labels stay in score.py.
"""

from dataclasses import dataclass

from src.extract.schemas import Candidate
from src.validate.schemas import EvidenceSpan

_DECISIONS = {"confirm", "reject"}


@dataclass(frozen=True)
class GoldCandidate:
    """A candidate plus the reviewer action, when the file actually has one."""

    candidate: Candidate
    event_action: str | None


def decision_action(event: dict) -> str | None:
    """Return confirm or reject. Any other ``event_action`` is not a decision."""
    raw = event.get("event_action")
    if isinstance(raw, str) and raw.strip().lower() in _DECISIONS:
        return raw.strip().lower()
    return None


def gold_candidate_from_event(
    event: dict,
    *,
    project_id: str,
    meeting_id: str,
    candidate_index: int,
    run_id: str,
) -> GoldCandidate:
    """Copy statement and evidence. Do not read relation or a requirement id."""
    evidence_in = event.get("evidence") or []
    spans = [
        EvidenceSpan(turn_id=item["turn_id"], start=int(item["start"]), end=int(item["end"]))
        for item in evidence_in
        if isinstance(item, dict) and "turn_id" in item and "start" in item and "end" in item
    ]
    statement = event.get("statement")
    if isinstance(statement, str) and statement.strip():
        text = statement.strip()
    elif evidence_in and isinstance(evidence_in[0], dict):
        quote = evidence_in[0].get("quote")
        text = quote.strip() if isinstance(quote, str) else ""
    else:
        text = ""
    candidate = Candidate(
        candidate_id=f"{meeting_id}-{run_id[:8]}-G{candidate_index:04d}",
        project_id=project_id,
        meeting_id=meeting_id,
        text_norm=text,
        evidence=spans,
        atomic=True,
    )
    return GoldCandidate(candidate=candidate, event_action=decision_action(event))
