"""Oracle path, classifier downgrade, register identity, and score arithmetic.

No Azure calls and no local encoder weights.
"""

import json
from datetime import UTC, datetime
from pathlib import Path

import pytest
import yaml
from sqlalchemy.orm import Session, sessionmaker

import src.extract
from src.api.queries import proposals as query_proposals
from src.classify.classify import ClassificationOutcome, apply_soft_downgrade, classify_candidate
from src.classify.schemas import Classification, Relation
from src.engine.state_machine import EventType, State
from src.eval.gold_candidates import gold_candidate_from_event
from src.eval.metrics import (
    DRIVING_LABELS,
    align_by_span,
    expected_register,
    illegal_transition_rate,
    relation_report,
)
from src.eval.run_baseline import run_baseline
from src.eval.run_pipeline import _log_local_embedding, run_pipeline
from src.eval.score import score_run
from src.extract import ExtractionResult
from src.extract.schemas import Candidate
from src.logging.calls import ModelCallError, ParsedResponse
from src.persist.database import create_database_engine
from src.persist.models import (
    Base,
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
    Turn,
)
from src.persist.models import (
    Candidate as CandidateRow,
)
from src.persist.register import confirm_current, write_version
from src.retrieve.embedder import encoder_kind, get_embedder
from src.retrieve.embeddings import EmbeddingCall
from src.validate.schemas import EvidenceSpan
from tests.test_classification_contract import make_inputs


class _Logger:
    def __init__(self, contents: list[object]) -> None:
        self.contents = list(contents)
        self.calls = 0

    def call(self, **kwargs: object) -> ParsedResponse:
        assert kwargs["stage"] == "classify"
        self.calls += 1
        item = self.contents.pop(0)
        if isinstance(item, Exception):
            raise item
        return ParsedResponse(
            call_id=f"c{self.calls}",
            content=str(item),
            input_tokens=1,
            output_tokens=1,
            served_model="gpt-4o-2024-11-20",
            latency_ms=1,
            retries=0,
        )


def _prediction(relation: str, matched: str | None, replacement: bool) -> str:
    return json.dumps(
        {
            "matched_requirement_id": matched,
            "relation": relation,
            "rationale": "The source is explicit.",
            "replacement_stated": replacement,
        }
    )


def test_supersession_without_replacement_downgrades_once() -> None:
    logger = _Logger([_prediction("supersession", "R01", False)])
    outcome = classify_candidate(
        None,
        session=None,
        run_id="run",
        inputs=make_inputs(),
        deployment_name="cia-chat",
        logger=logger,  # type: ignore[arg-type]
    )
    assert logger.calls == 1
    assert outcome.downgraded is True
    assert outcome.model_relation == "supersession"
    assert outcome.classification is not None
    assert outcome.classification.relation == Relation.CONTRADICTION
    assert outcome.classification.replacement_stated is False
    assert outcome.retrieved_ids == tuple(outcome.classification.retrieved_ids)


def test_stated_replacement_is_not_downgraded() -> None:
    logger = _Logger([_prediction("supersession", "R01", True)])
    outcome = classify_candidate(
        None,
        session=None,
        run_id="run",
        inputs=make_inputs(),
        deployment_name="cia-chat",
        logger=logger,  # type: ignore[arg-type]
    )
    assert outcome.downgraded is False
    assert outcome.classification is not None
    assert outcome.classification.relation == Relation.SUPERSESSION


def test_hard_failure_retries_once_and_is_not_repaired() -> None:
    logger = _Logger(["{", "{"])
    outcome = classify_candidate(
        None,
        session=None,
        run_id="run",
        inputs=make_inputs(),
        deployment_name="cia-chat",
        logger=logger,  # type: ignore[arg-type]
    )
    assert logger.calls == 2
    assert outcome.classification is None
    assert outcome.error
    kept = Classification(
        matched_requirement_id="R01",
        relation=Relation.SUPERSESSION,
        rationale="unchanged",
        retrieved_ids=["R01"],
        replacement_stated=False,
    )
    downgraded, flag = apply_soft_downgrade(kept)
    assert flag is True
    assert kept.relation == Relation.SUPERSESSION
    assert downgraded.relation == Relation.CONTRADICTION


