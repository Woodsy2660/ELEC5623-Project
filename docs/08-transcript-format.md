# 08 — Transcript format

## Overview

Transcripts pass through two stages:

1. **Authored** — human-written draft in plain text (`authored/*.txt`)
2. **Canonical** — normalised JSONL with stable turn IDs (`canonical/*.jsonl`)

Normalisation happens exactly once, at authoring time, via `src/ingest/normalise.py`.
The canonical file is frozen. Every gold evidence offset is authored against those exact bytes.

## Authored format (*.txt)

Plain text, one turn per block, separated by blank lines:

```
[Speaker Name]
Turn text goes here. May span multiple lines
as long as there are no blank lines within.

[Another Speaker]
Next turn text.
```

Speaker labels are enclosed in square brackets on their own line. Everything after
the speaker line until the next blank line (or EOF) is the turn text.

## Canonical format (*.jsonl)

One JSON object per line:

```json
{"turn_index": 0, "turn_id": "D1-M01:0000", "speaker": "Speaker Name", "text": "Turn text..."}
{"turn_index": 1, "turn_id": "D1-M01:0001", "speaker": "Another Speaker", "text": "Next turn..."}
```

### Required fields

| Field | Type | Description |
|-------|------|-------------|
| `turn_index` | int | Zero-based index, contiguous |
| `turn_id` | str | `{meeting_id}:{turn_index:04d}` |
| `speaker` | str | Exact speaker label from scenario.yaml |
| `text` | str | Turn text, normalised once at authoring |

### Normalisation rules (applied once by normalise.py)

1. Strip leading/trailing whitespace from each turn
2. Collapse internal runs of whitespace to single spaces
3. Normalise unicode to NFC
4. No other transformations

**Do not re-normalise on import.** The canonical file is byte-faithful source of truth.

## Scenario manifest (scenario.yaml)

```yaml
id: D1
name: "Client portal"
client: "Northwind Logistics"

speakers:
  - label: "Sarah Chen"
    role: "Product Owner"
    can_confirm_scope: true
  - label: "Mike Torres"
    role: "Lead Consultant"
    can_confirm_scope: false
  - label: "Jordan Kim"
    role: "Technical Lead"
    can_confirm_scope: false

meetings:
  - ordinal: 1
    title: "Initial requirements"
    canonical: "canonical/M01.jsonl"
  - ordinal: 2
    title: "Feature refinement"
    canonical: "canonical/M02.jsonl"
```

Every speaker appearing in a canonical file must be listed in `speakers`.
An unmapped speaker is a hard error that blocks import.

## Gold evidence format (gold.yaml)

```yaml
events:
  - event_index: 0
    meeting_ordinal: 1
    requirement_id: "R01"
    relation: "new"
    evidence:
      - turn_id: "D1-M01:0003"
        quote: "Users must be able to log in using their email"
```

The `quote` field is the exact substring that must appear in the turn text.
`tools/resolve_spans.py` resolves quotes to (start, end) offsets and writes `gold.yaml`
with resolved spans.
