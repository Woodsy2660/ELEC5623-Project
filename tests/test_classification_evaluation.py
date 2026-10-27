"""Hand-calculated E3 metrics and CLI checks, never model-performance evidence."""

import hashlib
import json
import subprocess
import sys
from pathlib import Path

import pytest
from pydantic import ValidationError

from src.eval.classification_schemas import ClassificationRun
from src.eval.score import score_classification


def prediction(
    case_id: str,
    relation: str = "refinement",
    matched: str | None = "R1",
    *,
    project_id: str = "P1",
    offered: tuple[str, ...] | None = ("R1", "R2"),
) -> dict[str, object]:
    return {
        "project_id": project_id,
        "case_id": case_id,
        "status": "ok",
        "offered_ids": offered,
        "raw_content": json.dumps(
            {
                "matched_requirement_id": matched,
                "relation": relation,
                "rationale": "Source evidence.",
            }
        ),
    }


def run_data(cases: list[dict[str, object]], method: str = "pipeline") -> dict[str, object]:
    return {
        "kind": "dev-e3-oracle",
        "split": "dev",
        "method": method,
        "run_id": "software-test-only",
        "repeat_index": 1,
        "model": "test-fixture-no-model-called",
        "prompt_hash": "a" * 40,
        "inputs_sha256": "b" * 64,
        "cases": cases,
    }


def write_gold(tmp_path: Path, cases: list[tuple[str, str, str | None, str]]) -> Path:
    gold = tmp_path / "dev-classification-labels.json"
    gold.write_text(
        json.dumps(
            {
                "split": "dev",
                "cases": [
                    {
                        "project_id": project,
                        "case_id": case_id,
                        "expected_requirement_id": matched,
                        "expected_relation": relation,
                    }
                    for project, case_id, matched, relation in cases
                ],
            }
        )
    )
    return gold


def score(data: dict[str, object], gold: Path) -> dict[str, object]:
    return score_classification(ClassificationRun.model_validate(data), gold)


def test_four_and_six_class_f1_include_control_false_positives(tmp_path: Path) -> None:
    gold = write_gold(
        tmp_path,
        [
            ("P1", "new", None, "new"),
            ("P1", "refine", "R1", "refinement"),
            ("P1", "conflict", "R1", "contradiction"),
            ("P1", "replace", "R1", "supersession"),
            ("P1", "repeat", "R1", "restatement"),
            ("P1", "question", None, "not_requirement"),
        ],
    )
    result = score(
        run_data(
            [
                prediction("new", "new", None),
                prediction("refine"),
                prediction("conflict", "contradiction"),
                prediction("replace", "supersession"),
                prediction("repeat", "restatement"),
                # A control predicted as supersession must lower its precision.
                prediction("question", "supersession"),
            ]
        ),
        gold,
    )
    relationships = result["relationships"]
    assert relationships["four_class"]["macro_f1"] == pytest.approx(11 / 12)
    assert relationships["six_class"]["macro_f1"] == pytest.approx(7 / 9)
    supersession = relationships["four_class"]["per_class"]["supersession"]
    assert supersession["support"] == 1
    assert supersession["false_positive"] == 1
    assert supersession["precision"] == 0.5
    assert relationships["confusion_matrix"]["not_requirement"]["supersession"] == 1
    assert result["matching"]["no_match_accuracy"] == 0.5
    assert result["matching"]["joint_id_relation_accuracy"] == pytest.approx(5 / 6)


@pytest.mark.parametrize("replacement_stated", [False, True])
def test_current_four_field_response_scores_the_raw_relation(
    tmp_path: Path, replacement_stated: bool
) -> None:
    gold = write_gold(tmp_path, [("P1", "replace", "R1", "supersession")])
    item = prediction("replace", "supersession")
    content = json.loads(item["raw_content"])
    content["replacement_stated"] = replacement_stated
    item["raw_content"] = json.dumps(content)

    result = score(run_data([item]), gold)

    assert result["coverage"] == 1.0
    assert result["matching"]["joint_id_relation_accuracy"] == 1.0
    # Offline raw-output scoring must not apply the runtime's soft downgrade.
    assert result["cases"][0]["predicted_relation"] == "supersession"


