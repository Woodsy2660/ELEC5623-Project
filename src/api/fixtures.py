"""Hard-coded D1 fixtures.

``scenarios/dev/`` has no authored files yet. The register, proposals, evidence
quotes and settings are the D1 content drawn in ``design/``. Offsets exist only
long enough to build a pre-split quote. Latency and cost figures from
``meetings.html`` are omitted: the design README marks them as fiction.
"""

from dataclasses import dataclass, field

from src.api.decisions import confirmation_gate, intended_state
from src.api.evidence import quote_from_span, quote_unhighlighted
from src.api.schemas import (
    AuditBlock,
    ConnectionSetting,
    EvidenceQuote,
    MeetingOut,
    ProjectOut,
    ProjectSettings,
    ProposalOut,
    RegisterRow,
    RelationCount,
    RequirementDetail,
    RetrievedAlternative,
    SpeakerSetting,
    StateCount,
    TimelineEntry,
)
from src.classify.schemas import Classification, Relation
from src.engine.state_machine import EventType, State
from src.validate.schemas import EvidenceSpan

D1 = "D1"


@dataclass
class StoredTurn:
    meeting_id: str
    turn_index: int
    speaker: str
    text: str
    quote: EvidenceQuote


@dataclass
class Store:
    projects: dict[str, ProjectOut]
    register: dict[str, list[RegisterRow]]
    details: dict[str, dict[str, RequirementDetail]]
    proposals: dict[str, list[ProposalOut]]
    proposal_list_meta: dict[str, tuple[str, str, int]]
    meetings: dict[str, list[MeetingOut]]
    turns: dict[str, list[StoredTurn]]
    settings: dict[str, ProjectSettings]
    event_seq: int = 0
    _turns_by_id: dict[str, StoredTurn] = field(default_factory=dict)

    def next_event_id(self) -> str:
        self.event_seq += 1
        return f"evt-{self.event_seq:04d}"

    def add_turn(self, turn: StoredTurn) -> StoredTurn:
        self.turns.setdefault(turn.meeting_id, []).append(turn)
        self._turns_by_id[turn.quote.turn_id] = turn
        return turn


def turn_id(meeting_id: str, index: int) -> str:
    return f"{meeting_id}:{index:04d}"


def highlighted(
    meeting_id: str, index: int, speaker: str, before: str, span: str, after: str
) -> StoredTurn:
    text = f"{before}{span}{after}"
    tid = turn_id(meeting_id, index)
    evidence = EvidenceSpan(turn_id=tid, start=len(before), end=len(before) + len(span))
    return StoredTurn(
        meeting_id=meeting_id,
        turn_index=index,
        speaker=speaker,
        text=text,
        quote=quote_from_span(speaker=speaker, text=text, span=evidence),
    )


def plain(meeting_id: str, index: int, speaker: str, text: str) -> StoredTurn:
    tid = turn_id(meeting_id, index)
    return StoredTurn(
        meeting_id=meeting_id,
        turn_index=index,
        speaker=speaker,
        text=text,
        quote=quote_unhighlighted(turn_id=tid, speaker=speaker, text=text),
    )


def _row(
    requirement_id: str,
    version: int,
    text: str,
    state: State,
    changed_label: str,
    note: str | None = None,
) -> RegisterRow:
    return RegisterRow(
        requirement_id=requirement_id,
        version=version,
        version_label=f"{requirement_id} v{version}",
        text=text,
        state=state,
        changed_label=changed_label,
        note=note,
    )


