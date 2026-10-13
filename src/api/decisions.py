"""Confirmation gate. Writes are accepted only when the Python state engine agrees.

``can_confirm`` on each proposal is produced here. The decision route calls the
same gate again, so the button state is not the only check. TypeScript does not
get a copy of this table.
"""

from src.api.schemas import CommittedEvent, DecisionConflict, DecisionRequest, ProposalOut
from src.engine.state_machine import EventType, State, validate_transition

AUTHORITY_REASON = "Needs confirmation from a scope owner"


def intended_state(from_state: State | None, event_type: EventType | None) -> State | None:
    """State the engine would write, ignoring the authority hold."""
    if event_type is None:
        return from_state
    return validate_transition(from_state, event_type)


def confirmation_gate(
    *,
    from_state: State | None,
    event_type: EventType | None,
    speaker_can_confirm: bool,
    unresolved: bool,
) -> tuple[bool, str]:
    """Whether a confirm is legal, and the reason shown when it is not."""
    if unresolved:
        return False, AUTHORITY_REASON
    if event_type == EventType.SUPERSEDE and not speaker_can_confirm:
        return False, AUTHORITY_REASON
    if event_type is None:
        return True, ""
    if validate_transition(from_state, event_type) is None:
        source = from_state.value if from_state is not None else "none"
        return False, f"Illegal transition from {source} via {event_type.value}"
    return True, ""


def apply_decision(
    proposal: ProposalOut,
    request: DecisionRequest,
    *,
    event_id: str,
) -> CommittedEvent | DecisionConflict:
    """Accept or refuse one decision. Refusal is a conflict, not a rewritten proposal."""
    if proposal.decision is not None:
        return DecisionConflict(reason="Proposal already decided")

    if request.action in ("confirm", "edit"):
        allowed, reason = confirmation_gate(
            from_state=proposal.from_state,
            event_type=proposal.proposed_event,
            speaker_can_confirm=proposal.speaker_can_confirm,
            unresolved=proposal.unresolved,
        )
        if not allowed:
            return DecisionConflict(reason=reason or proposal.can_confirm_reason)
        if proposal.proposed_event is None:
            return _event(
                proposal,
                request,
                event_id=event_id,
                event_type=None,
                from_state=proposal.from_state,
                to_state=proposal.from_state,
                register_changed=False,
                reason="Restatement noted; register unchanged",
            )
        # The gate already asked the engine. Ask it again at the write.
        to_state = validate_transition(proposal.from_state, proposal.proposed_event)
        if to_state is None:
            source = proposal.from_state.value if proposal.from_state is not None else "none"
            return DecisionConflict(
                reason=f"Illegal transition from {source} via {proposal.proposed_event.value}"
            )
        return _event(
            proposal,
            request,
            event_id=event_id,
            event_type=proposal.proposed_event,
            from_state=proposal.from_state,
            to_state=to_state,
            register_changed=True,
            reason="Committed",
        )

    if proposal.proposed_event == EventType.CREATE:
        to_state = validate_transition(State.PROPOSED, EventType.REJECT)
        if to_state is None:
            return DecisionConflict(reason="Illegal transition from proposed via reject")
        return _event(
            proposal,
            request,
            event_id=event_id,
            event_type=EventType.REJECT,
            from_state=State.PROPOSED,
            to_state=to_state,
            register_changed=True,
            reason="Proposal rejected; requirement withdrawn",
        )

    return _event(
        proposal,
        request,
        event_id=event_id,
        event_type=None,
        from_state=proposal.from_state,
        to_state=proposal.from_state,
        register_changed=False,
        reason="Proposal dismissed; register unchanged",
    )


def _event(
    proposal: ProposalOut,
    request: DecisionRequest,
    *,
    event_id: str,
    event_type: EventType | None,
    from_state: State | None,
    to_state: State | None,
    register_changed: bool,
    reason: str,
) -> CommittedEvent:
    edited = request.edited_text if request.action == "edit" else None
    return CommittedEvent(
        id=event_id,
        project_id=proposal.project_id,
        proposal_id=proposal.id,
        action=request.action,
        event_type=event_type,
        from_state=from_state,
        to_state=to_state,
        register_changed=register_changed,
        edited_text=edited,
        reason=reason,
    )
