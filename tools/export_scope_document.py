"""Render a project's requirements register as a client-ready scope document (HTML).

Usage:
    python -m tools.export_scope_document --db sqlite:///demo.db --project DEMO \
        --out scope.html [--client "Tideway Logistics"] [--consultancy "Larkspur Digital"]

The HTML is self-contained and print-ready: open it in a browser and use
Print > Save as PDF for a PDF. It reads the same data as GET /projects/{id}/export,
then resolves each evidence span to the exact quoted words and speaker.

Sections: agreed scope (current confirmed requirements), change history
(superseded versions and what replaced them), items not yet agreed, and a
sign-off block. Nothing here changes the register.
"""

from __future__ import annotations

import argparse
import html
from datetime import UTC, datetime
from pathlib import Path

from sqlalchemy.orm import Session

from src.export.register import ExportError, export_register
from src.persist.database import create_database_engine
from src.persist.models import Meeting, Speaker, Turn


def _quote(session: Session, span: dict, project_id: str) -> tuple[str, str, int]:
    turn = session.get(Turn, span.get("turn_id"))
    meeting = session.get(Meeting, turn.meeting_id) if turn else None
    if meeting is None or meeting.project_id != project_id:
        raise ExportError("Evidence is missing or outside the exported project")
    start, end = span.get("start"), span.get("end")
    if type(start) is not int or type(end) is not int or not 0 <= start < end <= len(turn.text):
        raise ExportError("Evidence offsets do not resolve to the stored transcript")
    return turn.text[start:end], turn.speaker, meeting.ordinal


def _current_version(req: dict) -> dict:
    for version in req["versions"]:
        if version["version_id"] == req["current_version"]:
            if version["state"] != req["current_state"] or version["text"] != req["current_text"]:
                raise ExportError("Current pointer disagrees with requirement history")
            return version
    raise ExportError("Current requirement version is missing")


def _date(value: str | None) -> str:
    if not value:
        return ""
    try:
        return datetime.fromisoformat(value.replace("Z", "+00:00")).strftime("%d %b %Y")
    except ValueError:
        return value