def test_invalid_json_then_a_valid_call_is_accepted() -> None:
    logger = _Logger(["{", _prediction("new", None, False)])
    outcome = classify_candidate(
        None,
        session=None,
        run_id="run",
        inputs=make_inputs(),
        deployment_name="cia-chat",
        logger=logger,  # type: ignore[arg-type]
    )
    assert logger.calls == 2
    assert outcome.error is None
    assert outcome.classification is not None
    assert outcome.classification.relation == Relation.NEW


def test_transport_failure_is_not_retried_again_by_the_classifier() -> None:
    logger = _Logger([ModelCallError("down")])
    outcome = classify_candidate(
        None,
        session=None,
        run_id="run",
        inputs=make_inputs(),
        deployment_name="cia-chat",
        logger=logger,  # type: ignore[arg-type]
    )
    assert logger.calls == 1
    assert outcome.classification is None


def test_gold_candidate_drops_labels() -> None:
    built = gold_candidate_from_event(
        {
            "relation": "supersession",
            "requirement_id": "R99",
            "canonical_requirement_id": "R99",
            "expected_state_after": "superseded",
            "event_action": "Supersede",
            "statement": "Sessions last sixty minutes.",
            "evidence": [{"turn_id": "D1-M02:0001", "start": 1, "end": 4, "quote": "ignored"}],
        },
        project_id="D1",
        meeting_id="D1-M02",
        candidate_index=0,
        run_id="abcdef123456",
    )
    dumped = built.candidate.model_dump()
    assert dumped["text_norm"] == "Sessions last sixty minutes."
    assert "supersession" not in json.dumps(dumped)
    assert "R99" not in json.dumps(dumped)
    assert built.event_action is None
    confirmed = gold_candidate_from_event(
        {
            "event_action": "Confirm",
            "evidence": [{"turn_id": "T1", "start": 0, "end": 3, "quote": "Use SSO."}],
        },
        project_id="P",
        meeting_id="M",
        candidate_index=1,
        run_id="abcdef123456",
    )
    assert confirmed.event_action == "confirm"
    assert confirmed.candidate.text_norm == "Use SSO."


