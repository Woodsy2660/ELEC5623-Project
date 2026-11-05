# Three-meeting customer-portal demonstration

FR01/FR03/FR04/FR12 demonstration inputs. These are authored, fictional English
meetings, not AMI excerpts, client records, independent gold labels or a benchmark.
The same fictional client and consultancy names are used only for presentation.
No expected model predictions or approval decisions are supplied to inference.

All three manifests use project `DEMO` and the same configured speakers. Only
Priya Raman can confirm scope; Alex Morgan and Tom Alder cannot. Each manifest
contains one meeting so it can run after a reviewer has decided the prior meeting.

| Stage | Input | Discussion |
|---|---|---|
| m1 | Kick-off, 7 turns | Email/password login, order list and invoice PDF |
| m2 | Two weeks later, 6 turns | Replace login with SSO and add delivery dates |
| m3 | Scope sign-off, 5 turns | Add purchase-order numbers and shipment emails |

Titles describe the fictional sequence. Dates shown by the app are import/event
recording dates, not independently verified meeting dates. "Scope sign-off" is a
meeting title; importing it never constitutes client sign-off.

## Generate and review in order

Use a dedicated fresh database, the pinned local embedding model, and an Azure
chat deployment configured as in `docs/12-track-c-review.md`. The pipeline reads
its `.env`; the local API reads process environment. Model generation incurs Azure
usage. Never put the Azure key into the browser. From the repository root:

```sh
.venv/bin/python -m src.eval.run_pipeline --scenario scenarios/demo/m1 --mode demo --candidate-source extracted --repeat 1 --db sqlite:///portal-demo.db
```

Point the local API's `DATABASE_URL` at `sqlite:///portal-demo.db`, configure
`REVIEWER_TOKEN`, then start the API and Vite UI as documented in
[`docs/12-track-c-review.md`](../../docs/12-track-c-review.md). Open Settings,
enter the same token under Reviewer access and click Apply. Use the app navigation
within that browser tab to review each suggestion, check its evidence, and confirm,
edit or reject as appropriate. A full page reload clears the token from memory.

Only after finishing m1 review, generate m2 against the same database:

```sh
.venv/bin/python -m src.eval.run_pipeline --scenario scenarios/demo/m2 --mode demo --candidate-source extracted --repeat 1 --db sqlite:///portal-demo.db
```

Review m2 before generating m3:

```sh
.venv/bin/python -m src.eval.run_pipeline --scenario scenarios/demo/m3 --mode demo --candidate-source extracted --repeat 1 --db sqlite:///portal-demo.db
```

Run each stage once per database; repeats can create additional pending proposals.
Do not generate all meetings against an empty register and call that a sequential
lifecycle demonstration. Do not weaken evidence validation, change authority or
supply expected labels to force the desired output. Inspect failures and disclose
any edited suggestions or shortened processing time in the recording.

The browser import and CLI importer still have a known hash-order collision when
reusing the same meeting. Use the CLI sequence above; this PR does not fix that
separate integration defect. The published preview remains fixture-backed. These
files make the inputs reproducible, not a guarantee of live model quality.

## Export the recorded scope

After review, the existing UI Export button downloads structured JSON. The separate
read-only HTML helper produces a print-ready document from the same database:

```sh
.venv/bin/python -m tools.export_scope_document --db sqlite:///portal-demo.db --project DEMO --out /tmp/portal-scope.html --client "Tideway Logistics" --consultancy "Larkspur Digital"
```

On Windows use the virtualenv Python and a suitable output path. The helper follows
the current version pointer, retains linked replacements and withdrawn items, and
resolves evidence only within the selected project. Pending suggestions remain in
the review queue and are excluded from agreed scope. The document does not record
sign-off. SR row numbers are presentation numbering, not stable requirement IDs.
Open the HTML in a browser and optionally print it to PDF. No PDF is created by the
helper, and the file has no external stylesheet or font dependency.

Keep databases, credentials, generated scope documents, model responses and recordings
out of this input directory. Report demo observations separately from model-accuracy
results. The independent failure-auditing fix is tracked in PR #7.
