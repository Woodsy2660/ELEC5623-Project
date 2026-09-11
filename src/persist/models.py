"""SQLAlchemy models matching the schema in docs/02-architecture.md."""

from datetime import datetime

from sqlalchemy import (
    Boolean,
    DateTime,
    Float,
    ForeignKey,
    Integer,
    LargeBinary,
    String,
    Text,
)
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column


class Base(DeclarativeBase):
    """Base class for all models."""

    pass


# Core entities


class Project(Base):
    """A project containing meetings and requirements."""

    __tablename__ = "projects"

    id: Mapped[str] = mapped_column(String, primary_key=True)
    name: Mapped[str] = mapped_column(String, nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime, nullable=False)


class Meeting(Base):
    """A meeting transcript within a project."""

    __tablename__ = "meetings"

    id: Mapped[str] = mapped_column(String, primary_key=True)
    project_id: Mapped[str] = mapped_column(ForeignKey("projects.id"), nullable=False)
    ordinal: Mapped[int] = mapped_column(Integer, nullable=False)
    source_hash: Mapped[str] = mapped_column(String, nullable=False)
    imported_at: Mapped[datetime] = mapped_column(DateTime, nullable=False)


class Turn(Base):
    """A single turn (utterance) within a meeting transcript."""

    __tablename__ = "turns"

    id: Mapped[str] = mapped_column(String, primary_key=True)
    meeting_id: Mapped[str] = mapped_column(ForeignKey("meetings.id"), nullable=False)
    turn_index: Mapped[int] = mapped_column(Integer, nullable=False)
    speaker: Mapped[str] = mapped_column(String, nullable=False)
    text: Mapped[str] = mapped_column(Text, nullable=False)


class Speaker(Base):
    """Speaker authority configuration per project."""

    __tablename__ = "speakers"

    project_id: Mapped[str] = mapped_column(ForeignKey("projects.id"), primary_key=True)
    speaker_label: Mapped[str] = mapped_column(String, primary_key=True)
    role: Mapped[str] = mapped_column(String, nullable=False)
    can_confirm_scope: Mapped[bool] = mapped_column(Boolean, nullable=False)


# Requirements register


class Requirement(Base):
    """Stable family ID for a requirement."""

    __tablename__ = "requirements"

    id: Mapped[str] = mapped_column(String, primary_key=True)
    project_id: Mapped[str] = mapped_column(ForeignKey("projects.id"), nullable=False)


class RequirementVersion(Base):
    """A versioned snapshot of a requirement."""

    __tablename__ = "requirement_versions"

    id: Mapped[str] = mapped_column(String, primary_key=True)
    requirement_id: Mapped[str] = mapped_column(ForeignKey("requirements.id"), nullable=False)
    version: Mapped[int] = mapped_column(Integer, nullable=False)
    text: Mapped[str] = mapped_column(Text, nullable=False)
    state: Mapped[str] = mapped_column(String, nullable=False)
    evidence_json: Mapped[str] = mapped_column(Text, nullable=False)
    embedding_blob: Mapped[bytes | None] = mapped_column(LargeBinary, nullable=True)
    created_event_id: Mapped[str] = mapped_column(ForeignKey("events.id"), nullable=False)


class RequirementCurrent(Base):
    """Denormalised current state of a requirement."""

    __tablename__ = "requirements_current"

    requirement_id: Mapped[str] = mapped_column(ForeignKey("requirements.id"), primary_key=True)
    current_version_id: Mapped[str] = mapped_column(
        ForeignKey("requirement_versions.id"), nullable=False
    )
    state: Mapped[str] = mapped_column(String, nullable=False)
    text: Mapped[str] = mapped_column(Text, nullable=False)


# Pipeline artifacts


