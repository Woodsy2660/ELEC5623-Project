"""FR01/03/12: demo presentation/export checks with synthetic offline records."""

import json
from pathlib import Path

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from src.ingest.loader import import_meeting, load_scenario
from src.persist.database import create_database_engine, initialize_database, transaction
from src.persist.models import Meeting, Project, Turn


def test_demo_meetings_load_sequentially_with_stable_project_and_no_gold(tmp_path):
    root = Path("scenarios/demo")
    engine = create_database_engine(f"sqlite:///{tmp_path / 'demo.db'}")
    initialize_database(engine)
    original = {}
    for index, folder in enumerate(["m1", "m2", "m3"], 1):
        path = root / folder
        assert not (path / "gold.yaml").exists()
        file = path / "canonical" / f"M{index:02d}.jsonl"
        rows = [json.loads(line) for line in file.read_text().splitlines()]
        with transaction(engine) as db:
            project = load_scenario(db, path)
            assert project.id == "DEMO"
            imported = import_meeting(db, project.id, file, index)
            assert imported.ordinal == index
            assert import_meeting(db, project.id, file, index).id == imported.id
            actual = db.scalars(
                select(Turn).where(Turn.meeting_id == imported.id).order_by(Turn.turn_index)
            ).all()
            assert [(r.id, r.speaker, r.text) for r in actual] == [
                (r["turn_id"], r["speaker"], r["text"]) for r in rows
            ]
            original.update({r.id: r.text for r in actual})
    with Session(engine) as db:
        assert db.scalar(select(func.count()).select_from(Project)) == 1
        assert db.scalar(select(func.count()).select_from(Meeting)) == 3
        assert db.scalar(select(func.count()).select_from(Turn)) == len(original) == 18
    engine.dispose()
