"""FR09/FR10 adapter: all retained versions, with explicit embedding provenance."""

from pydantic import TypeAdapter
from sqlalchemy import select
from sqlalchemy.orm import Session

from src.classify.schemas import CurrentHead
from src.persist.models import Requirement, RequirementCurrent, RequirementVersion
from src.retrieve.schemas import RequirementVersion as RetrievalVersion
from src.retrieve.schemas import VectorRecord
from src.validate.schemas import EvidenceSpan


def retrieval_snapshot(
    session: Session, project_id: str
) -> tuple[tuple[RetrievalVersion, ...], tuple[CurrentHead, ...]]:
    """Never omit historical states or guess metadata for legacy bare vectors."""
    versions, heads = [], []
    rows = session.scalars(
        select(RequirementVersion)
        .join(Requirement)
        .where(Requirement.project_id == project_id)
        .order_by(Requirement.id, RequirementVersion.version)
    )
    for row in rows:
        if row.embedding_blob is None:
            raise ValueError(f"Version {row.id} has no embedding")
        vector = VectorRecord.model_validate_json(row.embedding_blob)
        versions.append(
            RetrievalVersion(
                **vector.model_dump(),
                project_id=project_id,
                requirement_id=row.requirement_id,
                version=row.version,
                text=row.text,
                state=row.state,
                evidence=TypeAdapter(tuple[EvidenceSpan, ...]).validate_json(row.evidence_json),
            )
        )
    for head in session.scalars(
        select(RequirementCurrent).join(Requirement).where(Requirement.project_id == project_id)
    ):
        version = session.get(RequirementVersion, head.current_version_id)
        if (
            version is None
            or version.requirement_id != head.requirement_id
            or version.state != head.state
            or version.text != head.text
        ):
            raise ValueError("Current pointer disagrees with retained history")
        heads.append(
            CurrentHead(
                requirement_id=head.requirement_id, version=version.version, state=head.state
            )
        )
    return tuple(versions), tuple(heads)
