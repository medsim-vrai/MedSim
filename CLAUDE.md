# MEDSIM 8 (Medsim-VRAI) — Claude Code project instructions

MEDSIM 8 is the eighth major version, **forked from `../medsim_v7/`
on 2026‑05‑28** to add the VRAI Faces tablet-facing avatar surface
without disturbing the active V7 multi‑patient build. V8 inherits
every V6 + V7 capability 1:1 (ControlRoom, multi‑patient, EHR,
devices, voice, debrief) and adds:

- A translucent, animatable 3D facial avatar rendered in Chrome on a
  tablet.
- QR launch from the portal: `GET /qr/face/<character_id>.svg` and
  facilitator launcher `GET /portal/face/launch/<character_id>` — both
  added at the bottom of `portal/server.py`.
- Lip-sync + emotion animation driven by MedSim speech output, flowing
  as `VRAISpeechFrame` packets over BroadcastChannel (same-origin) or
  WebSocket (cross-app).
- Pause/resume across tab hide, low battery, or shell signal (ADR-0018).
  No scenario state is lost on tablet sleep.

**VRAI Faces lives under `vrai-faces/`** — its own pnpm workspace.
Read `vrai-faces/Memory_management.MD` and
`vrai-faces/docs/VRAI_Faces_Claude_Code_Guide.md` BEFORE touching anything
under `vrai-faces/packages/`. The 18 ADRs in §7 of that file are the
contracts.

## V7 lineage (preserved verbatim)

MEDSIM 7 (Medsim-MP) was the seventh major version, built as a sibling
to `../medsim_v6/`. V7 inherits every V6 feature 1:1 in single-patient
mode and adds a **multi-patient, multi-student** layer: one instructor
can run 6–8 simultaneous patient encounters with 16–24 student
stations, organized through a ControlRoom abstraction.

**Active build:** read `BUILD_STATE.md` in this directory — it is the
checkpoint for the V7 multi-patient build and tells any session where
to resume. The 22-module plan lives at
`../../Multipatient multi student simualtion/deliverables/Development_Plan.md`
and the per-module spec / status PDFs live under `docs/module_guides/`.

**Backwards-compat contract:** every phase must finish with the v6
test suite green on v7 in single-patient mode. The release gate is M21.

**Pause/resume protocol:** see `CONTINUATION.md`. The build is
designed to be paused and restarted across sessions without loss —
`BUILD_STATE.md` carries the phase table, the v7 chart-event database
at `~/.medsim/v7/` carries simulation content, and the per-module PDF
guides carry the design specs.

## V7 additions at a glance

- **ControlRoom** — `portal/control_room.py` — a roomful of Encounters
  under one instructor. Single-patient mode is just a room of 1.
- **Encounter** = the v6 ControlSession promoted in place; v7-only
  fields (`room_id`, `encounter_label`, `activity_id`, `chart_mode`,
  `patient_persona_id`, `assigned_student_ids`) default to safe
  single-patient values.
- **Student** dataclass — persisted in the `student` table (M1 schema
  v4) so rostering survives server restarts.
- **Schema migration v4** — new tables (`control_room`, `student`,
  `activity`) + five new columns on `ehr_session`. Existing v6 DBs
  upgrade in place; legacy rows get NULL `room_id`.
- **DB path bumped** to `~/.medsim/v7/medsim.db` (with `V6_DIR`,
  `V5_DIR` aliases preserved for back-compat).

The full feature list (charge-nurse dashboard, scenes engine,
activities, dual chart mode, cohort debrief, WebSocket transport,
cost caps, observer seat, capacity hardening, Playwright) lands across
modules M3–M21. See `BUILD_STATE.md` for current status.

---

## V6 baseline (inherited)

MEDSIM 6 is the sixth major version. V6 inherits every V5 feature
unchanged and adds **simulated medical devices** (IV pumps, enteral
pumps, dispensing cabinets) plus an instructor control surface for
device assignment and alarm injection. Every V6 feature works in V7
single-patient mode and in each V7 Encounter.

---

## V5 baseline (inherited)

