"""FR01-03/09/11, E4: synthetic offline inputs, never measured model output."""

import json
from concurrent.futures import ThreadPoolExecutor
from datetime import UTC, datetime
from uuid import uuid4

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import event, func, select
from sqlalchemy.orm import Session

from src.api.app import create_app
from src.api.queries import proposals as query_proposals
from src.classify.schemas import Classification
from src.eval.replay_to_cutoff import _compute_actual_state
from src.persist.database import (
    create_database_engine,
    initialize_database,
    review_transaction,
    transaction,
)
from src.persist.models import (
    Candidate,
    Event,
    Meeting,
    ModelCall,
    Project,
    Proposal,
    ProposalReview,
    Requirement,
    RequirementCurrent,
    RequirementVersion,
    Run,
    Speaker,
    Turn,
)
from src.persist.retrieval import retrieval_snapshot
from src.persist.review import (
    ReviewConflict,
    ReviewDecision,
    commit_decision,
    explicit_replacement,
    stage_proposal,
)
from src.retrieve.schemas import VectorRecord

AUTH = {"Authorization": "Bearer synthetic-test-token"}


def synthetic_embedding(text: str) -> VectorRecord:
    """Deliberately synthetic vectors for transaction tests, not retrieval quality."""
    return VectorRecord(
        embedding_model="test-only",
        embedding_version="1",
        embedding_dim=2,
        embedding=(float(len(text)), 1.0),
    )


@pytest.fixture
def database(tmp_path):
    url = f"sqlite:///{tmp_path / 'review.db'}"
    engine = create_database_engine(url)
    initialize_database(engine)
    now = datetime.now(UTC)
    with transaction(engine) as db:
        for pid in ("P1", "P2"):
            db.add(Project(id=pid, name=f"Synthetic {pid}", created_at=now))
        db.add(
            Run(
                id="run",
                mode="demo",
                candidate_source="synthetic-test",
                repeat_index=1,
                prompt_hash="a" * 40,
                model_deployment="no-model-called",
                temp=0,
                started_at=now,
                notes="Synthetic test records; not a model evaluation",
            )
        )
        db.flush()
        for pid in ("P1", "P2"):
            db.add(
                Meeting(
                    id=f"{pid}-M01", project_id=pid, ordinal=1, source_hash=pid, imported_at=now
                )
            )
            db.add(
                Speaker(
                    project_id=pid,
                    speaker_label="OWNER",
                    role="Scope owner",
                    can_confirm_scope=True,
                )
            )
            db.add(
                Speaker(
                    project_id=pid,
                    speaker_label="OBSERVER",
                    role="Observer",
                    can_confirm_scope=False,
                )
            )
        db.add(
            ModelCall(
                id="test-call",
                run_id="run",
                stage="synthetic-test",
                deployment_name="none",
                served_model="none",
                prompt_hash="a" * 40,
                temperature=0,
                seed=None,
                input_tokens=0,
                output_tokens=0,
                latency_ms=0,
                retries=0,
                cost=0,
                raw_json_path="synthetic-test-no-response",
            )
        )
    yield engine, url
    engine.dispose()


def stage(
    engine,
    *,
    text="Users can sign in.",
    relation="new",
    matched=None,
    ids=None,
    project="P1",
    speaker="OWNER",
    quote=None,
):
    uid = str(uuid4())
    with transaction(engine) as db:
        tid = f"{project}-M01:{uid}"
        source = quote if quote is not None else text
        db.add(
            Turn(id=tid, meeting_id=f"{project}-M01", turn_index=1, speaker=speaker, text=source)
        )
        db.flush()
        db.add(
            Candidate(
                id=uid,
                meeting_id=f"{project}-M01",
                run_id="run",
                text_norm=text,
                evidence_json=json.dumps([{"turn_id": tid, "start": 0, "end": len(source)}]),
                extract_call_id="test-call",
            )
        )
        db.flush()
        proposal = stage_proposal(
            db,
            candidate_id=uid,
            classification=Classification(
                matched_requirement_id=matched,
                relation=relation,
                rationale="Synthetic test classification",
                retrieved_ids=ids or [],
            ),
            speaker_label=speaker,
        )
        return proposal.id