@pytest.mark.parametrize("replacement_stated", [None, "false", 0, 1, [], {}])
def test_current_replacement_flag_is_not_coerced_or_dropped(
    tmp_path: Path, replacement_stated: object
) -> None:
    gold = write_gold(tmp_path, [("P1", "replace", "R1", "supersession")])
    item = prediction("replace", "supersession")
    content = json.loads(item["raw_content"])
    content["replacement_stated"] = replacement_stated
    item["raw_content"] = json.dumps(content)

    result = score(run_data([item]), gold)

    assert result["errors"]["invalid"] == 1
    assert result["coverage"] == 0.0
    assert result["matching"]["joint_id_relation_accuracy"] == 0.0
    assert result["relationships"]["confusion_matrix"]["supersession"]["error"] == 1


def test_failures_are_not_dropped_or_reinterpreted_as_no_match(tmp_path: Path) -> None:
    gold = write_gold(
        tmp_path,
        [("P1", name, None, "new") for name in ("ok", "missing", "bad", "failed", "pending")],
    )
    bad = prediction("bad", "new", None)
    bad["raw_content"] = "```json\n{}\n```"
    result = score(
        run_data(
            [
                prediction("ok", "new", None),
                bad,
                {"project_id": "P1", "case_id": "failed", "status": "error", "error": "timeout"},
                {
                    **prediction("pending", "new", None),
                    "status": "unresolved",
                    "error": "Not resolved; do not credit the attached prediction",
                },
            ]
        ),
        gold,
    )
    assert result["total_cases"] == 5
    assert result["errors"] == {"missing": 1, "invalid": 1, "error": 1, "unresolved": 1}
    assert result["coverage"] == 0.2
    assert result["matching"]["no_match_accuracy"] == 0.2
    assert result["matching"]["predicted_no_match"] == 1
    assert result["matching"]["no_match_precision"] == 1.0
    assert result["relationships"]["confusion_matrix"]["new"]["error"] == 4
    assert result["relationships"]["four_class"]["per_class"]["new"]["f1"] == pytest.approx(1 / 3)
    assert result["relationships"]["four_class"]["macro_f1"] == pytest.approx(1 / 12)


def test_matching_metrics_and_retrieval_diagnostics_have_separate_denominators(
    tmp_path: Path,
) -> None:
    gold = write_gold(
        tmp_path,
        [
            ("P1", "correct", "R1", "refinement"),
            ("P1", "classifier", "R1", "refinement"),
            ("P1", "retriever", "R1", "refinement"),
            ("P1", "new", None, "new"),
            ("P1", "false_new", "R1", "refinement"),
        ],
    )
    result = score(
        run_data(
            [
                prediction("correct"),
                prediction("classifier", matched="R2"),
                prediction("retriever", matched="R2", offered=("R2",)),
                prediction("new", "new", None),
                prediction("false_new", "new", None),
            ]
        ),
        gold,
    )
    assert result["matching"] == {
        "id_accuracy_including_no_match": 0.4,
        "historical_cases": 4,
        "historical_id_accuracy": 0.25,
        "no_match_cases": 1,
        "predicted_no_match": 2,
        "no_match_accuracy": 1.0,
        "no_match_precision": 0.5,
        "joint_id_relation_accuracy": 0.4,
    }
    assert result["retrieval_diagnostics"] == {
        "retrieval_missed_gold": 1,
        "gold_offered": 3,
        "offered_ids_unavailable": 0,
        "wrong_id_with_gold_offered": 2,
        "output_error_with_gold_offered": 0,
    }
    # Right relation and wrong ID get relation credit, but never joint credit.
    assert result["cases"][1]["relation_correct"] is True
    assert result["cases"][1]["id_correct"] is False


