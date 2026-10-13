"""HTTP models for the fixture API.

Evidence leaves Python already split into before, span and after. These models
have no character offsets. Lifecycle fields use the engine and classifier types
so the wire format cannot grow a second state machine.
"""

from typing import Literal

from pydantic import BaseModel, Field, model_validator

from src.classify.schemas import Classification, Relation
from src.engine.state_machine import EventType, State


class EvidenceQuote(BaseModel):
    """One utterance split around its evidence span.

    ``before + span + after`` is the stored turn. A turn with nothing to
    highlight has an empty span and the utterance in ``before``.
    """

    turn_id: str
    speaker: str
    before: str
    span: str
    after: str


class StreamTurn(EvidenceQuote):
    """One server-sent turn. ``partial`` is true while that turn is still forming."""

    partial: bool = False


class RegisterRow(BaseModel):
    requirement_id: str
    version: int
    version_label: str
    text: str
    state: State
    changed_label: str
    note: str | None = None


class TimelineEntry(BaseModel):
    version: int
    state: State | None = None
    relation: Relation | None = None
    when_label: str
    text: str
    historical: bool
    struck: bool
    evidence: list[EvidenceQuote] = Field(default_factory=list)
    footer: str | None = None


class AuditBlock(BaseModel):
    family_created: str
    events: list[str]
    prompt_version: str
    model: str
    rejected_proposals: str


class RequirementDetail(BaseModel):
    id: str
    project_id: str
    title: str | None
    current_state: State
    current_text: str
    current_version: int
    summary: str
    timeline: list[TimelineEntry]
    audit: AuditBlock | None = None


class RetrievedAlternative(BaseModel):
    rank: int
    requirement_id: str
    text: str
    state: State
    chosen: bool


class DecisionConflict(BaseModel):
    reason: str


class CommittedEvent(BaseModel):
    id: str
    project_id: str
    proposal_id: str
    action: Literal["confirm", "reject", "edit"]
    event_type: EventType | None
    from_state: State | None
    to_state: State | None
    register_changed: bool
    edited_text: str | None = None
    reason: str


class ProposalOut(BaseModel):
    """A proposal awaiting a human decision.

    ``can_confirm`` and ``can_confirm_reason`` are filled by the Python gate.
    ``from_state`` is the lifecycle state the engine reads. ``proposal_status``
    is the unconfirmed-model chip on the card, which is not a lifecycle input.
    """

    id: str
    project_id: str
    meeting_id: str
    requirement_id: str | None
    queue_text: str
    statement: str
    classification: Classification
    proposed_event: EventType | None
    from_state: State | None
    to_state: State | None
    proposal_status: Literal["proposed"] = "proposed"
    can_confirm: bool
    can_confirm_reason: str
    unresolved: bool
    evidence: list[EvidenceQuote]
    retrieved: list[RetrievedAlternative]
    speaker_label: str
    speaker_name: str
    speaker_role: str
    speaker_can_confirm: bool
    authority_note: str | None = None
    decision: CommittedEvent | None = None


class ProposalList(BaseModel):
    project_id: str
    meeting_id: str | None
    queue_label: str
    scope_count_label: str
    discarded_candidates: int
    proposals: list[ProposalOut]


class DecisionRequest(BaseModel):
    action: Literal["confirm", "reject", "edit"]
    edited_text: str | None = None

    @model_validator(mode="after")
    def edit_has_text(self) -> "DecisionRequest":
        if self.action == "edit" and not (self.edited_text and self.edited_text.strip()):
            raise ValueError("Edit requires replacement text")
        return self


class StateCount(BaseModel):
    state: State
    count: int


class ProjectOut(BaseModel):
    id: str
    name: str
    client: str
    meeting_count: int
    requirement_count: int
    state_counts: list[StateCount]
    empty: bool
    proposal_count: int
    review_note: str
    live_title: str | None = None
    live_detail: str | None = None


class RelationCount(BaseModel):
    relation: Relation
    count: int


class MeetingOut(BaseModel):
    id: str
    project_id: str
    ordinal: int | None
    title: str
    home_title: str | None = None
    when_label: str
    status: Literal["past", "live", "upcoming"]
    turn_count: int
    source_name: str | None = None
    candidates: int | None = None
    discarded: int | None = None
    proposals: int | None = None
    confirmed: int | None = None
    relation_counts: list[RelationCount] = Field(default_factory=list)
    not_requirement_count: int | None = None
    footer: str | None = None
    capture_label: str | None = None


class ImportedTurn(BaseModel):
    speaker: str
    text: str


class MeetingCreate(BaseModel):
    title: str
    ordinal: int
    source_name: str
    turns: list[ImportedTurn]


class SpeakerSetting(BaseModel):
    speaker_label: str
    display_name: str
    name: str
    role: str
    can_confirm_scope: bool


class ConnectionSetting(BaseModel):
    id: str
    label: str
    description: str
    status: Literal["connected", "disconnected"]


class ProjectSettings(BaseModel):
    project_id: str
    connections: list[ConnectionSetting]
    capture_default: Literal["ask", "always"]
    speakers: list[SpeakerSetting]
    deployment: str
    temperature: float
    retrieval_k: int
    extract_prompt: str
    classify_prompt: str
    prompt_status: str
    project_isolation: bool
    provider_retention_note: str


class ReasonBody(BaseModel):
    reason: str
