# 02 — Architecture

## Runtime pipeline

Fixed nine-step DAG. Two generative stages, one gate. No agent loop, no tool-calling into the database.

```
transcript file
  → [D] Ingest: turns with stable IDs                    → turn_store        FR04
  → [G] LLM-1: extract atomic candidates + evidence spans                    FR05
  → [D] Evidence validator: substring resolve or reject                      FR06
  → [D] Hybrid retrieve top-k families from versioned corpus                 FR10
  → [G] LLM-2: classify {requirement_id|no_match, relation, rationale}       FR07/08
  → [D] Map (relation, current_state) → proposed event
  → [D] State engine: validate transition                                    FR11
  → [H/G] Confirm / edit / reject                                            FR01/02/03
  → [D] One transaction: insert event + new version + update current row     FR09
  → updated corpus feeds the next meeting
```

`[D]` deterministic · `[G]` generative · `[H/G]` human in demo mode, gold decision file in eval mode.

The two LLM calls are deliberately separate so extraction quality and matching quality can be measured
independently (E2 vs E3). This roughly doubles cost; the justification is the measurement, and it only
holds if E3-oracle is actually run. See `docs/04-evaluation.md`.

## Persistence: events **and** current rows

Not full event sourcing. Two stores written in the same SQLite transaction:

- `events` — append-only, immutable. Source of audit and of E5 cutoff replay.
- `requirements_current` — denormalised current rows. Read by Streamlit and retrieval.

**Replay is an evaluation-harness operation, not a live read path.** The running system never rebuilds
state by replaying events. `src/eval/replay_to_cutoff.py` does, for E5.

### Schema

```
projects(id, name, created_at)
meetings(id, project_id, ordinal, source_hash, imported_at)
turns(id, meeting_id, turn_index, speaker, text)
speakers(project_id, speaker_label, role, can_confirm_scope)   -- see Authority below

requirements(id, project_id)                                    -- stable family ID
requirement_versions(id, requirement_id, version, text, state,
                     evidence_json, embedding_blob, created_event_id)
requirements_current(requirement_id, current_version_id, state, text)

candidates(id, meeting_id, run_id, text_norm, evidence_json, extract_call_id)
proposals(id, run_id, candidate_id, retrieved_ids_json, predicted_id,
          predicted_relation, proposed_event, engine_verdict)
events(id, project_id, ts, actor, event_type, payload_json, run_id)   -- append only

runs(id, mode, candidate_source, repeat_index, prompt_hash,
     model_deployment, temp, started_at, notes)
model_calls(id, run_id, stage, prompt_hash, input_tokens, output_tokens,
            latency_ms, retries, cost, raw_json_path)

gold_events(scenario_id, meeting_ordinal, event_index, ...)      -- SEPARATE. Scoring only.
```

**`gold_events` is a separate table and is never joined in an inference path.** Only
`src/eval/score.py` reads it.

**Embeddings are written on version creation**, inside the same transaction as the event and current-row
write. There is no separate indexing step and no eventual consistency.

**Ingest is idempotent**: `(project_id, source_hash)` short-circuits re-import. Test this (E1).

**Deletion (NFR03)** is a project-scoped cascade including embedding blobs. Test it (E7).

## Requirement lifecycle state machine

`src/engine/`. Pure functions, standard library only, no I/O.

| From | Event | To |
|---|---|---|
| — | Create | Proposed |
| Proposed | Confirm | Confirmed |
| Proposed | Reject | Withdrawn |
| Confirmed | Refine | Confirmed (new version) |
| Confirmed | Contradict | Contradicted |
| Confirmed or Contradicted | Supersede | Superseded |
| Contradicted | Resolve | Confirmed |

Unlisted transitions → engine rejects, register unchanged, rejection logged.

**No-ops** (do not invent new confirmed states):

- `restatement` → no state change; optional `Noted` event for audit.
- `not_requirement` → candidate never reaches the register; counted in coverage, not as a lifecycle
  event.

**Hedge protection.** A classifier that wrongly labels a hedge `supersession` must still fail the rule
table. The guard: `Supersede` is only emitted when the evidence turn's speaker has
`can_confirm_scope = true` **and** the utterance states a replacement. Otherwise the proposal is
`unresolved`.

