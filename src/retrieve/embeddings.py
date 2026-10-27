"""Pinned local sentence embeddings. Every attempted encode batch requires a trace sink."""

import hashlib
import json
import time
from collections.abc import Callable, Sequence
from pathlib import Path

from pydantic import BaseModel, ConfigDict

from src.retrieve.prepare_model import CONFIG_PATH, MODEL_CACHE
from src.retrieve.schemas import VectorRecord


class EmbeddingCall(BaseModel):
    """Batch trace; local encoders have no generated tokens or API cost."""

    model_config = ConfigDict(extra="forbid", frozen=True, protected_namespaces=())

    model_id: str
    config_hash: str
    texts: tuple[str, ...]
    input_tokens: int
    latency_ms: int
    vectors: tuple[tuple[float, ...], ...]
    error: str | None = None


class LocalEmbedder:
    """CPU inference from cached safe weights; no fallback or automatic downloads."""

    def __init__(
        self,
        record_call: Callable[[EmbeddingCall], None],
        cache_dir: Path = MODEL_CACHE,
    ) -> None:
        from sentence_transformers import SentenceTransformer

        config_bytes = CONFIG_PATH.read_bytes()
        config = json.loads(config_bytes)
        self.embedding_model = config["model_id"]
        self.embedding_version = config["revision"]
        self.embedding_dim = config["dimensions"]
        self.model_id = f"{self.embedding_model}@{self.embedding_version}"
        self.config_hash = hashlib.sha1(
            f"blob {len(config_bytes)}\0".encode() + config_bytes
        ).hexdigest()
        self._record_call = record_call
        self._dimensions = self.embedding_dim
        self._max_tokens = config["max_tokens"]
        self._model = SentenceTransformer(
            config["model_id"],
            revision=config["revision"],
            cache_folder=str(cache_dir),
            device=config["device"],
            local_files_only=True,
            trust_remote_code=False,
            model_kwargs={"use_safetensors": True},
        )
        if self._model.get_sentence_embedding_dimension() != self._dimensions:
            raise ValueError("Cached model has an unexpected embedding dimension")
        if self._model.max_seq_length != self._max_tokens:
            raise ValueError("Cached model has an unexpected token limit")
        self._model.eval()

    def encode(self, texts: Sequence[str]) -> tuple[VectorRecord, ...]:
        """Encode a nonempty batch; reject oversized text instead of silently truncating."""
        if not texts or any(not text.strip() for text in texts):
            raise ValueError("Provide a nonempty batch of nonblank texts")
        started = time.perf_counter()
        input_tokens = 0
        vectors: tuple[tuple[float, ...], ...] = ()
        error: str | None = None
        try:
            tokens = self._model.tokenizer(
                list(texts), add_special_tokens=True, truncation=False, padding=False
            )["input_ids"]
            input_tokens = sum(len(ids) for ids in tokens)
            if any(len(ids) > self._max_tokens for ids in tokens):
                raise ValueError(f"Text exceeds the {self._max_tokens}-token embedding limit")
            encoded = self._model.encode(
                list(texts),
                batch_size=len(texts),
                normalize_embeddings=True,
                convert_to_numpy=True,
                show_progress_bar=False,
            )
            vectors = tuple(tuple(float(value) for value in row) for row in encoded)
            if len(vectors) != len(texts) or any(
                len(vector) != self._dimensions for vector in vectors
            ):
                raise ValueError("Encoder returned an unexpected vector shape")
            return tuple(
                VectorRecord(
                    embedding_model=self.embedding_model,
                    embedding_version=self.embedding_version,
                    embedding_dim=self.embedding_dim,
                    embedding=vector,
                )
                for vector in vectors
            )
        except Exception as exc:
            error = f"{type(exc).__name__}: {exc}"
            raise
        finally:
            self._record_call(
                EmbeddingCall(
                    model_id=self.model_id,
                    config_hash=self.config_hash,
                    texts=tuple(texts),
                    input_tokens=input_tokens,
                    latency_ms=round((time.perf_counter() - started) * 1000),
                    vectors=vectors,
                    error=error,
                )
            )
