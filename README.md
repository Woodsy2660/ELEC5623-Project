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

## Team

| Track | Owner |
|---|---|
| A — Ingestion, extraction, evidence, export | Benjamin Wood |
| B — Retrieval, matching, classification | Danyang |
| C — State engine, persistence, review, logging | *(fill in)* |

## Quickstart

```bash
python -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt
cp .env.example .env        # add your Azure Foundry deployment details

# The state engine runs with no credentials and no database:
pytest src/engine

# Load a development scenario and score one metric:
python -m src.eval.ingest_scenario --scenario scenarios/dev/D1
python -m src.eval.run_pipeline --mode eval --candidate-source gold --repeat 1
python -m src.eval.score --run <run_id>
```

## Pipeline

```
transcript → ingest → extract (LLM) → validate evidence → retrieve (hybrid)
          → classify (LLM) → propose event → state engine → confirm → commit
```

Deterministic stages enforce what must not depend on model behaviour. Generative stages interpret
language. The model has no write access to the register.
