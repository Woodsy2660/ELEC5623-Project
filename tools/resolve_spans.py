#!/usr/bin/env python3
"""Resolve evidence quotes to character offsets for gold authoring.

This tool reads gold.src.yaml (with human-authored quotes) and canonical JSONL files,
resolves each quote to (start, end) offsets, and writes gold.yaml with resolved spans.

Usage:
    python tools/resolve_spans.py scenarios/dev/D1

The tool expects:
    - scenarios/dev/D1/gold.src.yaml  (input: quotes only)
    - scenarios/dev/D1/canonical/*.jsonl (canonical transcripts)
    - scenarios/dev/D1/gold.yaml (output: resolved spans)

Gold authoring and runtime extraction resolve evidence through the SAME function
(src.validate.resolve.resolve_quote), ensuring comparability.
"""

import json
import sys
from pathlib import Path

import yaml

# Import the shared resolution logic from src/validate
from src.validate.resolve import QuoteAmbiguous, QuoteNotFound, resolve_quote


def load_canonical_turns(scenario_dir: Path) -> dict[str, str]:
    """Load all turns from canonical JSONL files.

    Returns:
        Mapping of turn_id to turn text.
    """
    turns: dict[str, str] = {}
    canonical_dir = scenario_dir / "canonical"

    for jsonl_path in sorted(canonical_dir.glob("*.jsonl")):
        with open(jsonl_path, encoding="utf-8") as f:
            for line in f:
                if line.strip():
                    record = json.loads(line)
                    turns[record["turn_id"]] = record["text"]

    return turns


def resolve_gold_spans(scenario_dir: Path) -> dict:
    """Resolve quotes in gold.src.yaml to spans in gold.yaml.

    Args:
        scenario_dir: Path to scenario directory (e.g., scenarios/dev/D1).

    Returns:
        The gold data with resolved spans.

    Raises:
        QuoteNotFound: If a quote cannot be found.
        QuoteAmbiguous: If a quote appears multiple times.
    """
    gold_src_path = scenario_dir / "gold.src.yaml"
    if not gold_src_path.exists():
        raise FileNotFoundError(f"Gold source file not found: {gold_src_path}")

    with open(gold_src_path, encoding="utf-8") as f:
        gold_data = yaml.safe_load(f)

    turns = load_canonical_turns(scenario_dir)

    # Resolve each evidence quote
    for event in gold_data.get("events", []):
        for evidence in event.get("evidence", []):
            turn_id = evidence["turn_id"]
            quote = evidence["quote"]

            if turn_id not in turns:
                raise ValueError(f"Unknown turn_id in gold: {turn_id}")

            turn_text = turns[turn_id]
            start, end = resolve_quote(turn_text, quote)

            # Add resolved span to evidence
            evidence["start"] = start
            evidence["end"] = end

    return gold_data


def main() -> None:
    if len(sys.argv) < 2:
        print("Usage: python tools/resolve_spans.py <scenario_dir>", file=sys.stderr)
        print("Example: python tools/resolve_spans.py scenarios/dev/D1", file=sys.stderr)
        sys.exit(1)

    scenario_dir = Path(sys.argv[1])

    if not scenario_dir.is_dir():
        print(f"Error: Not a directory: {scenario_dir}", file=sys.stderr)
        sys.exit(1)

    try:
        gold_data = resolve_gold_spans(scenario_dir)
    except (QuoteNotFound, QuoteAmbiguous) as e:
        print(f"Error resolving quote: {e}", file=sys.stderr)
        sys.exit(1)
    except Exception as e:
        print(f"Error: {e}", file=sys.stderr)
        sys.exit(1)

    gold_path = scenario_dir / "gold.yaml"
    with open(gold_path, "w", encoding="utf-8") as f:
        yaml.dump(gold_data, f, default_flow_style=False, allow_unicode=True, sort_keys=False)

    print(f"Wrote resolved gold file: {gold_path}")

    # Report statistics
    event_count = len(gold_data.get("events", []))
    evidence_count = sum(
        len(event.get("evidence", [])) for event in gold_data.get("events", [])
    )
    print(f"Resolved {evidence_count} evidence spans across {event_count} events.")


if __name__ == "__main__":
    main()