def _proposal(
    *,
    proposal_id: str,
    requirement_id: str | None,
    queue_text: str,
    statement: str,
    relation: Relation,
    rationale: str,
    proposed_event: EventType | None,
    from_state: State | None,
    speaker_label: str,
    speaker_name: str,
    speaker_role: str,
    speaker_can_confirm: bool,
    unresolved: bool,
    evidence: list[EvidenceQuote],
    retrieved: list[RetrievedAlternative],
    authority_note: str | None = None,
) -> ProposalOut:
    allowed, reason = confirmation_gate(
        from_state=from_state,
        event_type=proposed_event,
        speaker_can_confirm=speaker_can_confirm,
        unresolved=unresolved,
    )
    matched = None if relation == Relation.NEW else requirement_id
    return ProposalOut(
        id=proposal_id,
        project_id=D1,
        meeting_id="D1-M02",
        requirement_id=requirement_id,
        queue_text=queue_text,
        statement=statement,
        classification=Classification(
            matched_requirement_id=matched,
            relation=relation,
            rationale=rationale,
            retrieved_ids=[item.requirement_id for item in retrieved],
        ),
        proposed_event=proposed_event,
        from_state=from_state,
        to_state=intended_state(from_state, proposed_event),
        can_confirm=allowed,
        can_confirm_reason=reason,
        unresolved=unresolved,
        evidence=evidence,
        retrieved=retrieved,
        speaker_label=speaker_label,
        speaker_name=speaker_name,
        speaker_role=speaker_role,
        speaker_can_confirm=speaker_can_confirm,
        authority_note=authority_note,
    )


def _alt(
    rank: int, requirement_id: str, text: str, state: State, chosen: bool
) -> RetrievedAlternative:
    return RetrievedAlternative(
        rank=rank,
        requirement_id=requirement_id,
        text=text,
        state=state,
        chosen=chosen,
    )


def _d1_settings() -> ProjectSettings:
    return ProjectSettings(
        project_id=D1,
        connections=[
            ConnectionSetting(
                id="gcal",
                label="Google Calendar",
                description="Reads upcoming meetings so capture can be scheduled",
                status="connected",
            ),
            ConnectionSetting(
                id="gmeet",
                label="Google Meet",
                description="A capture bot joins as a visible participant and transcribes",
                status="connected",
            ),
            ConnectionSetting(
                id="zoom-teams",
                label="Zoom / Teams",
                description="Same capture path, different platform",
                status="disconnected",
            ),
        ],
        capture_default="ask",
        speakers=[
            SpeakerSetting(
                speaker_label="CLIENT_PO",
                display_name="Client PO",
                name="Priya Raman",
                role="Product owner",
                can_confirm_scope=True,
            ),
            SpeakerSetting(
                speaker_label="CLIENT_DEV",
                display_name="Client Dev",
                name="Tom Alder",
                role="Engineer",
                can_confirm_scope=False,
            ),
            SpeakerSetting(
                speaker_label="CONSULTANT_A",
                display_name="Consultant A",
                name="Ben Wood",
                role="Lead consultant",
                can_confirm_scope=False,
            ),
        ],
        deployment="foundry · cia-prod-01",
        temperature=0,
        retrieval_k=5,
        extract_prompt="extract_v1 · 8dc01b2",
        classify_prompt="classify_v1 · 8dc01b2",
        prompt_status="Frozen",
        project_isolation=True,
        provider_retention_note="Per the deployment's configuration",
    )


def _empty_settings(project_id: str) -> ProjectSettings:
    settings = _d1_settings()
    return settings.model_copy(update={"project_id": project_id, "speakers": []})


def _register() -> list[RegisterRow]:
    return [
        _row(
            "R04",
            1,
            "Customers can view all their orders, newest first, with status and total",
            State.CONFIRMED,
            "M01 · 4 Mar",
        ),
        _row(
            "R05",
            2,
            "CSV export of order history, with optional start and end date",
            State.CONFIRMED,
            "M02 · 18 Mar",
        ),
        _row(
            "R06",
            1,
            "On dispatch, the customer receives an order receipt email with line items and tracking number",
            State.CONFIRMED,
            "M01 · 4 Mar",
        ),
        _row(
            "R01",
            2,
            "Customers authenticate through the existing identity provider using SSO",
            State.PROPOSED,
            "M02 · 18 Mar",
        ),
        _row(
            "R08",
            1,
            "Session expires after 30 minutes of inactivity",
            State.PROPOSED,
            "M02 · 18 Mar",
        ),
        _row(
            "R03",
            1,
            "The system sends a password reset email containing a reset link",
            State.CONTRADICTED,
            "M02 · 18 Mar",
            "Challenged in M02 — no replacement stated, awaiting the identity provider team",
        ),
        _row(
            "R07",
            1,
            "Order history loads in under two seconds for a customer with 1000 orders",
            State.CONTRADICTED,
            "M02 · 18 Mar",
            "Challenged in M02 — no replacement number offered",
        ),
        _row(
            "R01",
            1,
            "Customers authenticate with an email address and password",
            State.SUPERSEDED,
            "M02 · 18 Mar",
        ),
        _row(
            "R05",
            1,
            "Customers can export their order history as CSV",
            State.SUPERSEDED,
            "M02 · 18 Mar",
        ),
        _row(
            "R02",
            1,
            "Passwords must be at least twelve characters",
            State.WITHDRAWN,
            "M02 · 18 Mar",
        ),
    ]