MEDSIM 5 is the fifth major version, built as a sibling to `../medsim_v4/`.
V5 inherits every V4 feature and **rebuilds the EHR into a functional
medical-records application**. V2–V4 shipped the EHR as static visual
mockups; V5 replaces them with one working EHR engine + three theme
layers, driven by the V3 chart-event database.

## V5 additions at a glance

- **Functional EHR engine** — `portal/ehr/_core/`. One React app shared
  by all three records systems; bootstraps from `/api/ehr/.../bootstrap`,
  renders the seeded patient + live `fold()` projection, and writes real
  records (notes, vitals, orders, results, MAR) via the chart-event API.
- **Three theme layers** — Helix / Cyrus / Meridian are now colour +
  label + font themes over the shared engine, not separate codebases.
- **Scenario-accurate pre-population** — the EHR patient is the
  scenario's primary persona; scenario detail flows into the chart.
- **Hardened SQLite** — `~/.medsim/v5/ehr.db` is the guaranteed store
  with schema versioning + migrations. Simulation content survives
  server restarts.
- **Live multi-station chart** — EHR stations poll the projection so the
  instructor's launched window and student devices share one chart.
- **Playwright UI tests** — headless-Chromium coverage of the EHR.

The old mockups are retired to `portal/ehr/{id}/mockup_reference/` as
visual reference only.

---

## V4 baseline (inherited)

MEDSIM 4 is the fourth major version. V4 inherits every V3 feature
unchanged and adds **ElevenLabs neural TTS** for character voices.

## V4 additions at a glance

- **ElevenLabs voice service** — `portal/voices.py`. Synthesizes character
  speech with the **`eleven_flash_v2_5`** model (low-latency, ~75 ms model
  inference, ~200 ms perceived) via the streaming endpoint.
- **Per-character voice selection** — for every persona the instructor
  picks from **5 candidate voices** filtered by the persona's sex, age
  band, and ethnicity/accent. Assignments live on the `ControlSession`
  (`voice_assignments`). Surfaced as a "Character voices" card in the ops
  view with a per-voice preview button.
- **Graceful fallback** — if the ElevenLabs key is missing, the API is
  unreachable, or a synth call fails, the system falls back to the V2/V3
  browser `SpeechSynthesis` path with the persona's existing voice
  profile. No feature is lost when ElevenLabs is offline.
- **Voice catalog** — fetched live from ElevenLabs `/v1/voices` and cached;
  a static fallback catalog (`portal/data/elevenlabs_fallback_voices.json`)
  covers offline use. Persona → trait mapping in
  `portal/data/persona_voice_traits.json`.

## V4 key resolution (ElevenLabs)

`portal/voices.py::get_api_key()` resolves in order:
1. vault credential `ELEVENLABS_API_KEY` (preferred — encrypted)
2. environment variable `ELEVENLABS_API_KEY`
3. `~/.medsim/elevenlabs.key` (plain file, 0600 — like a CLI credentials file)

Never commit the key to the repo.

## V4 new routes

| Method | Path | Purpose |
|---|---|---|
| GET  | `/api/voices`                      | Full voice catalog (live or fallback) |
| GET  | `/api/voices/health`               | ElevenLabs availability probe |
| GET  | `/api/voices/candidates/{persona}` | 5 candidate voices for a persona |
| POST | `/api/tts`                         | Streaming TTS proxy (Flash v2.5) |
| POST | `/api/control/voice`               | Persist a persona→voice assignment |

## V4 model + latency

Model is **`eleven_flash_v2_5`** with `optimize_streaming_latency=3` and
`output_format=mp3_44100_128`. This is the configuration that holds the
perceived latency near 200 ms. Do not switch to a Multilingual/Turbo
model without re-checking the latency budget.

---