def build_html(session: Session, project_id: str, client: str, consultancy: str) -> str:
    data = export_register(session, project_id)
    roles = {
        s.speaker_label: (s.role, s.can_confirm_scope)
        for s in session.query(Speaker).filter(Speaker.project_id == project_id)
    }
    meetings = sorted(
        session.query(Meeting).filter(Meeting.project_id == project_id), key=lambda m: m.ordinal
    )
    reqs = data["requirements"]
    current = [r for r in reqs if r["current_state"] == "confirmed"]
    superseded = [r for r in reqs if r["current_state"] == "superseded"]
    pending = [r for r in reqs if r["current_state"] in {"proposed", "contradicted"}]
    withdrawn = [r for r in reqs if r["current_state"] == "withdrawn"]
    for req in reqs:
        _current_version(req)

    def first_meeting(req: dict) -> int:
        ev = req["versions"][0]["evidence"]
        return _quote(session, ev[0], project_id)[2] or 0 if ev else 0

    current.sort(key=lambda r: (first_meeting(r), r["versions"][0]["created_event"]["timestamp"]))

    replaced_by: dict[str, dict] = {}
    for req in reqs:
        for version in req["versions"]:
            payload = version["created_event"].get("payload", {})
            if payload.get("replaces_requirement_id"):
                replaced_by[payload["replaces_requirement_id"]] = version

    def evidence_html(version: dict) -> str:
        parts = []
        for span in version["evidence"]:
            text, speaker, ordinal = _quote(session, span, project_id)
            role, can_confirm = roles.get(speaker, ("", False))
            who = f"{html.escape(speaker)}{', ' + html.escape(role) if role else ''}"
            parts.append(
                f'<div class="ev">“{html.escape(text)}”<span>{who} · Meeting {ordinal}'
                f"{' · can approve scope' if can_confirm else ''}</span></div>"
            )
        return "".join(parts)

    rows = []
    for index, req in enumerate(current, start=1):
        version = _current_version(req)
        recorded_at = _date(version["created_event"]["timestamp"])
        history = version["version"]
        rows.append(
            f'<tr><td class="id">SR-{index:02d}</td><td><div class="req">{html.escape(req["current_text"])}</div>'
            f"{evidence_html(version)}</td><td class=\"st\">Agreed<br><small>Recorded {recorded_at}"
            f"{' · v' + str(history) if history > 1 else ''}</small></td></tr>"
        )

    changes = []
    for req in superseded:
        latest = _current_version(req)
        predecessors = [v for v in req["versions"] if v["version"] < latest["version"]]
        old = predecessors[-1] if predecessors else latest
        replacement = replaced_by.get(req["requirement_id"])
        replacement_html = (
            f'<div class="req">{html.escape(replacement["text"])}</div>{evidence_html(replacement)}'
            if replacement
            else '<div class="req">No linked replacement recorded</div>'
        )
        changes.append(
            f'<tr><td><s>{html.escape(old["text"])}</s>{evidence_html(old)}</td>'
            f'<td>{replacement_html}</td><td class="st">{_date(latest["created_event"]["timestamp"])}</td></tr>'
        )
    withdrawn_html = "".join(
        f'<li>{html.escape(req["current_text"])} <em>(withdrawn)</em></li>' for req in withdrawn
    )

    pend = [
        f'<li>{html.escape(r["current_text"])} <em>({html.escape(r["current_state"])})</em></li>'
        for r in pending
    ]
    meeting_list = ", ".join(
        f"Meeting {m.ordinal} ({_date(m.imported_at.isoformat())})" for m in meetings
    )
    approver = next((label for label, (_, ok) in roles.items() if ok), "")
    approver_role = roles.get(approver, ("", False))[0]
    today = datetime.now(UTC).strftime("%d %B %Y")

    return f"""<!doctype html><html lang="en"><head><meta charset="utf-8">
<title>Requirements Scope · {html.escape(data["project_name"])}</title>
<style>
@page {{ size: A4; margin: 18mm 16mm; }}
body {{ font-family: "DM Sans", "Helvetica Neue", Arial, sans-serif; color:#0f0e0d; background:#fbf9f6; margin:0; font-size:11pt; line-height:1.45; }}
.page {{ max-width: 780px; margin: 0 auto; padding: 40px 36px; background:#fbf9f6; }}
h1 {{ font-family: "Playfair Display", Georgia, serif; font-weight:500; font-size:30pt; margin:0 0 4px; }}
h2 {{ font-family: "Playfair Display", Georgia, serif; font-weight:500; font-size:16pt; margin:28px 0 10px; border-bottom:1px solid #c7b3a1; padding-bottom:6px; }}
.meta {{ color:#6b645c; font-size:10pt; }} .meta b {{ color:#0f0e0d; font-weight:600; }}
.band {{ display:flex; justify-content:space-between; align-items:flex-end; border-bottom:3px solid #0f0e0d; padding-bottom:14px; margin-bottom:18px; }}
.brand {{ font-weight:700; letter-spacing:2px; font-size:10pt; }}
table {{ width:100%; border-collapse:collapse; }} td {{ vertical-align:top; padding:10px 8px; border-bottom:1px solid #e9e3dc; }}
td.id {{ font-family: ui-monospace, Menlo, monospace; font-size:9.5pt; color:#6b645c; width:58px; }}
td.st {{ width:92px; color:#1b6b6a; font-weight:600; font-size:10pt; }} td.st small {{ color:#6b645c; font-weight:400; }}
.req {{ font-weight:500; }} .ev {{ font-family: Georgia, serif; font-size:10pt; color:#56504a; margin-top:4px; padding-left:10px; border-left:2px solid #c7b3a1; }}
.ev span {{ display:block; font-family:"DM Sans", Arial, sans-serif; font-size:8.5pt; color:#8b8276; margin-top:2px; }}
s {{ color:#8a5c45; }} ul {{ margin:6px 0 0 18px; }} .note {{ font-size:9pt; color:#6b645c; }}
.sign {{ display:flex; gap:32px; margin-top:14px; }} .sign div {{ flex:1; border-top:1px solid #0f0e0d; padding-top:6px; font-size:9.5pt; color:#56504a; }}
</style></head><body><div class="page">
<div class="band"><div><div class="brand">{html.escape(consultancy.upper())}</div>
<h1>Requirements Scope</h1><div class="meta">{html.escape(data["project_name"])}{' · ' + html.escape(client) if client else ''}</div></div>
<div class="meta" style="text-align:right">Issued {today}<br>Generated by Consult SI</div></div>
<div class="meta"><b>Based on:</b> {meeting_list} (import dates). <b>Agreed requirements:</b> {len(current)} · <b>Changes:</b> {len(superseded)} · <b>Not yet agreed:</b> {len(pending)}</div>
<h2>1. Agreed scope</h2>
<table>{''.join(rows) or '<tr><td>No agreed requirements yet.</td></tr>'}</table>
<h2>2. Change history</h2>
{('<table>' + ''.join(changes) + '</table>') if changes else '<p class="note">No agreed requirement has been replaced.</p>'}
{('<p class="note">Withdrawn requirements:</p><ul>' + withdrawn_html + '</ul>') if withdrawn else ''}
<h2>3. Not yet agreed</h2>
{('<ul>' + ''.join(pend) + '</ul>') if pend else '<p class="note">No register item is awaiting agreement. Proposals still in the review queue are not part of this scope.</p>'}
<h2>4. Sign-off</h2>
<p class="note">This document reflects recorded requirement states and transcript evidence. Review pending suggestions separately. Generating it does not record client sign-off.</p>
<div class="sign"><div>{html.escape(approver)}{', ' + html.escape(approver_role) if approver_role else ''}<br>Client</div><div>Lead consultant<br>{html.escape(consultancy)}</div><div>Date</div></div>
</div></body></html>"""


def main() -> None:
    parser = argparse.ArgumentParser(description="Export the register as a scope document (HTML).")
    parser.add_argument("--db", required=True)
    parser.add_argument("--project", required=True)
    parser.add_argument("--out", default="scope.html")
    parser.add_argument("--client", default="")
    parser.add_argument("--consultancy", default="Consult SI")
    args = parser.parse_args()
    engine = create_database_engine(args.db)
    with Session(engine) as session:
        document = build_html(session, args.project, args.client, args.consultancy)
    Path(args.out).write_text(document, encoding="utf-8")
    print(f"Wrote {args.out}")


if __name__ == "__main__":
    main()
