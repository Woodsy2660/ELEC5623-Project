"""Scoring module for E2, E3, E5 and related metrics.

This is the only module permitted to read gold_events.
"""

import argparse
import hashlib
import json
from pathlib import Path
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator

from src.classify.schemas import Relation
from src.eval.classification_schemas import (
    CaseIdentity,
    ClassificationObservation,
    ClassificationRun,
)
from src.eval.retrieval_schemas import RetrievalObservation


class RetrievalGoldCase(BaseModel):
    """Dev match label; never supplied to a retrieval or embedding call."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    case_id: str = Field(min_length=1)
    expected_requirement_id: str | None = Field(..., min_length=1)


class RetrievalGold(BaseModel):
    """Only this scoring module opens retrieval labels."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    schema_version: Literal[1] = 1
    split: Literal["dev"]
    cases: tuple[RetrievalGoldCase, ...] = Field(min_length=1)

    @model_validator(mode="after")
    def unique_cases(self) -> "RetrievalGold":
        ids = [case.case_id for case in self.cases]
        if len(ids) != len(set(ids)):
            raise ValueError("Duplicate gold case ID")
        return self


def score_retrieval(
    observations: tuple[RetrievalObservation, ...],
    gold_path: Path,
) -> dict[str, object]:
    """E3 recall@3/5/8. Failed/missing matchable cases stay in the denominator."""
    if any("holdout" in part.casefold() for part in gold_path.resolve().parts):
        raise ValueError("This development scorer does not open holdout files")
    gold_bytes = gold_path.read_bytes()
    gold = RetrievalGold.model_validate_json(gold_bytes)
    observed = {item.case_id: item for item in observations}
    if len(observed) != len(observations):
        raise ValueError("Duplicate observed case ID")
    unknown = set(observed) - {case.case_id for case in gold.cases}
    if unknown:
        raise ValueError(f"Observed cases missing from gold: {sorted(unknown)}")
    channels = ("bm25", "dense", "fused")
    cutoffs = (3, 5, 8)
    counts = {channel: {str(k): 0 for k in cutoffs} for channel in channels}
    matchable = sum(case.expected_requirement_id is not None for case in gold.cases)
    errors = 0
    valid = 0
    cases = []
    for case in gold.cases:
        item = observed.get(case.case_id)
        error = "missing output" if item is None else item.error
        if item is not None and item.result is not None:
            rankings = {
                "bm25": item.result.bm25_family_ids,
                "dense": item.result.dense_family_ids,
                "fused": item.result.fused_family_ids,
            }
            if any(len(ids) != len(set(ids)) for ids in rankings.values()):
                error = "invalid output: duplicate ranked family ID"
            elif any(set(ids) != set(rankings["fused"]) for ids in rankings.values()):
                error = "invalid output: channel family sets disagree"
        else:
            rankings = {channel: () for channel in channels}
        if error is not None:
            errors += 1
        else:
            valid += 1
        ranks = {}
        for channel, ids in rankings.items():
            rank = (
                ids.index(case.expected_requirement_id) + 1
                if error is None and case.expected_requirement_id in ids
                else None
            )
            ranks[channel] = rank
            if case.expected_requirement_id is not None:
                for k in cutoffs:
                    counts[channel][str(k)] += int(rank is not None and rank <= k)
        cases.append(
            {
                "case_id": case.case_id,
                "expected_requirement_id": case.expected_requirement_id,
                "ranks": ranks,
                "error": error,
            }
        )
    return {
        "kind": "dev-retrieval-only",
        "gold_sha256": hashlib.sha256(gold_bytes).hexdigest(),
        "total_cases": len(gold.cases),
        "matchable_cases": matchable,
        "no_match_cases": len(gold.cases) - matchable,
        "valid_outputs": valid,
        "error_or_missing_outputs": errors,
        "coverage": valid / len(gold.cases),
        "recall_at_k": {
            channel: {k: hits / matchable if matchable else None for k, hits in values.items()}
            for channel, values in counts.items()
        },
        "no_match_accuracy": None,
        "notes": "No-match accuracy requires a classifier. No-match cases are not recall successes.",
        "cases": cases,
    }


