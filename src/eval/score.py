"""Scoring module for E2, E3, E5 and related metrics.

This is the only module permitted to read gold_events.
"""

import argparse
import hashlib
import json
from pathlib import Path
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator

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


def main() -> None:
    parser = argparse.ArgumentParser(description="Score a completed run against gold data.")
    source = parser.add_mutually_exclusive_group(required=True)
    source.add_argument(
        "--run",
        type=str,
        help="Run ID to score",
    )
    source.add_argument("--rankings", type=Path, help="Retrieval-only rankings.json")
    parser.add_argument("--gold", type=Path, help="Dev-only retrieval match labels")
    parser.add_argument("--output", type=Path, help="Optional metrics JSON output")
    args = parser.parse_args()
    if args.rankings is not None:
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
