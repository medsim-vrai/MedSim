# MEDSIM V6 · BUILD STATE

**v6.0 status: foundation + 3 reference devices DONE. Pending: manual LAN test (see `LAN_TEST.md`).**

V6 is V5 plus a complete device subsystem (simulated pumps, dispensing
cabinets, instructor control surface, A2HS-installable mobile UIs,
enhanced debrief). The V5 EHR rebuild documented further down this file
is fully intact — all 52 V5 tests still pass under V6.

## V6 additions

| Step | What | Status |
|---|---|---|
| 1  | Clone v5 → v6 (rsync + fresh venv + path bump to `~/.medsim/v6/`) | ✓ Done |
| 2  | Schema migration v3 — `device_station`, `device_event`, `device_assignment` tables | ✓ Done |
| 3  | `DeviceStation` dataclass + ControlSession integration | ✓ Done |
| 4  | `portal/devices/` tree + SVG skins + audio assets | ✓ Done |
| 5+6| HTTP routes + WebSocket transport (bidirectional) | ✓ Done |
| 7  | Shared device engine (state machine, alarms, persistence) | ✓ Done |
| 8  | BD Alaris IV pump reference device | ✓ Done |
| 9  | Cardinal Kangaroo OMNI enteral pump reference device | ✓ Done |
| 10 | BD Pyxis MedStation ES cabinet reference device | ✓ Done |
| 11 | Device front-end + manifest + A2HS install path | ✓ Done |
| 12 | Instructor control surface (roster, mint+QR, inject, assign) | ✓ Done |
| 13 | Enhanced debrief (5 new sections) + `compare/rules_devices.py` | ✓ Done |
| 14 | Pause/resume integrity (WS broadcast, audio gating, fold-based recovery) | ✓ Done |
| 15 | Tests — 37 new + 52 V5 = **89 passed, 1 skipped, 0 failed** | ✓ Done |
| —  | Manual LAN test on 2 tablets + laptop (per `LAN_TEST.md`) | ⏳ Pending |

Reference device coverage: 1 IV pump + 1 enteral pump + 1 cabinet. The
remaining 4 IV pumps + 4 enteral pumps + 4 cabinets land in v6.1+ as
skin+spec additions (no engine changes needed — the engine is
device-kind-agnostic by design).

---

# MEDSIM V5 — EHR Functional Rebuild · BUILD STATE

**This file is the checkpoint.** It is the single source of truth for the
V5 EHR rebuild. If the build is paused or interrupted, a new session
resumes by reading this file top-to-bottom, then continuing at the phase
marked `IN PROGRESS` (or the first `NOT STARTED` phase).

Last updated: Phase 0.

---

## How to resume (read this first if you are a fresh session)

1. Read this whole file.
2. Read `CLAUDE.md` for project conventions.
3. Find the current phase below (`▶ CURRENT PHASE`).
4. Open that phase's checklist; continue at the first unchecked item.
5. Simulation content is **not** at risk — it lives in SQLite at
   `~/.medsim/v5/ehr.db` and is unaffected by build interruptions.
6. After finishing any phase: run the test suite, tick the phase's
   acceptance box, move `▶ CURRENT PHASE`, append to the Changelog.

Run tests with: `.venv/bin/python -m pytest tests/ -q`

---

## Why this rebuild exists (evaluation — do not lose this context)

The V2–V4 EHR bundles (`portal/ehr/{helix,cyrus,meridian}/`) are the
original **visual design mockups copied verbatim** — not functional apps.
Defects found:

1. **Seeded patient never reaches the screen.** `app.jsx` does
   `useState(window.HELIX_PATIENTS[0])` at mount, capturing the mockup
   patient. `medsim_v3_client.js` overwrites the global *afterwards* —
   too late; React already captured the old value. Result: the chart
   always shows mockup patients, never the scenario persona.
2. **Only the patient list is even attempted.** Vitals, labs, results,
   notes, order catalog, MAR all render from hard-coded `window.HELIX_*`
   globals the bootstrap never touches.