class Candidate(Base):
    """An extracted candidate requirement statement."""

    __tablename__ = "candidates"

    id: Mapped[str] = mapped_column(String, primary_key=True)
    meeting_id: Mapped[str] = mapped_column(ForeignKey("meetings.id"), nullable=False)
    run_id: Mapped[str] = mapped_column(ForeignKey("runs.id"), nullable=False)
    text_norm: Mapped[str] = mapped_column(Text, nullable=False)
    evidence_json: Mapped[str] = mapped_column(Text, nullable=False)
    extract_call_id: Mapped[str] = mapped_column(ForeignKey("model_calls.id"), nullable=False)


class Proposal(Base):
    """A classification proposal awaiting confirmation."""

    __tablename__ = "proposals"

    id: Mapped[str] = mapped_column(String, primary_key=True)
    run_id: Mapped[str] = mapped_column(ForeignKey("runs.id"), nullable=False)
    candidate_id: Mapped[str] = mapped_column(ForeignKey("candidates.id"), nullable=False)
    retrieved_ids_json: Mapped[str] = mapped_column(Text, nullable=False)
    predicted_id: Mapped[str | None] = mapped_column(String, nullable=True)
    predicted_relation: Mapped[str] = mapped_column(String, nullable=False)
    proposed_event: Mapped[str] = mapped_column(String, nullable=False)
    engine_verdict: Mapped[str] = mapped_column(String, nullable=False)


class Event(Base):
    """Append-only event log."""

    __tablename__ = "events"

    id: Mapped[str] = mapped_column(String, primary_key=True)
    project_id: Mapped[str] = mapped_column(ForeignKey("projects.id"), nullable=False)
    ts: Mapped[datetime] = mapped_column(DateTime, nullable=False)
    actor: Mapped[str] = mapped_column(String, nullable=False)
    event_type: Mapped[str] = mapped_column(String, nullable=False)
    payload_json: Mapped[str] = mapped_column(Text, nullable=False)
    run_id: Mapped[str | None] = mapped_column(ForeignKey("runs.id"), nullable=True)


# Run management


class Run(Base):
    """A single pipeline execution run."""

    __tablename__ = "runs"

    id: Mapped[str] = mapped_column(String, primary_key=True)
    mode: Mapped[str] = mapped_column(String, nullable=False)
    candidate_source: Mapped[str] = mapped_column(String, nullable=False)
    repeat_index: Mapped[int] = mapped_column(Integer, nullable=False)
    prompt_hash: Mapped[str] = mapped_column(String, nullable=False)
    model_deployment: Mapped[str] = mapped_column(String, nullable=False)
    temp: Mapped[float] = mapped_column(Float, nullable=False)
    started_at: Mapped[datetime] = mapped_column(DateTime, nullable=False)
    notes: Mapped[str | None] = mapped_column(Text, nullable=True)


class ModelCall(Base):
    """Record of a single model API call."""

    __tablename__ = "model_calls"

    id: Mapped[str] = mapped_column(String, primary_key=True)
    run_id: Mapped[str] = mapped_column(ForeignKey("runs.id"), nullable=False)
    stage: Mapped[str] = mapped_column(String, nullable=False)
    prompt_hash: Mapped[str] = mapped_column(String, nullable=False)
    input_tokens: Mapped[int] = mapped_column(Integer, nullable=False)
    output_tokens: Mapped[int] = mapped_column(Integer, nullable=False)
    latency_ms: Mapped[int] = mapped_column(Integer, nullable=False)
    retries: Mapped[int] = mapped_column(Integer, nullable=False)
    cost: Mapped[float] = mapped_column(Float, nullable=False)
    raw_json_path: Mapped[str] = mapped_column(String, nullable=False)


# Gold data (scoring only)


class GoldEvent(Base):
    """Gold-standard events for evaluation. Only accessed by src/eval/score.py."""

    __tablename__ = "gold_events"

    scenario_id: Mapped[str] = mapped_column(String, primary_key=True)
    meeting_ordinal: Mapped[int] = mapped_column(Integer, primary_key=True)
    event_index: Mapped[int] = mapped_column(Integer, primary_key=True)
    event_type: Mapped[str] = mapped_column(String, nullable=False)
    payload_json: Mapped[str] = mapped_column(Text, nullable=False)
