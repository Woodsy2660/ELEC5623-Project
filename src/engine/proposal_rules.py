"""Deterministic proposal rules for requirement lifecycle changes (FR11).

This module deliberately accepts primitive values rather than Pydantic stage models.
``src.engine`` must remain standard-library-only; the integration layer converts a
classification result to these arguments before calling :func:`assess_proposal`.
"""

from collections.abc import Collection
from dataclasses import dataclass
from enum import Enum

from src.engine.state_machine import EventType, State, validate_transition


class Verdict(str, Enum):
    """Outcome of deterministic validation before a proposal can be confirmed."""

    ALLOWED = "allowed"
    REJECTED = "rejected"
    UNRESOLVED = "unresolved"
    NO_OP = "no_op"


@dataclass(frozen=True)
class RuleVerdict:
    """A deterministic assessment of one classification proposal."""

    verdict: Verdict
    proposed_event: EventType | None
    resulting_state: State | None
    reason: str


_EVENT_BY_RELATION: dict[str, EventType] = {
    "new": EventType.CREATE,
    "refinement": EventType.REFINE,
    "contradiction": EventType.CONTRADICT,
    "supersession": EventType.SUPERSEDE,
}
_NO_OP_RELATIONS = {"restatement", "not_requirement"}


def assess_proposal(
    *,
    relation: str,
    matched_requirement_id: str | None,
    retrieved_ids: Collection[str],
    current_state: State | None,
    speaker_can_confirm_scope: bool,
    replacement_stated: bool,
) -> RuleVerdict:
    """Map a classification result to an allowed lifecycle event or a safe verdict.

    ``current_state`` is the state of ``matched_requirement_id``. It must be
    ``None`` for a ``new`` candidate. ``replacement_stated`` is intentionally an
    explicit input: deriving it from evidence text belongs to the integration
    contract with Tracks A and B, not to this pure state engine.
    """
    if relation not in {*_EVENT_BY_RELATION, *_NO_OP_RELATIONS}:
        return _rejected("unknown relation")

    if matched_requirement_id is not None and matched_requirement_id not in retrieved_ids:
        return _rejected("matched requirement was not retrieved")

    if relation == "new":
        if matched_requirement_id is not None:
            return _rejected("new relation must not name a historical requirement")
        if current_state is not None:
            return _rejected("new relation must not have a current state")
        return _allowed(EventType.CREATE, None)

    if relation == "not_requirement":
        return RuleVerdict(Verdict.NO_OP, None, current_state, "not a lifecycle statement")

    if matched_requirement_id is None:
        return _rejected("relation requires a matched requirement")
    if current_state is None:
        return _rejected("matched requirement has no current state")

    if relation == "restatement":
        return RuleVerdict(Verdict.NO_OP, None, current_state, "restatement has no state change")

    if relation == "supersession" and (not speaker_can_confirm_scope or not replacement_stated):
        return RuleVerdict(
            Verdict.UNRESOLVED,
            None,
            current_state,
            "supersession requires an authorised speaker and an explicit replacement",
        )

    event_type = _EVENT_BY_RELATION[relation]
    return _allowed(event_type, current_state)


def _allowed(event_type: EventType, from_state: State | None) -> RuleVerdict:
    resulting_state = validate_transition(from_state, event_type)
    if resulting_state is None:
        return _rejected(f"{event_type.value} is illegal from {from_state}")
    return RuleVerdict(Verdict.ALLOWED, event_type, resulting_state, "valid transition")


def _rejected(reason: str) -> RuleVerdict:
    return RuleVerdict(Verdict.REJECTED, None, None, reason)
