# Handover for the report — 27 October 2026

This note is for the people writing the ELEC5623 report. It describes the integration branch after the measurement harness was wired, and it separates what the code can do from what has been measured.

The repository is an assessed experiment, not a product. Read `docs/04-evaluation.md` for the metric definitions this file relies on. Where an older document disagrees with this file about D1 or about whether a live number exists, use this file.

## Status

The pipeline can run a development scenario from gold candidates through retrieval, classification, the rule table, and the state engine, and `score.py` can write a dev-split score file. The strong baseline can do the same comparison with its two required differences. None of that has been executed against the live model.

There is no oracle number, no extracted number, and no baseline number. Do not put an F1, a recall, a cost, or a latency in the results section until `runs/<run_id>/score.json` exists for that run. A unit test that stubs the classifier is not a result.

## What the report can say now

- The system under test is a fixed pipeline. The model proposes. A deterministic engine in `src/engine/` decides whether a transition is legal. The model never writes the register.
- Two run modes share that pipeline after the candidate exists. `eval` can take gold candidates or extracted candidates. `demo` is the review UI, and it still reads in-memory fixtures.
- Gold-candidate injection is the oracle. It exists so extraction error is not reported as matching failure. The quantity the method section should name is E3-oracle minus E3-pipeline.
- The headline metric is four-class macro-F1 over `new`, `refinement`, `contradiction`, and `supersession`. Six-class macro-F1, which also includes `restatement` and `not_requirement`, is secondary. Classes with support 0 are excluded from the mean and named. Do not switch denominators silently.
- The comparison system is a strong baseline: same model, deployment, temperature, seed, transcripts, logger, and gold decision sequence. It differs in exactly two ways. It sees the whole register in the prompt, and it writes the parsed change without the transition validator.
- If end-of-meeting state accuracy does not separate the two systems, the report leads with the null-result protocol already written in `docs/04-evaluation.md` and stored on every score file. That framing was fixed before any measured run.

## What the report must not say

- Do not say the system has been evaluated, or that it meets the proposal targets (extraction F1 ≥ 0.80, retrieval recall ≥ 0.90, historical-id accuracy ≥ 0.85, macro-F1 ≥ 0.80, and the E5 and E8 targets). Those targets are the bar. They are not results.
- Do not say meeting 2 supersedes R01. It does not.
- Do not say D1 event 9 is a hedge that lands in `contradicted`. Event 9 is a refinement of R07. D1 has no contradicted requirement and no hedge flag.
- Do not say the system was scored on eight scenarios, three meetings each, or on a holdout. Only `scenarios/dev/D1` can be scored. It has two meetings and 14 gold events.
- Do not say Ablation A or Ablation B was run. Neither runner exists. `docs/04` calls Ablation A the honest test at this register size, because the whole register fits in the prompt. The report should say that comparison is outstanding.
- Do not say three repeats were run. The protocol asks for three. The next run is one repeat. Repeat variance is therefore not yet a result, even though the null-result protocol lists it.
- Do not treat a system requirement id as a copy of the gold id. The pipeline allocates `R01`, `R02`, and so on. The scorer maps gold ids to system ids through the aligned `new` events. A missed `new` shifts later ids, and historical-id accuracy uses the map.
- Do not describe the hosted UI as running this pipeline. The API still serves `src/api/fixtures.py`. Confirm and reject in the UI do not write SQLite.

## The system the method section can describe

```
transcript → ingest → extract (LLM-1) → evidence check
          → hybrid retrieve → classify (LLM-2) → proposal rules
          → state engine → human or gold confirm → one SQLite commit
```

Gold mode replaces only the extract step. From retrieval onward the two modes are the same function, `_process_candidate` in `src/eval/run_pipeline.py`.

The classifier receives a speaker label. It does not receive `can_confirm_scope`, and it does not infer authority from the text. After classification, the rule table reads that flag from the `speakers` table. An unmapped speaker cannot confirm scope. There is no default of true.

