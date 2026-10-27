"""One encoder identity for every vector this process writes.

``CIA_ENCODER=local`` is the default. The local MiniLM is offline and
deterministic. ``CIA_ENCODER=azure`` selects the deployed cia-embed deployment.
Do not change the default until an oracle run has produced numbers: the Azure
comparison is a second run of the same candidates, not a silent switch.
"""

import math
import os
from collections.abc import Callable
from typing import Protocol

from src.logging.calls import CallLogger
from src.retrieve.embeddings import EmbeddingCall, LocalEmbedder


class Embedder(Protocol):
    """L2-normalised vectors plus the identity stored on every register row."""

    model: str
    version: str
    dim: int

    def encode(self, texts: list[str]) -> list[tuple[float, ...]]:
        """Return one L2-normalised vector per text."""

    def fingerprint(self) -> str:
        """Stable id recorded on the run row."""


def _l2_normalize(vector: tuple[float, ...]) -> tuple[float, ...]:
    """Azure embeddings are not unit vectors. Retrieval compares unit vectors."""
    scale = max(abs(component) for component in vector)
    if scale == 0:
        raise ValueError("Embedding must be nonzero")
    scaled = tuple(component / scale for component in vector)
    norm = math.sqrt(math.fsum(component * component for component in scaled))
    if norm == 0:
        raise ValueError("Embedding must be nonzero")
    return tuple(component / norm for component in scaled)


def encoder_kind() -> str:
    """Resolve ``CIA_ENCODER``. Unset means local."""
    kind = os.environ.get("CIA_ENCODER", "local").strip().lower()
    if kind in {"", "local"}:
        return "local"
    if kind == "azure":
        return "azure"
    raise ValueError(f"CIA_ENCODER must be local or azure, not {kind!r}")


class LocalPipelineEmbedder:
    """The pinned MiniLM. ``encode`` returns the same tuples retrieval stores."""

    def __init__(self, record_call: Callable[[EmbeddingCall], None] | None = None) -> None:
        self._inner = LocalEmbedder(record_call or (lambda _call: None))
        self.model = self._inner.embedding_model
        self.version = self._inner.embedding_version
        self.dim = int(self._inner.embedding_dim)

    def encode(self, texts: list[str]) -> list[tuple[float, ...]]:
        return [record.embedding for record in self._inner.encode(texts)]

    def fingerprint(self) -> str:
        return self._inner.config_hash


class AzurePipelineEmbedder:
    """cia-embed through the logged embedding caller. Vectors are normalised here."""

    def __init__(self, logger: CallLogger, *, run_id: str) -> None:
        from src.llm.config import FOUNDRY_EMBED_DIM, FOUNDRY_EMBED_MODEL, FOUNDRY_EMBED_VERSION

        self.model = FOUNDRY_EMBED_MODEL
        self.version = FOUNDRY_EMBED_VERSION
        self.dim = FOUNDRY_EMBED_DIM
        self._logger = logger
        self._run_id = run_id

    def encode(self, texts: list[str]) -> list[tuple[float, ...]]:
        vectors = self._logger.embed(run_id=self._run_id, texts=texts)
        if len(vectors) != len(texts) or any(len(vector) != self.dim for vector in vectors):
            raise ValueError(f"cia-embed returned an unexpected shape; expected dim {self.dim}")
        return [_l2_normalize(vector) for vector in vectors]

    def fingerprint(self) -> str:
        import hashlib

        from src.llm.config import FOUNDRY_EMBED_DEPLOYMENT

        raw = f"{FOUNDRY_EMBED_DEPLOYMENT}|{self.model}|{self.version}|{self.dim}".encode()
        return hashlib.sha1(raw).hexdigest()


def get_embedder(
    *,
    record_local: Callable[[EmbeddingCall], None] | None = None,
    azure_logger: CallLogger | None = None,
    run_id: str | None = None,
) -> Embedder:
    """Build the encoder selected by ``CIA_ENCODER``. The default is local."""
    kind = encoder_kind()
    if kind == "local":
        return LocalPipelineEmbedder(record_local)
    if azure_logger is None or not run_id:
        raise ValueError("CIA_ENCODER=azure requires a call logger and a run id")
    return AzurePipelineEmbedder(azure_logger, run_id=run_id)
