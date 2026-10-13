"""Local-run trace adapter using the existing Run/ModelCall schema, without register access.

This does not define or replace the shared logger interface owned by Tracks A/C.
"""

import json
from datetime import UTC, datetime
from importlib.metadata import version
from pathlib import Path
from uuid import uuid4

from sqlalchemy import create_engine
from sqlalchemy.orm import Session

from src.persist.models import Base, ModelCall, Run
from src.retrieve.embeddings import EmbeddingCall


class LocalTrace:
    """One isolated run folder with raw vectors, runtime versions and call rows."""

    def __init__(
        self,
        output_root: Path,
        model_id: str,
        config_hash: str,
        *,
        mode: str = "demo",
        candidate_source: str = "local-smoke",
        repeat_index: int = 1,
    ) -> None:
        self.run_id = str(uuid4())
        self.output_dir = output_root / self.run_id
        self.output_dir.mkdir(parents=True, exist_ok=False)
        self._engine = create_engine(f"sqlite:///{self.output_dir / 'trace.sqlite'}")
        Base.metadata.create_all(self._engine, tables=[Run.__table__, ModelCall.__table__])
        packages = ("sentence-transformers", "transformers", "torch", "numpy", "huggingface-hub")
        runtime = {package: version(package) for package in packages}
        (self.output_dir / "runtime.json").write_text(json.dumps(runtime, indent=2))
        with Session(self._engine) as session, session.begin():
            session.add(
                Run(
                    id=self.run_id,
                    mode=mode,
                    candidate_source=candidate_source,
                    repeat_index=repeat_index,
                    prompt_hash=config_hash,
                    model_deployment=model_id,
                    temp=0,
                    started_at=datetime.now(UTC),
                    notes="Local embeddings only. Config blob hash; no generation prompt.",
                )
            )

    def record(self, call: EmbeddingCall) -> None:
        """Record successful and failed local batches; all retries are explicit new calls."""
        call_id = str(uuid4())
        raw_path = self.output_dir / f"{call_id}.json"
        raw_path.write_text(call.model_dump_json(indent=2))
        with Session(self._engine) as session, session.begin():
            session.add(
                ModelCall(
                    id=call_id,
                    run_id=self.run_id,
                    stage="local_embedding",
                    prompt_hash=call.config_hash,
                    input_tokens=call.input_tokens,
                    output_tokens=0,
                    latency_ms=call.latency_ms,
                    retries=0,
                    cost=0,
                    raw_json_path=str(raw_path),
                )
            )

    def close(self) -> None:
        """Release the isolated trace database."""
        self._engine.dispose()
