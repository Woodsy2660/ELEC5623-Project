# AGENTS.md — operating instructions for coding agents

Read this file first. Then read `docs/01-context.md` and `docs/02-architecture.md` before writing any
code.

This repository implements an assessed university experiment, not a product. The deliverable is a
measured comparison between two systems. Code exists to produce that measurement.

---

## Hard rules

These are not preferences. Violating one invalidates the experiment.

1. **The model never writes to the register.** Every write passes deterministic validation and then a
   confirmation gate (human in demo mode, gold decision file in eval mode).
2. **No orchestration framework.** No LangChain, LangGraph, LlamaIndex agents, Semantic Kernel. The
   pipeline is a fixed nine-step DAG written in plain Python.
3. **`src/engine/` imports nothing beyond the standard library.** No DB, no Azure credentials, no
   network. It must be testable with `pytest src/engine` on a machine with no secrets.
4. **Every model call is logged** to `model_calls` with prompt git hash, deployment name, temperature,
   token counts, latency, retries and cost. No exceptions, including baseline calls and retries.
5. **Gold labels never enter an inference code path.** They live in `gold_events`, joined only by
   `src/eval/score.py`. If you find yourself importing gold data into `src/classify/` or
   `src/retrieve/`, stop.
6. **Prompts are files, not string literals.** They live in `/prompts`, are referenced by path, and
   their git hash is recorded on every call.
7. **Never weaken the baseline.** It gets the same model, temperature, pinned version, transcripts and
   logger. It differs from the system under test in exactly two ways: no explicit retrieval stage, no
   deterministic transition validator.
8. **Missing, invalid and unresolved outputs are errors**, counted in primary metrics. Never silently
   drop, never repair by parsing, never substitute a default.

## Do not build

Off the table unless the team explicitly overrides after a schedule review:

- Agent frameworks, vector databases, React or FastAPI frontends, LangSmith or W&B
- Fine-tuning, custom embedding training
- Live Zoom/Teams/Fireflies integration
- Full event-sourced runtime (projections, upcasters, rebuild-on-read)
- Weighted score fusion requiring tuning on the dev split
- Any product feature not traced to an FR in `docs/03-requirements.md`

If a choice is not specified in these documents, **pick the smaller one** and note it in the PR.

## Where things are

| Need | File |
|---|---|
| Why this exists, what we claim | `docs/01-context.md` |
| Pipeline, data model, state machine, retrieval | `docs/02-architecture.md` |
| FR/NFR/constraint list and ownership | `docs/03-requirements.md` |
| E1–E8, run modes, harness, baseline, null-result protocol | `docs/04-evaluation.md` |
| Label definitions, corpus authoring protocol | `docs/05-annotation-and-corpus.md` |
| Build order, week plan, three-way split, cut list | `docs/06-build-plan.md` |
| Repo layout, code conventions, logging shape | `docs/07-conventions.md` |

## Before you open a PR

- Does every new file sit under a directory named in `docs/07-conventions.md`?
- Does every behaviour change trace to an FR or NFR ID?
- Do `src/engine/` tests still pass with no network and no `.env`?
- Did you add a row to `model_calls` for any new call site?
- Did you touch anything in the "Do not build" list?
