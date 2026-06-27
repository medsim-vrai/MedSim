# FR-018 — Scenario support documents (instructor injection + AI roles)

**Status:** BUILDING (S1). **Logged:** 2026-06-26. Extends FR-014 (scanned docs)
and ties to FR-017 (scenario export carries authored docs).

## Problem / goal
FR-014 lets a *student* scan a document into a patient's chart — those are
**always part of the AI context** (the AI sees what the student charts; no role
choice or role notation is shown for them).

Instructors also want to **inject documents as scenario support material** — with
a stated **purpose**, a **type** + **chart area** (filing), and a binary **AI
role** (refined 2026-06-27 from an earlier 3-way context/distraction/on_ask model):
- **Part of the AI** (`ai_mode=context`) — characters know about it and may
  use/discuss it from the start.
- **Not part of the AI** (`ai_mode=on_ask`) — it sits in the chart but stays
  OUTSIDE the AI role **until a student brings it up** during the scenario; then it
  joins the role. If the student never raises it, it stays outside — which
  naturally provides the "distraction" / red-herring behavior, so there is **no
  separate Distraction mode** in the UI (the `distraction` value remains accepted
  by storage but unused).

Two **injection points** (instructor chose *both*): authored into the scenario
(saved, reusable, travels with export) **and** injected live during a run.
Reveal-on-ask fires by *both* paths (instructor chose *both*): an **operator
"reveal"** button **and** **AI auto-detect** when the student references it.

## Design
### Storage
- Reuse the per-patient document store (`scanned_docs.py`) so instructor docs show
  up in the chart alongside student scans. New fields on a doc record:
  `source="instructor"`, `purpose` (instructor note), `ai_mode`
  (`context|distraction|on_ask`), `revealed` (bool, for on_ask).
- **Authored** docs are also stored in the **scenario** (so they persist + export
  via FR-017) and are materialized into the run's per-encounter store at launch.
- **Live** docs are written straight to the per-encounter store.

### Student visibility
Instructor docs render in the chart like any document — **the mode/purpose is
instructor-only metadata, never shown to students** (a "distraction" must not be
labeled as one). Default: on_ask docs ARE visible in the chart (so the student can
notice + ask); `revealed` only gates **AI engagement**, not student visibility.

### AI runtime wiring (`runtime.py` turn context)
- **context** (and **revealed** on_ask) → the doc's purpose + AI summary are added
  to the character turn context, so characters can reference it.
- **distraction** → NOT added as relevant context; if the student raises it, the
  character responds truthfully but treats it as clinically irrelevant (won't steer
  the student toward it).
- **on_ask** (unrevealed) → withheld from context entirely.
- Feed the **summary/purpose text** into context (not raw image bytes) to keep
  per-turn cost/latency sane; reuse the FR-014 `doc_summary` draft.

### Reveal-on-ask (both paths)
- **Operator reveal:** a "reveal" control on the operator console flips
  `revealed=True` → next turn the doc is live context.
- **AI auto-detect:** when a student turn references the document (name/topic
  match against the doc's purpose/summary), auto-flip `revealed=True` and surface a
  note to the operator. Operator path is the reliable fallback.

### Injection UI
- **Authoring:** add a "Support documents" section to the scenario builder /
  Scenario Studio — upload + purpose + ai_mode, saved with the scenario.
- **Live:** an operator-console control to inject a doc mid-run with purpose +
  ai_mode (+ the reveal button for on_ask).

## Staged build
- **S1 — Storage model** (this stage): `scanned_docs` fields (`source=instructor`,
  `purpose`, `ai_mode`, `revealed`) + `set_reveal()`; tests.
- **S2 — AI runtime wiring:** context/distraction/on_ask behavior in `runtime.py`
  turn context (the behavioral heart).
- **S3 — Live injection + operator reveal:** console control + inject/reveal API.
- **S4 — Authoring injection:** scenario-saved support docs (+ export via FR-017).
- **S5 — AI auto-detect reveal:** student-turn reference → auto-reveal + operator note.
- **S6 — Tests + full gate + field verify.**

## Open questions
- on_ask visibility — default is "visible in chart, AI-dormant"; alternative is
  "hidden until revealed." (Assumed the former; easy to flip.)
- Distraction when directly asked — confirm "truthful but clinically irrelevant".
- Per-turn context budget if many context-docs are attached (cap N / summary length).

## Files (by stage)
- `portal/scanned_docs.py` (S1), `portal/runtime.py` (S2/S5),
  `portal/server.py` + operator console template/JS (S3), scenario builder /
  Scenario Studio + `scenarios.py`/`authored_content.py` (S4),
  `tests/v8/test_scanned_docs.py` + new `tests/v8/test_support_docs_ai.py`.