3. **Seed name is randomized** — `ehr_seed._synth_name()` invents a
   random name for patient personas, so the chart never matches the
   scenario.
4. **Screens are display mockups** — cannot create notes, the order
   cart is not wired to the backend, vitals are a static table.

What is **sound**: `ehr_db.py` (SQLite, append-only `chart_event`,
EHR-agnostic envelope, `fold()` projection) is the correct database
architecture, already shared by all three EHRs and read by the
comparison engine + debrief. The DB design stays — it is hardened, and
the UIs are rebuilt to actually use it.

---

## Architecture decisions (locked — from operator Q&A)

- **Workspace:** new `medsim_v5/` (copy of v4). v4 stays as fallback.
- **EHR architecture:** ONE functional EHR React engine + THREE thin
  theme layers (Helix / Cyrus / Meridian colours, tab labels, fonts).
  The 50k-line mockups are retired to visual reference only.
- **Testing:** Playwright (headless Chromium) for EHR UI tests, in
  addition to the existing Python API/DB suite.
- **Database:** no new database — harden the existing
  `~/.medsim/v5/ehr.db` (SQLite). It is the shared store for all three
  records systems. Content generated during a simulation (notes,
  orders, vitals, events, comparison reports) persists there and
  survives server restarts.

---

## Phase plan

Each phase ends GREEN (tests pass) and CONTENT-SAFE (nothing in
`ehr.db` is lost). An interruption between phases loses no work.

| # | Phase | Status |
|---|---|---|
| 0 | Checkpoint + scaffold V5 | ✅ DONE |
| 1 | Database hardening | ✅ DONE |
| 2 | Seed correctness | ✅ DONE |
| 3 | Functional EHR core + 3 themes | ✅ DONE |
| 4 | Live projection + multi-station sync | ✅ DONE |
| 5 | Verification | ✅ DONE |
| 6 | Extensible master catalog + notation authorship | ✅ DONE |

`▶ CURRENT PHASE: — (build complete)`

Phases 0–5 delivered the functional EHR rebuild (51/51 tests). Phase 6
is an in-place increment: a persistent, extensible master order catalog
and captured note authorship.

### Phase 6 — Extensible master catalog + notation authorship

- [x] `ehr_db.py` migration 2: `catalog_addition` table (global,
      persistent) + `add_catalog_item` / `catalog_additions` /
      `remove_catalog_item` (in-memory fallback included).
- [x] `GET …/orders/catalog` → `_merged_catalog()` = base catalog.json +
      master additions; additions tagged `added`.
- [x] `POST …/orders/catalog` adds a custom supply/service/medication
      to the master list, attributed to the station's device label.
- [x] `POST …/orders` auto-promotes any unknown (category, code) into
      the master list so ad-hoc orders "continue forward."
- [x] EHR Orders tab: "Add a custom supply / service / medication" form;
      custom items show a `custom` pill.
- [x] Note authorship: `STATION_LABEL` in the bootstrap; `note.save`
      payload carries `author`; `fold()` + the Notes tab surface it.
- [x] EHR admin lists the master catalog with per-row remove.
- [x] Tests: catalog add survives a simulated restart, global across
      EHRs; merged catalog; auto-promote; note author; Playwright
      custom-order form.
- **Acceptance:** ✅ custom supplies/services/meds join a persistent
      master list usable by all three EHRs; notes carry their author;
      restart loses nothing. 54/54 tests pass.

Files touched: `portal/ehr_db.py` (migration 2 + catalog API + note
author in fold), `portal/server.py` (`_merged_catalog`, catalog GET/POST,
auto-promote, `STATION_LABEL`, admin route + remove),
`portal/ehr/_core/ehr_app.jsx` (custom-order form, note author),
`portal/templates/ehr_admin.html` (master-catalog table),
`tests/{test_ehr_db,test_e2e_v3,test_ehr_ui}.py`.

---

### Phase 0 — Checkpoint + scaffold V5