A supersession whose model output says `replacement_stated` is false is downgraded to contradiction before the rule table. The downgrade is counted. The rationale is that a wrong contradiction leaves agreed scope in place, and a wrong supersession would replace it. Under eval mode, with no confirm/reject column, an allowed contradiction is then applied. A gold `reject` would block a write. A gold `confirm` cannot force a write the engine rejected. D1 has no `event_action` column, so eval applies every engine-allowed proposal. `Supersede` in `docs/05` is a lifecycle name, not a human-gate decision. Only the exact strings `confirm` and `reject` are gate actions.

A `new` item is created as `proposed` and then confirmed in place. That second step does not write another version or another embedding. Later meetings therefore see confirmed scope, and version numbers are not inflated. `refinement` and `supersession` write one new version. `contradiction` writes one new version in state `contradicted`. `restatement` and `not_requirement` do not change the register. Rejected, unresolved, and failed calls still write a proposal row so they stay in the denominator.

Each candidate is committed before the next one starts. That matters inside a meeting: D1's password requirement is introduced and refined in meeting 1, and the refinement has to be able to retrieve the row just created.

States and the legal transitions are only in `src/engine/state_machine.py`:

| From | Event | To |
|---|---|---|
| (none) | create | proposed |
| proposed | confirm | confirmed |
| proposed | reject | withdrawn |
| confirmed | refine | confirmed |
| confirmed | contradict | contradicted |
| confirmed | supersede | superseded |
| contradicted | supersede | superseded |
| contradicted | resolve | confirmed |

Supersession keeps the family. The new text is a new version of the same requirement. Older versions stay in the table so retrieval can still see them.

Retrieval is hybrid. BM25 and dense cosine are fused with reciprocal rank fusion, k = 60, operating top-k 5. The proposal row stores the full BM25, dense, and fused rankings, so the scorer can report recall at 3, 5, and 8 on each channel. A query whose encoder model, version, or dimension disagrees with a stored vector raises. A 1536-dimensional vector is never cosine-scored against a 384-dimensional one. An empty register is legal. The classifier's id enum is then only null.

Failures stay failures. Schema-invalid classifier output is retried once, then recorded as an error proposal. It is not repaired into a legal label. Transport errors are already retried once inside the logger and are not retried again. Every chat call goes through `src/logging/calls.py`. The only `embeddings.create` call is there too. Local encodes are logged as stage `embed` with cost 0.

## How a finished run is scored

`python -m src.eval.score --run <run_id> --db <sqlite url>` writes `runs/<run_id>/score.json` and prints a summary. `runs/` is gitignored. Copy the file into the report appendix when it exists. The report's `split` field will say `dev` for a path under `scenarios/dev`. Gold candidates are labelled column `oracle`. Extracted candidates are labelled column `pipeline`. The baseline keeps the column name `baseline`.

Only `src/eval/score.py` reads gold `relation`, gold requirement id, and expected state. The runners may read statement text, evidence spans, and an optional confirm/reject action. `src/eval/ingest_scenario.py` still raises `NotImplementedError`. The pipeline loads the scenario itself. Do not cite that script as a working step.

Alignment for extraction is evidence-span overlap on the same turn. It is not text similarity. A gold event with no overlapping prediction is a miss. A prediction with no gold event is spurious. Both stay visible. E2 is computed only for an extracted run. Oracle and baseline runs record E2 as skipped.

E3 reports, with support beside each figure:

- Retrieval recall at 3, 5, and 8, separately for dense-only, BM25-only, and fused. The denominator is gold events whose relation is historical: refinement, contradiction, supersession, restatement. The expected id is the mapped system id. If that family was never created, the event stays a miss.
- Historical-id accuracy on those same events.
- No-match accuracy and no-match precision as two numbers. No-match gold is `new` or `not_requirement`. Accuracy asks whether the prediction named no id. Precision asks, among non-error predictions that named no id, how many were those gold relations.
- Relation macro-F1, the full confusion matrix, and per-class support. The headline is the four driving classes. Six-class is secondary.
- Joint accuracy: the right id and the right label together. For `new`, the right id is null. Errors and unaligned gold count as incorrect.

On D1 the gold support inside the four headline classes is new 8, refinement 4, contradiction 0, supersession 2. Contradiction will be listed under `four_class_excluded_zero_support` and left out of the mean. The printed headline can still say four-class. The report must say that D1 gives that class no gold instances, so the mean is over the classes that have support. False predictions of contradiction still appear in the confusion matrix. They do not, by themselves, pull a zero-support class back into the mean.

