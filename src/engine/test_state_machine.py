"""Tests for the state machine. The module under test remains stdlib-only."""

import pytest
from hypothesis import given
from hypothesis import strategies as st

from src.engine.state_machine import EventType, State, validate_transition

# Independent oracle transcribed from docs/02, never imported from production.
EXPECTED = {
    (None, "create"): "proposed",
    ("proposed", "confirm"): "confirmed",
    ("proposed", "reject"): "withdrawn",
    ("confirmed", "refine"): "confirmed",
    ("confirmed", "contradict"): "contradicted",
    ("confirmed", "supersede"): "superseded",
    ("contradicted", "supersede"): "superseded",
    ("contradicted", "resolve"): "confirmed",
}


def test_create_from_none_produces_proposed() -> None:
    """Creating a requirement produces Proposed state."""
    result = validate_transition(None, EventType.CREATE)
    assert result == State.PROPOSED


def test_confirm_proposed_produces_confirmed() -> None:
    """Confirming a proposed requirement produces Confirmed state."""
    result = validate_transition(State.PROPOSED, EventType.CONFIRM)
    assert result == State.CONFIRMED


def test_reject_proposed_produces_withdrawn() -> None:
    """Rejecting a proposed requirement produces Withdrawn state."""
    result = validate_transition(State.PROPOSED, EventType.REJECT)
    assert result == State.WITHDRAWN


def test_refine_confirmed_stays_confirmed() -> None:
    """Refining a confirmed requirement stays Confirmed (new version)."""
    result = validate_transition(State.CONFIRMED, EventType.REFINE)
    assert result == State.CONFIRMED


def test_contradict_confirmed_produces_contradicted() -> None:
    """Contradicting a confirmed requirement produces Contradicted state."""
    result = validate_transition(State.CONFIRMED, EventType.CONTRADICT)
    assert result == State.CONTRADICTED


def test_supersede_confirmed_produces_superseded() -> None:
    """Superseding a confirmed requirement produces Superseded state."""
    result = validate_transition(State.CONFIRMED, EventType.SUPERSEDE)
    assert result == State.SUPERSEDED


def test_supersede_contradicted_produces_superseded() -> None:
    """Superseding a contradicted requirement produces Superseded state."""
    result = validate_transition(State.CONTRADICTED, EventType.SUPERSEDE)
    assert result == State.SUPERSEDED


def test_resolve_contradicted_produces_confirmed() -> None:
    """Resolving a contradicted requirement produces Confirmed state."""
    result = validate_transition(State.CONTRADICTED, EventType.RESOLVE)
    assert result == State.CONFIRMED


def test_invalid_transition_returns_none() -> None:
    """Invalid transitions return None."""
    # Cannot confirm a confirmed requirement
    result = validate_transition(State.CONFIRMED, EventType.CONFIRM)
    assert result is None


def test_cannot_create_from_existing_state() -> None:
    """Cannot create from an existing state."""
    result = validate_transition(State.PROPOSED, EventType.CREATE)
    assert result is None


@pytest.mark.parametrize("from_state", [None, *State])
@pytest.mark.parametrize("event_type", list(EventType))
def test_only_documented_transitions_succeed(
    from_state: State | None, event_type: EventType
) -> None:
    """No state/event pair outside the documented transition table can succeed."""
    result = validate_transition(from_state, event_type)

    assert result == EXPECTED.get((from_state, event_type))


@given(st.lists(st.sampled_from(list(EventType)), max_size=100))
def test_sequences_keep_state_when_transition_is_illegal(events: list[EventType]) -> None:
    state = None
    expected = None
    for event in events:
        result = validate_transition(state, event)
        expected_result = EXPECTED.get((expected, event))
        assert result == expected_result
        if result is not None:
            state = result
            expected = expected_result