def _details(
    rows: list[RegisterRow], quotes: dict[str, EvidenceQuote]
) -> dict[str, RequirementDetail]:
    by_family: dict[str, list[RegisterRow]] = {}
    for row in rows:
        by_family.setdefault(row.requirement_id, []).append(row)

    details: dict[str, RequirementDetail] = {}
    for requirement_id, family in by_family.items():
        current = family[0]
        timeline = [
            TimelineEntry(
                version=row.version,
                state=row.state,
                relation=None,
                when_label=row.changed_label,
                text=row.text,
                historical=row.state in (State.SUPERSEDED, State.WITHDRAWN),
                struck=row.state == State.SUPERSEDED,
                evidence=[],
                footer=row.note,
            )
            for row in family
        ]
        details[requirement_id] = RequirementDetail(
            id=requirement_id,
            project_id=D1,
            title=None,
            current_state=current.state,
            current_text=current.text,
            current_version=current.version,
            summary=f"Current version v{current.version}",
            timeline=timeline,
            audit=None,
        )

    login = quotes["D1-M01:0003"]
    sso = quotes["D1-M02:0002"]
    details["R01"] = RequirementDetail(
        id="R01",
        project_id=D1,
        title="Authentication",
        current_state=State.PROPOSED,
        current_text="Customers authenticate through the existing identity provider using SSO.",
        current_version=2,
        summary="Current version v2 · awaiting confirmation · 2 versions, 3 events",
        timeline=[
            TimelineEntry(
                version=2,
                state=None,
                relation=Relation.SUPERSESSION,
                when_label="Meeting 2 · 18 Mar",
                text="Customers authenticate through the existing identity provider using SSO.",
                historical=False,
                struck=False,
                evidence=[sso],
                footer="Proposed by the agent · awaiting confirmation from Priya Raman",
            ),
            TimelineEntry(
                version=1,
                state=State.SUPERSEDED,
                relation=None,
                when_label="Meeting 2 · 18 Mar",
                text="Customers authenticate with an email address and password.",
                historical=True,
                struck=True,
                evidence=[],
                footer="Replaced, not deleted. Its evidence is kept.",
            ),
            TimelineEntry(
                version=1,
                state=None,
                relation=Relation.NEW,
                when_label="Meeting 1 · 4 Mar",
                text="Customers authenticate with an email address and password.",
                historical=True,
                struck=False,
                evidence=[login],
                footer="Confirmed by Priya Raman · 4 Mar, 14:22",
            ),
        ],
        audit=AuditBlock(
            family_created="Meeting 1 · 4 Mar",
            events=["Create", "Confirm", "Supersede"],
            prompt_version="classify_v1 · 8dc01b2",
            model="pinned · temp 0",
            rejected_proposals="None",
        ),
    )
    reset = quotes["D1-M02:0006"]
    r03 = details["R03"]
    r03.timeline[0].evidence = [reset]
    return details


