# Design export — Consult SI screens

Ten standalone HTML screens, exported from the design canvas. Open `index.html` in a
browser and the links work: this is a navigable static prototype, not a picture of one.

```
index.html      Home — projects, live call, upcoming
register.html   Register — all five lifecycle states in one table
review.html     Review queue + proposal card   ← the most important screen
capture.html    Live capture — streaming transcript, no proposals
meetings.html   Meetings — upcoming (calendar) and past (runs)
detail.html     Requirement detail — versions, evidence, audit
import.html     Import — the secondary path
settings.html   Settings — connections, authority, model, data
sidecar.html    In-call sidecar + recording pill (a fragment, not a page)
flow.html       Capture / navigation / pipeline map (reference, not an app screen)

styles/tokens.css   design-system tokens — COPIED, never hand-edit
styles/app.css      component classes — COPIED, never hand-edit
assets/             the Consult SI mark, ink and light
```

## What these are for

They are the **specification** for `/web`. Every class name, token, state colour and piece
of copy is intentional and traceable to a requirement. Port them; don't reinterpret them.

## Rules carried by the markup

- **Contrast carries authority.** `--ink` = confirmed, `--ink-proposed` = unconfirmed model
  output, `--ink-historical` = superseded/withdrawn. Never render a proposal in `--ink`.
- **Hue carries lifecycle state, and nothing else.** Teal confirmed, indigo contradicted,
  clay superseded, grey withdrawn/empty. Connection status, capture status and counts use
  the neutral `.cia-tag` / `.cia-count` instead. If a new status needs a colour, it gets
  ink and a border, not a state hue.
- **Interactive is black.** No accent hue for links or controls.
- **Evidence is serif** (`.cia-evidence__quote`) and always shown inside its surrounding
  turn text, never as a bare clip.
- **No confidence numbers anywhere.** The model's rationale is prose. A score would imply
  calibrated certainty the system does not have (NFR06).
- **Three typefaces, each semantic.** Playfair Display for display + transcript, DM Sans
  for interface, JetBrains Mono for identifiers only.

## Known fictions in the markup

Replace, do not ship:

- Client and project names (Northwind Logistics, Meridian Freight) are placeholders.
- Latency and cost figures on `meetings.html` are invented. Use real E8 numbers or cut them.
- `capture.html` shows live meeting-platform capture, which C01 of the submitted proposal
  excludes from this semester. Build it as a replay of a stored transcript, labelled as a
  simulation.