### Speaker authority

The rule above is unimplementable without a definition of authority, and the proposal explicitly states
that a speaker name or confident tone does not establish it. Therefore:

Authority is **per-project configuration**, loaded at scenario-ingest time into `speakers`. Each speaker
label maps to a role and a boolean `can_confirm_scope`. Typically the client representative and product
owner are true; consultants and observers are false. The classifier receives the speaker label; the rule
table reads the flag. Neither infers authority from text.

## Retrieval (FR10)

**The retrieval corpus is every retained version in the project** — including `contradicted`,
`superseded` and `withdrawn` rows. Indexing only current heads manufactures false `new` labels exactly
on the cross-meeting reference cases E5 exists to score (Meeting 3 referring to Meeting 1 wording that
Meeting 2 superseded).

Per candidate:

1. BM25 over version texts, project-scoped.
2. Dense cosine over local embeddings of version texts.
3. **Collapse each ranked list to families first**, keeping each family's best rank.
4. RRF fuse over family ranks.
5. Return top-k families with all versions, states and texts.

**Step 3 order matters.** Fusing before collapsing lets a family with many versions accumulate score
purely for having a long history. With BM25 returning versions of family A at ranks 1–3 and family B at
rank 4, summing RRF contributions gives A `1/61 + 1/62 + 1/63 ≈ 0.0484` against B's `1/64 ≈ 0.0156` —
a 3× advantage earned by version count, not relevance. Collapsing first puts A at rank 1 and B at rank
2, scoring `1/61` vs `1/62`. Head-only indexing biases against revised requirements; naive collapse
biases toward them. Collapse-then-fuse is neutral.

### RRF

```
RRF(family) = Σ_i  1 / (k + r_i(family))        k = 60
```

`r_i` is the family's best rank in retriever `i`'s deduplicated list. Rank-based rather than
score-based because BM25 scores (unbounded, corpus-dependent) and cosine similarities (bounded) are not
comparable without per-query normalisation we would have to tune on three dev scenarios. The `k` term
prevents one retriever's top hit from dominating — without it rank 1 is worth twice rank 2, so
agreement between retrievers would lose to confidence within one.

**Do not replace RRF with weighted score blending.**

### Defaults and upgrade ladder

Default `k = 5`. Measure recall@3/@5/@8 on gold candidates in the dev split before changing anything.
**Always log dense-only recall, BM25-only recall and fused recall separately** — that is the diagnostic
that tells you which channel is failing.

Only after a measured failure, in this order:

1. Increase `k`.
2. Embed statement plus actor/object keywords.
3. Local cross-encoder rerank over the BM25 ∪ dense union.
4. Foundry embedding API — last resort, breaks offline determinism.

## LLM stages

### LLM-1 Extract (FR05)

- Input: ordered turns for one meeting, with speaker labels.
- Output: list of `{text_norm, evidence: [{turn_id, start, end}], atomic: true}`.
- No register access.
- **Candidates must be atomic** — one obligation each. Compound turns are split at extraction, never
  classified as a bundle.
- Candidates failing FR06 validation are rejected, counted as extraction errors, and never shown to a
  reviewer.

### LLM-2 Classify (FR07, FR08)

- Input: one candidate, its evidence text, the retrieved families, and the speaker label of the evidence
  turn.
- Output schema, enum-constrained:

```
matched_requirement_id: <retrieved family ids> | no_match
relation: new | refinement | contradiction | supersession | restatement | not_requirement
rationale: str
```

- `new` is legal only with `no_match`. `refinement | contradiction | supersession | restatement`
  require a retrieved id.
- The per-call enum eliminates invented IDs entirely. It does **not** eliminate wrong-ID-from-list;
  that is what E3 measures.
- One retry on schema failure. Log the retry. A second failure is an error, not a fallback.

Speaker label is passed because client "we will use SSO" and consultant "what about SSO?" are different
acts.

## Evidence spans (FR06)

`turn_id = (meeting_id, turn_index)` — deterministic, stable across re-import, no hashing.
An evidence span is `(turn_id, start_char, end_char)`.

Validation is a substring comparison against stored turn text. No model involvement, fully
deterministic, roughly eight lines. This is why the hardest-sounding safety requirement is also the
cheapest.
