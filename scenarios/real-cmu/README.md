# CMU interviews — scored copies with draft gold

Three real requirements-elicitation interviews with gold labels, for measuring how the system behaves on
unscripted speech. The transcripts are byte-identical copies of `scenarios/cmu-demo/*/canonical/M01.jsonl`.
The only other change is `scenario.yaml`: the Stakeholder is treated as scope owner
(`can_confirm_scope: true`) so eval-mode decisions can be replayed.

| Folder | Project | Source interview | Turns | Gold events |
|---|---|---|---:|---|
| `github/` | `CMU-GITHUB` | ID 11, GitHub collaboration | 111 | 12 not_requirement |
| `email/` | `CMU-EMAIL` | ID 20, email client | 104 | 4 new, 1 restatement, 11 not_requirement |
| `messaging/` | `CMU-MESSAGING` | ID 32, messaging app | 84 | 1 new, 1 restatement, 10 not_requirement |

## Status: AI-drafted, needs human review

The gold was drafted with AI assistance on 2026-11-05 and has not been reviewed. Before any result is
reported, a team member who did not write the prompts reviews every label and quote, and the review is
recorded here.

These files are **not a holdout split**. The drafter had already seen system output on these interviews
(`docs/14-cmu-interview-runs.md`), so report them as a supplementary real-speech set and do not tune
prompts on them.

## Labelling rule

Labels follow `docs/05-annotation-and-corpus.md` without exceptions, so results compare with D1 and D2:

- `new`: the stakeholder states, without hedging, a capability they want or need ("the feature I want
  is…", "the most important one would be…").
- `restatement`: a later repetition or summary of that same ask, by either speaker.
- `not_requirement`: hedged wishes ("it would be nice", "could have", "maybe"), complaints that state
  no ask, descriptions of how the current product works, usage goals, and interviewer questions or
  suggestions.

Only turns likely to be mistaken for requirements are labelled; navigation narration and small talk are
not. Evidence quotes are exact substrings of the canonical turns, resolved with
`PYTHONPATH=. python tools/resolve_spans.py scenarios/real-cmu/<folder>`.

## What this set can and cannot measure

- Can: extraction on real speech, rejection of hedges and descriptions (no-match accuracy), false
  supersession on unscripted talk, and repetition within one meeting.
- Cannot: cross-meeting lifecycle. Each interview is one session with a different person. The public
  dataset has no follow-up meetings (all 34 interviews are single sessions), so reversals are tested
  only on the authored scenarios D1 and D2.

Gold-candidate validation runs on 2026-11-05 (one repeat each, files check only): six-class macro-F1
0.91 (github), 0.38 (email), 0.46 (messaging); zero false supersessions. On email the classifier
labelled three of the four explicit asks `not_requirement`.

## Source and licence

Source: `study1/data1/transcripts.json` in
[cmu-relab/goalgeneration](https://github.com/cmu-relab/goalgeneration). Preparation is described in
`scenarios/cmu-demo/README.md`. The published text was not checked against audio.

```text
MIT License

Copyright (c) 2025 Ateeq Sharfuddin and Travis Breaux

Permission is hereby granted, free of charge, to any person obtaining a copy
of this software and associated documentation files (the "Software"), to deal
in the Software without restriction, including without limitation the rights
to use, copy, modify, merge, publish, distribute, sublicense, and/or sell
copies of the Software, and to permit persons to whom the Software is
furnished to do so, subject to the following conditions:

The above copyright notice and this permission notice shall be included in all
copies or substantial portions of the Software.

THE SOFTWARE IS PROVIDED "AS IS", WITHOUT WARRANTY OF ANY KIND, EXPRESS OR
IMPLIED, INCLUDING BUT NOT LIMITED TO THE WARRANTIES OF MERCHANTABILITY,
FITNESS FOR A PARTICULAR PURPOSE AND NONINFRINGEMENT. IN NO EVENT SHALL THE
AUTHORS OR COPYRIGHT HOLDERS BE LIABLE FOR ANY CLAIM, DAMAGES OR OTHER
LIABILITY, WHETHER IN AN ACTION OF CONTRACT, TORT OR OTHERWISE, ARISING FROM,
OUT OF OR IN CONNECTION WITH THE SOFTWARE OR THE USE OR OTHER DEALINGS IN THE
SOFTWARE.
```
