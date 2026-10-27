"""SQLite initialization and transaction primitives (FR09; E4 foundation).

No model calls or lifecycle decisions belong here. Business writes must first
pass deterministic validation and the demo/evaluation confirmation gate.
"""

import json
import sqlite3
from collections.abc import Iterator
from contextlib import contextmanager

from sqlalchemy import Engine, create_engine, event, inspect
from sqlalchemy.engine import URL, make_url
from sqlalchemy.orm import Session
from sqlalchemy.pool import ConnectionPoolEntry

from src.persist.models import Base
from src.retrieve.schemas import VectorRecord

DEFAULT_DATABASE_URL = "sqlite:///consulting_intelligence.db"


def create_database_engine(database_url: str | URL = DEFAULT_DATABASE_URL) -> Engine:
    """Create a synchronous SQLite engine; do not create tables or read .env.

    Relative file paths resolve against the process working directory. Foreign
    keys are enabled on every connection, not just during schema initialization.
    """
    if isinstance(database_url, str) and not database_url.strip():
        raise ValueError("DATABASE_URL must not be empty")
    url = make_url(database_url)
    if url.drivername not in {"sqlite", "sqlite+pysqlite"}:
        raise ValueError("Only synchronous SQLite databases are supported")
    engine = create_engine(url)

    @event.listens_for(engine, "connect")
    def _enable_foreign_keys(connection: sqlite3.Connection, _record: ConnectionPoolEntry) -> None:
        cursor = connection.cursor()
        try:
            cursor.execute("PRAGMA foreign_keys=ON")
        finally:
            cursor.close()

    return engine


_ADDITIVE_COLUMNS: dict[str, tuple[tuple[str, str], ...]] = {
    "requirement_versions": (
        ("embedding_model", "VARCHAR"),
        ("embedding_version", "VARCHAR"),
        ("embedding_dim", "INTEGER"),
    ),
    "proposals": (
        ("rankings_json", "TEXT"),
        ("decision", "VARCHAR"),
        ("downgraded", "BOOLEAN NOT NULL DEFAULT 0"),
    ),
    "proposal_reviews": (
        ("classifier_replacement_stated", "BOOLEAN"),
        ("expected_project_heads_json", "TEXT"),
    ),
}


def _add_missing_columns(connection) -> None:
    """Apply the small additive SQLite migration needed by the integrated A/B schema."""
    inspector = inspect(connection)
    tables = set(inspector.get_table_names())
    for table, columns in _ADDITIVE_COLUMNS.items():
        if table not in tables:
            continue
        present = {column["name"] for column in inspector.get_columns(table)}
        for name, declaration in columns:
            if name not in present:
                connection.exec_driver_sql(
                    f'ALTER TABLE "{table}" ADD COLUMN "{name}" {declaration}'
                )
                present.add(name)


def _backfill_vector_records(connection) -> None:
    """Convert validated legacy VectorRecord JSON blobs to A/B's split vector schema."""
    rows = connection.exec_driver_sql(
        """SELECT id, embedding_blob FROM requirement_versions
           WHERE embedding_blob IS NOT NULL
             AND embedding_model IS NULL
             AND embedding_version IS NULL
             AND embedding_dim IS NULL"""
    )
    for version_id, blob in rows:
        try:
            vector = VectorRecord.model_validate_json(bytes(blob))
        except (TypeError, ValueError):
            # Bare vectors have no trustworthy encoder identity. Leave them null;
            # retrieval will fail closed until an explicit migration is supplied.
            continue
        connection.exec_driver_sql(
            """UPDATE requirement_versions
               SET embedding_blob = ?, embedding_model = ?, embedding_version = ?, embedding_dim = ?
               WHERE id = ?""",
            (
                json.dumps(list(vector.embedding)).encode("utf-8"),
                vector.embedding_model,
                vector.embedding_version,
                vector.embedding_dim,
                version_id,
            ),
        )


def initialize_database(engine: Engine) -> None:
    """Create missing tables and apply idempotent additive SQLite schema upgrades.

    Existing rows are preserved. Legacy full ``VectorRecord`` blobs are converted
    only when their encoder identity validates; bare vectors are never guessed.
    """
    with engine.begin() as connection:
        Base.metadata.create_all(connection)
        _add_missing_columns(connection)
        _backfill_vector_records(connection)


@contextmanager
def transaction(engine: Engine) -> Iterator[Session]:
    """Commit on success, roll back on failure, and close the session.

    This is a storage primitive, not an authorized requirement-write service.
    Callers must not manually commit inside this context or bypass the gate.
    """
    with Session(engine) as session, session.begin():
        yield session


@contextmanager
def review_transaction(engine: Engine) -> Iterator[Session]:
    """Serialize SQLite review writers before reading the current pointer."""
    with Session(engine) as session:
        try:
            session.connection().exec_driver_sql("BEGIN IMMEDIATE")
            yield session
            session.commit()
        except BaseException:
            session.rollback()
            raise
