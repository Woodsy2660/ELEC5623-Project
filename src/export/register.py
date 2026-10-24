"""FR12: Register and history export.

Structured export containing for every requirement family:
- requirement id, current version number, current state
- current statement text
- every retained version: version number, state, statement, the event that
  created it, and its evidence references (turn_id, start, end)
- the decision history: event type, actor, timestamp, reason where present

Superseded and withdrawn versions are INCLUDED. FR09 keeps history and FR03
requires it to stay accessible.
"""

import csv
import json
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from src.persist.models import (
    Event,
    Project,
    Requirement,
    RequirementCurrent,
    RequirementVersion,
)


class ExportError(Exception):
    """Raised when export fails."""

    pass


def export_register(session: Session, project_id: str) -> dict[str, Any]:
    """Export the register and decision history for a project.

    Args:
        session: Database session.
        project_id: The project to export.

    Returns:
        Structured dict suitable for JSON serialisation containing:
        - project metadata
        - requirements list with full version and decision history

    Raises:
        ExportError: If the project does not exist.
    """
    # Verify project exists
    project = session.get(Project, project_id)
    if project is None:
        raise ExportError(f"Project not found: {project_id}")

    # Get all requirements for this project
    requirements = (
        session.execute(
            select(Requirement)
            .where(Requirement.project_id == project_id)
            .order_by(Requirement.id)
        )
        .scalars()
        .all()
    )

    # Build requirements list
    requirements_data: list[dict[str, Any]] = []

    for req in requirements:
        # Get current version info
        current = (
            session.execute(
                select(RequirementCurrent).where(
                    RequirementCurrent.requirement_id == req.id
                )
            )
            .scalars()
            .first()
        )

        # Get all versions for this requirement (including superseded/withdrawn)
        versions = (
            session.execute(
                select(RequirementVersion)
                .where(RequirementVersion.requirement_id == req.id)
                .order_by(RequirementVersion.version)
            )
            .scalars()
            .all()
        )

        # Build versions list
        versions_data: list[dict[str, Any]] = []
        for ver in versions:
            # Parse evidence JSON
            evidence = json.loads(ver.evidence_json) if ver.evidence_json else []

            # Get the event that created this version
            event = session.get(Event, ver.created_event_id)
            created_event_data = None
            if event:
                created_event_data = {
                    "event_id": event.id,
                    "event_type": event.event_type,
                    "actor": event.actor,
                    "timestamp": _format_datetime(event.ts),
                    "payload": json.loads(event.payload_json) if event.payload_json else {},
                }

            versions_data.append({
                "version_id": ver.id,
                "version": ver.version,
                "state": ver.state,
                "text": ver.text,
                "evidence": evidence,  # Contains turn_id, start, end
                "created_event": created_event_data,
            })

        # Get decision history (all events that reference this requirement)
        decision_history = _get_decision_history(session, project_id, req.id)

        # Build requirement entry
        req_data: dict[str, Any] = {
            "requirement_id": req.id,
            "current_version": current.current_version_id if current else None,
            "current_state": current.state if current else None,
            "current_text": current.text if current else None,
            "versions": versions_data,
            "decision_history": decision_history,
        }

        # Add current version number
        if current and versions:
            current_ver = next(
                (v for v in versions if v.id == current.current_version_id), None
            )
            if current_ver:
                req_data["current_version_number"] = current_ver.version

        requirements_data.append(req_data)

    return {
        "project_id": project_id,
        "project_name": project.name,
        "exported_at": _format_datetime(datetime.now(UTC)),
        "requirements": requirements_data,
    }


def _get_decision_history(
    session: Session, project_id: str, requirement_id: str
) -> list[dict[str, Any]]:
    """Get decision history for a requirement.

    Returns events in chronological order that affected this requirement.
    """
    # Query events for this project that reference the requirement
    events = (
        session.execute(
            select(Event)
            .where(Event.project_id == project_id)
            .order_by(Event.ts)
        )
        .scalars()
        .all()
    )

    history: list[dict[str, Any]] = []

    for event in events:
        payload = json.loads(event.payload_json) if event.payload_json else {}

        # Check if this event references our requirement
        if _event_references_requirement(payload, requirement_id):
            entry: dict[str, Any] = {
                "event_id": event.id,
                "event_type": event.event_type,
                "actor": event.actor,
                "timestamp": _format_datetime(event.ts),
            }

            # Include reason if present
            if "reason" in payload:
                entry["reason"] = payload["reason"]

            history.append(entry)

    return history


def _event_references_requirement(payload: dict[str, Any], requirement_id: str) -> bool:
    """Check if an event payload references a specific requirement."""
    # Check various payload fields that might reference a requirement
    if payload.get("requirement_id") == requirement_id:
        return True
    if payload.get("target_requirement_id") == requirement_id:
        return True
    if payload.get("predicted_id") == requirement_id:
        return True
    if requirement_id in payload.get("requirement_ids", []):
        return True
    return False


def _format_datetime(dt: datetime) -> str:
    """Format datetime as ISO 8601 string."""
    return dt.isoformat() if dt else None


def write_export(session: Session, project_id: str, path: Path) -> None:
    """Write register export as JSON.

    Args:
        session: Database session.
        project_id: The project to export.
        path: Output file path.

    Raises:
        ExportError: If export fails.
    """
    data = export_register(session, project_id)
    path.write_text(
        json.dumps(data, indent=2, ensure_ascii=False, sort_keys=True),
        encoding="utf-8",
    )


def write_export_csv(session: Session, project_id: str, path: Path) -> None:
    """Write register export as flat CSV rows.

    Each row represents one requirement version with its metadata.

    Args:
        session: Database session.
        project_id: The project to export.
        path: Output file path.

    Raises:
        ExportError: If export fails.
    """
    data = export_register(session, project_id)

    # Define CSV columns
    fieldnames = [
        "requirement_id",
        "version",
        "version_id",
        "state",
        "text",
        "is_current",
        "evidence_json",
        "created_event_id",
        "created_event_type",
        "created_actor",
        "created_timestamp",
    ]

    with open(path, "w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=fieldnames)
        writer.writeheader()

        for req in data["requirements"]:
            current_version_id = req.get("current_version")

            for ver in req["versions"]:
                row = {
                    "requirement_id": req["requirement_id"],
                    "version": ver["version"],
                    "version_id": ver["version_id"],
                    "state": ver["state"],
                    "text": ver["text"],
                    "is_current": ver["version_id"] == current_version_id,
                    "evidence_json": json.dumps(ver["evidence"]),
                    "created_event_id": ver["created_event"]["event_id"] if ver["created_event"] else None,
                    "created_event_type": ver["created_event"]["event_type"] if ver["created_event"] else None,
                    "created_actor": ver["created_event"]["actor"] if ver["created_event"] else None,
                    "created_timestamp": ver["created_event"]["timestamp"] if ver["created_event"] else None,
                }
                writer.writerow(row)
