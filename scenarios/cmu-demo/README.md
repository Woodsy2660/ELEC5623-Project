# CMU interview demo samples

Three requirements-elicitation interviews from a public CMU research dataset, prepared as local demo
fixtures. They are not part of the dev or holdout corpus, carry no gold labels, and must not be used to
report model accuracy. Scored copies with draft gold live in `scenarios/real-cmu/`.

Each interview is about a different product, so each is a separate one-meeting project. They exercise
extraction, evidence checking, retrieval and classification within a meeting. They do not exercise the
cross-meeting lifecycle, which is the project's claim.

| Folder | Project | Source interview | Turns |
|---|---|---|---:|
| `github/` | `CMU-GITHUB` | ID 11, GitHub collaboration | 111 |
| `email/` | `CMU-EMAIL` | ID 20, email client | 104 |
| `messaging/` | `CMU-MESSAGING` | ID 32, messaging app | 84 |

## Source and attribution

Source: `study1/data1/transcripts.json` in
[cmu-relab/goalgeneration](https://github.com/cmu-relab/goalgeneration). Copyright (c) 2025 Ateeq
Sharfuddin and Travis Breaux, released under the MIT License; keep that license notice with any copy.
The published text was not checked against audio.

Changes made: removed the file header, mapped `[n] Interviewer:` and `[n] Stakeholder:` turns to the
authored format, and normalised whitespace and Unicode with `src.ingest.normalise`. Spelling, disfluencies
and encoding artifacts such as `Â` are kept as published.

Neither speaker is configured to confirm scope. An interviewed user does not approve project scope, so
proposals stay pending in the review queue.

## Run

From the repository root, one fresh database per project:

```powershell
python -m src.eval.run_pipeline --scenario scenarios/cmu-demo/github --mode demo --candidate-source extracted --repeat 1 --db sqlite:///cmu-github.db
```

This calls the Azure chat model and incurs cost. Do not add these files to a scored split. Eval mode
runs without gold and auto-confirms allowed proposals, so use it only for the gold-free measurements in
`docs/14-cmu-interview-runs.md`.
