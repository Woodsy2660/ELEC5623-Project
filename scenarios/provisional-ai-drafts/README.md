# Five holdout scenario drafts

STATUS: AI-authored drafts, not adjudicated gold and not ready for formal holdout scoring. Dialogue and provisional labels were created together. The author separation, independent third-party labelling, adjudication and pre-adjudication agreement required by docs/05-annotation-and-corpus.md have not been completed. Keep this material away from prompt development and freeze prompts before holdout scoring.

H1 library and H2 clinic contain reversals, unresolved conflicts and historical references. H3 food bank, H4 museum and H5 sports club are no-reversal controls. Related but distinct obligations are separate families. H1 includes delayed approval; the D2 documentation notes that the current evaluation harness may auto-confirm proposals and may not measure the delay.

Each scenario has three meetings and 15 provisional events. Files include authored text, canonical JSONL, scenario metadata, gold source quotes and resolved evidence spans. JSON syntax is valid YAML. Independently review every label, family, speaker authority, source span and potential missing event. The files do not define complete decision replay or expected meeting-end register states; author and adjudicate these before sequential state scoring. Historical restatements and delayed approval need particular care.

The short scripted dialogue is not evidence of natural meetings or independent ground truth; improve conversational variation through the independent authoring process. Count final per-class support and disclose shortfalls against proposal targets.

## Use in this repository

Supplied by the team on 2026-11-05 after prompts and rules were frozen at f444ad8. No teammate
will rewrite them, so they serve as a provisional out-of-sample test, not the formal holdout. The
folder name avoids "holdout" because the development scorer refuses holdout paths; that guard
protects a real holdout and is left in place. Results: docs/16-provisional-drafts.md.