def _read_observations(items: list[dict[str, object]]) -> tuple[RetrievalObservation, ...]:
    """Malformed outputs with a known case ID become explicit failures, not repairs."""
    observations = []
    for item in items:
        case_id = item.get("case_id")
        if not isinstance(case_id, str) or not case_id:
            raise ValueError("Cannot associate an output without a valid case ID")
        try:
            observations.append(RetrievalObservation.model_validate(item))
        except ValueError as exc:
            observations.append(
                RetrievalObservation(case_id=case_id, error=f"invalid output: {exc}")
            )
    return tuple(observations)


class ClassificationGoldCase(CaseIdentity):
    """Aligned development label, read only here and never used in inference."""

    expected_requirement_id: str | None = Field(..., min_length=1, strict=True)
    expected_relation: Relation

    @model_validator(mode="after")
    def valid_label(self) -> "ClassificationGoldCase":
        _check_relation_id(self.expected_relation, self.expected_requirement_id)
        return self


class ClassificationGold(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    schema_version: Literal[1] = 1
    split: Literal["dev"]
    cases: tuple[ClassificationGoldCase, ...] = Field(min_length=1)

    @model_validator(mode="after")
    def unique_cases(self) -> "ClassificationGold":
        keys = [(case.project_id, case.case_id) for case in self.cases]
        if len(keys) != len(set(keys)):
            raise ValueError("Duplicate project/case ID in gold")
        return self


def _check_relation_id(relation: Relation, matched: str | None) -> None:
    if matched is not None and not matched.strip():
        raise ValueError("Requirement ID must not be blank")
    if relation == Relation.NEW and matched is not None:
        raise ValueError("New requires a null requirement ID")
    if relation not in {Relation.NEW, Relation.NOT_REQUIREMENT} and matched is None:
        raise ValueError("Historical relationship requires a requirement ID")


class _ClassificationPrediction(BaseModel):
    """Shared scoring shape; baseline IDs are not constrained to retrieved IDs."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    matched_requirement_id: str | None = Field(..., min_length=1, strict=True)
    relation: Relation
    rationale: str = Field(min_length=1, strict=True)

    @model_validator(mode="after")
    def valid_prediction(self) -> "_ClassificationPrediction":
        _check_relation_id(self.relation, self.matched_requirement_id)
        if not self.rationale.strip():
            raise ValueError("Rationale must not be blank")
        return self


def _unique_json_fields(pairs: list[tuple[str, object]]) -> dict[str, object]:
    result = {}
    for name, value in pairs:
        if name in result:
            raise ValueError(f"Duplicate JSON field: {name}")
        result[name] = value
    return result


def _reject_json_constant(value: str) -> None:
    raise ValueError(f"Invalid JSON constant: {value}")


def _strict_json(content: str | bytes) -> object:
    return json.loads(
        content, object_pairs_hook=_unique_json_fields, parse_constant=_reject_json_constant
    )


def _relation_metrics(
    confusion: dict[str, dict[str, int]], labels: tuple[str, ...]
) -> dict[str, object]:
    per_class = {}
    for label in labels:
        tp = confusion[label][label]
        support = sum(confusion[label].values())
        predicted = sum(row[label] for row in confusion.values())
        fp, fn = predicted - tp, support - tp
        per_class[label] = {
            "support": support,
            "predicted": predicted,
            "true_positive": tp,
            "false_positive": fp,
            "false_negative": fn,
            "precision": tp / predicted if predicted else 0.0,
            "recall": tp / support if support else 0.0,
            "f1": 2 * tp / (2 * tp + fp + fn) if 2 * tp + fp + fn else 0.0,
        }
    return {
        "labels": labels,
        "per_class": per_class,
        "macro_f1": (
            sum(item["f1"] for item in per_class.values()) / len(labels)
            if any(item["support"] for item in per_class.values())
            else None
        ),
        "zero_support_labels": [label for label, item in per_class.items() if not item["support"]],
    }


def score_classification(run: ClassificationRun, gold_path: Path) -> dict[str, object]:
    """Score aligned E3-oracle outputs, keeping failures in gold denominators.

    No model, database, human correction, extracted-candidate alignment or E5 replay.
    Macro-F1 uses fixed label lists; errors are false negatives, not a seventh class.
    Controls remain in confusion rows, including false positives for driving labels.
    """
    if any("holdout" in part.casefold() for part in gold_path.resolve().parts):
        raise ValueError("This development scorer does not open holdout files")
    gold_bytes = gold_path.read_bytes()
    gold = ClassificationGold.model_validate(_strict_json(gold_bytes))
    # Recheck nested raw dictionaries, which callers can otherwise mutate after construction.
    run = ClassificationRun.model_validate(run.model_dump())
    observed = {}
    gold_keys = {(case.project_id, case.case_id) for case in gold.cases}
    for raw in run.cases:
        identity = CaseIdentity.model_validate(
            {"project_id": raw.get("project_id"), "case_id": raw.get("case_id")}
        )
        key = (identity.project_id, identity.case_id)
        if key in observed:
            raise ValueError(f"Duplicate observed project/case ID: {key}")
        if key not in gold_keys:
            raise ValueError(f"Observed project/case missing from gold: {key}")
        observed[key] = raw

    labels = tuple(relation.value for relation in Relation)
    driving = ("new", "refinement", "contradiction", "supersession")
    confusion = {label: dict.fromkeys((*labels, "error"), 0) for label in labels}
    errors = dict.fromkeys(("missing", "invalid", "error", "unresolved"), 0)
    total = len(gold.cases)
    historical = sum(case.expected_requirement_id is not None for case in gold.cases)
    id_correct = historical_correct = no_match_correct = predicted_no_match = joint_correct = 0
    diagnostics = dict.fromkeys(
        (
            "retrieval_missed_gold",
            "gold_offered",
            "offered_ids_unavailable",
            "wrong_id_with_gold_offered",
            "output_error_with_gold_offered",
        ),
        0,
    )
    cases = []
    for case in gold.cases:
        raw = observed.get((case.project_id, case.case_id))
        prediction = observation = None
        error_kind = error = None
        if raw is None:
            error_kind, error = "missing", "Missing output"
        else:
            try:
                observation = ClassificationObservation.model_validate(raw)
                if run.method == "baseline" and observation.offered_ids is not None:
                    raise ValueError("Baseline must not claim explicit retrieval provenance")
                if run.method != "baseline" and observation.status == "ok":
                    if observation.offered_ids is None:
                        raise ValueError("Pipeline/full-history output requires offered_ids")
                if observation.status != "ok":
                    error_kind, error = observation.status, observation.error
                else:
                    prediction = _ClassificationPrediction.model_validate(
                        _strict_json(observation.raw_content)
                    )
                    if (
                        run.method != "baseline"
                        and prediction.matched_requirement_id is not None
                        and prediction.matched_requirement_id not in observation.offered_ids
                    ):
                        raise ValueError("Predicted ID was not offered to the classifier")
            except (ValueError, TypeError) as exc:
                prediction = None
                error_kind, error = "invalid", str(exc)
        if error_kind is not None:
            errors[error_kind] += 1
            prediction = None
        predicted_label = prediction.relation.value if prediction is not None else "error"
        confusion[case.expected_relation.value][predicted_label] += 1
        same_id = prediction is not None and (
            prediction.matched_requirement_id == case.expected_requirement_id
        )
        same_relation = prediction is not None and prediction.relation == case.expected_relation
        id_correct += int(same_id)
        historical_correct += int(same_id and case.expected_requirement_id is not None)
        no_match_correct += int(same_id and case.expected_requirement_id is None)
        predicted_no_match += int(
            prediction is not None and prediction.matched_requirement_id is None
        )
        joint_correct += int(same_id and same_relation)

        retrieval = None
        if run.method == "pipeline" and case.expected_requirement_id is not None:
            offered = observation.offered_ids if observation is not None else None
            if offered is None:
                retrieval = "unavailable"
                diagnostics["offered_ids_unavailable"] += 1
            elif case.expected_requirement_id not in offered:
                retrieval = "missed_gold"
                diagnostics["retrieval_missed_gold"] += 1
            else:
                retrieval = "gold_offered"
                diagnostics["gold_offered"] += 1
                diagnostics["wrong_id_with_gold_offered"] += int(
                    prediction is not None and not same_id
                )
                diagnostics["output_error_with_gold_offered"] += int(prediction is None)
        cases.append(
            {
                "project_id": case.project_id,
                "case_id": case.case_id,
                "expected_requirement_id": case.expected_requirement_id,
                "expected_relation": case.expected_relation.value,
                "predicted_requirement_id": (
                    prediction.matched_requirement_id if prediction is not None else None
                ),
                "predicted_relation": predicted_label,
                "id_correct": same_id,
                "relation_correct": same_relation,
                "error_kind": error_kind,
                "error": error,
                "retrieval": retrieval,
            }
        )
    no_match = total - historical
    failed = sum(errors.values())
    return {
        "kind": "dev-e3-oracle-metrics",
        "run_id": run.run_id,
        "method": run.method,
        "split": run.split,
        "repeat_index": run.repeat_index,
        "model": run.model,
        "prompt_hash": run.prompt_hash,
        "inputs_sha256": run.inputs_sha256,
        "gold_sha256": hashlib.sha256(gold_bytes).hexdigest(),
        "total_cases": total,
        "valid_outputs": total - failed,
        "coverage": (total - failed) / total,
        "errors": errors,
        "matching": {
            "id_accuracy_including_no_match": id_correct / total,
            "historical_cases": historical,
            "historical_id_accuracy": historical_correct / historical if historical else None,
            "no_match_cases": no_match,
            "predicted_no_match": predicted_no_match,
            "no_match_accuracy": no_match_correct / no_match if no_match else None,
            "no_match_precision": no_match_correct / predicted_no_match
            if predicted_no_match
            else None,
            "joint_id_relation_accuracy": joint_correct / total,
        },
        "relationships": {
            "four_class": _relation_metrics(confusion, driving),
            "six_class": _relation_metrics(confusion, labels),
            "confusion_matrix": confusion,
        },
        "retrieval_diagnostics": diagnostics if run.method == "pipeline" else None,
        "scoring_policy": {
            "alignment": "Caller-supplied project_id/case_id; E3-oracle only",
            "failures": "Missing, invalid, failed and unresolved outputs are incorrect",
            "macro_f1": "Fixed label sets; zero-support F1=0; all-zero-support group=null",
            "controls": "All gold rows contribute false positives, including control labels",
            "interpretation": "Software scoring only; no E3-pipeline or E5 state metrics",
        },
        "cases": cases,
    }


def main() -> None:
    parser = argparse.ArgumentParser(description="Score a completed run against gold data.")
    source = parser.add_mutually_exclusive_group(required=True)
    source.add_argument(
        "--run",
        type=str,
        help="Run ID to score",
    )
    source.add_argument("--rankings", type=Path, help="Retrieval-only rankings.json")
    source.add_argument("--predictions", type=Path, help="Saved dev-e3-oracle predictions JSON")
    parser.add_argument("--gold", type=Path, help="Dev-only labels for the selected scoring mode")
    parser.add_argument("--output", type=Path, help="Optional metrics JSON output")
    args = parser.parse_args()
    if args.predictions is not None:
        if args.gold is None:
            parser.error("--predictions requires --gold")
        if any("holdout" in part.casefold() for part in args.predictions.resolve().parts):
            parser.error("This development entry point does not open holdout files")
        prediction_bytes = args.predictions.read_bytes()
        run = ClassificationRun.model_validate(_strict_json(prediction_bytes))
        metrics = score_classification(run, args.gold)
        metrics["predictions_sha256"] = hashlib.sha256(prediction_bytes).hexdigest()
        text = json.dumps(metrics, indent=2)
        if args.output is not None:
            args.output.write_text(text)
        print(text)
    elif args.rankings is not None:
        if args.gold is None:
            parser.error("--rankings requires --gold")
        report = json.loads(args.rankings.read_text())
        if report.get("kind") != "dev-retrieval-only" or report.get("split") != "dev":
            parser.error("Expected dev-retrieval-only rankings")
        observations = _read_observations(report["observations"])
        metrics = score_retrieval(observations, args.gold)
        metrics["run_id"] = report["run_id"]
        metrics["repeat_index"] = report["repeat_index"]
        metrics["inputs_sha256"] = report["inputs_sha256"]
        text = json.dumps(metrics, indent=2)
        if args.output is not None:
            args.output.write_text(text)
        print(text)
    else:
        raise NotImplementedError(f"Full pipeline scoring not yet implemented: run={args.run}")


if __name__ == "__main__":
    main()