E4 walks the event log through `validate_transition`. The pipeline's illegal-transition rate should be 0 because illegal proposals are not written. The baseline can be non-zero because it writes with enforcement off. Measure both. Do not argue the pipeline rate from the code and skip the measurement.

E5 replays each meeting cutoff and compares every gold requirement's version and state with the state implied by the gold relations. D1 has no `expected_state_after` field. The scorer derives the expected register by replaying those relations through the same transition table. A file that does contain `expected_state_after` overrides that derivation. The derived D1 register is in the next section. Reversal final-state accuracy covers requirements whose final expected state differs from the state at the end of the meeting that introduced them, or whose final state is contradicted or superseded. On D1 those requirements are R05 and R06.

False supersession is a predicted supersession where the gold relation is not supersession, over the non-supersession gold events. The score also counts model labels that were supersession before the soft downgrade. D1 has no hedge flag. Say that. This rate is not a hedge-only rate.

E8 is summed from `model_calls`: calls by stage, tokens, retries, cost, and latency percentiles. A missing figure means the logger missed a call, not that the call was free.

The null-result paragraph stored in every score file is:

> If E5 accuracy does not separate the systems, lead with illegal-transition rate (structurally 0 for the pipeline), invented-id rate (0 by construction for the pipeline), repeat variance, false-supersession on hedges, and tokens and cost as the register grows. This framing was fixed before the measured runs.

Invented-id rate counts a historical prediction whose id was not in the offered list. The pipeline builds that list into the classifier schema, so its rate should be 0. New ids are allocated by the store and are not counted as invented. The baseline records the register ids that existed before each change and can be non-zero.

## D1, the only scorable scenario

Path: `scenarios/dev/D1`. Client portal for Northwind Logistics. Speakers in `scenario.yaml`:

| Speaker | Role | Can confirm scope |
|---|---|---|
| Sarah Chen | Product Owner | yes |
| Mike Torres | Lead Consultant | no |
| Jordan Kim | Technical Lead | no |

Meetings: `D1-M01` "Initial requirements", `D1-M02` "Feature refinement". Canonical JSONL is in `canonical/`. Gold is `gold.yaml`. Fields on each event are `event_index`, `meeting_ordinal`, `requirement_id`, `relation`, and `evidence` with `turn_id`, `quote`, `start`, and `end`. There is no statement field, no `event_action`, and no `expected_state_after`.

| Index | Meeting | Gold id | Relation | What the quote decides |
|---|---|---|---|---|
| 0 | 1 | R01 | new | Email-and-password login |
| 1 | 1 | R02 | new | Password of at least eight characters, with a number |
| 2 | 1 | R02 | refinement | Password must also include a special character |
| 3 | 1 | R03 | new | Dashboard of recent orders and pending shipments |
| 4 | 1 | R04 | new | Important notifications on the dashboard |
| 5 | 1 | R05 | new | In-app notifications are sufficient for now |
| 6 | 1 | R06 | new | Session expires after thirty minutes |
| 7 | 2 | R06 | supersession | Change the timeout to sixty minutes |
| 8 | 2 | R07 | new | Add two-factor authentication |
| 9 | 2 | R07 | refinement | Two-factor authentication is mandatory for all users |
| 10 | 2 | R03 | refinement | Dashboard also shows account balance |
| 11 | 2 | R05 | supersession | Email notifications as well as in-app |
| 12 | 2 | R08 | new | Export order history as a PDF |
| 13 | 2 | R08 | refinement | PDF includes date, items, quantities, and totals |

If a run matched every gold label and eval confirmed each `new`, the register after meeting 2 would be:

| Gold id | Text the family ends on | State | Version |
|---|---|---|---|
| R01 | Email-and-password login | confirmed | 1 |
| R02 | Password with a special character | confirmed | 2 |
| R03 | Dashboard including account balance | confirmed | 2 |
| R04 | Notifications on the dashboard | confirmed | 1 |
| R05 | Email plus in-app notifications | superseded | 2 |
| R06 | Sixty-minute session | superseded | 2 |
| R07 | Mandatory two-factor authentication | confirmed | 2 |
| R08 | PDF export with the table fields | confirmed | 2 |

