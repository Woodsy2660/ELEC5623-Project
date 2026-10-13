"""Initialize the local SQLite schema without secrets or model calls."""

import argparse
import os

from src.persist.database import (
    DEFAULT_DATABASE_URL,
    create_database_engine,
    initialize_database,
)


def main() -> None:
    """Create missing tables in the configured SQLite database (FR09)."""
    parser = argparse.ArgumentParser(description="Initialize SQLite tables without deleting data.")
    parser.add_argument(
        "--database-url",
        default=os.environ.get("DATABASE_URL", DEFAULT_DATABASE_URL),
        help="SQLite URL; defaults to DATABASE_URL or sqlite:///consulting_intelligence.db",
    )
    args = parser.parse_args()
    engine = create_database_engine(args.database_url)
    try:
        initialize_database(engine)
    finally:
        engine.dispose()
    print("SQLite schema initialized; existing data was preserved.")


if __name__ == "__main__":
    main()