def decide(engine, pid, action="confirm", edited_text=None, embed=synthetic_embedding):
    with review_transaction(engine) as db:
        return commit_decision(
            db,
            proposal_id=pid,
            decision=ReviewDecision(action=action, actor="test-human", edited_text=edited_text),
            embed_text=embed,
        )


def family(engine, project="P1"):
    pid = stage(engine, project=project)
    decide(engine, pid)
    with Session(engine) as db:
        return db.scalar(select(Requirement.id).where(Requirement.project_id == project))


def counts(engine):
    with Session(engine) as db:
        return tuple(
            db.scalar(select(func.count()).select_from(t))
            for t in (Event, Requirement, RequirementVersion, RequirementCurrent)
        )


def api(url, **kwargs):
    return TestClient(
        create_app(
            database_url=url,
            reviewer_token="synthetic-test-token",
            embed_text=synthetic_embedding,
            **kwargs,
        )
    )


def test_confirm_persists_and_reopens_with_evidence_and_history(database):
    engine, url = database
    pid = stage(engine)
    assert counts(engine) == (0, 0, 0, 0)
    with api(url) as client:
        proposal = client.get("/projects/P1/proposals").json()["proposals"][0]
        assert proposal["can_confirm"] is True
        assert proposal["evidence"][0]["span"] == "Users can sign in."
        assert "start" not in proposal["evidence"][0]
        response = client.post(
            f"/proposals/{pid}/decision", headers=AUTH, json={"action": "confirm"}
        )
        assert response.status_code == 200, response.text
        assert response.json()["to_state"] == "confirmed"
    assert counts(engine) == (3, 1, 1, 1)  # Create, Confirm, review audit; one current version.
    with api(url) as reopened:
        rows = reopened.get("/projects/P1/requirements").json()
        assert len(rows) == 1 and rows[0]["state"] == "confirmed"
        rid = rows[0]["requirement_id"]
        detail = reopened.get(f"/projects/P1/requirements/{rid}").json()
        assert [v["state"] for v in detail["timeline"]] == ["confirmed"]
        assert reopened.get("/projects/P2/requirements").json() == []
        assert reopened.get(f"/projects/P2/requirements/{rid}").status_code == 404
        exported = reopened.get("/projects/P1/export").json()
        assert len(exported["requirements"][0]["versions"]) == 1
        duplicate = reopened.post(
            f"/proposals/{pid}/decision", headers=AUTH, json={"action": "confirm"}
        )
        assert duplicate.status_code == 409
        assert "already decided" in duplicate.json()["reason"]
    with Session(engine) as db:
        assert len(db.scalars(select(Event).where(Event.event_type == "review_blocked")).all()) == 1
        versions, heads = retrieval_snapshot(db, "P1")
        # A new requirement's Create and Confirm events share one retained version.
        assert len(versions) == 1 and heads[0].version == 1
        assert {v.embedding_model for v in versions} == {"test-only@1"}


def test_authentication_required_and_missing_configuration_blocks_writes(database):
    engine, url = database
    pid = stage(engine)
    with api(url) as client:
        assert (
            client.post(f"/proposals/{pid}/decision", json={"action": "confirm"}).status_code == 401
        )
    app = create_app(database_url=url, reviewer_token="", embed_text=synthetic_embedding)
    with TestClient(app) as client:
        assert (
            client.post(
                f"/proposals/{pid}/decision", headers=AUTH, json={"action": "confirm"}
            ).status_code
            == 503
        )
    assert counts(engine) == (0, 0, 0, 0)


