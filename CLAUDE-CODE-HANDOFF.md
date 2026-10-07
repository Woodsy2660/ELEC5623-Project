# Handoff prompts for Claude Code

Place the export at `design/` in the repo root, then run these in order. Each is a
separate session; don't merge them. Stop and check the result between prompts.

---

## Prompt 1 — scaffold and contract

```
Set up the React frontend for this project. The design is already done: `design/`
holds ten standalone HTML screens that are the specification for every route, plus
`design/styles/tokens.css` and `design/styles/app.css`.

Read first, in order:
  AGENTS.md
  docs/02-architecture.md
  docs/03-requirements.md
  design/README.md

This session is SCAFFOLD ONLY. Do not port any screen yet.

Build:

1. `/web` — Vite + React + TypeScript. React Router and TanStack Query. NOTHING else:
   no component library, no Tailwind, no CSS-in-JS, no state manager. The design system
   is plain CSS custom properties and adding a second styling vocabulary would duplicate it.

2. `web/src/styles/` — copy tokens.css and app.css from `design/styles/` verbatim and
   import them once in main.tsx. Add `npm run sync:ds` that re-copies them, and a CI
   check that fails if the copies differ from `design/styles/`. These files are exports,
   not sources: never hand-edit them.

3. `src/api/` (Python) — a FastAPI router with every endpoint below, each returning
   hard-coded fixtures built from `scenarios/dev/D1`. Response models are Pydantic,
   reusing the schemas already defined under `src/`. No database access this session.

     GET  /projects
     GET  /projects/{pid}/requirements
     GET  /projects/{pid}/requirements/{rid}
     GET  /projects/{pid}/proposals
     POST /proposals/{id}/decision
     GET  /projects/{pid}/meetings
     POST /projects/{pid}/meetings
     GET  /meetings/{mid}/turns
     GET  /meetings/{mid}/stream        (SSE; stub that replays stored turns)
     GET  /projects/{pid}/settings
     PUT  /projects/{pid}/settings

4. `npm run gen:api` — openapi-typescript against the running server, output to
   `web/src/api/schema.d.ts`. Plus a thin typed fetch client. The API types are
   GENERATED; never hand-write or hand-edit them.

5. `web/src/routes/` — one empty route component per screen, wired into the router, each
   rendering only its name. Routes carry the project id in the path for everything
   project-scoped: `/projects/:projectId/register` and so on.

Two contract rules that must hold in the code you write:

- THE STATE ENGINE STAYS IN PYTHON. No TypeScript may compute, predict or validate a
  lifecycle transition. The decision endpoint returns either the committed event or a
  409 with a reason, and the frontend renders whichever came back. The server sends
  `can_confirm: bool` and `can_confirm_reason: string` on each proposal; the UI renders
  the button state from those fields and never derives them.

- EVIDENCE IS SENT PRE-SPLIT. `/meetings/{mid}/turns` and every proposal's evidence
  return `{turn_id, speaker, before, span, after}`. The frontend never slices a string by
  character offset — an off-by-one in JS would look exactly like an FR06 failure.

When done: `npm run dev` serves the empty routes, `npm run gen:api` regenerates types
cleanly, and `pytest src/engine` still passes with no network. Summarise what you built
and list any decision the docs didn't cover.
```

---

## Prompt 2 — component library

```
Port the design system components from `design/` into `web/src/components/`.

Read `design/README.md` and `design/styles/app.css` first, then the screens that use each
component. Every component already exists as markup in the exported HTML — your job is to
extract it into typed React, not to redesign it.

Build, each in its own file with a typed props interface:

  AppShell        logo header, sidebar nav, content slot   (see any screen)
  ScopeBar        client / project switcher / count / isolation note
  StateChip       confirmed | proposed | contradicted | superseded | withdrawn
  StatusTag       neutral status: on | off | live   (.cia-tag)
  CountBadge      .cia-count
  RelationChip    the six relation labels; contradiction and supersession tint
  EvidenceQuote   {speaker, turnId, before, span, after, onJump}
  ProposalCard    head, evidence, rationale, retrieved alternatives, action triad
  RegisterTable   rows with data-state, version, chip
  AuthorityBadge  can / cannot confirm scope
  Sidecar         pill + panel   (see sidecar.html)

Rules:
- Use the existing class names from app.css. Do not invent new ones, do not write new CSS
  for anything app.css already covers, and do not convert these to inline styles.
- StateChip takes a state and nothing else. It must not accept a colour or variant prop —
  the mapping from state to hue is the design system's job, not a caller's.
- StatusTag is for connection status, capture status and counts. It must never render a
  lifecycle hue. If you find yourself wanting one, the thing being shown is a state and
  belongs in StateChip.
- ProposalCard renders `can_confirm` from props. It contains no logic deciding whether a
  transition is legal.
- No component fetches. Data comes in as props; routes do the fetching.

Add a `/web/src/routes/Kitchen.tsx` dev-only route rendering every component in every
state, using the D1 content from the exported screens. Do not add Storybook.
```

---

## Prompt 3 — screens, in this order

```
Port the screens from `design/` into `web/src/routes/`, one at a time, in this order.
Stop after each and show me the result before starting the next.

  1. register.html   → /projects/:projectId/register
  2. detail.html     → /projects/:projectId/requirements/:rid
  3. review.html     → /projects/:projectId/review
  4. index.html      → /          (cross-project; no ScopeBar)
  5. meetings.html   → /projects/:projectId/meetings
  6. import.html     → /projects/:projectId/import
  7. settings.html   → /projects/:projectId/settings

For each:
- Reproduce the exported markup faithfully: same structure, same classes, same copy.
  Where the HTML has inline styles for one-off layout, keep them as style objects. Where
  it uses a class from app.css, use the class.
- Replace the hard-coded rows and cards with data from the matching TanStack Query hook
  against the fixture endpoints. Nothing may be hard-coded that the API returns.
- Keep every piece of explanatory copy. Lines like "Scoped to this project — retrieval
  never crosses projects" and "No proposals yet. Matching runs when the meeting ends" are
  requirements made visible, not filler.
- Preserve accessibility as drawn: real <button>, <a href>, <label> for every input;
  aria-current on the active nav item; the disabled Confirm keeps its visible reason.

Do not port capture.html in this session. Do not add features that are not in the
exported screens.
```

---

## Prompt 4 — live capture, last

```
Port capture.html to /projects/:projectId/capture and sidecar.html as a component.

The transcript streams over `GET /meetings/{mid}/stream` as server-sent events, one turn
per event. The last turn renders in `.cia-turn--partial` until a complete turn replaces it.

C01 of the submitted proposal excludes live meeting-platform capture from this semester,
so the server side replays a stored D1 transcript at realistic pace. Label it in the UI as
a replay. Do not add a meeting-bot integration.

The proposals panel stays empty for the whole session and keeps its explanatory copy.
Nothing on this screen may show model output about the meeting in progress — no counts,
no candidates, no classifications. That restraint is the design, not an omission.
```

---

## After the port

Amend two docs, since this reverses recorded decisions:

- `docs/07-conventions.md` — Streamlit becomes React/Vite; add the `/web` tree, the
  generated-types rule, and the sync rule for the two CSS files.
- `docs/01-context.md` — add the change to the deviations table.
- `AGENTS.md` — add "the state engine stays in Python" to the hard rules, or an agent
  working in `/web` will helpfully reimplement transition logic in TypeScript.
