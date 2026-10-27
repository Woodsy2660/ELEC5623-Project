"""E3 retrieval-only dev runner. Reads inputs, never gold; every encode is traced."""

import argparse
import hashlib
import json
from collections.abc import Callable
from pathlib import Path

from src.eval.retrieval_schemas import (
    RetrievalDataset,
    RetrievalObservation,
)
from src.retrieve.embeddings import LocalEmbedder
from src.retrieve.hybrid import retrieve
from src.retrieve.local_trace import LocalTrace
from src.retrieve.prepare_model import CONFIG_PATH, REPO_ROOT
from src.retrieve.schemas import RequirementVersion, RetrievalRequest, VectorRecord


def run_retrieval(
    dataset: RetrievalDataset,
    encode: Callable[[list[str]], tuple[VectorRecord, ...]],
) -> tuple[RetrievalObservation, ...]:
    """Encode only visible, project-scoped text. Each bad case is an explicit error."""
    observations = []
    for case in dataset.cases:
        visible = [
            v
            for v in case.history
            if v.project_id == case.candidate.project_id
            and v.available_after_meeting <= case.history_cutoff
        ]
        try:
            vectors = encode([v.text for v in visible] + [case.candidate.text_norm])
            if len(vectors) != len(visible) + 1:
                raise ValueError("Encoder returned an unexpected batch size")
            versions = [
                RequirementVersion(
                    project_id=v.project_id,
                    requirement_id=v.requirement_id,
                    version=v.version,
                    text=v.text,
                    state=v.state,
                    evidence=v.evidence,
                    embedding_model=vector.embedding_model,
                    embedding_version=vector.embedding_version,
                    embedding_dim=vector.embedding_dim,
                    embedding=vector.embedding,
                )
                for v, vector in zip(visible, vectors[:-1], strict=True)
            ]
            query = vectors[-1]
            result = retrieve(
                RetrievalRequest(
                    candidate=case.candidate,
                    embedding_model=query.embedding_model,
                    embedding_version=query.embedding_version,
                    embedding_dim=query.embedding_dim,
                    embedding=query.embedding,
                    top_k=8,
                ),
                versions,
            )
            observations.append(RetrievalObservation(case_id=case.case_id, result=result))
        except Exception as exc:
            observations.append(
                RetrievalObservation(case_id=case.case_id, error=f"{type(exc).__name__}: {exc}")
            )
    return tuple(observations)


def main() -> None:
    """Run cached local encoder on a supplied dev-only, label-free JSON input file."""
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--inputs", type=Path, required=True)
    parser.add_argument("--repeat", type=int, choices=[1, 2, 3], default=1)
    args = parser.parse_args()
    if any("holdout" in part.casefold() for part in args.inputs.resolve().parts):
        parser.error("This development entry point does not open holdout files")
    dataset_bytes = args.inputs.read_bytes()
    dataset = RetrievalDataset.model_validate_json(dataset_bytes)
    config_bytes = CONFIG_PATH.read_bytes()
    config = json.loads(config_bytes)
    config_hash = hashlib.sha1(f"blob {len(config_bytes)}\0".encode() + config_bytes).hexdigest()
    model_id = f"{config['model_id']}@{config['revision']}"
    trace = LocalTrace(
        REPO_ROOT / "runs",
        model_id,
        config_hash,
        mode="eval",
        candidate_source="provided-dev",
        repeat_index=args.repeat,
    )
    try:
        embedder = LocalEmbedder(trace.record)
        observations = run_retrieval(dataset, embedder.encode)
        report = {
            "kind": "dev-retrieval-only",
            "split": "dev",
            "run_id": trace.run_id,
            "repeat_index": args.repeat,
            "model": model_id,
            "config_hash": config_hash,
            "inputs_sha256": hashlib.sha256(dataset_bytes).hexdigest(),
            "observations": [item.model_dump(mode="json") for item in observations],
        }
        output = trace.output_dir / "rankings.json"
        output.write_text(json.dumps(report, indent=2))
        print(f"Rankings: {output}")
        print(
            f"Cases: {len(observations)}; errors: {sum(o.error is not None for o in observations)}"
        )
    finally:
        trace.close()


if __name__ == "__main__":
    main()
