"""E3 denominator, failure accounting, label separation and historical cutoff checks."""

import json
from pathlib import Path

import pytest
from pydantic import ValidationError

from src.eval.retrieval_schemas import RetrievalDataset, RetrievalObservation
from src.eval.run_retrieval import run_retrieval
from src.eval.score import _read_observations, score_retrieval
from src.retrieve.schemas import RetrievalResult, VectorRecord


def write_gold(tmp_path: Path, cases: list[tuple[str, str | None]]) -> Path:
    path = tmp_path / "dev-labels.json"
    path.write_text(
        json.dumps(
            {
                "split": "dev",
                "cases": [
                    {"case_id": case_id, "expected_requirement_id": expected}
                    for case_id, expected in cases
                ],
            }
        )
    )
    return path


def observation(case_id: str, ranking: tuple[str, ...]) -> RetrievalObservation:
    return RetrievalObservation(
        case_id=case_id,
        result=RetrievalResult(
            candidate_id=case_id,
            project_id="P1",
            embedding_model="test-fixture",
            families=(),
            bm25_family_ids=ranking,
            dense_family_ids=tuple(reversed(ranking)),
            fused_family_ids=ranking,
        ),
    )


def dataset_data() -> dict[str, object]:
    return {
        "split": "dev",
        "cases": [
            {
                "case_id": "D1-M3-C1",
                "meeting_ordinal": 3,
                "history_cutoff": 2,
                "candidate": {
                    "candidate_id": "C1",
                    "project_id": "P1",
                    "meeting_id": "M3",
                    "text_norm": "email login",
                    "evidence": [],
                },
                "history": [
                    {
                        "project_id": "P1",
                        "requirement_id": "R1",
                        "version": 1,
                        "text": "email login",
                        "state": "superseded",
                        "available_after_meeting": 1,
                    },
                    {
                        "project_id": "P1",
                        "requirement_id": "R1",
                        "version": 2,
                        "text": "company single sign on",
                        "state": "confirmed",
                        "available_after_meeting": 2,
                    },
                    {
                        "project_id": "P1",
                        "requirement_id": "FUTURE",
                        "version": 1,
                        "text": "future meeting private wording",
                        "state": "confirmed",
                        "available_after_meeting": 3,
                    },
                    {
                        "project_id": "P2",
                        "requirement_id": "OTHER",
                        "version": 1,
                        "text": "other project private wording",
                        "state": "confirmed",
                        "available_after_meeting": 1,
                    },
                ],
            }
        ],
    }


def test_channels_and_cutoffs_are_scored_independently(tmp_path: Path) -> None:
    gold = write_gold(tmp_path, [("a", "R4")])
    ranking = tuple(f"R{i}" for i in range(1, 9))
    metrics = score_retrieval((observation("a", ranking),), gold)
    assert metrics["recall_at_k"] == {
        "bm25": {"3": 0.0, "5": 1.0, "8": 1.0},
        "dense": {"3": 0.0, "5": 1.0, "8": 1.0},
        "fused": {"3": 0.0, "5": 1.0, "8": 1.0},
    }
    assert metrics["cases"][0]["ranks"] == {"bm25": 4, "dense": 5, "fused": 4}


def test_failed_and_missing_predictions_stay_in_recall_denominator(tmp_path: Path) -> None:
    gold = write_gold(tmp_path, [("a", "R1"), ("b", "R1"), ("c", "R1")])
    outputs = (observation("a", ("R1",)), RetrievalObservation(case_id="b", error="encode failed"))
    metrics = score_retrieval(outputs, gold)
    assert metrics["recall_at_k"]["fused"]["3"] == pytest.approx(1 / 3)
    assert metrics["error_or_missing_outputs"] == 2
    assert metrics["coverage"] == pytest.approx(1 / 3)
    assert metrics["cases"][2]["error"] == "missing output"


def test_no_match_cases_are_not_recall_successes(tmp_path: Path) -> None:
    gold = write_gold(tmp_path, [("a", "R1"), ("b", None)])
    metrics = score_retrieval((observation("a", ("R2",)), observation("b", ())), gold)
    assert metrics["matchable_cases"] == 1
    assert metrics["no_match_cases"] == 1
    assert metrics["recall_at_k"]["fused"]["8"] == 0.0
    assert metrics["no_match_accuracy"] is None


def test_all_no_match_dataset_has_no_recall_value(tmp_path: Path) -> None:
    gold = write_gold(tmp_path, [("a", None)])
    metrics = score_retrieval((observation("a", ()),), gold)
    assert metrics["recall_at_k"]["fused"]["3"] is None


