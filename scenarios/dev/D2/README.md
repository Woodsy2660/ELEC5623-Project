# D2 — event-sequence draft and dialogue brief

**Status:** Draft for Danyang to review and Lucas to turn into dialogue. No transcript or final evidence spans exist yet. Initial drafting used AI assistance; this is not final human-reviewed gold.

Gold author: Danyang (Track B). Dialogue author: Lucas (Track C), following the rotation in `docs/05-annotation-and-corpus.md`. This is a dev scenario, not a no-reversal control.

## Scenario

A consulting team discusses a small employee portal and payment service across three meetings. Three obligations deliberately share email-related wording but have different purposes: employee login (R01), password-reset link delivery (R02), and payment receipt delivery (R03). Never merge these families.

The client representative can confirm scope. The consultant and observer cannot. Configure these roles before ingestion; do not infer authority from confidence or job titles in dialogue. A question remains a question even when the client asks it.

## Events to realise

There are 18 labelled content events, six per meeting. Additional conversational filler is allowed and must be annotated if it falls within the evaluation coverage. The descriptions below specify intent, not lines to copy into the transcript.

| Event | Meeting | Speaker | Relation | Match / historical reference | Intended content | Current version / state afterwards |
|---|---|---|---|---|---|---|
| 1 | 1 | client | new | no_match | Establish email-and-password login as agreed scope. | R01 v1 / confirmed |
| 2 | 1 | client | new | no_match | Establish delivery of password-reset links by email; this is separate from login. | R02 v1 / confirmed |
| 3 | 1 | consultant | new | no_match | Propose receipt email delivery. The client explicitly postpones approval; do not confirm it. | R03 v1 / proposed |
| 4 | 1 | consultant | not_requirement | no_match | Ask whether corporate single sign-on might be an option. No replacement is decided. | R01 v1 / confirmed |
| 5 | 1 | observer | not_requirement | no_match | Ask whether receipts could be sent by SMS. It remains an open question. | R03 v1 / proposed |
| 6 | 1 | client | restatement | R01 v1 | Repeat the agreed email-and-password login decision without adding a constraint. | R01 v1 / confirmed |
| 7 | 2 | client | restatement | R03 v1 | Explicitly approve the receipt-email proposal from Meeting 1. The content is unchanged; the approval is new. | R03 v1 / confirmed |
| 8 | 2 | client | refinement | R02 v1 | Add a two-minute delivery limit to emailed password-reset links. Email remains the channel. | R02 v2 / confirmed |
| 9 | 2 | client | supersession | R01 v1 | Explicitly replace email-and-password login with corporate single sign-on, with no email-login fallback. | R01 v2 / confirmed |
| 10 | 2 | client | not_requirement | no_match | Ask whether SMS receipts could be cheaper. Even an authorised speaker has not made a replacement decision. | R03 v1 / confirmed |
| 11 | 2 | client | contradiction | R03 v1 | State that the agreed automatic receipt-email obligation cannot stand because the mail delivery arrangement is unavailable. State no replacement. Keep the conflict unresolved. | R03 v1 / contradicted |
| 12 | 2 | client | restatement | R02 v2 | Summarise password-reset delivery by email within two minutes, with no new restriction. | R02 v2 / confirmed |
| 13 | 3 | consultant | restatement | R01 v1 | Refer to the email-and-password wording from Meeting 1 as the approach already replaced in Meeting 2. The reference must not reinstate it or create a new requirement. | R01 v2 / confirmed |
| 14 | 3 | client | supersession | R02 v2 | Explicitly replace email delivery of password-reset links with SMS. Preserve the existing two-minute delivery limit. | R02 v3 / confirmed |
| 15 | 3 | client | refinement | R01 v2 | Add a five-second authentication limit to corporate single sign-on. The single sign-on requirement remains true. | R01 v3 / confirmed |
| 16 | 3 | client | restatement | R01 v3 | Repeat the current single-sign-on decision including its five-second limit. | R01 v3 / confirmed |
| 17 | 3 | client | restatement | R03 v1 | Summarise that the previously agreed receipt email remains blocked and unresolved. Do not approve an alternative or resolve the conflict. | R03 v1 / contradicted |
| 18 | 3 | consultant | restatement | R02 v2 | Refer to the earlier email-reset wording as a decision now replaced by SMS in this meeting. Do not undo the replacement. | R02 v3 / confirmed |

