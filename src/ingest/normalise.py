"""Normalise authored transcripts to canonical JSONL format.

This script is run ONCE at authoring time to produce the frozen canonical file.
All gold evidence offsets are authored against these exact bytes.

Usage:
    python -m src.ingest.normalise scenarios/dev/D1/authored/M01.txt D1-M01 > canonical/M01.jsonl
"""

import json
import re
import sys
import unicodedata
from pathlib import Path


def normalise_text(text: str) -> str:
    """Apply normalisation rules to turn text.

    1. Strip leading/trailing whitespace
    2. Collapse internal runs of whitespace to single spaces
    3. Normalise unicode to NFC
    """
    text = text.strip()
    text = re.sub(r"\s+", " ", text)
    text = unicodedata.normalize("NFC", text)
    return text


def parse_authored_transcript(content: str) -> list[tuple[str, str]]:
    """Parse an authored transcript into (speaker, text) pairs.

    Format:
        [Speaker Name]
        Turn text which may span
        multiple lines.

        [Next Speaker]
        Next turn text.
    """
    turns: list[tuple[str, str]] = []
    lines = content.split("\n")

    current_speaker: str | None = None
    current_text_lines: list[str] = []

    for line in lines:
        # Check for speaker line
        speaker_match = re.match(r"^\[([^\]]+)\]$", line.strip())

        if speaker_match:
            # Save previous turn if exists
            if current_speaker is not None and current_text_lines:
                text = " ".join(current_text_lines)
                turns.append((current_speaker, normalise_text(text)))

            current_speaker = speaker_match.group(1)
            current_text_lines = []
        elif line.strip():
            # Non-empty line, add to current turn
            current_text_lines.append(line.strip())
        elif current_speaker is not None and current_text_lines:
            # Blank line ends the turn
            text = " ".join(current_text_lines)
            turns.append((current_speaker, normalise_text(text)))
            current_text_lines = []

    # Handle last turn if not terminated by blank line
    if current_speaker is not None and current_text_lines:
        text = " ".join(current_text_lines)
        turns.append((current_speaker, normalise_text(text)))

    return turns


def convert_to_jsonl(turns: list[tuple[str, str]], meeting_id: str) -> list[dict]:
    """Convert parsed turns to canonical JSONL records."""
    records = []
    for idx, (speaker, text) in enumerate(turns):
        record = {
            "turn_index": idx,
            "turn_id": f"{meeting_id}:{idx:04d}",
            "speaker": speaker,
            "text": text,
        }
        records.append(record)
    return records


def main() -> None:
    if len(sys.argv) < 3:
        print("Usage: python -m src.ingest.normalise <authored_file> <meeting_id>", file=sys.stderr)
        print("Example: python -m src.ingest.normalise authored/M01.txt D1-M01", file=sys.stderr)
        sys.exit(1)

    authored_path = Path(sys.argv[1])
    meeting_id = sys.argv[2]

    if not authored_path.exists():
        print(f"Error: File not found: {authored_path}", file=sys.stderr)
        sys.exit(1)

    content = authored_path.read_text(encoding="utf-8")
    turns = parse_authored_transcript(content)
    records = convert_to_jsonl(turns, meeting_id)

    for record in records:
        print(json.dumps(record, ensure_ascii=False))


if __name__ == "__main__":
    main()