MEDSIM 3 is the third major version, built as a sibling to `../medsim_v2/`.
V3 inherits every V2 feature unchanged and adds an **integrated EHR layer**:
operators pick one of three EHR look-alikes (Helix Health, Cyrus Care,
Meridian EHR) at scenario setup; a chartable patient is pre-populated
from the primary persona + selected modules; a second QR/URL lets students
join the chart on any Chrome-capable device; every save/order is logged;
when the operator clicks **Charting complete** a hybrid comparison engine
(deterministic rules + Haiku 4.5 rubric) scores the documentation against
the transcript and appends two new sections to the V2 debrief
(Documentation alignment, Orders alignment).

## V3 additions at a glance

- **EHR template registry** — three rebuilt UIs (`portal/ehr/{helix,cyrus,meridian}/`)
  loaded as single-file React-in-browser bundles. Mockups in
  `../../../Desktop/Training Bridge/Med Records sys/Graphic interfaces/Medical records(6)/`
  are the visual reference; V3 swaps their static `data.jsx` arrays for
  fetches against the V3 API.
- **Wizard step 2b — Records system** — radio selector inserted between
  step 2 (Scenario) and step 3 (Curriculum). Default from scenario JSON.
- **Pre-population pipeline** — `portal/ehr_seed.py` builds a neutral
  `ChartSeed` from persona + selected modules; per-EHR adapters
  (`portal/ehr/{ehr_id}/adapter.py`) install it as the EHR's native rows.
- **EHR station** — separate QR/URL/identity from chat stations.
- **Append-only chart event log** — `chart_event` table in
  `~/.medsim/v3/ehr.db` (SQLite). One event envelope (see Blueprint §10).
- **Hybrid comparison engine** — `portal/compare/{rules,rubric,score}.py`.
- **Charting-complete lock-in** — `POST /portal/control/charting_complete`
  triggers comparison, freezes chart UI, makes the debrief render.

## What V3 inherits from V2 untouched

- Auth + vault at `~/.medsim/vault.enc` (shared with V1/V2/V3).
- `ControlSession` singleton, station registry, persona library (24),
  modules, programs, NCJMM tagger, per-turn Haiku runtime, debrief JSON
  store, voice chat stations, 3-second ops polling.

## V3 storage layout

```
~/.medsim/
  vault.enc                    # unchanged
  v3/
    ehr.db                     # SQLite — chart + events + comparison
    seeds/<session>.json       # frozen ChartSeed per session
```

Debriefs continue to be written to `data/debriefs/<session_id>.json` by
the existing V2 path; V3 just enriches them with two new sections.

## V3 new routes (full table in Blueprint PDF §9)

| Method | Path | Purpose |
|---|---|---|
| GET  | `/ehr/join?code=ABC123`               | EHR join landing |
| POST | `/ehr/join`                           | Register EHR station |
| GET  | `/ehr/{join}/{station}`               | Serve EHR bundle for session's `ehr_id` |
| GET  | `/api/ehr/{join}/{station}/bootstrap` | Patients, seed, current chart state |
| POST | `/api/ehr/{join}/{station}/event`     | Append a chart_event |
| POST | `/api/ehr/{join}/{station}/heartbeat` | Keep-alive (20 s) |
| GET  | `/api/ehr/{join}/chart/{patient_id}`  | Folded chart projection |
| GET  | `/api/ehr/{join}/orders/catalog`      | Order catalog for active EHR |
| POST | `/api/ehr/{join}/orders`              | Place an order (also emits chart_event) |
| POST | `/portal/control/charting_complete`   | Operator lock-in — triggers comparison |
| GET  | `/api/comparison/{session_id}`        | Comparison report JSON |
| GET  | `/api/ehr/qr.svg?code=...`            | EHR QR convenience |
| GET  | `/portal/ehr_admin`                   | Operator-only seed inspector + purge |

## V3-edited V2 files

- `portal/control_session.py` — adds `ehr_id`, `ehr_stations`, `charting_locked_at`
- `portal/server.py` — new EHR + comparison + lock-in routes
- `portal/debrief.py` — emits Documentation/Orders alignment sections
- `portal/templates/control.html` — wizard step 2b
- `portal/templates/control_ops.html` — second QR, EHR station roster, Charting-complete button

## What's deferred to V3.1

