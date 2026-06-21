# FR-013 — Local Context Layer + Scenario Generation in the card GUI

**Status:** PROPOSED (future feature — not yet built)
**Logged:** 2026-06-17
**Surfaces:** Mission Control card GUI (`/portal/console`), a new ingestion portal page,
the clinical/character prompt pipeline.

---

## Objective

Let a program tailor the simulation's clinical logic to **local practice**. Today the
AI answers from **best practices**. FR-013 adds a **local context layer** —
**local standing orders, medications, and treatment priorities** — that the logic
consults *after* best practices, so character/clinician responses conform to the
site's own protocols, formulary, and priorities.

> Baseline = best practices. Overlay = the program's local protocols/meds/priorities.
> The local overlay refines/overrides the baseline so the sim "speaks local."

The instructor can **turn this layer on or off**, and it is **off-by-default best
practice** unless local context is active.

## Why

- Different hospitals/programs have different standing orders, formularies, and
  escalation priorities. A generic best-practice sim can teach the "wrong" local
  workflow. A toggleable local overlay makes the sim match where the trainees work.
- Keeps best-practice as the safe default; local context is an explicit, reviewed
  opt-in (not free-form, not silently injected).

## Components

### 1. Local-context ingestion portal page (NEW)
A clean portal page (its own nav entry) to build the local-context library:
- **Import** source documents: **PDF, Word (.docx), Excel (.xlsx)**.
- **Ingestion → confirmation → validation, per item:** parse each source into
  discrete items (a standing order, a formulary entry, a treatment-priority rule).
  The instructor **reviews each extracted item**, can **edit/change** it, and then
  **marks it Active or Inactive**. Nothing goes live until confirmed (mirror the
  FR-008 staged-error "nothing is staged until you confirm" posture).
- Items are typed: **standing orders · medications/formulary · treatment priorities**
  (extensible).
- Active items form the **local overlay**; inactive items are retained but not used.

### 2. AI integration (best-practices → local overlay)
- The character/clinical turn prompt is assembled as: **best-practice baseline**, then
  **active local-context items** layered on top (so the model conforms to local
  practice). This is an additive prompt-context block, like the FR-001/002 med board
  and FR-009 handoff blocks injected at turn time — authored data, code-selected, the
  model never invents protocols.
- Must be injected by **every** character-turn path (operator PTT, station/listen,
  shared station) — see the FR-009 "inject the prompt block everywhere" invariant.

### 3. On/off toggle (instructor)
- The instructor can **enable/disable** the local-context layer for a session.
- The **toggle lives on the Set up (startup) / scenario page** — chosen at launch.
- Off → pure best practice. On → best practice + active local overlay.

### 4. "Scenario generation & context" entry point in the card GUI (NEW)
- The card GUI currently has **no path to generate new scenarios** the way the classic
  room does. Add a button **next to the Debrief tab/button** labelled e.g.
  **"Scenario generation & context"**.
- This area houses **both**: (a) **scenario generation** (parity with classic
  scenario authoring), and (b) **local-context additions** (entry point to the
  ingestion page above). Co-locating them gives the new GUI the authoring surface it's
  missing.

## UX summary
- **Set up page:** a **Local context: on/off** toggle (with a hint that it overlays
  local protocols on best practice).
- **Top tabs / next to Debrief:** a **Scenario generation & context** entry → scenario
  builder + the local-context ingestion/library page.
- **Ingestion page:** drag/drop PDF/docx/xlsx → parsed item list → per-item
  edit + Active/Inactive → saved to the local-context library.

## Phasing & effort estimate

> Rough, pre-discovery sizing to support prioritization — **not a commitment**.
> Ranges are focused-dev-days; actuals hinge on the parsing-fidelity call (P2) and
> the scenario-generation approach (P7). T-shirt: S ≤ ~1.5 d · M ~2–3 d · L ~4–6 d.

### FR-013a — Local context layer

| Phase | Scope | Size | Rough effort | Risk |
|------|-------|:----:|:-----------:|------|
| P1 | Data model + library store + CRUD API (item: type · source · content · active/inactive) | S | ~1.5–2 d | Low |
| P2 | Document ingestion + parse (PDF / Word / Excel → candidate items) | L | ~3–5 d | **High** — fidelity varies per source; lean on P3 validation |
| P3 | Review queue UI: per-item confirm / edit / activate-deactivate (FR-008 staged posture) | M | ~2–3 d | Low |
| P4 | AI overlay: assemble local block + inject in **every** turn path (operator PTT · listen · shared) + tests | M | ~2–3 d | Med — must hit every path (FR-009 invariant) or it silently no-ops |
| P5 | Set up on/off toggle + flag plumbed into turn assembly | S | ~1 d | Low |

**Subtotal:** ~9.5–14 d.

### FR-013b — Scenario generation + context entry point

| Phase | Scope | Size | Rough effort | Risk |
|------|-------|:----:|:-----------:|------|
| P6 | "Scenario generation & context" button next to Debrief + area shell + link into the ingestion page | S | ~1–1.5 d | Low |
| P7 | Scenario generation engine | L / M | ~4–6 d (LLM-assisted) · ~2–3 d (template) | Med — approach undecided; co-locates with P6 |

**Subtotal:** ~3–4.5 d (template) to ~5–7.5 d (LLM-assisted).

**Combined rough order:** ~3–4 weeks of focused dev for the full feature.

### Recommended sequencing — thin vertical first
Ship a **manual-entry MVP** before the risky parser:
**P1 → P5 → P4** with hand-entered items (defer P2/P3). That proves the
best-practice → local-overlay loop end-to-end (toggle on, type one standing order,
watch a character respect it) in ~**4–5 d**, and de-risks the prompt plumbing before
any document-parsing work. Then layer **P2 + P3** (ingestion + review), then
**FR-013b**. Critical path is **P2 parsing fidelity** — keep it simple + validate
heavily, or the estimate balloons.

## Open questions
- Parsing fidelity per format (PDF tables, Excel formularies) — start with a simple
  extract + heavy instructor validation, improve later.
- Storage model + PHI posture (local protocols are not PHI, but keep authored data
  separate + reviewable; respect ADR-0014 trainee-free-text rules).
- Conflict handling when a local item contradicts best practice (local wins, but flag
  it in the item review).
- Scenario generation scope (LLM-assisted vs template) — define separately; this FR
  just establishes the entry point + that it shares the area with context.

## Related
- FR-001/002 (med board prompt injection), FR-008 (staged-error confirm-before-arm
  flow), FR-009 (handoff prompt-block-at-turn-time + "inject everywhere" invariant).