- [x] Copy v4 → v5
- [x] Bump pyproject → medsim5 / 5.0.0a
- [x] Write this BUILD_STATE.md
- [x] venv + `.[serve,dev]` + Playwright Chromium installed
- [x] Update CLAUDE.md header for V5
- [x] Baseline: full test suite green on the fresh copy (38 passed)
- **Acceptance:** ✅ resumable structure exists; suite green.

### Phase 1 — Database hardening

- [x] `ehr_db.py`: SQLite is the guaranteed store — `~/.medsim/v5/`
      (0700 dir / 0600 db), in-memory only on a read-only FS and then
      logged loudly to stderr + surfaced via `storage_status()`.
- [x] `schema_version` table + ordered `SCHEMA_MIGRATIONS` runner.
- [x] `fold()` rewritten — covers the full §10 catalog: notes, orders
      (+order.modify status), vitals, assessments, med.administer,
      result.acknowledge, intake/output, allergies, problems, comms, flags.
- [x] `storage_status()` + persistence banner on `/portal/ehr_admin`.
- [x] Test: `test_content_survives_simulated_server_restart` (close
      connection + drop in-memory mirrors → reconnect → content intact).
- **Acceptance:** ✅ server restart preserves all chart content;
      43/43 tests pass.

Files touched: `portal/ehr_db.py` (rewritten), `portal/server.py`
(ehr_admin passes `storage`), `portal/templates/ehr_admin.html`
(persistence banner), `tests/test_ehr_db.py` (+5 tests),
`tests/test_e2e_v3.py` (dropped stale `_mem_orders` reset).

### Phase 2 — Seed correctness

- [x] `ehr_seed._patient_name()` replaces `_synth_name()` — proper
      persona names kept verbatim (Mr. Bennett, Mrs. Kowalski); given-name
      personas keep their first name + deterministic surname; pure
      descriptors synthesize deterministically. `persona_id` +
      `persona_label` recorded on the seed.
- [x] Scenario detail flows in: `scenario_text` → admit-note HPI +
      encounter reason; `alteredState` → documented in admit + nursing
      notes; modules → A&P + chief complaint + problem list. Two
      pre-existing signed notes (Admission H&P + Nursing Admission Note).
- [x] `chief_complaint` + `persona_label` added to all 3 EHR adapters'
      patient rows.
- [x] Tests: name fidelity, given-name handling, persona identity on
      seed, scenario_text in admit note, altered-state documented.
- **Acceptance:** ✅ seed patient = scenario persona with scenario
      detail; 48/48 tests pass.

Files touched: `portal/ehr_seed.py` (name resolution, notes, chief
complaint, encounter reason), `portal/ehr/{helix,cyrus,meridian}/adapter.py`
(chief_complaint + persona_label), `tests/test_ehr_seed.py` (+5 tests).

### Phase 3 — Functional EHR core + 3 themes

- [x] `portal/ehr/_core/` — shared functional React engine
      (`ehr_app.jsx`, `index.html`, `themes.js`); bootstraps from
      `window.MEDSIM_V3`, renders the seeded patient + fold() projection.
- [x] Notes: create / edit / sign / addendum → `note.save` / `note.addendum`.
- [x] Vitals: record row → `vitals.record`, flowsheet shows it.
- [x] Orders: catalog search + cart + rationale + sign → `order.place`.
- [x] Results: view + acknowledge → `result.acknowledge`.
- [x] MAR (`med.administer`) + allergies/problems (`*.add`) wired.
- [x] 3 theme layers; `_render_ehr_bundle` serves `_core/` per ehr_id.
- [x] Old mockup JSX retired to `ehr/{id}/mockup_reference/`.
- [x] **Bug found + fixed:** the engine fetched against `V3.BASE_URL`
      (the QR/LAN host) → cross-origin CORS failure from localhost.
      Now uses same-origin relative URLs.
- [x] Playwright UI test (`test_ehr_ui.py`): real browser drives the EHR.
- **Acceptance:** ✅ write/sign note persists + survives reload; order
      places; vitals update the flowsheet — proven by Playwright.
      50/50 tests pass.