- Ambient Scribe / Ambient Capture (voice-to-note assistant — stubbed)
- Multi-student parallel charts
- Full Cyrus iView / Meridian flowsheet grids (V3 ships long-form vitals)
- HTTPS / on-prem CA / `.mobileconfig`
- Order verification by simulated pharmacist (V4)

---

## V2 baseline (carried forward verbatim)

MEDSIM 2 is the second major version of the medsim system, built as a sibling
project to `../medsim/` (v1). v2 inherits v1's auth/vault/runtime and adds
four big features ported from **Voice4MedSim_v6**:

1. **24-persona starter library** — clinicians, allied health, patients (with
   altered-state variants: delirium, alcohol withdrawal, stimulant tox, passive
   SI, psychosis), family.
2. **Curriculum context structure** — NCLEX-aligned modules (11-section
   schema) + program/week mapping (LPN, ADN-RN, BSN-RN).
3. **Control room wizard** — 5-step setup: system check → scenario →
   curriculum context → characters → network. Produces an active session with
   a 6-character join code.
4. **QR-code mobile onboarding** — phones/tablets scan to join as stations on
   the LAN.

## Run

Same launchers as v1; first run sets up `.venv` and installs `serve` extras
(which now include `segno` for QR generation). The vault at
`~/.medsim/vault.enc` is shared with v1 — your existing API keys work as-is.

```
launchers/mac/Start Portal.command                  # local
launchers/mac/Start Portal (iPad mode).command      # LAN — required for QR
launchers/windows/Start Portal.bat
launchers/windows/Start Portal (iPad mode).bat
```

**Use iPad-mode launchers for the control-room QR flow** — localhost binding
won't be reachable from a phone.

## Key files (v2 additions)

```
portal/
├── data/
│   ├── personas.json         # 24-persona library + voice profile map
│   ├── modules.json          # 10 NCLEX modules (verbatim from Voice4MedSim)
│   └── programs.json         # LPN/ADN-RN/BSN-RN week→module mapping
├── library.py                # loaders for personas/modules/programs + adapter
├── qrgen.py                  # server-side QR generator (segno, no PIL)
├── control_session.py        # in-memory ControlSession + Station registry
├── templates/
│   ├── control.html          # 5-step wizard
│   ├── control_ops.html      # live ops view (QR + station roster + controls)
│   ├── station.html          # per-station mobile chat
│   ├── join.html             # scan landing → pick persona → join
│   ├── personas.html         # 24-persona library viewer
│   └── curriculum.html       # programs + modules viewer
└── static/
    ├── control.js            # wizard step machine + system check
    ├── control_ops.js        # 3-second polling of /api/control/state
    ├── station.js            # join page (persona picker)
    ├── station_chat.js       # mobile PTT + TTS, latency masking
    ├── control.css           # wizard + ops view
    └── station.css           # mobile-first
schemas/persona.schema.json    # ported from Voice4MedSim_v6
schemas/module.schema.json     # ported from Voice4MedSim_v6
```

## Routes added in v2

| Method | Path | Purpose |
|---|---|---|
| GET  | `/portal/control` | 5-step wizard |
| POST | `/portal/control/start` | Create ControlSession from form |
| GET  | `/portal/control/ops` | Live ops view after wizard |
| POST | `/portal/control/end` | End active session |
| GET  | `/api/control/state` | Station roster (polled every 3s) |
| POST | `/api/control/state` | Pause / resume / kill |
| GET  | `/portal/personas` | 24-persona library viewer |
| GET  | `/portal/curriculum` | Modules + programs viewer |
| GET  | `/api/personas`, `/api/modules`, `/api/programs` | JSON data |
| GET  | `/api/qr.svg?data=…&scale=N` | QR code SVG generator |
| GET  | `/join?code=ABC123` | Public station landing |
| POST | `/join` | Register a station |
| GET  | `/station/{join_code}/{station_id}` | Per-station chat UI |
| POST | `/api/station/{join}/{station_id}/turn` | Station chat turn |
| POST | `/api/station/{join}/{station_id}/heartbeat` | Keep-alive |