@pytest.mark.parametrize("method", ["baseline", "full_history"])
def test_comparators_use_same_metrics_without_claiming_retrieval(
    method: str, tmp_path: Path
) -> None:
    gold = write_gold(tmp_path, [("P1", "a", "R1", "refinement")])
    offered = None if method == "baseline" else ("R1", "R2")
    result = score(run_data([prediction("a", offered=offered)], method), gold)
    assert result["matching"]["historical_id_accuracy"] == 1.0
    assert result["retrieval_diagnostics"] is None


def test_unknown_baseline_id_is_a_wrong_match_not_a_retrieval_schema_failure(
    tmp_path: Path,
) -> None:
    gold = write_gold(tmp_path, [("P1", "a", "R1", "refinement")])
    result = score(run_data([prediction("a", matched="INVENTED", offered=None)], "baseline"), gold)
    assert result["valid_outputs"] == 1
    assert result["matching"]["historical_id_accuracy"] == 0.0
    assert result["cases"][0]["relation_correct"] is True


def test_pipeline_out_of_enum_id_is_invalid_and_cannot_get_relation_credit(tmp_path: Path) -> None:
    gold = write_gold(tmp_path, [("P1", "a", "R1", "refinement")])
    result = score(run_data([prediction("a", matched="INVENTED")]), gold)
    assert result["errors"]["invalid"] == 1
    assert result["cases"][0]["relation_correct"] is False
    assert result["retrieval_diagnostics"]["output_error_with_gold_offered"] == 1


@pytest.mark.parametrize(
    "content",
    [
        '{"matched_requirement_id":"R1","relation":"refinement","relation":"new","rationale":"x"}',
        '{"matched_requirement_id":"R1","relation":"refinement","rationale":NaN}',
        '```json\n{"matched_requirement_id":"R1","relation":"refinement","rationale":"x"}\n```',
        '{"matched_requirement_id":null,"relation":"refinement","rationale":"x"}',
        '{"matched_requirement_id":"R1","relation":"new","rationale":"x"}',
        '{"matched_requirement_id":"R1","relation":"unknown","rationale":"x"}',
        '{"matched_requirement_id":"R1","relation":"refinement","rationale":"  "}',
        '{"matched_requirement_id":"R1","relation":"refinement","rationale":"x","state":"confirmed"}',
        "[]",
        '{"matched_requirement_id":"R1","relation":"refinement","rationale":"x"} trailing',
    ],
)
def test_malformed_raw_outputs_count_as_errors_without_repairs(
    content: str, tmp_path: Path
) -> None:
    gold = write_gold(tmp_path, [("P1", "a", "R1", "refinement")])
    item = {**prediction("a"), "raw_content": content}
    result = score(run_data([item]), gold)
    assert result["errors"]["invalid"] == 1
    assert result["coverage"] == 0.0
    assert result["matching"]["historical_id_accuracy"] == 0.0


@pytest.mark.parametrize(
    "update",
    [
        {"offered_ids": ["R1", "R1"]},
        {"offered_ids": [" "]},
        {"offered_ids": None},
        {"raw_content": None},
        {"error": "unexpected error attached to ok"},
        {"status": "unresolved", "error": " "},
        {"expected_relation": "refinement"},
    ],
)
def test_bad_identifiable_envelopes_remain_in_the_denominator(update: dict, tmp_path: Path) -> None:
    gold = write_gold(tmp_path, [("P1", "a", "R1", "refinement")])
    result = score(run_data([{**prediction("a"), **update}]), gold)
    assert result["total_cases"] == 1
    assert result["errors"]["invalid"] == 1


def test_case_identity_is_project_scoped(tmp_path: Path) -> None:
    gold = write_gold(
        tmp_path,
        [("P1", "same-id", "R1", "refinement"), ("P2", "same-id", None, "new")],
    )
    result = score(
        run_data([prediction("same-id"), prediction("same-id", "new", None, project_id="P2")]),
        gold,
    )
    assert result["matching"]["joint_id_relation_accuracy"] == 1.0


