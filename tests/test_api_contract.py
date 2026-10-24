"""Contract tests for the fixture API.

Evidence on the wire is pre-split. Decisions are accepted only when the Python
state engine allows them. These tests do not read gold labels.
"""

import json

import pytest
from fastapi.testclient import TestClient

from src.api.app import app
from src.api.decisions import confirmation_gate
from src.api.schemas import EvidenceQuote
from src.api.store import reset_store
from src.engine.state_machine import EventType, State

client = TestClient(app)

EVIDENCE_KEYS = {"turn_id", "speaker", "before", "span", "after"}
TURN_KEYS = EVIDENCE_KEYS | {"partial"}


@pytest.fixture(autouse=True)
def _fresh_store() -> None:
    reset_store()


def test_evidence_model_has_no_character_offsets() -> None:
    assert set(EvidenceQuote.model_fields) == EVIDENCE_KEYS


def test_openapi_evidence_schema_has_no_offsets() -> None:
    schemas = client.get("/openapi.json").json()["components"]["schemas"]
    assert set(schemas["EvidenceQuote"]["properties"]) == EVIDENCE_KEYS
    assert "EvidenceSpan" not in schemas
    assert "start" not in schemas["EvidenceQuote"]["properties"]
    assert "end" not in schemas["EvidenceQuote"]["properties"]


def test_proposals_carry_server_side_confirm_flag() -> None:
    body = client.get("/projects/D1/proposals").json()
    assert body["discarded_candidates"] == 1
    assert len(body["proposals"]) == 7
    blocked = next(item for item in body["proposals"] if item["id"] == "D1-P-R03")
    assert blocked["can_confirm"] is False
    assert blocked["can_confirm_reason"] == "Needs confirmation from a scope owner"
    assert set(blocked["evidence"][0]) == EVIDENCE_KEYS
    allowed = next(item for item in body["proposals"] if item["id"] == "D1-P-R01")
    assert allowed["can_confirm"] is True
    assert allowed["can_confirm_reason"] == ""


def test_evidence_concatenates_to_the_stored_turn() -> None:
    turns = client.get("/meetings/D1-M02/turns").json()
    quoted = next(turn for turn in turns if turn["turn_id"] == "D1-M02:0002")
    assert set(quoted) == TURN_KEYS
    text = quoted["before"] + quoted["span"] + quoted["after"]
    assert quoted["span"] == "we will use single sign-on instead"
    assert text.startswith("Our security team won't sign off")
    assert "start" not in quoted
    assert "end" not in quoted


def test_confirm_supersession_commits_engine_state() -> None:
    response = client.post("/proposals/D1-P-R01/decision", json={"action": "confirm"})
    assert response.status_code == 200
    body = response.json()
    assert body["event_type"] == "supersede"
    assert body["from_state"] == "confirmed"
    assert body["to_state"] == "superseded"
    assert body["register_changed"] is True
    again = client.post("/proposals/D1-P-R01/decision", json={"action": "confirm"})
    assert again.status_code == 409
    assert again.json()["reason"] == "Proposal already decided"


def test_unresolved_confirm_is_conflict() -> None:
    response = client.post("/proposals/D1-P-R03/decision", json={"action": "confirm"})
    assert response.status_code == 409
    assert response.json()["reason"] == "Needs confirmation from a scope owner"


def test_reject_new_requirement_withdraws_through_engine() -> None:
    response = client.post("/proposals/D1-P-R08/decision", json={"action": "reject"})
    assert response.status_code == 200
    body = response.json()
    assert body["event_type"] == "reject"
    assert body["from_state"] == "proposed"
    assert body["to_state"] == "withdrawn"
    assert body["register_changed"] is True


def test_restatement_confirm_does_not_change_register() -> None:
    response = client.post("/proposals/D1-P-R06/decision", json={"action": "confirm"})
    assert response.status_code == 200
    body = response.json()
    assert body["register_changed"] is False
    assert body["event_type"] is None
    assert body["to_state"] == "confirmed"


def test_edit_without_text_is_rejected() -> None:
    response = client.post("/proposals/D1-P-R01/decision", json={"action": "edit"})
    assert response.status_code == 422


def test_illegal_transition_is_not_confirmable() -> None:
    allowed, reason = confirmation_gate(
        from_state=State.PROPOSED,
        event_type=EventType.SUPERSEDE,
        speaker_can_confirm=True,
        unresolved=False,
    )
    assert allowed is False
    assert reason == "Illegal transition from proposed via supersede"


def test_stream_replays_pre_split_turns() -> None:
    with client.stream("GET", "/meetings/D1-M03/stream") as response:
        assert response.status_code == 200
        assert response.headers["content-type"].startswith("text/event-stream")
        raw = "".join(response.iter_text())
    payloads = [
        json.loads(line.removeprefix("data: "))
        for line in raw.splitlines()
        if line.startswith("data: ")
    ]
    assert len(payloads) == 4
    assert payloads[-1]["partial"] is True
    assert payloads[0]["partial"] is False
    assert set(payloads[0]) == TURN_KEYS


def test_import_blocks_unmapped_speaker_and_replays_same_source() -> None:
    blocked = client.post(
        "/projects/D1/meetings",
        json={
            "title": "Requirements review",
            "ordinal": 4,
            "source_name": "D1-M04.txt",
            "turns": [{"speaker": "CLIENT_CFO", "text": "We should revisit the budget."}],
        },
    )
    assert blocked.status_code == 409
    assert blocked.json()["reason"] == "Blocked: one speaker has no role"

    created = client.post(
        "/projects/D1/meetings",
        json={
            "title": "Requirements review",
            "ordinal": 4,
            "source_name": "D1-M04.txt",
            "turns": [{"speaker": "Client PO", "text": "Budget stands."}],
        },
    )
    assert created.status_code == 201
    replay = client.post(
        "/projects/D1/meetings",
        json={
            "title": "Requirements review",
            "ordinal": 4,
            "source_name": "D1-M04.txt",
            "turns": [{"speaker": "Client PO", "text": "Budget stands."}],
        },
    )
    assert replay.status_code == 200
    assert replay.json()["id"] == created.json()["id"]


def test_unknown_project_is_404() -> None:
    response = client.get("/projects/missing/requirements")
    assert response.status_code == 404
    assert response.json()["reason"] == "Unknown project missing"