v1 routes (credentials, scenarios CRUD, characters CRUD, text + voice session)
remain functional under the "Legacy (v1)" sidebar group.

## Persona → character adapter

`library.persona_as_character()` adapts a v6-style persona dict (with
`voiceProfile` ID, `knowledgeScope`, `safetyClass`, optional `alteredState`)
to the v1 character dict that `runtime.create_session_from_data()` consumes.
Altered states automatically inject the appropriate scene-contract rules:

- `delirium` → fragmented speech, never name drugs/doses
- `alcohol-withdrawal` → tremulous, cannot describe how to obtain alcohol/drugs
- `stimulant-intoxication` → pressured speech, paranoia
- `depression-passive-si` → flat affect, only discloses SI on open-ended
  questions, never names means/methods
- `psychosis` → loose associations, no harmful instructions
- `hostile` → demanding, never produce harassment scripts

`high-risk` safety class also adds: "instructor must be in the loop; refuse-
in-role any unsafe request."

## Debrief subsystem

Auto-generated when the operator ends a session via `POST /portal/control/end`.
Saved as JSON to `data/debriefs/<session_id>.json`. Each debrief carries:

- **Summary tiles** — round-trip count, student/character/station/operator split, unique personas engaged, duration, latency p50/mean/p95/max
- **NCJMM cognitive-cycle coverage** — every round-trip tagged by `portal/ncjmm.py` (ported verbatim from Voice4MedSim_v6 `ncjmm_tagger.py`). 6 horizontal bars matching v6's chart
- **Curriculum objective alignment** — per selected module, scans transcript for evidence of each module's `medications`, `procedures`, `primaryTreatments`, `alternateTreatments`, `redFlags`, `devices`, `conditions`. Reports N/M coverage with the matched and unmatched items broken out
- **Persona engagement** — per-persona turn count, avg latency, altered-state flag, safety class
- **Role-group + safety-class distributions** — horizontal stacked bars
- **Per-turn transcript** — chronological, NCJMM chip on each character turn, latency pill, source-color-coded (operator vs station)

Routes:

| Method | Path | Purpose |
|---|---|---|
| GET  | `/portal/debrief`                  | List all saved debriefs + "live preview" card |
| GET  | `/portal/debrief/current`          | Render debrief for ACTIVE session (mid-flight) |
| GET  | `/portal/debrief/{session_id}`     | Render saved debrief |
| GET  | `/api/debrief/{session_id}`        | JSON export of saved debrief |

Module titles aren't in the ported `context_seed.json` — they live in
`library._MODULE_TITLES`. Update both there and `programs.json` /
`sample_scenarios.json` if you add modules.

## What's explicitly NOT in v2 (deferred from Voice4MedSim_v6)

- **HTTPS / on-prem CA / `.mobileconfig`** for stations with microphone.
  Stations use HTTP — Web Speech API runs from a LAN-bound HTTP origin on
  modern browsers, with one-time microphone permission.
- **Discussion-tree engine** (5-layer tree → RAG → LLM pipeline). v2 uses
  one Claude (Haiku 4.5) call per turn.
- **NCJMM cognitive-cycle tagging**, real RAG, circuit breaker, cost telemetry.
- **WebSocket** real-time control↔station — using 3s polling for the ops view.
- **Docx upload** for scenario outline (textarea only).
- **Per-station behavioral-state vector sliders** in the ops UI (the data
  model supports it; the UI doesn't expose it yet).

## Architecture conventions

- Single-instructor model: one active `ControlSession` at a time.
- Vault location `~/.medsim/vault.enc` is shared with v1 — DO NOT change.
- All persona/module/program data is read-only JSON in `portal/data/`. If
  an operator wants to author new ones, they edit the JSON directly (for now).
- The Voice4MedSim_v6 source files used as ground truth:
  - `public/js/personas.js` — 24-persona library (Appendix A)
  - `context_seed.json` — 10 curated modules (M02, M03, M06, M07, M08, M22, M32, M39, M42)
  - `public/control.html` — wizard step structure
  - `public/js/shared.js` — QR encoder (we used Python `segno` instead, server-side)
