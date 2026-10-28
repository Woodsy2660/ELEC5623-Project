"""Storage foundation tests; no model calls, gold labels, or fixture API (FR09/E4)."""

import json
import sys
from collections.abc import Iterator
from datetime import datetime
from pathlib import Path

import pytest
from sqlalchemy import Engine, inspect, select
from sqlalchemy.engine import URL
from sqlalchemy.exc import IntegrityError

from src.persist.__main__ import main
from src.persist.database import create_database_engine, initialize_database, transaction
from src.persist.models import Meeting, Project
from src.retrieve.schemas import VectorRecord

EXPECTED_TABLES = {
    "projects",
    "meetings",
    "turns",
    "speakers",
    "requirements",
    "requirement_versions",
    "requirements_current",
    "candidates",
    "proposals",
    "proposal_reviews",
    "events",
    "runs",
    "model_calls",
    "gold_events",
}


def project(project_id: str) -> Project:
    """A synthetic project, not evaluation corpus data."""
    return Project(id=project_id, name="Storage test", created_at=datetime(2026, 1, 1))


@pytest.fixture
def database(tmp_path: Path) -> Iterator[Engine]:
    engine = create_database_engine(URL.create("sqlite", database=str(tmp_path / "test.db")))
    initialize_database(engine)
    try:
        yield engine
    finally:
        engine.dispose()


def test_initialization_creates_the_existing_schema(database: Engine) -> None:
    assert set(inspect(database).get_table_names()) == EXPECTED_TABLES
    columns = {column["name"] for column in inspect(database).get_columns("requirement_versions")}
    assert {
        "embedding_blob",
        "embedding_model",
        "embedding_version",
        "embedding_dim",
    } <= columns
    with transaction(database) as session:
        assert session.scalars(select(Project)).all() == []


def test_initializing_again_preserves_rows(database: Engine) -> None:
    with transaction(database) as session:
        session.add(project("P1"))
    initialize_database(database)
    with transaction(database) as session:
        assert session.get(Project, "P1") is not None


def test_initialization_migrates_additive_columns_and_only_backfills_verified_vectors(
    tmp_path: Path,
) -> None:
    engine = create_database_engine(URL.create("sqlite", database=str(tmp_path / "legacy.db")))
    legacy = VectorRecord(
        embedding_model="legacy-model",
        embedding_version="rev1",
        embedding_dim=2,
        embedding=(0.6, 0.8),
    )
    try:
        with engine.begin() as connection:
            connection.exec_driver_sql(
                "CREATE TABLE requirement_versions (id TEXT PRIMARY KEY, embedding_blob BLOB)"
            )
            connection.exec_driver_sql("CREATE TABLE proposals (id TEXT PRIMARY KEY)")
            connection.exec_driver_sql(
                "CREATE TABLE proposal_reviews (proposal_id TEXT PRIMARY KEY)"
            )
            connection.exec_driver_sql(
                "INSERT INTO requirement_versions (id, embedding_blob) VALUES (?, ?)",
                ("verified", legacy.model_dump_json().encode("utf-8")),
            )
            connection.exec_driver_sql(
                "INSERT INTO requirement_versions (id, embedding_blob) VALUES (?, ?)",
                ("unverified", json.dumps([0.6, 0.8]).encode("utf-8")),
            )

        initialize_database(engine)
        with engine.connect() as connection:
            rows = {
                row[0]: row[1:]
                for row in connection.exec_driver_sql(
                    "SELECT id, embedding_blob, embedding_model, embedding_version, embedding_dim "
                    "FROM requirement_versions"
                )
            }
        migrated = rows["verified"]
        assert json.loads(migrated[0].decode("utf-8")) == [0.6, 0.8]
        assert migrated[1:] == ("legacy-model", "rev1", 2)
        assert rows["unverified"][1:] == (None, None, None)
        assert {column["name"] for column in inspect(engine).get_columns("proposals")} >= {
            "rankings_json",
            "decision",
            "downgraded",
        }
        assert "classifier_replacement_stated" in {
            column["name"] for column in inspect(engine).get_columns("proposal_reviews")
        }
        assert "expected_project_heads_json" in {
            column["name"] for column in inspect(engine).get_columns("proposal_reviews")
        }
    finally:
        engine.dispose()


def test_committed_data_survives_close_and_reopen(tmp_path: Path) -> None:
    url = URL.create("sqlite", database=str(tmp_path / "restart.db"))
    first = create_database_engine(url)
    try:
        initialize_database(first)
        with transaction(first) as session:
            session.add(project("P1"))
    finally:
        first.dispose()

    reopened = create_database_engine(url)
    try:
        with transaction(reopened) as session:
            saved = session.get(Project, "P1")
            assert saved is not None
            assert saved.name == "Storage test"
    finally:
        reopened.dispose()


def test_failure_rolls_back_every_flushed_write(database: Engine) -> None:
    with pytest.raises(RuntimeError, match="simulated interruption"):
        with transaction(database) as session:
            session.add(project("P1"))
            session.flush()
            session.add(project("P2"))
            session.flush()
            raise RuntimeError("simulated interruption")
    with transaction(database) as session:
        assert session.scalars(select(Project)).all() == []
        session.add(project("P3"))
    with transaction(database) as session:
        assert session.get(Project, "P3") is not None


def test_foreign_keys_are_enabled_on_each_connection(database: Engine) -> None:
    with database.connect() as first, database.connect() as second:
        assert first.exec_driver_sql("PRAGMA foreign_keys").scalar_one() == 1
        assert second.exec_driver_sql("PRAGMA foreign_keys").scalar_one() == 1


def test_missing_parent_is_rejected_and_rolled_back(database: Engine) -> None:
    with pytest.raises(IntegrityError):
        with transaction(database) as session:
            session.add(
                Meeting(
                    id="M1",
                    project_id="missing-project",
                    ordinal=1,
                    source_hash="synthetic-source",
                    imported_at=datetime(2026, 1, 1),
                )
            )
    with transaction(database) as session:
        assert session.scalars(select(Meeting)).all() == []


def test_primary_key_conflict_rolls_back_other_writes(database: Engine) -> None:
    with transaction(database) as session:
        session.add(project("existing"))
    with pytest.raises(IntegrityError):
        with transaction(database) as session:
            session.add(project("new"))
            session.flush()
            session.add(project("existing"))
    with transaction(database) as session:
        assert session.get(Project, "existing") is not None
        assert session.get(Project, "new") is None


@pytest.mark.parametrize("url", ["postgresql://localhost/test", "sqlite+aiosqlite:///:memory:"])
def test_non_sync_sqlite_url_is_rejected(url: str) -> None:
    with pytest.raises(ValueError, match="Only synchronous SQLite"):
        create_database_engine(url)


def test_empty_database_url_is_rejected() -> None:
    with pytest.raises(ValueError, match="must not be empty"):
        create_database_engine("")


def test_cli_uses_database_url_environment_variable(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    target = tmp_path / "configured.db"
    url = URL.create("sqlite", database=str(target))
    monkeypatch.setenv("DATABASE_URL", url.render_as_string(hide_password=False))
    monkeypatch.setattr(sys, "argv", ["python -m src.persist"])
    main()
    assert target.exists()
    assert "existing data was preserved" in capsys.readouterr().out
    engine = create_database_engine(url)
    try:
        assert set(inspect(engine).get_table_names()) == EXPECTED_TABLES
    finally:
        engine.dispose()
