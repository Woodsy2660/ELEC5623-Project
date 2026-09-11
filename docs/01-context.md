# 01 — Context and claim

## The problem

Software consultants hold repeated requirements meetings with clients. Decisions made in one meeting
are revised, contradicted or reversed in a later one. A transcript preserves what was said, but a
usable requirements register must additionally connect statements across meetings and distinguish
unresolved proposals from confirmed scope.

Target failure modes:

- A statement that modifies an existing requirement is filed as a new one, so the register accumulates
  duplicates.
- A reversal is missed, so outdated scope stays in the register.
- A hedged suggestion is applied as though it were an approved decision.
- A change is matched to the wrong requirement, so the wrong feature is altered.

**Worked example.** Meeting 1 confirms "users log in by email". Meeting 2 states "we will use SSO
instead". The system should recognise both statements concern the same requirement, classify the second
as a supersession, retain the original version and its evidence, and present a proposed replacement for
confirmation. Had Meeting 2 said "could SSO be an option?", that is insufficient evidence of
replacement and must surface as unresolved.

## The claim under test

Isolating three mechanisms produces more consistent item-level lifecycle state than a strong
prompt-plus-database baseline, especially on reversals:

1. **Explicit candidate retrieval** — retrieve plausibly matching existing requirements rather than
   placing the whole register in the prompt.
2. **Constrained relationship classification** — classify the candidate-to-history relationship into a
   closed label set.
3. **Deterministic transition validation** — a non-model state engine validates every proposed
   lifecycle change before a human sees it.

We do not assume the baseline cannot produce similar outputs. **A null result on E5 accuracy is a
pre-committed acceptable outcome.** See `docs/04-evaluation.md` §Null-result protocol for what we
report instead.

## Fixed constraints

| Constraint | Value |
|---|---|
| Nature | University assessed experiment and live demo, not a product |
| Team | 3 part-time students (was 4; one withdrew Week 6) |
| Time | Weeks 6–13, approximately 8 weeks |
| Model access | Azure Microsoft Foundry / Azure for Students. Pinned version, temperature 0, structured outputs |
| Budget | Student Azure credit; hard spending cap set after pilot |
| Data | No real client data. Authored or de-identified transcripts only |
| Repeats | Three repeats of every model evaluation, mean and spread reported |
| Prompt discipline | Developed on the dev split only, frozen before holdout scoring |

The single most important consequence: **the primary deliverable is a controlled experiment.** The
system must run headless and repeatably over the full corpus, three times, with every call logged.
Anything that obscures which calls were made, at what prompt version, at what cost, is a liability.

## Related work we are positioned against

- **AI-assisted Script Management** (Singhal, Carvalho, Breaux, 2026) — tracks coverage of predefined
  interview topics using four-turn windows; generates follow-up questions. Our unit of analysis is the
  same requirement across successive meetings, not topic coverage.
- **iReDev** (Jin et al., 2026) — closest comparison. Multiple knowledge-driven agents, event-driven
  coordination, Git-backed artefact pool, human collaboration for requirements development and
  evolution. Our scope is narrower: utterance-to-requirement identity and item-level lifecycle
  transitions with evidence links. *Note: the submitted proposal states seven agents; a reviewer
  suggested six. Verify against the published tool description before repeating either figure in the
  final report. This is a report fix, not a build task.*
- **TraceLLM** (Alturayeif, Ahmad, Hassine, 2026) — pairwise trace-link prediction, binary labels. We
  predict a historical requirement ID plus a multiclass temporal relationship that drives a lifecycle
  transition.

**Commercial alternatives:** Notion AI Meeting Notes, Fireflies, Atlassian Rovo. Evidence-linked
extraction with human review already exists commercially. Our differentiation rests on cross-meeting
lifecycle behaviour, not on evidence links.

## Deviations from the submitted proposal

Recorded here so the final report can declare them rather than quietly omit them.

| Proposal said | Now | Reason |
|---|---|---|
| 4 team members | 3 | One member withdrew in Week 6 |
| 12 scenarios (4 dev / 8 holdout) | 8 scenarios (3 dev / 5 holdout) | Reduced team; balanced scenarios beat thin ones |
| ≥15 holdout examples per relationship class | Likely 8–14 for rarer classes | Follows from the scenario cut. Proposal pre-commits to reporting shortfall rather than tuning on test |
| E6: 4–6 external counterbalanced participants | Lightweight protocol, teammates plus outsiders if available | Not on critical path; sample limitation declared |
| Four relationship labels | Four *transition-driving* labels plus two utterance labels | `restatement` and `not_requirement` had nowhere to go; see `docs/05-annotation-and-corpus.md` |
