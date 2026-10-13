"""FR10/E3: history, isolation, cosine and collapse-before-fuse regression checks."""

import math

import pytest
from pydantic import ValidationError

from src.engine.state_machine import State
from src.extract.schemas import Candidate
from src.retrieve.hybrid import retrieve
from src.retrieve.schemas import RequirementVersion, RetrievalRequest

MODEL = "synthetic-unit-fixture-v1"


def version(
    family: str,
    text: str,
    embedding: tuple[float, ...] = (1, 0),
    *,
    number: int = 1,
    project: str = "P1",
    state: State = State.CONFIRMED,
    model: str = MODEL,
) -> RequirementVersion:
    return RequirementVersion(
        project_id=project,
        requirement_id=family,
        version=number,
        text=text,
        state=state,
        embedding_model=model,
        embedding=embedding,
    )


def request(
    text: str = "email login", embedding: tuple[float, ...] = (1, 0), top_k: int = 5
) -> RetrievalRequest:
    return RetrievalRequest(
        candidate=Candidate(
            candidate_id="C1", project_id="P1", meeting_id="M3", text_norm=text, evidence=[]
        ),
        embedding_model=MODEL,
        embedding=embedding,
        top_k=top_k,
    )


def test_historical_wording_returns_whole_family() -> None:
    old = version("R1", "email login", state=State.SUPERSEDED)
    current = version("R1", "company single sign on", number=2, embedding=(0.5, 0.5))
    unrelated = version("R2", "purchase receipt", embedding=(0, 1))
    result = retrieve(request(top_k=1), [current, unrelated, old])
    assert result.retrieved_ids == ["R1"]
    assert result.families[0].versions == (old, current)
    assert result.families[0].versions[0].state == State.SUPERSEDED


@pytest.mark.parametrize("state", list(State))
def test_all_retained_states_are_searchable(state: State) -> None:
    result = retrieve(request(), [version("R1", "email login", state=state)])
    assert result.retrieved_ids == ["R1"]


def test_other_project_does_not_affect_any_ranking_or_statistics() -> None:
    corpus = [version("R1", "email login"), version("R2", "reset email", (0, 1))]
    # Different model and dimension in another project must also be excluded.
    outsider = version("R0", "email login", (1, 0, 0), project="P2", model="other")
    assert retrieve(request(), corpus) == retrieve(request(), [outsider, *corpus])


def test_many_versions_do_not_earn_extra_rrf_votes() -> None:
    corpus = [version("A", "email login", number=i) for i in range(1, 5)]
    corpus.append(version("B", "email login", (0.9, 0.1)))
    result = retrieve(request(), corpus)
    assert result.bm25_family_ids == ("A", "B")
    assert result.dense_family_ids == ("A", "B")
    a, b = result.families
    assert a.rrf_score == pytest.approx(2 / 61)
    assert b.rrf_score == pytest.approx(2 / 62)
    assert len(a.versions) == 4


def test_bm25_uses_project_document_frequencies_and_length_normalisation() -> None:
    # Each candidate term occurs in one document. Shorter R2 wins on length;
    # repeated 'rare' still receives BM25 saturation, rather than linear scoring.
    corpus = [version("R1", "rare rare rare filler filler filler", (1, 0))]
    corpus.append(version("R2", "unique", (0, 1)))
    result = retrieve(request("rare unique"), corpus)
    assert result.bm25_family_ids == ("R2", "R1")


def test_dense_cosine_not_dot_product_and_rrf_uses_both_channels() -> None:
    corpus = [
        version("A", "email login", (1, 1)),
        version("B", "email login", (3, 0)),
        version("C", "email login", (100, 100)),
    ]
    result = retrieve(request(), corpus)
    assert result.bm25_family_ids == ("A", "B", "C")
    assert result.dense_family_ids == ("B", "A", "C")
    assert result.fused_family_ids == ("A", "B", "C")
    assert result.families[0].rrf_score == pytest.approx(1 / 61 + 1 / 62)


def test_near_duplicates_stay_separate_families() -> None:
    corpus = [
        version("LOGIN", "email login", (1, 0, 0)),
        version("RESET", "password reset email", (0, 1, 0)),
        version("RECEIPT", "purchase receipt email", (0, 0, 1)),
    ]
    result = retrieve(request("password reset email", (0, 1, 0)), corpus)
    assert result.retrieved_ids[0] == "RESET"
    assert set(result.retrieved_ids) == {"LOGIN", "RESET", "RECEIPT"}


def test_input_order_and_repeated_calls_do_not_change_result() -> None:
    corpus = [version("B", "email login"), version("A", "email login")]
    expected = retrieve(request(), corpus)
    assert expected.retrieved_ids == ["A", "B"]
    assert retrieve(request(), list(reversed(corpus))) == expected
    assert retrieve(request(), corpus) == expected


def test_no_lexical_overlap_is_not_silently_dropped_or_called_no_match() -> None:
    result = retrieve(request("export invoices"), [version("R1", "email login")])
    assert result.retrieved_ids == ["R1"]


def test_empty_project_returns_empty_rankings() -> None:
    result = retrieve(request(), [version("R1", "email login", project="P2")])
    assert result.retrieved_ids == []
    assert result.bm25_family_ids == result.dense_family_ids == result.fused_family_ids == ()


def test_top_k_limits_families_but_keeps_diagnostic_rankings() -> None:
    corpus = [version(str(i), "email login") for i in range(10)]
    result = retrieve(request(top_k=3), corpus)
    assert len(result.families) == 3
    assert len(result.fused_family_ids) == 10
    assert len(retrieve(request(), corpus).families) == 5
    assert len(retrieve(request(top_k=20), corpus).families) == 10


@pytest.mark.parametrize("vector", [(), (0, 0), (math.nan, 1), (math.inf, 1)])
def test_bad_query_vectors_are_errors(vector: tuple[float, ...]) -> None:
    with pytest.raises(ValidationError):
        request(embedding=vector)


@pytest.mark.parametrize("vector", [(0, 0), (math.nan, 1), (-math.inf, 1)])
def test_bad_corpus_vectors_are_errors(vector: tuple[float, ...]) -> None:
    with pytest.raises(ValidationError):
        version("R1", "email login", vector)


@pytest.mark.parametrize("top_k", [0, -1])
def test_invalid_top_k_is_an_error(top_k: int) -> None:
    with pytest.raises(ValidationError):
        request(top_k=top_k)


def test_model_mismatch_is_an_error() -> None:
    with pytest.raises(ValueError, match="model/revision"):
        retrieve(request(), [version("R1", "email login", model="different-revision")])


def test_dimension_mismatch_is_an_error() -> None:
    with pytest.raises(ValueError, match="dimensions"):
        retrieve(request(), [version("R1", "email login", (1, 0, 0))])


def test_duplicate_version_is_an_error() -> None:
    entry = version("R1", "email login")
    with pytest.raises(ValueError, match="Duplicate"):
        retrieve(request(), [entry, entry])


@pytest.mark.parametrize("text", ["", "   ", "!!!"])
def test_unsearchable_query_is_an_error(text: str) -> None:
    with pytest.raises(ValueError, match="searchable"):
        retrieve(request(text), [])


def test_extreme_finite_vectors_do_not_overflow() -> None:
    result = retrieve(
        request(embedding=(1e308, 1e308)),
        [version("A", "email login", (1e-300, 1e-300)), version("B", "email login", (1, 0))],
    )
    assert result.dense_family_ids == ("A", "B")