R01 is unchanged in meeting 2. Nothing in D1 is contradicted. This table is the gold-derived expectation inside the scorer. It is not an observation of the model.

The other scenario directories are not usable for a result. `scenarios/dev/D2` is a README and a draft sequence, with no transcript. D3 is absent. `scenarios/holdout`, `scenarios/dev-adversarial`, and `scenarios/holdout-adversarial` are empty. Holdout gold stays unread until the prompts are frozen. The prompts are not frozen: `prompts/classify_v1.txt` gained a required `replacement_stated` field in this push, so its git blob hash is a new series. There is no earlier scored classify run to invalidate.

## Models, encoder, and logging

Resource `Consulting-Agent-System`, resource group `Consultant-Agent`, Australia East, Azure for Students. The unused account `Consulting-open-ai` is in the same group. Details and the pin rationale are in `docs/09-model-deployment.md`.

| Deployment | Model | Version | SKU | Capacity | Upgrade |
|---|---|---|---|---|---|
| `cia-chat` | `gpt-4o` | `2024-11-20` | GlobalStandard | 50 | `NoAutoUpgrade` |
| `cia-embed` | `text-embedding-3-small` | `1` | GlobalStandard | 50 | `NoAutoUpgrade` |

`gpt-6.1-sol` version `2026-09-29` is an older deployment on the same resource, capacity 500, upgrade `OnceNewDefaultVersionAvailable`. It is not the experiment. Do not repoint it and do not change its upgrade policy.

Client pin: API version `2024-10-21`, temperature 0, seed 42, chat deployment `cia-chat`. Endpoint `https://consulting-agent-system.openai.azure.com/`. The key lives only in `.env`, which is gitignored. Do not paste it into the report, the chat, or a commit.

The active dense encoder is local MiniLM, not `cia-embed`:

| Field | Value |
|---|---|
| Model | `sentence-transformers/all-MiniLM-L6-v2` |
| Revision | `1110a243fdf4706b3f48f1d95db1a4f5529b4d41` |
| Dimensions | 384 |
| Device | CPU |
| Config | `src/retrieve/model_config.json`, `encoder_role` = `active` |

Track B had not measured recall@k on an authored scenario. Switching the scorer to the 1536-dimensional Foundry embedding would not repair a measured failure, and it would make a later comparison with the local encoder impossible. `CIA_ENCODER` defaults to `local`. `azure` selects `cia-embed`. The Azure comparison is a second oracle run on the same gold candidates after the local oracle exists. It is not a substitute for installing MiniLM.

Rates used by the logger, per 1M tokens, from `src/llm/config.py`: gpt-4o / `cia-chat` at $2.50 input and $10 output; `text-embedding-3-small` / `cia-embed` at $0.02 input and $0 output. Local MiniLM encodes are logged at cost 0. The pricing table in `docs/09-model-deployment.md` does not yet list the embedding rate. Use `config.py` for the report.

A schema smoke on 26 October 2026, which is not an evaluation, showed that Azure strict `json_schema` accepts the classifier's nullable id enum, including an enum of only null when the register is empty. The served chat model was `gpt-4o-2024-11-20`. One embedding call returned 1536 dimensions. Do not cite either call as E3 or E8.

Role assignments for `danyang@uni.sydney.edu.au` and `lucas@uni.sydney.edu.au` have not been made. Until someone with access grants Cognitive Services OpenAI User and Azure AI Developer on this resource, those accounts cannot call the deployments. The grants were left undone on purpose.

## What this push contains

The gold path used to copy `relation` and the gold requirement id into the engine and skip retrieval and the classifier. That replayed the answer key. It now copies statement text and evidence only. Both candidate sources then retrieve, classify, assess, and commit.

New or rewritten for that path:

| Piece | Where |
|---|---|
| Classifier call, one retry, soft downgrade | `src/classify/classify.py`, prompt `prompts/classify_v1.txt` |
| Encoder protocol. Local is the default. Azure is optional | `src/retrieve/embedder.py` |
| Register write and in-place confirm | `src/persist/register.py` |
| Gold candidate builder | `src/eval/gold_candidates.py` |
| Shared pipeline | `src/eval/run_pipeline.py` |
| Metric functions | `src/eval/metrics.py` |
| `score.py --run` | `src/eval/score.py` |
| Strong baseline | `src/eval/run_baseline.py`, prompt `prompts/baseline_v1.txt` |
| Measurement tests, no network and no MiniLM | `tests/test_measurement.py` |