def test_supersession_preserves_old_text_and_creates_linked_confirmed_replacement(database):
    engine, _ = database
    rid = family(engine)
    pid = stage(
        engine,
        text="Users sign in with SSO.",
        relation="supersession",
        matched=rid,
        ids=[rid],
        quote="We will use SSO instead.",
    )
    result = decide(engine, pid)
    assert result.to_state == "superseded"
    with Session(engine) as db:
        old = db.get(RequirementCurrent, rid)
        assert old.state == "superseded" and old.text == "Users can sign in."
        replacement = db.scalar(
            select(RequirementCurrent).where(RequirementCurrent.requirement_id != rid)
        )
        assert replacement.state == "confirmed" and replacement.text == "Users sign in with SSO."
        supersede = db.scalar(select(Event).where(Event.event_type == "supersede"))
        assert (
            json.loads(supersede.payload_json)["replacement_requirement_id"]
            == replacement.requirement_id
        )
        version = db.get(RequirementVersion, replacement.current_version_id)
        assert (
            json.loads(db.get(Event, version.created_event_id).payload_json)[
                "replaces_requirement_id"
            ]
            == rid
        )
        versions, _ = retrieval_snapshot(db, "P1")
        assert len(versions) == 3


@pytest.mark.parametrize(
    "speaker,quote",
    [
        ("OBSERVER", "We will use SSO instead."),
        ("OWNER", "Could we use SSO instead?"),
        ("OWNER", "If approved, we will use SSO instead."),
        ("OWNER", "We will not use SSO instead."),
        ("OWNER", "SSO might be useful."),
    ],
)
def test_hedges_and_unauthorised_speakers_do_not_supersede(database, speaker, quote):
    engine, _ = database
    rid = family(engine)
    pid = stage(
        engine, relation="supersession", matched=rid, ids=[rid], speaker=speaker, quote=quote
    )
    before = counts(engine)
    with pytest.raises(ReviewConflict, match="authorised speaker and an explicit replacement"):
        decide(engine, pid)
    assert counts(engine) == before


def test_reject_and_no_op_are_audited_without_mutating_register(database):
    engine, _ = database
    pid = stage(engine)
    rejected = decide(engine, pid, "reject")
    assert not rejected.register_changed and counts(engine) == (1, 0, 0, 0)
    rid = family(engine)
    pid = stage(engine, relation="restatement", matched=rid, ids=[rid])
    before = counts(engine)
    assert not decide(engine, pid).register_changed
    assert counts(engine) == (before[0] + 1, *before[1:])


def test_queue_does_not_resurface_legacy_decisions_after_schema_upgrade(database):
    engine, _ = database
    pid = stage(engine)
    decide(engine, pid)
    with transaction(engine) as db:
        # The old C schema stored the decision only on ProposalReview.
        db.get(Proposal, pid).decision = None
        queue = query_proposals(db, "P1")
        assert queue.proposals == []
        assert queue.queue_label == "0 pending proposals"


def test_refine_edits_reembed_and_preserve_original_prediction(database):
    engine, _ = database
    rid = family(engine)
    pid = stage(engine, relation="refinement", matched=rid, ids=[rid], text="Longer sessions.")
    seen = []

    def embed(text):
        seen.append(text)
        return synthetic_embedding(text)

    result = decide(engine, pid, "edit", "Sessions expire after 30 minutes.", embed)
    assert seen == ["Sessions expire after 30 minutes."]
    assert result.to_state == "confirmed"
    with Session(engine) as db:
        p = db.get(Proposal, pid)
        assert db.get(Candidate, p.candidate_id).text_norm == "Longer sessions."
        assert db.get(RequirementCurrent, rid).text == "Sessions expire after 30 minutes."
        assert len(db.scalars(select(RequirementVersion)).all()) == 2


