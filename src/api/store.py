"""Process-wide fixture store. Rebuilt from the D1 design export on reset."""

from src.api.fixtures import Store, build_store

_store: Store | None = None


def get_store() -> Store:
    global _store
    if _store is None:
        _store = build_store()
    return _store


def reset_store() -> Store:
    global _store
    _store = build_store()
    return _store