@pytest.mark.parametrize("kind", ["duplicate", "unknown", "unidentifiable"])
def test_bad_alignment_aborts_instead_of_guessing(kind: str, tmp_path: Path) -> None:
    gold = write_gold(tmp_path, [("P1", "a", "R1", "refinement")])
    cases = {
        "duplicate": [prediction("a"), prediction("a")],
        "unknown": [prediction("a", project_id="P2")],
        "unidentifiable": [{"status": "error", "error": "no identity"}],
    }
    with pytest.raises(ValueError):
        score(run_data(cases[kind]), gold)


def test_duplicate_and_inconsistent_gold_are_rejected(tmp_path: Path) -> None:
    gold = write_gold(tmp_path, [("P1", "a", None, "new"), ("P1", "a", None, "new")])
    with pytest.raises(ValueError, match="Duplicate"):
        score(run_data([]), gold)
    gold = write_gold(tmp_path, [("P1", "a", None, "supersession")])
    with pytest.raises(ValueError, match="requires"):
        score(run_data([]), gold)


def test_no_predicted_no_match_and_no_driving_support_are_explicit(tmp_path: Path) -> None:
    gold = write_gold(tmp_path, [("P1", "a", "R1", "restatement")])
    result = score(run_data([prediction("a", "restatement")]), gold)
    assert result["matching"]["no_match_accuracy"] is None
    assert result["matching"]["no_match_precision"] is None
    assert result["relationships"]["four_class"]["macro_f1"] is None
    assert result["relationships"]["six_class"]["macro_f1"] == pytest.approx(1 / 6)
    assert len(result["relationships"]["six_class"]["zero_support_labels"]) == 5


def test_empty_predictions_are_all_missing(tmp_path: Path) -> None:
    gold = write_gold(tmp_path, [("P1", "a", None, "new")])
    result = score(run_data([]), gold)
    assert result["errors"]["missing"] == 1
    assert result["coverage"] == 0.0
    assert result["matching"]["historical_id_accuracy"] is None


def test_holdout_path_is_rejected_before_reading(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    def forbidden_read(_path: Path) -> bytes:
        pytest.fail("Development scorer attempted to read holdout gold")

    monkeypatch.setattr(Path, "read_bytes", forbidden_read)
    with pytest.raises(ValueError, match="holdout"):
        score(run_data([]), tmp_path / "holdout" / "never-open.json")


@pytest.mark.parametrize(
    "update",
    [{"split": "holdout"}, {"repeat_index": 0}, {"prompt_hash": "unknown"}, {"model": " "}],
)
def test_run_provenance_is_required(update: dict) -> None:
    with pytest.raises(ValidationError):
        ClassificationRun.model_validate({**run_data([]), **update})


def test_cli_writes_reproducible_metrics_and_provenance(tmp_path: Path) -> None:
    gold = write_gold(tmp_path, [("P1", "a", "R1", "refinement")])
    predictions = tmp_path / "predictions.json"
    predictions.write_text(json.dumps(run_data([prediction("a")])))
    output = tmp_path / "metrics.json"
    result = subprocess.run(
        [
            sys.executable,
            "-m",
            "src.eval.score",
            "--predictions",
            str(predictions),
            "--gold",
            str(gold),
            "--output",
            str(output),
        ],
        capture_output=True,
        text=True,
        check=True,
    )
    metrics = json.loads(output.read_text())
    assert metrics == json.loads(result.stdout)
    assert metrics["predictions_sha256"] == hashlib.sha256(predictions.read_bytes()).hexdigest()
    assert metrics["gold_sha256"] == hashlib.sha256(gold.read_bytes()).hexdigest()
    assert metrics["matching"]["historical_id_accuracy"] == 1.0
    assert metrics["run_id"] == "software-test-only"


def test_cli_rejects_prediction_file_duplicate_json_keys(tmp_path: Path) -> None:
    predictions = tmp_path / "predictions.json"
    predictions.write_text('{"kind":"dev-e3-oracle", "kind":"hidden-overwrite"}')
    result = subprocess.run(
        [
            sys.executable,
            "-m",
            "src.eval.score",
            "--predictions",
            str(predictions),
            "--gold",
            str(tmp_path / "not-opened.json"),
        ],
        capture_output=True,
        text=True,
    )
    assert result.returncode != 0
    assert "Duplicate JSON field" in result.stderr
