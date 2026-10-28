# Consulting Intelligence Agent

ELEC5623 Applied Generative AI in Engineering — University of Sydney, Semester 2 2026, Group 18.

Evidence-grounded, cross-meeting requirement matching and lifecycle reasoning. The system ingests
consultant–client meeting transcripts and maintains a versioned requirements register in which every
change is linked to its transcript evidence, validated against an explicit state machine, and confirmed
by a human before it alters agreed scope.

**This repository is an assessed experiment, not a product.** Its purpose is to produce a measured
comparison between this pipeline and a strong prompt-plus-database baseline.

## Documentation

Coding agents: read `AGENTS.md` first.

| | |
|---|---|
| [`AGENTS.md`](AGENTS.md) | Hard rules, what not to build |
| [`docs/01-context.md`](docs/01-context.md) | Problem, claim under test, constraints, deviations from proposal |
| [`docs/02-architecture.md`](docs/02-architecture.md) | Pipeline, data model, state machine, retrieval |
| [`docs/03-requirements.md`](docs/03-requirements.md) | FR/NFR/constraints, ownership, traceability |
| [`docs/04-evaluation.md`](docs/04-evaluation.md) | E1–E8, run modes, baseline, null-result protocol |
| [`docs/05-annotation-and-corpus.md`](docs/05-annotation-and-corpus.md) | Label definitions, authoring protocol |
| [`docs/06-build-plan.md`](docs/06-build-plan.md) | Build order, schedule, three-way split, cut list |
| [`docs/07-conventions.md`](docs/07-conventions.md) | Repo layout, code conventions, logging |
| [`docs/11-remaining-implementation.md`](docs/11-remaining-implementation.md) | Current implementation status against Ben's draft |
| [`docs/12-track-c-review.md`](docs/12-track-c-review.md) | SQLite review setup, behavior, validation and remaining work |
| [`handover.md`](handover.md) | 27 Oct 2026 status for the report: what is wired, what is unmeasured, what D1 contains |

## Team

| Track | Owner |
|---|---|
| A — Ingestion, extraction, evidence, export | Benjamin Wood |
| B — Retrieval, matching, classification | Danyang |
| C — State engine, persistence, review, logging | Lucas |

## Quickstart

For the local human-review demo on Windows, follow the step-by-step instructions in
[`docs/12-track-c-review.md`](docs/12-track-c-review.md#local-demo-on-windows-powershell).
A fresh clone does not include a SQLite database: `*.db` files are local and ignored by
Git. To create a new D1 review queue, install the pinned local embedding model and run
the demo pipeline with an Azure OpenAI chat key. Reviewing proposals already present in
a database does not call Azure and does not need that key.

The browser's **Reviewer access** field takes the same `REVIEWER_TOKEN` value configured
for the local API. This is a shared local-demo write token, not a user account. Keep the
API bound to localhost and never put the Azure key in the browser or a `VITE_*` variable.
The detailed guide covers setup, pipeline generation, API and UI startup, and review.
Do not use eval mode as the interactive demo: its missing-decision behavior is being
reconciled with the project's gold-decision gate requirement.

```bash
# The deterministic state engine runs without credentials or a database:
pytest src/engine
```

## Pipeline

```
transcript → ingest → extract (LLM) → validate evidence → retrieve (hybrid)
          → classify (LLM) → propose event → state engine → confirm → commit
```

Deterministic stages enforce what must not depend on model behaviour. Generative stages interpret
language. The model has no write access to the register.
