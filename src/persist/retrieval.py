"""FR09/FR10 adapter: all retained versions, with explicit embedding provenance."""

import json

from pydantic import TypeAdapter
from sqlalchemy import select
from sqlalchemy.orm import Session

from src.classify.schemas import CurrentHead
from src.persist.models import Requirement, RequirementCurrent, RequirementVersion
from src.retrieve.schemas import RequirementVersion as RetrievalVersion
from src.retrieve.schemas import VectorRecord
from src.validate.schemas import EvidenceSpan


def vector_record_from_version(row: RequirementVersion) -> VectorRecord:
    """Read B's split vector storage without inferring missing encoder metadata."""
    if (
        row.embedding_blob is None
        or row.embedding_model is None
        or row.embedding_version is None
        or row.embedding_dim is None
    ):
        raise ValueError(f"Version {row.id} has no verifiable embedding metadata")
    try:
        values = json.loads(row.embedding_blob.decode("utf-8"))
        return VectorRecord(
            embedding_model=row.embedding_model,
            embedding_version=row.embedding_version,
            embedding_dim=row.embedding_dim,
            embedding=tuple(values),
        )
    except (AttributeError, UnicodeDecodeError, json.JSONDecodeError, TypeError, ValueError) as exc:
        raise ValueError(f"Version {row.id} has an invalid stored vector") from exc


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
        vector = vector_record_from_version(row)
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
