"""Real local-model smoke demo; illustrative inputs, not team corpus or E3 evaluation."""

import argparse
import hashlib
import json

from src.engine.state_machine import State
from src.extract.schemas import Candidate
from src.retrieve.embeddings import LocalEmbedder
from src.retrieve.hybrid import retrieve
from src.retrieve.local_trace import LocalTrace
from src.retrieve.prepare_model import CONFIG_PATH, REPO_ROOT
from src.retrieve.schemas import RequirementVersion, RetrievalRequest


def main() -> None:
    """Encode public illustrative requirements and display the three rankings."""
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--query", default="Employees should authenticate with the corporate identity provider."
    )
    parser.add_argument("--top-k", type=int, default=5)
    args = parser.parse_args()
    if not args.query.strip() or args.top_k < 1:
        parser.error("query must be nonblank and top-k must be positive")
    config_bytes = CONFIG_PATH.read_bytes()
    config = json.loads(config_bytes)
    model_id = f"{config['model_id']}@{config['revision']}"
    config_hash = hashlib.sha1(f"blob {len(config_bytes)}\0".encode() + config_bytes).hexdigest()
    trace = LocalTrace(REPO_ROOT / "runs", model_id, config_hash)
    rows = [
        ("LOGIN", 1, "Employees log in with email and password.", State.SUPERSEDED),
        ("LOGIN", 2, "Employees sign in using company single sign-on.", State.CONFIRMED),
        ("RESET", 1, "Users receive a password reset link by email.", State.CONFIRMED),
        ("RECEIPT", 1, "Customers receive a purchase receipt by email.", State.CONFIRMED),
        ("EXPORT", 1, "Administrators export monthly sales reports as CSV files.", State.CONFIRMED),
    ]
    try:
        embedder = LocalEmbedder(trace.record)
        vectors = embedder.encode([row[2] for row in rows] + [args.query])
        corpus = [
            RequirementVersion(
                project_id="local-smoke",
                requirement_id=row[0],
                version=row[1],
                text=row[2],
                state=row[3],
                embedding_model=vector.embedding_model,
                embedding=vector.embedding,
            )
            for row, vector in zip(rows, vectors[:-1], strict=True)
        ]
        candidate = Candidate(
            candidate_id="C1",
            project_id="local-smoke",
            meeting_id="M3",
            text_norm=args.query,
            evidence=[],
        )
        result = retrieve(
            RetrievalRequest(
                candidate=candidate,
                embedding_model=model_id,
                embedding=vectors[-1].embedding,
                top_k=args.top_k,
            ),
            corpus,
        )
        report = {
            "kind": "illustrative smoke run, not an evaluation score",
            "query": args.query,
            "model": model_id,
            "bm25": result.bm25_family_ids,
            "dense": result.dense_family_ids,
            "fused": result.fused_family_ids,
            "retrieved": [
                {
                    "id": family.requirement_id,
                    "versions": [
                        {"version": v.version, "text": v.text, "state": v.state.value}
                        for v in family.versions
                    ],
                }
                for family in result.families
            ],
            "trace_dir": str(trace.output_dir),
        }
        (trace.output_dir / "retrieval.json").write_text(json.dumps(report, indent=2))
        print(json.dumps(report, indent=2))
    finally:
        trace.close()


if __name__ == "__main__":
    main()
