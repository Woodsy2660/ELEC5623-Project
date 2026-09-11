"""Requirement lifecycle state machine. Pure functions, stdlib only."""

from enum import Enum


class State(str, Enum):
    """Requirement lifecycle states."""

    PROPOSED = "proposed"
    CONFIRMED = "confirmed"
    WITHDRAWN = "withdrawn"
    CONTRADICTED = "contradicted"
    SUPERSEDED = "superseded"


class EventType(str, Enum):
    """State transition event types."""

    CREATE = "create"
    CONFIRM = "confirm"
    REJECT = "reject"
    REFINE = "refine"
    CONTRADICT = "contradict"
    SUPERSEDE = "supersede"
    RESOLVE = "resolve"


# Valid transitions: (from_state, event_type) -> to_state
# None as from_state means initial creation
TRANSITIONS: dict[tuple[State | None, EventType], State] = {
    (None, EventType.CREATE): State.PROPOSED,
    (State.PROPOSED, EventType.CONFIRM): State.CONFIRMED,
    (State.PROPOSED, EventType.REJECT): State.WITHDRAWN,
    (State.CONFIRMED, EventType.REFINE): State.CONFIRMED,
    (State.CONFIRMED, EventType.CONTRADICT): State.CONTRADICTED,
    (State.CONFIRMED, EventType.SUPERSEDE): State.SUPERSEDED,
    (State.CONTRADICTED, EventType.SUPERSEDE): State.SUPERSEDED,
    (State.CONTRADICTED, EventType.RESOLVE): State.CONFIRMED,
}


def validate_transition(from_state: State | None, event_type: EventType) -> State | None:
    """Validate a state transition.

    Args:
        from_state: Current state (None for creation).
        event_type: The event being applied.

    Returns:
        The resulting state if valid, None if the transition is illegal.
    """
    return TRANSITIONS.get((from_state, event_type))