def test_stale_proposal_and_revoked_authority_are_rechecked(database):
    engine, url = database
    rid = family(engine)
    first = stage(engine, relation="refinement", matched=rid, ids=[rid], text="First edit.")
    stale = stage(engine, relation="refinement", matched=rid, ids=[rid], text="Stale edit.")
    decide(engine, first)
    before = counts(engine)
    with pytest.raises(ReviewConflict, match="changed since"):
        decide(engine, stale)
    assert counts(engine) == before
    pid = stage(
        engine, relation="supersession", matched=rid, ids=[rid], quote="We will use SSO instead."
    )
    with api(url) as client:
        settings = client.get("/projects/P1/settings").json()
        next(s for s in settings["speakers"] if s["speaker_label"] == "OWNER")[
            "can_confirm_scope"
        ] = False
        assert client.put("/projects/P1/settings", headers=AUTH, json=settings).status_code == 200
        assert (
            client.post(
                f"/proposals/{pid}/decision", headers=AUTH, json={"action": "confirm"}
            ).status_code
            == 409
        )


def test_new_family_invalidates_a_staged_no_match_proposal(database):
    engine, _ = database
    first = stage(engine, text="Users can sign in.")
    stale = stage(engine, text="Users can access invoices.")
    decide(engine, first)
    before = counts(engine)
    with pytest.raises(ReviewConflict, match="Project requirements or states changed"):
        decide(engine, stale)
    assert counts(engine) == before


@pytest.mark.parametrize(
    "damage", ["foreign_evidence", "bad_offset", "foreign_retrieved", "invented_match", "legacy"]
)
def test_invalid_proposals_fail_closed(database, damage):
    engine, url = database
    rid = family(engine)
    other = family(engine, "P2")
    pid = stage(engine, relation="refinement", matched=rid, ids=[rid])
    with transaction(engine) as db:
        p = db.get(Proposal, pid)
        c = db.get(Candidate, p.candidate_id)
        if damage == "foreign_evidence":
            foreign = db.scalar(select(Turn).where(Turn.meeting_id == "P2-M01"))
            c.evidence_json = json.dumps([{"turn_id": foreign.id, "start": 0, "end": 3}])
        elif damage == "bad_offset":
            spans = json.loads(c.evidence_json)
            spans[0]["end"] = 99999
            c.evidence_json = json.dumps(spans)
        elif damage == "foreign_retrieved":
            p.retrieved_ids_json = json.dumps([rid, other])
        elif damage == "invented_match":
            p.retrieved_ids_json = "[]"
        else:
            db.delete(db.get(ProposalReview, pid))
    before = counts(engine)
    with api(url) as client:
        item = next(
            p for p in client.get("/projects/P1/proposals").json()["proposals"] if p["id"] == pid
        )
        assert not item["can_confirm"]
        assert (
            client.post(
                f"/proposals/{pid}/decision", headers=AUTH, json={"action": "confirm"}
            ).status_code
            == 409
        )
    assert counts(engine)[1:] == before[1:]


def test_mid_write_failure_rolls_back_events_versions_pointer_and_decision(database):
    engine, _ = database
    pid = stage(engine)

    def fail(conn, cursor, statement, parameters, context, executemany):
        if statement.startswith("INSERT INTO requirements_current"):
            raise RuntimeError("injected interruption after event and version flush")

    event.listen(engine, "before_cursor_execute", fail)
    try:
        with pytest.raises(RuntimeError, match="injected interruption"):
            decide(engine, pid)
    finally:
        event.remove(engine, "before_cursor_execute", fail)
    assert counts(engine) == (0, 0, 0, 0)
    with Session(engine) as db:
        assert db.get(ProposalReview, pid).decision_event_id is None
    assert decide(engine, pid).register_changed


def test_two_reviewers_cannot_commit_the_same_proposal(database):
    engine, _ = database
    pid = stage(engine)

    def attempt(_):
        try:
            return decide(engine, pid).register_changed
        except ReviewConflict:
            return False

    with ThreadPoolExecutor(max_workers=2) as pool:
        assert sorted(pool.map(attempt, range(2))) == [False, True]
    assert counts(engine) == (3, 1, 1, 1)