`requirement_versions` now stores `embedding_model`, `embedding_version`, and `embedding_dim`. A pipeline write with enforcement on must supply a vector and that identity. The baseline write uses enforcement off, so an illegal transition is stored and can be counted. Proposals store `rankings_json`, `decision`, and `downgraded`. Gold candidates store a null extract-call id, so an oracle run has no `model_calls` row with stage `extract`.

The tests that lock the report-facing behaviour:

- A supersession with `replacement_stated` false becomes contradiction and keeps the model's original label beside it. A true flag stays supersession. Invalid JSON is retried once and then recorded. A transport error is not given a second retry.
- A gold event that carries a relation, a requirement id, and `event_action: Supersede` produces a candidate whose text is the quote or statement and whose gate action is empty.
- On the real D1 file, with a fake embedder and a classifier that always says `new`, the run writes 14 proposals, 14 confirmed families, encoder identity on every version, no extract-stage call, and a later ranking that still contains R01. The score file is dev-split, column oracle, E2 skipped, E4 rate 0. Meeting-2 state accuracy is not 1, because the stub labelled everything `new`. That run is a wiring test. Its F1 is not the system's F1.
- The same D1 expected-register table above is asserted from the gold file.
- A baseline responder that supersedes a nonexistent R99 is scored with illegal-transition rate 1 and invented-id rate 1.
- No pipeline module reads gold labels. No chat or embedding SDK call sits under `src/` outside `src/logging/`.

The last full `pytest` run in this worktree, before this handover, was 238 passed and 1 failed. The failure is `tests/test_hosted.py::test_vercel_entrypoint_serves_the_prefixed_api`, because `web/dist` does not exist. That directory is gitignored and this work did not build the frontend. The hosted test that points static files at a temporary directory passed. Use `.venv` and Python 3.11. The Anaconda interpreter on this machine does not have the project dependencies.

## What is still open

Do these in order. The first block is what the results section is waiting on.

1. Finish the local encoder on a machine that will run the eval. CPU `torch==2.8.0` is specified in `requirements-retrieval.txt` and should be installed from the PyTorch CPU index, then `sentence-transformers==5.1.1`, `transformers==4.56.2`, `numpy==2.2.6`, and `huggingface-hub==0.34.4`. On the machine that made this commit, torch had installed and the sentence-transformers install was still running. Do not start a second pip into the same `.venv` while that one is running. MiniLM weights are not in `.venv/embedding-cache`. The Hugging Face cache on that machine has a GPT-2 snapshot, which this encoder cannot use. After the packages import, run `python -m src.retrieve.prepare_model`. Leave `CIA_ENCODER` unset.
2. Oracle run on a fresh database, one repeat, then score it. Check that `model_calls` has stage `classify` and no stage `extract`, that every version has encoder identity, and that every proposal has a non-empty retrieved-id list. Meeting 2's fused ranking should be able to see meeting 1 families, including R01. Do not fail the run because R01 was not superseded.
3. Extracted run on a second fresh database, then score it. E3-oracle minus E3-pipeline is the number the report should quote for the cost of extraction.
4. Baseline run on a third fresh database, with no test responder, then score it. Compare E4, invented-id rate, false supersession, and E8. If E5 does not separate them, lead with the null-result protocol and say which of its terms D1 cannot support. Hedges are one of those terms. Repeat variance is another until repeats 2 and 3 exist.
5. Only after the local oracle number exists, repeat that oracle with `CIA_ENCODER=azure` and compare dense-only recall. Do not change the default.
6. If the clock allows it after the three scored runs, connect confirm and reject to `src/persist/register.py`. That is the demo behaviour that has to be the same decision as eval. The API still applies decisions to the fixture store in `src/api/decisions.py`.

Cut, in this order, if the deadline arrives first: repeats beyond one, any scenario other than D1, speaker-settings and project-delete routes, then import and export routes. A dev-split oracle, an extracted run, a real baseline, and an honest limitations section is a better report than a wider evaluation that did not finish.

