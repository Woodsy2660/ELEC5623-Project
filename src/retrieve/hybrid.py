"""FR10: project-scoped BM25 + cosine, family collapse, then reciprocal-rank fusion.

No network, database access, gold labels or model calls. The caller supplies a snapshot of
history available at the current meeting and embeddings from one pinned model/revision.
"""

import math
import re
from collections import Counter
from collections.abc import Sequence

from src.retrieve.schemas import (
    RequirementVersion,
    RetrievalRequest,
    RetrievalResult,
    RetrievedFamily,
)


def _tokens(text: str) -> list[str]:
    return re.findall(r"[^\W_]+", text.casefold())


def _bm25_scores(query: str, versions: Sequence[RequirementVersion]) -> list[float]:
    """BM25 with fixed k1=1.5 and b=0.75; statistics use this project only."""
    documents = [Counter(_tokens(version.text)) for version in versions]
    lengths = [sum(document.values()) for document in documents]
    average_length = sum(lengths) / len(lengths)
    if average_length == 0:
        return [0.0] * len(documents)
    frequencies = Counter(term for document in documents for term in document)
    query_terms = sorted(set(_tokens(query)))
    scores = []
    for document, length in zip(documents, lengths, strict=True):
        score = 0.0
        for term in query_terms:
            count = document[term]
            if count == 0:
                continue
            df = frequencies[term]
            idf = math.log1p((len(documents) - df + 0.5) / (df + 0.5))
            denominator = count + 1.5 * (1 - 0.75 + 0.75 * length / average_length)
            score += idf * count * 2.5 / denominator
        scores.append(score)
    return scores


def _unit_vector(vector: tuple[float, ...]) -> tuple[float, ...]:
    # Scaling first prevents overflow/underflow for finite, very large/small inputs.
    scale = max(abs(component) for component in vector)
    scaled = tuple(component / scale for component in vector)
    norm = math.sqrt(math.fsum(component * component for component in scaled))
    return tuple(component / norm for component in scaled)


def _family_ranking(
    versions: Sequence[RequirementVersion], scores: Sequence[float]
) -> tuple[str, ...]:
    ordered = sorted(
        zip(versions, scores, strict=True),
        key=lambda item: (-item[1], item[0].requirement_id, item[0].version),
    )
    # Deduplicate BEFORE assigning family ranks: repeated versions earn no extra votes.
    return tuple(dict.fromkeys(version.requirement_id for version, _ in ordered))


def retrieve(request: RetrievalRequest, corpus: Sequence[RequirementVersion]) -> RetrievalResult:
    """Return top-k families plus full diagnostic rankings; invalid inputs raise errors.

    All lifecycle states are retained. Ties use stable family IDs and version numbers,
    independently of input order. No relevance floor is applied: the classifier, not the
    retriever, must decide whether any family matches (including no_match).
    """
    if not _tokens(request.candidate.text_norm):
        raise ValueError("Candidate must contain searchable text")
    versions = [v for v in corpus if v.project_id == request.candidate.project_id]
    seen: set[tuple[str, int]] = set()
    for version in versions:
        key = (version.requirement_id, version.version)
        if key in seen:
            raise ValueError(f"Duplicate requirement version: {key}")
        seen.add(key)
        if (
            version.embedding_model != request.embedding_model
            or version.embedding_version != request.embedding_version
            or version.embedding_dim != request.embedding_dim
            or len(version.embedding) != len(request.embedding)
        ):
            raise ValueError(
                "Refusing to compare embeddings from different encoders: "
                f"query {request.embedding_model} version {request.embedding_version} "
                f"dim {request.embedding_dim} ({len(request.embedding)} values), "
                f"corpus {version.requirement_id} v{version.version} "
                f"{version.embedding_model} version {version.embedding_version} "
                f"dim {version.embedding_dim} ({len(version.embedding)} values). "
                "A 1536-dim Foundry vector and a 384-dim local vector are not the same space."
            )

    bm25_ids: tuple[str, ...] = ()
    dense_ids: tuple[str, ...] = ()
    fused_ids: tuple[str, ...] = ()
    families: tuple[RetrievedFamily, ...] = ()
    if versions:
        bm25_ids = _family_ranking(versions, _bm25_scores(request.candidate.text_norm, versions))
        query = _unit_vector(request.embedding)
        dense_scores = [
            math.fsum(a * b for a, b in zip(query, _unit_vector(v.embedding), strict=True))
            for v in versions
        ]
        dense_ids = _family_ranking(versions, dense_scores)
        bm25_ranks = {family_id: i for i, family_id in enumerate(bm25_ids, start=1)}
        dense_ranks = {family_id: i for i, family_id in enumerate(dense_ids, start=1)}
        scores = {
            family_id: 1 / (60 + bm25_ranks[family_id]) + 1 / (60 + dense_ranks[family_id])
            for family_id in bm25_ids
        }
        fused_ids = tuple(sorted(scores, key=lambda family_id: (-scores[family_id], family_id)))
        families = tuple(
            RetrievedFamily(
                requirement_id=family_id,
                versions=tuple(
                    sorted(
                        (v for v in versions if v.requirement_id == family_id),
                        key=lambda v: v.version,
                    )
                ),
                bm25_rank=bm25_ranks[family_id],
                dense_rank=dense_ranks[family_id],
                rrf_score=scores[family_id],
            )
            for family_id in fused_ids[: request.top_k]
        )
    return RetrievalResult(
        candidate_id=request.candidate.candidate_id,
        project_id=request.candidate.project_id,
        embedding_model=request.embedding_model,
        embedding_version=request.embedding_version,
        embedding_dim=request.embedding_dim,
        families=families,
        bm25_family_ids=bm25_ids,
        dense_family_ids=dense_ids,
        fused_family_ids=fused_ids,
    )