For `new`, `no_match` is the classification target; the family ID shown in the last column is assigned after creation. For `not_requirement`, the family in the last column is only context for checking that it stays unchanged, not a required match label. Historical reference versions in events 13 and 18 differ from the current version intentionally.

## Expected meeting-end register

| Meeting | R01: login | R02: password-reset links | R03: payment receipts |
|---|---|---|---|
| 1 | v1, confirmed: email and password | v1, confirmed: email delivery | v1, proposed: email receipts |
| 2 | v2, confirmed: corporate single sign-on; v1 superseded | v2, confirmed: email within two minutes | v1, contradicted: no replacement agreed |
| 3 | v3, confirmed: corporate single sign-on within five seconds | v3, confirmed: SMS within two minutes; v2 superseded | v1, contradicted: still unresolved |

Retain every historical version and its evidence. A retained version is not necessarily current scope. Refinement does not create a second family. Each accepted replacement must keep the same family ID, supersede the previous current version, and make the approved replacement the current version.

## Before finalising the gold file

1. **Supersession:** The current rule table validates `Supersede` to `superseded`, but does not specify the complete same-family replacement transaction. The JSON records proposed semantic steps (close old version, create replacement, confirm replacement). These are not an implemented runtime adapter contract.
2. **Delayed confirmation:** Event 7 repeats unchanged content but changes approval from proposed to confirmed. Its draft relation is `restatement` with a separate `Confirm` decision. This needs alignment with the annotation guide, which also describes restatement as a no-op. Do not silently relabel the existing requirement as `new` to make it work.
3. **References to history:** Events 13 and 18 explicitly describe an earlier decision as superseded; event 17 repeats an unresolved conflict. These draft `restatement` labels must be reviewed against the actual dialogue. Bare repetition of the old obligation could instead imply a new reversal and should not be used.
4. **Evidence:** After dialogue authoring, replace every null source span with the actual turn index and character offsets. Resolve spans against exact transcript text. Keep relation, confirmation decision and version effects distinct.

## Brief for Lucas

Please write three ordered meeting transcripts that realise the events above, preserving their order and outcomes. Use natural conversation and your own wording; do not copy the canonical requirement sentences verbatim throughout.

- Make the three email-related obligations clearly separate, while allowing overlapping words that could confuse matching.
- In Meeting 1, leave receipt-email approval pending. In Meeting 2, explicitly approve it before the later unresolved conflict.
- Make each replacement explicit: email/password login becomes corporate single sign-on; emailed reset links become SMS. Keep the reset delivery limit when changing its channel.
- Include questions and hedges, including one from the authorised client, without implying approval.
- In Meeting 3, refer back to the original login decision as already replaced. Later refer to the earlier reset-email decision as replaced too. Do not restore either old obligation.
- Vary wording with short acknowledgments, interruptions or clarification, but keep each scored content event identifiable. Do not put IDs, relation labels or state names in spoken dialogue.
- Use stable speaker labels `client`, `consultant`, and `observer`; their authority is project configuration. IDs and evidence offsets can be added after the text is stable.

Danyang reviews the sequence and labels; Lucas writes the dialogue. After reconciliation, create the final transcript and gold in the agreed harness format. Do not pass this draft or its labels to inference.

## Evaluation limits

This draft contains new (3), refinement (2), supersession (2), contradiction (1), restatement (7), and not_requirement (3). It includes delayed approval, historical back-references, and near-duplicate obligations. It does not by itself satisfy the whole-corpus coverage or class-balance targets.

With only three families, recall@3/@5/@8 is not informative once all three are available. Use D2 to inspect matching, relationship classification, authority handling and final-state consistency; do not claim retrieval quality from its top-k recall alone.

The current standalone retrieval runner takes a meeting-start snapshot. It cannot evaluate the within-meeting lookup in event 18 against the replacement created in event 14. Use a sequential harness that refreshes after approved writes for that case, or explicitly limit a meeting-start diagnostic; do not leak later versions into earlier candidates.

Files: `gold-sequence.draft.json` contains the structured authoring plan and snapshots; this README is the dialogue brief. Neither is a finished evaluation input.
