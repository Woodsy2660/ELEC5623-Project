"""Deterministic rule-table tests for proposal validation (FR11, E4)."""

import pytest

from src.engine.proposal_rules import Verdict, assess_proposal
from src.engine.state_machine import EventType, State


def assess(**overrides: object):  # type: ignore[no-untyped-def]
    """Build a valid refinement input and override only the case under test."""
    values: dict[str, object] = {
        "relation": "refinement",
        "matched_requirement_id": "R01",
        "retrieved_ids": ["R01", "R02"],
        "current_state": State.CONFIRMED,
        "speaker_can_confirm_scope": True,
        "replacement_stated": True,
    }
    values.update(overrides)
    return assess_proposal(**values)  # type: ignore[arg-type]


@pytest.mark.parametrize(
    ("relation", "state", "event", "resulting_state"),
    [
        ("refinement", State.CONFIRMED, EventType.REFINE, State.CONFIRMED),
        ("contradiction", State.CONFIRMED, EventType.CONTRADICT, State.CONTRADICTED),
        ("supersession", State.CONFIRMED, EventType.SUPERSEDE, State.SUPERSEDED),
        ("supersession", State.CONTRADICTED, EventType.SUPERSEDE, State.SUPERSEDED),
    ],
)
def test_transition_relations_map_to_legal_events(
    relation: str, state: State, event: EventType, resulting_state: State
) -> None:
    result = assess(relation=relation, current_state=state)

    assert result.verdict is Verdict.ALLOWED
    assert result.proposed_event is event
    assert result.resulting_state is resulting_state


def test_new_maps_to_create_without_a_historical_requirement() -> None:
    result = assess(relation="new", matched_requirement_id=None, current_state=None)

    assert result.verdict is Verdict.ALLOWED
    assert result.proposed_event is EventType.CREATE
    assert result.resulting_state is State.PROPOSED


@pytest.mark.parametrize("relation", ["restatement", "not_requirement"])
def test_non_transition_relations_are_no_ops(relation: str) -> None:
    result = assess(relation=relation)

    assert result.verdict is Verdict.NO_OP
    assert result.proposed_event is None
    assert result.resulting_state is State.CONFIRMED


@pytest.mark.parametrize(
    "overrides",
    [
        {"relation": "new", "matched_requirement_id": "R01", "current_state": State.CONFIRMED},
        {"relation": "refinement", "matched_requirement_id": None},
        {"relation": "contradiction", "current_state": State.PROPOSED},
        {"matched_requirement_id": "R99"},
        {"relation": "unknown"},
    ],
)
def test_invalid_classification_or_transition_is_rejected(overrides: dict[str, object]) -> None:
    result = assess(**overrides)

    assert result.verdict is Verdict.REJECTED
    assert result.proposed_event is None


@pytest.mark.parametrize(
    "overrides",
    [
        {"speaker_can_confirm_scope": False},
        {"replacement_stated": False},
        {"speaker_can_confirm_scope": False, "replacement_stated": False},
    ],
)
def test_supersession_without_required_guard_is_unresolved(overrides: dict[str, object]) -> None:
    result = assess(relation="supersession", **overrides)

    assert result.verdict is Verdict.UNRESOLVED
    assert result.proposed_event is None
    assert result.resulting_state is State.CONFIRMED