def test_default_encoder_is_local(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("CIA_ENCODER", raising=False)
    assert encoder_kind() == "local"
    monkeypatch.setenv("CIA_ENCODER", "azure")
    assert encoder_kind() == "azure"
    with pytest.raises(ValueError, match="call logger"):
        get_embedder()
    monkeypatch.setenv("CIA_ENCODER", "other")
    with pytest.raises(ValueError, match="local or azure"):
        encoder_kind()


def test_register_write_requires_encoder_identity_and_confirm_does_not_add_a_version(
    tmp_path: Path,
) -> None:
    engine = create_database_engine(f"sqlite:///{tmp_path / 'reg.db'}")
    Base.metadata.create_all(engine)
    session = sessionmaker(bind=engine)()
    session.add(Project(id="P", name="P", created_at=datetime(2026, 1, 1, tzinfo=UTC)))
    session.add(
        Run(
            id="run",
            mode="eval",
            candidate_source="gold",
            repeat_index=1,
            prompt_hash="hash",
            model_deployment="cia-chat",
            temp=0.0,
            started_at=datetime(2026, 1, 1, tzinfo=UTC),
        )
    )
    session.commit()
    candidate = Candidate(
        candidate_id="C",
        project_id="P",
        meeting_id="M",
        text_norm="Users sign in with email.",
        evidence=[EvidenceSpan(turn_id="M:0001", start=0, end=4)],
    )
    with pytest.raises(ValueError, match="embedding"):
        write_version(
            session,
            project_id="P",
            run_id="run",
            requirement_id="R01",
            event_type=EventType.CREATE,
            resulting_state=State.PROPOSED,
            candidate=candidate,
            classification=None,
            meeting_ordinal=1,
            seq=1,
            embedding=None,
            embedding_model=None,
            embedding_version=None,
            embedding_dim=None,
            enforce=True,
        )
    session.rollback()
    write_version(
        session,
        project_id="P",
        run_id="run",
        requirement_id="R01",
        event_type=EventType.CREATE,
        resulting_state=State.PROPOSED,
        candidate=candidate,
        classification=None,
        meeting_ordinal=1,
        seq=1,
        embedding=(1.0, 0.0),
        embedding_model="unit-fixture",
        embedding_version="v1",
        embedding_dim=2,
        enforce=True,
    )
    confirm_current(
        session,
        project_id="P",
        run_id="run",
        requirement_id="R01",
        candidate=candidate,
        classification=None,
        meeting_ordinal=1,
        seq=2,
        enforce=True,
    )
    session.commit()
    versions = session.query(RequirementVersion).all()
    assert len(versions) == 1
    assert versions[0].state == "confirmed"
    assert versions[0].embedding_model == "unit-fixture"
    assert versions[0].embedding_version == "v1"
    assert versions[0].embedding_dim == 2
    assert session.get(RequirementCurrent, "R01").state == "confirmed"
    assert session.query(Event).count() == 2
    session.close()
    engine.dispose()


def test_d1_expected_register_follows_the_gold_file() -> None:
    events = yaml.safe_load(Path("scenarios/dev/D1/gold.yaml").read_text(encoding="utf-8"))[
        "events"
    ]
    register = expected_register(events, 2)
    assert register["R01"] == {"state": "confirmed", "version": 1}
    assert register["R03"] == {"state": "confirmed", "version": 2}
    assert register["R05"] == {"state": "superseded", "version": 2}
    assert register["R06"] == {"state": "superseded", "version": 2}
    assert register["R07"] == {"state": "confirmed", "version": 2}
    assert "contradicted" not in {item["state"] for item in register.values()}


def test_four_class_macro_f1_names_zero_support() -> None:
    report = relation_report(
        [("new", "new"), ("new", "contradiction"), ("refinement", "refinement")],
        DRIVING_LABELS,
    )
    assert report["per_class"]["new"]["support"] == 2
    assert report["per_class"]["new"]["f1"] == pytest.approx(2 / 3)
    assert report["per_class"]["refinement"]["f1"] == 1
    assert report["excluded_zero_support"] == ["contradiction", "supersession"]
    assert report["macro_f1"] == pytest.approx((2 / 3 + 1) / 2)


def test_span_alignment_does_not_use_statement_text() -> None:
    gold = [
        {"relation": "new", "evidence": [{"turn_id": "T", "start": 0, "end": 5}]},
        {"relation": "new", "evidence": [{"turn_id": "T", "start": 10, "end": 15}]},
    ]
    predictions = [
        {
            "candidate_id": "a",
            "evidence": [{"turn_id": "T", "start": 12, "end": 18}],
            "predicted_relation": "new",
        },
        {
            "candidate_id": "b",
            "evidence": [{"turn_id": "T", "start": 0, "end": 2}],
            "predicted_relation": "refinement",
        },
    ]
    aligned, spurious = align_by_span(gold, predictions)
    assert spurious == []
    assert aligned[0][1]["candidate_id"] == "b"
    assert aligned[1][1]["candidate_id"] == "a"


def test_illegal_create_sequence_is_measured() -> None:
    legal = illegal_transition_rate(
        [
            {"requirement_id": "R01", "event_type": "create", "seq": 1},
            {"requirement_id": "R01", "event_type": "confirm", "seq": 2},
        ]
    )
    assert legal["rate"] == 0
    illegal = illegal_transition_rate(
        [{"requirement_id": "R01", "event_type": "supersede", "seq": 1}]
    )
    assert illegal["rate"] == 1


class _Embedder:
    model = "unit-fixture"
    version = "v1"
    dim = 2

    def encode(self, texts: list[str]) -> list[tuple[float, ...]]:
        return [(1.0, 0.0) for _ in texts]

    def fingerprint(self) -> str:
        return "fake"


def test_local_embedding_call_log_survives_later_pipeline_rollback(tmp_path: Path) -> None:
    db_url = f"sqlite:///{tmp_path / 'local-call-log.db'}"
    engine = create_database_engine(db_url)
    Base.metadata.create_all(engine)
    run_id = "local-embed-run"
    with Session(engine) as session:
        session.add(
            Run(
                id=run_id,
                mode="demo",
                candidate_source="extracted",
                repeat_index=1,
                prompt_hash="prompt-hash",
                model_deployment="local",
                temp=0,
                started_at=datetime.now(UTC),
                notes="{}",
            )
        )
        session.commit()
        _log_local_embedding(
            session,
            run_id,
            EmbeddingCall(
                model_id="local-model@revision",
                config_hash="encoder-hash",
                texts=("candidate",),
                input_tokens=2,
                latency_ms=4,
                vectors=((1.0, 0.0),),
            ),
            tmp_path / "runs",
        )
        session.rollback()

    with Session(engine) as session:
        rows = session.query(ModelCall).filter(ModelCall.run_id == run_id).all()
        assert len(rows) == 1
        assert rows[0].stage == "embed"
        assert rows[0].prompt_hash == "encoder-hash"
    engine.dispose()


def test_demo_extracted_pipeline_stages_track_b_output_without_register_writes(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    def fake_extract(session, client, *, run_id, meeting_id, **kwargs):
        turn = session.query(Turn).filter(Turn.meeting_id == meeting_id).first()
        assert turn is not None
        candidate_id = f"{meeting_id}-C0000"
        candidate = Candidate(
            candidate_id=candidate_id,
            project_id=session.get(Meeting, meeting_id).project_id,
            meeting_id=meeting_id,
            text_norm=turn.text,
            evidence=[EvidenceSpan(turn_id=turn.id, start=0, end=len(turn.text))],
            atomic=True,
        )
        session.add(
            CandidateRow(
                id=candidate_id,
                meeting_id=meeting_id,
                run_id=run_id,
                text_norm=candidate.text_norm,
                evidence_json=json.dumps([{"turn_id": turn.id, "start": 0, "end": len(turn.text)}]),
                extract_call_id=None,
            )
        )
        return ExtractionResult(
            candidates=[candidate], returned=3, accepted=1, rejected_unresolvable=2
        )

    def fake_classify(client, *, inputs, **kwargs):
        classification = Classification(
            matched_requirement_id=None,
            relation=Relation.NEW,
            rationale="Synthetic pipeline integration check.",
            retrieved_ids=list(inputs.retrieval.retrieved_ids),
        )
        return ClassificationOutcome(
            retrieved_ids=tuple(classification.retrieved_ids),
            classification=classification,
            downgraded=False,
            model_relation="new",
            error=None,
            call_ids=(),
        )

    monkeypatch.setattr(src.extract, "extract_candidates", fake_extract)
    db_url = f"sqlite:///{tmp_path / 'demo.db'}"
    stats = run_pipeline(
        scenario_dir=Path("scenarios/dev/D1"),
        mode="demo",
        candidate_source="extracted",
        repeat_index=1,
        db_url=db_url,
        runs_dir=tmp_path / "runs",
        client=object(),
        config=type("Cfg", (), {"deployment_name": "stub", "temperature": 0, "seed": 1})(),
        embedder=_Embedder(),
        classifier=fake_classify,
    )
    engine = create_database_engine(db_url)
    session = sessionmaker(bind=engine)()
    try:
        proposals = session.query(Proposal).filter(Proposal.run_id == stats["run_id"]).all()
        assert stats["errors"] == []
        assert stats["events_applied"] == 0
        assert len(proposals) == stats["proposals_created"] > 0
        assert all(proposal.decision is None for proposal in proposals)
        assert all(
            session.get(ProposalReview, proposal.id).embedding_json for proposal in proposals
        )
        queue = query_proposals(session, stats["project_id"])
        assert len(queue.proposals) == len(proposals)
        assert queue.discarded_candidates == 4
        assert all(
            item.can_confirm and item.classification.relation == Relation.NEW
            for item in queue.proposals
        )
        assert session.query(Requirement).count() == 0
        assert session.query(RequirementVersion).count() == 0
        assert session.query(Event).count() == 0
    finally:
        session.close()
        engine.dispose()


def test_demo_pipeline_rejects_gold_candidates() -> None:
    with pytest.raises(ValueError, match="gold is eval-only"):
        run_pipeline(
            scenario_dir=Path("unused"),
            mode="demo",
            candidate_source="gold",
            repeat_index=1,
        )


def test_gold_run_does_not_copy_labels_and_retrieval_sees_earlier_versions(tmp_path: Path) -> None:
    seen: list[Classification] = []

    def fake_classify(client, *, session, run_id, inputs, **kwargs):
        assert "speaker_can_confirm_scope" not in inputs.model_dump()
        seen.append(inputs.candidate)
        classification = Classification(
            matched_requirement_id=None,
            relation=Relation.NEW,
            rationale="stub",
            retrieved_ids=list(inputs.retrieval.retrieved_ids),
            replacement_stated=False,
        )
        return ClassificationOutcome(
            retrieved_ids=tuple(classification.retrieved_ids),
            classification=classification,
            downgraded=False,
            model_relation="new",
            error=None,
            call_ids=(),
        )

    stats = run_pipeline(
        scenario_dir=Path("scenarios/dev/D1"),
        mode="eval",
        candidate_source="gold",
        repeat_index=1,
        db_url=f"sqlite:///{tmp_path / 'oracle.db'}",
        runs_dir=tmp_path / "runs",
        client=object(),
        config=type("Cfg", (), {"deployment_name": "cia-chat", "temperature": 0.0, "seed": 42})(),
        embedder=_Embedder(),
        classifier=fake_classify,
    )
    assert stats["errors"] == []
    assert stats["proposals_created"] == 14
    assert len(seen) == 14
    sixty = next(candidate for candidate in seen if "sixty minutes" in candidate.text_norm)
    assert "supersession" not in sixty.text_norm

    engine = create_database_engine(f"sqlite:///{tmp_path / 'oracle.db'}")
    session = sessionmaker(bind=engine)()
    assert session.query(ModelCall).filter(ModelCall.stage == "extract").count() == 0
    proposals = session.query(Proposal).all()
    assert proposals
    assert {row.predicted_relation for row in proposals} == {"new"}
    assert all(
        json.loads(row.retrieved_ids_json) == json.loads(row.rankings_json)["offered"]
        for row in proposals
    )
    versions = session.query(RequirementVersion).all()
    assert len(versions) == 14
    assert all(
        row.embedding_model and row.embedding_version and row.embedding_dim for row in versions
    )
    assert session.query(Requirement).count() == 14
    later = max(proposals, key=lambda row: len(json.loads(row.rankings_json)["fused"]))
    assert "R01" in json.loads(later.rankings_json)["fused"]
    assert (
        session.query(RequirementCurrent).filter(RequirementCurrent.state == "confirmed").count()
        == 14
    )
    session.close()
    engine.dispose()
    report = score_run(
        stats["run_id"],
        db_url=f"sqlite:///{tmp_path / 'oracle.db'}",
        scenario_dir=Path("scenarios/dev/D1"),
    )
    assert report["split"] == "dev"
    assert report["column"] == "oracle"
    assert "skipped" in report["e2"]
    assert report["e4_illegal_transition_rate"]["rate"] == 0
    assert report["e5"]["per_meeting"]["2"]["support"] == 8
    assert report["e5"]["per_meeting"]["2"]["accuracy"] != 1
    assert set(report["four_class_support"]) == {
        "new",
        "refinement",
        "contradiction",
        "supersession",
    }


def test_baseline_writes_an_illegal_supersession_without_the_engine(tmp_path: Path) -> None:
    def responder(user: dict) -> str:
        if user["meeting_id"] != "D1-M01":
            return json.dumps({"changes": []})
        return json.dumps(
            {
                "changes": [
                    {
                        "statement": "Users sign in with a badge.",
                        "evidence": [
                            {
                                "turn_id": "D1-M01:0001",
                                "quote": "Users must be able to log in using their email address and a password",
                            }
                        ],
                        "requirement_id": "R99",
                        "relation": "supersession",
                    }
                ]
            }
        )

    stats = run_baseline(
        Path("scenarios/dev/D1"),
        "eval",
        1,
        db_url=f"sqlite:///{tmp_path / 'baseline.db'}",
        runs_dir=tmp_path / "runs",
        responder=responder,
    )
    assert stats["errors"] == []
    assert stats["events_applied"] == 1
    report = score_run(
        stats["run_id"],
        db_url=f"sqlite:///{tmp_path / 'baseline.db'}",
        scenario_dir=Path("scenarios/dev/D1"),
    )
    assert report["system"] == "baseline"
    assert report["e4_illegal_transition_rate"]["rate"] == 1
    assert report["invented_id_rate"]["invented"] == 1


def test_sdk_calls_stay_inside_the_logger() -> None:
    hits = []
    for path in Path("src").rglob("*.py"):
        if "logging" in path.parts:
            continue
        text = path.read_text(encoding="utf-8")
        for needle in ("chat.completions.create", "embeddings.create"):
            if needle in text:
                hits.append(f"{path.as_posix()}:{needle}")
    assert hits == []


def test_pipeline_modules_do_not_read_gold_labels() -> None:
    for relative in (
        "src/eval/run_pipeline.py",
        "src/eval/run_baseline.py",
        "src/eval/gold_candidates.py",
    ):
        text = Path(relative).read_text(encoding="utf-8")
        assert '.get("relation")' not in text
        assert '.get("requirement_id")' not in text
        assert "canonical_requirement_id" not in text
        assert "expected_state_after" not in text


def test_extraction_failure_is_visible_in_top_level_run_and_score(tmp_path):
    from unittest.mock import MagicMock

    client = MagicMock()
    client.chat.completions.create.side_effect = TimeoutError("provider unavailable")
    db_url = f"sqlite:///{tmp_path / 'failed-extraction.db'}"
    stats = run_pipeline(
        scenario_dir=Path("scenarios/dev/D1"),
        mode="demo",
        candidate_source="extracted",
        repeat_index=1,
        db_url=db_url,
        runs_dir=tmp_path / "runs",
        client=client,
        config=type("Cfg", (), {"deployment_name": "cia-chat", "temperature": 0, "seed": 42})(),
        embedder=_Embedder(),
    )
    assert stats["meetings_processed"] == 2 and stats["proposals_created"] == 0
    assert len(stats["errors"]) == 2
    assert all(
        "Extraction failed for D1-M" in error and "TimeoutError" in error
        for error in stats["errors"]
    )
    engine = create_database_engine(db_url)
    with Session(engine) as session:
        notes = json.loads(session.get(Run, stats["run_id"]).notes)
        assert notes["extraction"]["parse_failures"] == 2
        assert len(notes["extraction_errors"]) == 2
        assert all(len(error["call_ids"]) == 2 for error in notes["extraction_errors"])
        assert session.query(ModelCall).count() == client.chat.completions.create.call_count == 4
        assert session.query(Requirement).count() == 0
    engine.dispose()
    report = score_run(stats["run_id"], db_url=db_url, scenario_dir=Path("scenarios/dev/D1"))
    assert report["e8"]["calls"] == report["e8"]["failed_calls"] == 4
    assert report["e8"]["cost"] is None and report["e8"]["unknown_usage_calls"] == 4


def test_baseline_uses_same_failure_audit_and_does_not_write_register(tmp_path):
    from unittest.mock import MagicMock

    client = MagicMock()
    client.chat.completions.create.side_effect = TimeoutError("upstream private text")
    db_url = f"sqlite:///{tmp_path / 'failed-baseline.db'}"
    stats = run_baseline(
        scenario_dir=Path("scenarios/dev/D1"),
        mode="eval",
        repeat_index=1,
        db_url=db_url,
        runs_dir=tmp_path / "runs",
        client=client,
        config=type("Cfg", (), {"deployment_name": "cia-chat", "temperature": 0, "seed": 42})(),
    )
    assert len(stats["errors"]) == 2 and stats["events_applied"] == 0
    engine = create_database_engine(db_url)
    with Session(engine) as session:
        calls = session.query(ModelCall).all()
        assert len(calls) == client.chat.completions.create.call_count == 4
        assert all(call.stage == "baseline" for call in calls)
        assert session.query(Requirement).count() == 0
    engine.dispose()
    report = score_run(stats["run_id"], db_url=db_url, scenario_dir=Path("scenarios/dev/D1"))
    assert report["e8"]["failed_calls"] == report["e8"]["unknown_usage_calls"] == 4
    assert report["e8"]["cost"] is None