def test_embedding_failure_prevents_all_register_writes(database):
    engine, _ = database
    pid = stage(engine)

    def fail(_):
        raise ReviewConflict("Model unavailable")

    with pytest.raises(ReviewConflict, match="Model unavailable"):
        decide(engine, pid, embed=fail)
    assert counts(engine) == (0, 0, 0, 0)


def test_edited_text_cannot_switch_the_proposal_embedding_contract(database):
    engine, _ = database
    pid = stage(engine)
    with transaction(engine) as db:
        db.get(ProposalReview, pid).embedding_json = synthetic_embedding(
            "Users can sign in."
        ).model_dump_json()

    def incompatible_embedding(_text):
        return VectorRecord(
            embedding_model="other-model",
            embedding_version="1",
            embedding_dim=2,
            embedding=(1.0, 1.0),
        )

    with pytest.raises(ReviewConflict, match="does not match the Track B proposal encoder"):
        decide(engine, pid, "edit", "Users sign in with SSO.", incompatible_embedding)
    assert counts(engine) == (0, 0, 0, 0)


def test_replacement_rule_does_not_accept_negation():
    assert explicit_replacement(["We have decided to replace email login with SSO."])
    assert not explicit_replacement(["We won't replace email login with SSO."])


def test_existing_meeting_contract_imports_real_turns_and_is_idempotent(database):
    engine, url = database
    body = {
        "title": "Second meeting",
        "ordinal": 2,
        "source_name": "notes.txt",
        "turns": [{"speaker": "OWNER", "text": "  Keep exact whitespace.  "}],
    }
    with api(url) as client:
        blocked = client.post("/projects/P1/meetings", json=body)
        assert blocked.status_code == 401
        first = client.post("/projects/P1/meetings", headers=AUTH, json=body)
        assert first.status_code == 201, first.text
        assert first.json()["title"] == "Second meeting"
        second = client.post("/projects/P1/meetings", headers=AUTH, json=body)
        assert second.status_code == 200 and second.json()["id"] == first.json()["id"]
        turns = client.get("/meetings/P1-M02/turns").json()
        assert turns[0]["turn_id"] == "P1-M02:0000"
        assert turns[0]["before"] == "  Keep exact whitespace.  "
        body["turns"][0]["text"] = "Changed content"
        assert client.post("/projects/P1/meetings", headers=AUTH, json=body).status_code == 409
        body["ordinal"] = 3
        body["turns"][0]["speaker"] = "UNKNOWN"
        assert client.post("/projects/P1/meetings", headers=AUTH, json=body).status_code == 409
    with Session(engine) as db:
        assert db.get(Meeting, "P1-M03") is None


def test_replay_preserves_snapshot_versions_and_replacement_families(database):
    engine, _ = database
    rid = family(engine)
    pid = stage(
        engine,
        relation="supersession",
        matched=rid,
        ids=[rid],
        text="Use SSO.",
        quote="We will use SSO instead.",
    )
    decide(engine, pid)
    with Session(engine) as db:
        assert _compute_actual_state(db, run_id="run", project_id="P1", after_meeting=0) == {}
        actual = _compute_actual_state(db, run_id="run", project_id="P1", after_meeting=1)
        currents = db.scalars(select(RequirementCurrent)).all()
        assert set(actual) == {c.requirement_id for c in currents}
        for head in currents:
            expected_version = db.get(RequirementVersion, head.current_version_id)
            assert actual[head.requirement_id].state == head.state
            assert actual[head.requirement_id].version == expected_version.version
            assert actual[head.requirement_id].text == head.text


def test_precomputed_candidate_embedding_is_saved_without_a_model_call(database):
    engine, _ = database
    pid = stage(engine)
    with transaction(engine) as db:
        db.get(ProposalReview, pid).embedding_json = synthetic_embedding(
            "Users can sign in."
        ).model_dump_json()

    def unexpected(_):
        raise AssertionError("Unedited precomputed text must not be encoded again")

    decide(engine, pid, embed=unexpected)
    with Session(engine) as db:
        versions, _ = retrieval_snapshot(db, "P1")
        assert len(versions) == 1
