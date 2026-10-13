"""SQLite initialization and transaction primitives (FR09; E4 foundation).

No model calls or lifecycle decisions belong here. Business writes must first
pass deterministic validation and the demo/evaluation confirmation gate.
"""

import sqlite3
from collections.abc import Iterator
from contextlib import contextmanager

from sqlalchemy import Engine, create_engine, event
from sqlalchemy.engine import URL, make_url
from sqlalchemy.orm import Session
from sqlalchemy.pool import ConnectionPoolEntry

from src.persist.models import Base

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


def initialize_database(engine: Engine) -> None:
    """Create missing tables from existing models; never reset or migrate data.

    Calling this again preserves existing tables and rows. Schema changes to
    existing tables require a separate migration; create_all does not apply them.
    """
    with engine.begin() as connection:
        Base.metadata.create_all(connection)


@contextmanager
def transaction(engine: Engine) -> Iterator[Session]:
    """Commit on success, roll back on failure, and close the session.

    This is a storage primitive, not an authorized requirement-write service.
    Callers must not manually commit inside this context or bypass the gate.
    """
    with Session(engine) as session, session.begin():
        yield session