def _proposals(quotes: dict[str, EvidenceQuote]) -> list[ProposalOut]:
    email_login = "Customers authenticate with an email address and password"
    reset_email = "The system sends a password reset email containing a reset link"
    receipt = "On dispatch, the customer receives an order receipt email with line items and tracking number"
    passwords = "Passwords must be at least twelve characters"
    return [
        _proposal(
            proposal_id="D1-P-R01",
            requirement_id="R01",
            queue_text="Authenticate through the identity provider using SSO",
            statement="Customers authenticate through the existing identity provider using SSO.",
            relation=Relation.SUPERSESSION,
            rationale=(
                "The client product owner replaces email-and-password login with single sign-on. "
                "The previous obligation does not remain true."
            ),
            proposed_event=EventType.SUPERSEDE,
            from_state=State.CONFIRMED,
            speaker_label="CLIENT_PO",
            speaker_name="Priya Raman",
            speaker_role="Product owner",
            speaker_can_confirm=True,
            unresolved=False,
            evidence=[quotes["D1-M02:0002"]],
            retrieved=[
                _alt(1, "R01", email_login, State.CONFIRMED, True),
                _alt(2, "R03", reset_email, State.CONFIRMED, False),
            ],
        ),
        _proposal(
            proposal_id="D1-P-R03",
            requirement_id="R03",
            queue_text="Password reset email may no longer be required",
            statement="The password reset email may no longer be required under SSO.",
            relation=Relation.CONTRADICTION,
            rationale=(
                "The obligation is challenged but no replacement is stated, and the speaker "
                "cannot confirm scope. Classified as contradiction rather than supersession."
            ),
            proposed_event=EventType.CONTRADICT,
            from_state=State.CONFIRMED,
            speaker_label="CLIENT_DEV",
            speaker_name="Tom Alder",
            speaker_role="Engineer",
            speaker_can_confirm=False,
            unresolved=True,
            evidence=[quotes["D1-M02:0006"]],
            retrieved=[
                _alt(1, "R03", reset_email, State.PROPOSED, True),
                _alt(2, "R06", receipt, State.CONFIRMED, False),
                _alt(3, "R01", email_login, State.SUPERSEDED, False),
                _alt(4, "R02", passwords, State.WITHDRAWN, False),
            ],
            authority_note="Tom Alder (engineer) cannot confirm scope",
        ),
        _proposal(
            proposal_id="D1-P-R06",
            requirement_id="R06",
            queue_text="Order receipt email unchanged",
            statement="Order receipt email unchanged",
            relation=Relation.RESTATEMENT,
            rationale="The utterance repeats the confirmed receipt email and adds no obligation.",
            proposed_event=None,
            from_state=State.CONFIRMED,
            speaker_label="CLIENT_PO",
            speaker_name="Priya Raman",
            speaker_role="Product owner",
            speaker_can_confirm=True,
            unresolved=False,
            evidence=[quotes["D1-M02:0007"]],
            retrieved=[_alt(1, "R06", receipt, State.CONFIRMED, True)],
        ),
        _proposal(
            proposal_id="D1-P-R05",
            requirement_id="R05",
            queue_text="CSV export accepts a start and end date",
            statement="CSV export of order history, with optional start and end date",
            relation=Relation.REFINEMENT,
            rationale=(
                "The export obligation stays true and gains an optional date range. "
                "That is a refinement, not a replacement."
            ),
            proposed_event=EventType.REFINE,
            from_state=State.CONFIRMED,
            speaker_label="CLIENT_PO",
            speaker_name="Priya Raman",
            speaker_role="Product owner",
            speaker_can_confirm=True,
            unresolved=False,
            evidence=[quotes["D1-M02:0008"]],
            retrieved=[
                _alt(
                    1,
                    "R05",
                    "Customers can export their order history as CSV",
                    State.CONFIRMED,
                    True,
                )
            ],
        ),
        _proposal(
            proposal_id="D1-P-R07",
            requirement_id="R07",
            queue_text="Two-second load target disputed",
            statement="Two-second load target disputed",
            relation=Relation.CONTRADICTION,
            rationale="The two-second target is challenged and no replacement number is stated.",
            proposed_event=EventType.CONTRADICT,
            from_state=State.CONFIRMED,
            speaker_label="CLIENT_DEV",
            speaker_name="Tom Alder",
            speaker_role="Engineer",
            speaker_can_confirm=False,
            unresolved=False,
            evidence=[quotes["D1-M02:0009"]],
            retrieved=[
                _alt(
                    1,
                    "R07",
                    "Order history loads in under two seconds for a customer with 1000 orders",
                    State.CONFIRMED,
                    True,
                )
            ],
        ),
        _proposal(
            proposal_id="D1-P-R04",
            requirement_id="R04",
            queue_text="Order history unchanged",
            statement="Order history unchanged",
            relation=Relation.RESTATEMENT,
            rationale="The utterance repeats the confirmed order-history view and changes nothing.",
            proposed_event=None,
            from_state=State.CONFIRMED,
            speaker_label="CLIENT_PO",
            speaker_name="Priya Raman",
            speaker_role="Product owner",
            speaker_can_confirm=True,
            unresolved=False,
            evidence=[quotes["D1-M02:0010"]],
            retrieved=[
                _alt(
                    1,
                    "R04",
                    "Customers can view all their orders, newest first, with status and total",
                    State.CONFIRMED,
                    True,
                )
            ],
        ),
        _proposal(
            proposal_id="D1-P-R08",
            requirement_id=None,
            queue_text="Session expires after 30 minutes of inactivity",
            statement="Session expires after 30 minutes of inactivity",
            relation=Relation.NEW,
            rationale="No retrieved family is this obligation. It is a new requirement.",
            proposed_event=EventType.CREATE,
            from_state=None,
            speaker_label="CLIENT_PO",
            speaker_name="Priya Raman",
            speaker_role="Product owner",
            speaker_can_confirm=True,
            unresolved=False,
            evidence=[quotes["D1-M02:0011"]],
            retrieved=[
                _alt(1, "R01", email_login, State.SUPERSEDED, False),
                _alt(
                    2,
                    "R04",
                    "Customers can view all their orders, newest first, with status and total",
                    State.CONFIRMED,
                    False,
                ),
            ],
        ),
    ]