Still absent after that, and worth a limitations paragraph even if the numbers land:

- Ablation A (full register in the prompt, engine on) and Ablation B are not implemented. At D1's size the register fits in the prompt, so a retrieval win is not yet evidenced.
- E1 register integrity, E6 review-task completion, and E7 deletion and project-separation checks are not scored here. E6 needs people. E7's delete-with-cascade, including embedding blobs, has no route.
- The React Import button is disabled. There is no `POST /projects/{id}/import` and no `parse_transcript`. `import_meeting()` can already load the authored canonical files, which is what the eval runner uses. There is no `GET /projects/{id}/export` route. `src/export/register.py` has the export function.
- Speaker assignment through settings is not wired. An unmapped speaker must eventually block import. Authority stays configuration.
- `DELETE /projects/{id}` is not wired.
- Live meeting capture is out of scope. The capture screen, if it is shown, has to be labelled a replay of a stored transcript.
- `docs/11-remaining-implementation.md` is not the task list for this push. Its API steps are still the open demo work. Its overview, which treats the eval harness as already connected, is out of date. `README.md` used to tell people to run `ingest_scenario` without a scenario path. That command raises. The README quickstart now matches the commands below.
- `src/eval/replay_to_cutoff.py` still rebuilds gold state on its own. The scorer does not use it. Do not import it from the pipeline.
- `Requirement.id` is a global primary key. Put one scenario in each SQLite file. `create_all` is not a migration. An old `pipeline.db` from before the new columns will fail. Pass a new `--db`.
- Extracted candidate ids do not include the run id. A second extracted run in the same database can collide. Gold candidate ids include an eight-character run prefix. Use a fresh file per run anyway.
- `openai` and `jinja2` are installed in `.venv` and are not pinned in `requirements.txt`. Retrieval packages are pinned in `requirements-retrieval.txt`.

## How to produce the first numbers

From the repository root, with `.env` filled and the local encoder installed. Create the database directory first if you pass a `runs/` URL. SQLite will not create parent directories. `runs/` itself is gitignored, so the score file still has to be copied out by hand.

```bash
python -m src.retrieve.prepare_model

python -m src.eval.run_pipeline --scenario scenarios/dev/D1 --mode eval --candidate-source gold --repeat 1 --db sqlite:///runs/d1-oracle.db
python -m src.eval.score --run <run_id> --scenario scenarios/dev/D1 --db sqlite:///runs/d1-oracle.db

python -m src.eval.run_pipeline --scenario scenarios/dev/D1 --mode eval --candidate-source extracted --repeat 1 --db sqlite:///runs/d1-extracted.db
python -m src.eval.score --run <run_id> --scenario scenarios/dev/D1 --db sqlite:///runs/d1-extracted.db

python -m src.eval.run_baseline --scenario scenarios/dev/D1 --mode eval --repeat 1 --db sqlite:///runs/d1-baseline.db
python -m src.eval.score --run <run_id> --scenario scenarios/dev/D1 --db sqlite:///runs/d1-baseline.db
```

The pipeline and the baseline load `.env` without printing it. `get_deployment_config` does not load that file on its own. On Windows the interpreter is `.venv\Scripts\python.exe`. Chain shell commands with `;`, not `&&`, if the shell is Windows PowerShell 5.

Each command prints a run id. Put that id in the matching score command. The score command prints the headline, the per-class support, the excluded classes, both recall channels' cutoffs, the id and no-match figures, E4, E5 by meeting, false supersession, invented-id rate, E8, and the null-result paragraph.

## Suggested shape for the results section

Write the method from `docs/04-evaluation.md` and from the sections above. Then one table per scored run, taken from `score.json`, with support in the same row as the metric. Under it, one sentence for E3-oracle minus E3-pipeline on the headline and on retrieval recall. Then the baseline comparison, led by whichever of E5 or the null-result list the numbers actually support. Close with the limitations in "What is still open", including the empty corpus, the missing ablations, the single repeat, and the fact that contradiction has no gold support on D1.

Until those JSON files exist, the results section should say that the harness is in place and the measured runs have not been started.