Files touched: `portal/ehr/_core/{ehr_app.jsx,index.html,themes.js}`
(new), `portal/server.py` (`_render_ehr_bundle` → `_core/`),
`portal/ehr/{id}/mockup_reference/` (old JSX retired),
`tests/test_ehr_ui.py` (new — Playwright), `tests/test_e2e_v3.py`
(demo-route assertions updated for the `_core` bundle).

### Phase 4 — Live projection + multi-station sync

- [x] EHR engine polls `/api/ehr/{join}/chart/{patient}` every 5 s; the
      note editor is local state so a refresh never disturbs it.
- [x] Chart endpoint now returns `locked` — a passive (non-writing)
      station flips read-only when the operator fires lock-in.
- [x] Test `test_multi_station_chart_is_shared_and_lock_propagates`:
      station-1's note is visible to station-2's poll; lock-in
      propagates to the shared chart.
- **Acceptance:** ✅ stations share one live chart; 51/51 tests pass.

Files touched: `portal/ehr/_core/ehr_app.jsx` (5 s poll + lock pickup),
`portal/server.py` (chart route returns `locked`), `tests/test_e2e_v3.py`
(+multi-station test).

### Phase 5 — Verification

- [x] Playwright tests (`test_ehr_ui.py`): real Chromium drives a live
      uvicorn server — scenario patient renders, note save persists +
      survives reload, vitals record, order places; demo route renders.
- [x] Full Python + Playwright suite green — 51/51.
- [x] Comparison engine + debrief read the real chart — covered by
      `test_full_v3_flow` (charting_complete → debrief documentation
      alignment finds the charted items) and the multi-station test.
- [x] `themes.js` / `_core` added to pyproject package-data.
- **Acceptance:** ✅ green end-to-end.

---

## Decisions log

- Q: workspace → **new medsim_v5** (v4 kept as fallback).
- Q: EHR architecture → **shared functional core + 3 themes**.
- Q: EHR UI testing → **Playwright headless Chromium**.

## Open questions / deferred

- (none yet)

## Changelog

- Phase 0 started: v5 scaffolded from v4, pyproject bumped,
  BUILD_STATE.md created, phase task list created.
- Phase 0 DONE: venv + Playwright/Chromium installed, CLAUDE.md updated,
  baseline suite 38/38 green. → Phase 1.
- Phase 1 DONE: ehr_db.py hardened — SQLite-guaranteed at ~/.medsim/v5,
  schema_version migrations, full-catalog fold(), storage_status() +
  admin banner, restart-durability test. Suite 43/43 green. → Phase 2.
- Phase 2 DONE: ehr_seed.py — EHR patient identity = scenario persona;
  scenario_text/alteredState/modules flow into admit + nursing notes,
  chief complaint, encounter reason; adapters carry chief_complaint +
  persona_label. Suite 48/48 green. → Phase 3.
- Phase 3 DONE: functional EHR engine (_core/) + 3 themes; mockups
  retired; CORS/relative-URL bug fixed; Playwright UI test. 50/50. → Phase 4.
- Phase 4 DONE: 5 s chart poll, lock propagation to passive stations,
  multi-station shared-chart test. 51/51. → Phase 5.
- Phase 5 DONE: Playwright UI coverage, comparison/debrief verified
  against the real chart, package-data updated. 51/51 green.
  **V5 EHR REBUILD COMPLETE.**
- Phase 6 DONE: extensible persistent master order catalog (migration 2,
  global, auto-promoting ad-hoc orders) + note authorship via
  STATION_LABEL + admin master-catalog view. 54/54 green.
- Fix: medications ordered in CPOE now appear on the MAR. `MARTab` only
  read seed home-meds; it now also folds `chart.orders` entries with
  category "med" (flagged "ordered", honouring held/discontinued
  status) so an ordered medication is administrable. Playwright test
  extended to order a med and administer it from the MAR. 54/54 green.