def _meetings(turn_counts: dict[str, int]) -> list[MeetingOut]:
    return [
        MeetingOut(
            id="D1-M03",
            project_id=D1,
            ordinal=3,
            title="Requirements review · meeting 3",
            home_title="Requirements review · Client portal",
            when_label="Now",
            status="live",
            turn_count=turn_counts["D1-M03"],
            capture_label="Capturing",
        ),
        MeetingOut(
            id="cal-thu",
            project_id=D1,
            ordinal=None,
            title="Sprint review · Google Meet",
            home_title="Warehouse scanning · sprint review",
            when_label="Thu 09:30",
            status="upcoming",
            turn_count=0,
            capture_label="Bot will join",
        ),
        MeetingOut(
            id="cal-fri",
            project_id=D1,
            ordinal=None,
            title="Discovery call · Google Meet",
            home_title="Driver app · discovery call",
            when_label="Fri 14:00",
            status="upcoming",
            turn_count=0,
            capture_label="Not capturing",
        ),
        MeetingOut(
            id="D1-M02",
            project_id=D1,
            ordinal=2,
            title="Follow-up after security review",
            when_label="18 Mar",
            status="past",
            turn_count=turn_counts["D1-M02"],
            source_name="D1-M02.txt",
            candidates=8,
            discarded=1,
            proposals=7,
            confirmed=0,
            relation_counts=[
                RelationCount(relation=Relation.SUPERSESSION, count=1),
                RelationCount(relation=Relation.REFINEMENT, count=1),
                RelationCount(relation=Relation.CONTRADICTION, count=2),
                RelationCount(relation=Relation.RESTATEMENT, count=2),
                RelationCount(relation=Relation.NEW, count=1),
            ],
            not_requirement_count=1,
        ),
        MeetingOut(
            id="D1-M01",
            project_id=D1,
            ordinal=1,
            title="Initial requirements workshop",
            when_label="4 Mar",
            status="past",
            turn_count=turn_counts["D1-M01"],
            source_name="D1-M01.txt",
            candidates=7,
            discarded=0,
            proposals=7,
            confirmed=7,
            relation_counts=[RelationCount(relation=Relation.NEW, count=7)],
            footer="Confirmed by Priya Raman, 4 Mar",
        ),
    ]