def test_duplicate_or_unlabelled_outputs_fail_explicitly(tmp_path: Path) -> None:
    gold = write_gold(tmp_path, [("a", "R1")])
    item = observation("a", ("R1",))
    with pytest.raises(ValueError, match="Duplicate observed"):
        score_retrieval((item, item), gold)
    with pytest.raises(ValueError, match="missing from gold"):
        score_retrieval((observation("unknown", ()),), gold)


def test_duplicate_gold_is_rejected(tmp_path: Path) -> None:
    gold = write_gold(tmp_path, [("a", "R1"), ("a", "R1")])
    with pytest.raises(ValidationError, match="Duplicate gold"):
        score_retrieval((), gold)


def test_duplicate_ranked_ids_are_counted_as_invalid_outputs(tmp_path: Path) -> None:
    gold = write_gold(tmp_path, [("a", "R1")])
    metrics = score_retrieval((observation("a", ("R1", "R1")),), gold)
    assert metrics["error_or_missing_outputs"] == 1
    assert metrics["recall_at_k"]["fused"]["3"] == 0.0


def test_development_scorer_rejects_holdout_without_reading(tmp_path: Path) -> None:
    with pytest.raises(ValueError, match="holdout"):
        score_retrieval((), tmp_path / "holdout" / "does-not-exist.json")
    gold = write_gold(tmp_path, [("a", "R1")])
    gold.write_text(gold.read_text().replace('"dev"', '"holdout"'))
    with pytest.raises(ValidationError):
        score_retrieval((), gold)


def test_future_and_other_project_text_never_reaches_encoder() -> None:
    dataset = RetrievalDataset.model_validate(dataset_data())
    batches: list[list[str]] = []

    def encode(texts: list[str]) -> tuple[VectorRecord, ...]:
        batches.append(texts)
        return tuple(VectorRecord(embedding_model="test-fixture", embedding=(1, 0)) for _ in texts)

    outputs = run_retrieval(dataset, encode)
    assert batches == [["email login", "company single sign on", "email login"]]
    assert outputs[0].result.retrieved_ids == ["R1"]
    assert len(outputs[0].result.families[0].versions) == 2


def test_first_meeting_has_empty_history() -> None:
    data = dataset_data()
    data["cases"][0]["meeting_ordinal"] = 1
    data["cases"][0]["history_cutoff"] = 0
    batches: list[list[str]] = []

    def encode(texts: list[str]) -> tuple[VectorRecord, ...]:
        batches.append(texts)
        return (VectorRecord(embedding_model="test-fixture", embedding=(1, 0)),)

    output = run_retrieval(RetrievalDataset.model_validate(data), encode)
    assert batches == [["email login"]]
    assert output[0].result.retrieved_ids == []


def test_inference_inputs_reject_expected_match_labels() -> None:
    data = dataset_data()
    data["cases"][0]["expected_requirement_id"] = "R1"
    with pytest.raises(ValidationError, match="Extra inputs"):
        RetrievalDataset.model_validate(data)


def test_cutoff_and_duplicate_case_ids_are_checked() -> None:
    data = dataset_data()
    data["cases"][0]["history_cutoff"] = 3
    with pytest.raises(ValidationError, match="precede"):
        RetrievalDataset.model_validate(data)
    data = dataset_data()
    data["cases"].append(data["cases"][0])
    with pytest.raises(ValidationError, match="Duplicate case"):
        RetrievalDataset.model_validate(data)


def test_encoder_failure_does_not_drop_case() -> None:
    def fail(texts: list[str]) -> tuple[VectorRecord, ...]:
        raise RuntimeError("failed inference")

    outputs = run_retrieval(RetrievalDataset.model_validate(dataset_data()), fail)
    assert len(outputs) == 1
    assert outputs[0].result is None
    assert outputs[0].error == "RuntimeError: failed inference"


def test_malformed_raw_output_is_counted_as_an_error(tmp_path: Path) -> None:
    outputs = _read_observations([{"case_id": "a", "result": {"wrong": "schema"}}])
    gold = write_gold(tmp_path, [("a", "R1")])
    metrics = score_retrieval(outputs, gold)
    assert metrics["error_or_missing_outputs"] == 1
    assert metrics["recall_at_k"]["fused"]["3"] == 0.0


def test_unidentifiable_raw_output_fails_explicitly() -> None:
    with pytest.raises(ValueError, match="case ID"):
        _read_observations([{"result": {}}])
