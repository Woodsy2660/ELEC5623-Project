"""Local-only embedding adapter for approved register writes.

Each encoding attempt uses Track B's trace database under runs/. Those logs
survive a later register transaction rollback. No model weights download here.
"""

import hashlib
import json
from pathlib import Path

from src.persist.review import ReviewConflict
from src.retrieve.embeddings import LocalEmbedder
from src.retrieve.local_trace import LocalTrace
from src.retrieve.prepare_model import CONFIG_PATH
from src.retrieve.schemas import VectorRecord


def embed_review_text(text: str) -> VectorRecord:
    config_bytes = CONFIG_PATH.read_bytes()
    config = json.loads(config_bytes)
    model_id = f"{config['model_id']}@{config['revision']}"
    config_hash = hashlib.sha1(f"blob {len(config_bytes)}\0".encode() + config_bytes).hexdigest()
    trace = None
    try:
        trace = LocalTrace(Path("runs"), model_id, config_hash, candidate_source="review")
        return LocalEmbedder(trace.record).encode([text])[0]
    except (ImportError, OSError, ValueError) as exc:
        raise ReviewConflict(
            "Local embedding model is unavailable or rejected the text; register unchanged"
        ) from exc
    finally:
        if trace:
            trace.close()
