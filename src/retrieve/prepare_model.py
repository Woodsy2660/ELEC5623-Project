"""Explicit one-time download. Runtime encoding uses local files only."""

import json
from pathlib import Path

CONFIG_PATH = Path(__file__).with_name("model_config.json")
REPO_ROOT = Path(__file__).resolve().parents[2]
MODEL_CACHE = REPO_ROOT / ".venv" / "embedding-cache"


def main() -> None:
    """Download only the pinned safe weights, tokenizer and SentenceTransformer config."""
    from huggingface_hub import snapshot_download

    config = json.loads(CONFIG_PATH.read_text())
    path = snapshot_download(
        repo_id=config["model_id"],
        revision=config["revision"],
        cache_dir=str(MODEL_CACHE),
        allow_patterns=["*.json", "model.safetensors", "vocab.txt", "README.md"],
        ignore_patterns=["onnx/*", "openvino/*"],
    )
    print(f"Pinned model ready: {config['model_id']}@{config['revision']}")
    print(f"Local snapshot: {path}")


if __name__ == "__main__":
    main()
