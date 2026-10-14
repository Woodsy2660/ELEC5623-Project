"""Offline encoder contracts and trace tests, without downloads or encoder dependencies."""

import json
import sqlite3
import sys
from pathlib import Path
from types import SimpleNamespace

import pytest

from src.retrieve.embeddings import EmbeddingCall, LocalEmbedder
from src.retrieve.local_trace import LocalTrace


class FakeEncoder:
    """Stand-in to exercise truncation/error handling, never semantic performance."""

    max_seq_length = 256

    def get_sentence_embedding_dimension(self) -> int:
        return 384

    def eval(self) -> None:
        pass

    def tokenizer(self, texts: list[str], **kwargs: object) -> dict[str, list[list[int]]]:
        assert kwargs["truncation"] is False
        return {"input_ids": [[1] * (len(text.split()) + 2) for text in texts]}

    def encode(self, texts: list[str], **kwargs: object) -> list[list[float]]:
        assert kwargs["normalize_embeddings"] is True
        return [[1.0] + [0.0] * 383 for _ in texts]


def make_embedder(
    monkeypatch: pytest.MonkeyPatch, calls: list[EmbeddingCall], encoder: FakeEncoder | None = None
) -> LocalEmbedder:
    backend = encoder or FakeEncoder()

    def factory(model: str, **kwargs: object) -> FakeEncoder:
        assert model == "sentence-transformers/all-MiniLM-L6-v2"
        assert len(str(kwargs["revision"])) == 40
        assert kwargs["local_files_only"] is True
        assert kwargs["trust_remote_code"] is False
        assert kwargs["device"] == "cpu"
        assert kwargs["model_kwargs"] == {"use_safetensors": True}
        return backend

    monkeypatch.setitem(
        sys.modules, "sentence_transformers", SimpleNamespace(SentenceTransformer=factory)
    )
    return LocalEmbedder(calls.append)


def test_encoding_provenance_and_batch_trace(monkeypatch: pytest.MonkeyPatch) -> None:
    calls: list[EmbeddingCall] = []
    embedder = make_embedder(monkeypatch, calls)
    vectors = embedder.encode(["email login", "password reset"])
    assert len(vectors) == 2
    assert len(vectors[0].embedding) == 384
    assert vectors[0].embedding_model == embedder.model_id
    assert len(calls) == 1
    assert calls[0].input_tokens == 8
    assert calls[0].error is None
    assert len(calls[0].config_hash) == 40


def test_oversized_text_is_rejected_and_logged(monkeypatch: pytest.MonkeyPatch) -> None:
    calls: list[EmbeddingCall] = []
    embedder = make_embedder(monkeypatch, calls)
    with pytest.raises(ValueError, match="256-token"):
        embedder.encode(["word " * 255])
    assert len(calls) == 1
    assert calls[0].error is not None
    assert calls[0].vectors == ()


def test_wrong_output_shape_is_rejected_and_logged(monkeypatch: pytest.MonkeyPatch) -> None:
    class WrongShape(FakeEncoder):
        def encode(self, texts: list[str], **kwargs: object) -> list[list[float]]:
            return [[1.0]]

    calls: list[EmbeddingCall] = []
    embedder = make_embedder(monkeypatch, calls, WrongShape())
    with pytest.raises(ValueError, match="vector shape"):
        embedder.encode(["email login"])
    assert calls[0].error is not None


def test_failed_backend_is_logged_without_fallback(monkeypatch: pytest.MonkeyPatch) -> None:
    class FailedEncoder(FakeEncoder):
        def encode(self, texts: list[str], **kwargs: object) -> list[list[float]]:
            raise RuntimeError("inference failure")

    calls: list[EmbeddingCall] = []
    embedder = make_embedder(monkeypatch, calls, FailedEncoder())
    with pytest.raises(RuntimeError, match="inference failure"):
        embedder.encode(["email login"])
    assert calls[0].error == "RuntimeError: inference failure"


@pytest.mark.parametrize("texts", [[], [""], ["   "]])
def test_blank_inputs_fail_before_model_call(
    monkeypatch: pytest.MonkeyPatch, texts: list[str]
) -> None:
    calls: list[EmbeddingCall] = []
    embedder = make_embedder(monkeypatch, calls)
    with pytest.raises(ValueError, match="nonempty"):
        embedder.encode(texts)
    assert calls == []


def test_trace_sink_failure_prevents_success(monkeypatch: pytest.MonkeyPatch) -> None:
    embedder = make_embedder(monkeypatch, [])

    def broken_sink(call: EmbeddingCall) -> None:
        raise OSError("trace write failed")

    embedder._record_call = broken_sink
    with pytest.raises(OSError, match="trace write failed"):
        embedder.encode(["email login"])


def test_local_trace_uses_existing_call_schema_only(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr("src.retrieve.local_trace.version", lambda package: "test")
    trace = LocalTrace(tmp_path, "model@revision", "config-hash")
    call = EmbeddingCall(
        model_id="model@revision",
        config_hash="config-hash",
        texts=("email login",),
        input_tokens=4,
        latency_ms=7,
        vectors=((1.0, 0.0),),
    )
    trace.record(call)
    trace.record(call.model_copy(update={"error": "failed", "vectors": ()}))
    trace.close()
    with sqlite3.connect(trace.output_dir / "trace.sqlite") as connection:
        tables = {
            row[0]
            for row in connection.execute("SELECT name FROM sqlite_master WHERE type='table'")
        }
        assert tables == {"runs", "model_calls"}
        rows = list(
            connection.execute(
                "SELECT stage, input_tokens, output_tokens, cost, retries, raw_json_path FROM model_calls"
            )
        )
        assert len(rows) == 2
        assert rows[0][:5] == ("local_embedding", 4, 0, 0.0, 0)
        raw = json.loads(Path(rows[1][5]).read_text())
        assert raw["error"] == "failed"
