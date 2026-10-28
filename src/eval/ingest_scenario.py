"""Load authored scenario meetings without opening gold labels."""

import argparse
import json
import os
from pathlib import Path

from src.ingest.loader import load_scenario, load_scenario_meetings
from src.persist.database import (
    DEFAULT_DATABASE_URL,
    create_database_engine,
    initialize_database,
    review_transaction,
)


def ingest_scenario(scenario: Path, database_url: str) -> dict[str, object]:
    """Atomically ingest project, speaker authority and canonical meeting turns."""
    engine = create_database_engine(database_url)
    try:
        initialize_database(engine)
        with review_transaction(engine) as session:
            project = load_scenario(session, scenario)
            meetings = load_scenario_meetings(session, scenario)
            return {"project_id": project.id, "meeting_ids": [meeting.id for meeting in meetings]}
    finally:
        engine.dispose()


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--scenario",
        type=Path,
        required=True,
        help="Path to scenario directory (e.g., scenarios/dev/D1)",
    )
    parser.add_argument(
        "--database-url",
        default=os.environ.get("DATABASE_URL", DEFAULT_DATABASE_URL),
    )
    args = parser.parse_args()
    print(json.dumps(ingest_scenario(args.scenario, args.database_url)))


if __name__ == "__main__":
    main()
