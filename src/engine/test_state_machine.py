"""Tests for the state machine. The module under test remains stdlib-only."""

from hypothesis import given
from hypothesis import strategies as st

from src.engine.state_machine import TRANSITIONS, EventType, State, validate_transition


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


@given(st.sampled_from([None, *State]), st.sampled_from(list(EventType)))
def test_only_documented_transitions_succeed(
    from_state: State | None, event_type: EventType
) -> None:
    """No state/event pair outside the documented transition table can succeed."""
    result = validate_transition(from_state, event_type)

    if (from_state, event_type) in TRANSITIONS:
        assert result == TRANSITIONS[(from_state, event_type)]
    else:
        assert result is None
