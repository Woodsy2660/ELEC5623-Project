"""Offline FR10 smoke demo, using explicitly synthetic test vectors (not an E3 score)."""

from src.engine.state_machine import State
from src.extract.schemas import Candidate
from src.retrieve.hybrid import retrieve
from src.retrieve.schemas import RequirementVersion, RetrievalRequest
from src.validate.schemas import EvidenceSpan


def main() -> None:
    """Show historical-family retrieval without credentials, data files or downloads."""
    model = "synthetic-unit-fixture-v1"
    corpus = [
        RequirementVersion(
            project_id="demo",
            requirement_id="R01",
            version=1,
            text="Users log in with email and password.",
            state=State.SUPERSEDED,
            embedding_model=model,
            embedding=(1, 0, 0),
        ),
        RequirementVersion(
            project_id="demo",
            requirement_id="R01",
            version=2,
            text="Users authenticate with company single sign-on.",
            state=State.CONFIRMED,
            embedding_model=model,
            embedding=(1, 0, 0),
        ),
        RequirementVersion(
            project_id="demo",
            requirement_id="R02",
            version=1,
            text="Send password reset instructions by email.",
            state=State.CONFIRMED,
            embedding_model=model,
            embedding=(0, 1, 0),
        ),
        RequirementVersion(
            project_id="demo",
            requirement_id="R03",
            version=1,
            text="Send purchase receipts by email.",
            state=State.CONFIRMED,
            embedding_model=model,
            embedding=(0, 0, 1),
        ),
    ]
    text = "Return to the email and password login we agreed in the first meeting."
    candidate = Candidate(
        candidate_id="C01",
        project_id="demo",
        meeting_id="M3",
        text_norm=text,
        evidence=[EvidenceSpan(turn_id="M3:1", start=0, end=len(text))],
    )
    result = retrieve(
        RetrievalRequest(candidate=candidate, embedding_model=model, embedding=(1, 0, 0)),
        corpus,
    )
    print("SMOKE DEMO ONLY: synthetic vectors, no semantic model or measured recall.")
    print(result.model_dump_json(indent=2))


if __name__ == "__main__":
    main()