def build_store() -> Store:
    store = Store(
        projects={},
        register={},
        details={},
        proposals={},
        proposal_list_meta={},
        meetings={},
        turns={},
        settings={},
    )
    m01 = highlighted(
        "D1-M01",
        3,
        "Client PO",
        "",
        "Customers log in with their email address and a password",
        ". That's what they're used to on the old system and we don't want to retrain anyone.",
    )
    m02_sso = highlighted(
        "D1-M02",
        2,
        "Client PO",
        "Our security team won't sign off on us holding customer passwords, so ",
        "we will use single sign-on instead",
        ". Customers authenticate through our existing identity provider.",
    )
    m02_reset = highlighted(
        "D1-M02",
        6,
        "Client Dev",
        "It does, but ",
        "I'd want to confirm that with the identity provider team before you write it off",
        ". Leave it open for now.",
    )
    # The export quotes two turns in full. The other queue lines have no surrounding
    # turn in the HTML, so the span is the whole utterance.
    extra = [
        highlighted("D1-M02", 7, "Client PO", "", "Order receipt email unchanged", ""),
        highlighted(
            "D1-M02",
            8,
            "Client PO",
            "",
            "CSV export of order history, with optional start and end date",
            "",
        ),
        highlighted("D1-M02", 9, "Client Dev", "", "Two-second load target disputed", ""),
        highlighted("D1-M02", 10, "Client PO", "", "Order history unchanged", ""),
        highlighted(
            "D1-M02",
            11,
            "Client PO",
            "",
            "Session expires after 30 minutes of inactivity",
            "",
        ),
    ]
    live = [
        plain(
            "D1-M03",
            1,
            "Consultant A",
            "So before we go further, you mentioned there'd been a security review internally. "
            "Did anything land on us?",
        ),
        plain(
            "D1-M03",
            2,
            "Client Dev",
            "It did. Our security team won't sign off on us holding customer passwords at all.",
        ),
        plain(
            "D1-M03",
            3,
            "Client PO",
            "So we will use single sign-on instead. Customers authenticate through our existing "
            "identity provider, and we drop the email and password login entirely.",
        ),
        plain(
            "D1-M03",
            4,
            "Consultant A",
            "That's a significant change from the last session. Just to be clear, email and "
            "password login is off the table, not an option",
        ),
    ]
    for turn in (m01, m02_sso, m02_reset, *extra, *live):
        store.add_turn(turn)

    quotes = {turn.quote.turn_id: turn.quote for turn in store._turns_by_id.values()}
    rows = _register()
    store.register[D1] = rows
    store.details[D1] = _details(rows, quotes)
    store.proposals[D1] = _proposals(quotes)
    # The queue header says meeting 2. The scope bar on the same screen says meeting 3.
    # Both strings are kept so the screen can show the export as drawn.
    store.proposal_list_meta[D1] = (
        "From meeting 2 · 18 Mar",
        "7 proposals from meeting 3",
        1,
    )
    counts = {meeting_id: len(turns) for meeting_id, turns in store.turns.items()}
    store.meetings[D1] = _meetings(counts)
    store.settings[D1] = _d1_settings()

    store.projects[D1] = ProjectOut(
        id=D1,
        name="Client portal",
        client="Northwind Logistics",
        meeting_count=3,
        requirement_count=8,
        state_counts=[
            StateCount(state=State.CONFIRMED, count=3),
            StateCount(state=State.CONTRADICTED, count=2),
        ],
        empty=False,
        proposal_count=7,
        review_note="7 proposals to review",
        live_title="Requirements review · Client portal",
        live_detail="Google Meet · 4 participants · 47 turns captured",
    )
    store.projects["warehouse"] = ProjectOut(
        id="warehouse",
        name="Warehouse scanning",
        client="Northwind Logistics",
        meeting_count=3,
        requirement_count=14,
        state_counts=[
            StateCount(state=State.CONFIRMED, count=12),
            StateCount(state=State.SUPERSEDED, count=4),
        ],
        empty=False,
        proposal_count=0,
        review_note="Nothing to review",
    )
    store.projects["driver"] = ProjectOut(
        id="driver",
        name="Driver app",
        client="Meridian Freight",
        meeting_count=0,
        requirement_count=0,
        state_counts=[],
        empty=True,
        proposal_count=0,
        review_note="Capture a call, or import a transcript",
    )
    for project_id in ("warehouse", "driver"):
        store.register[project_id] = []
        store.details[project_id] = {}
        store.proposals[project_id] = []
        store.meetings[project_id] = []
        store.settings[project_id] = _empty_settings(project_id)
        store.proposal_list_meta[project_id] = ("", "", 0)
    return store
