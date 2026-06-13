# Coding Plan — Educator GUI "Mission Control" (2026-06-13)

Implementation-grain plan for the consolidated best example in
`docs/gui-redesign/MedSimVRAI_GUI-Redesign-Report.pdf`. Built the same modular
stage→gate→commit way as FR-008/FR-009. Honors two hard requirements:
**(1)** the GUI is an ALTERNATIVE — the classic control room (FR-005) stays the
DEFAULT fallback, one click away on every screen; **(2)** NO data is lost on
pause/stop/restart (extends `Memory_management.MD` §7 **ADR-0018** from the
tablet to the portal).

## Ground rules (Memory_management §0/§3/§7)
- **One module per PR**; module boundaries in §3 are contracts — cross them only with an ADR (§7).
- The GUI is a NEW FRONT-END over the SAME portal APIs the control room uses — **no parallel backend logic** to drift.
- Snapshots are **structured-clone-safe, versioned, and PHI-FREE** — trainee free-text is never persisted (ADR-0014 fail-closed).
- Every stage: portal gate (`pytest tests/v8 tests/test_device_routes.py`) + client gate when TS touched (`typecheck · no-any · vitest · build`); one commit per stage.
- Supporting trackers: `docs/gui-redesign/MedSimVRAI_GUI-Redesign.xlsx` (screen + state inventories, backlog).

---

## G1 — Portal resumability layer  *(foundation; ship first)  [new ADR-00xx]*
**Files:** `portal/session_state.py` (new) · per-module `snapshot()/restore()` in
`control_session.py`, `med_orders.py`, `med_errors.py`, `handoff.py` (+ voice/skin
assignments) · `portal/server.py` (boot resume hook) · `tests/v8/test_session_state.py`
- **ADR first** (extends ADR-0018 server-side): "the portal aggregates per-module
  PHI-free snapshots into ONE versioned `SessionState` blob, persisted to the
  already-restart-durable SQLite (`~/.medsim/v7/medsim.db`) on every mutation +
  on shutdown; restored on boot." Add the §3/§7 rows.
- `session_state.snapshot() -> dict` aggregates `{"version":1, "saved_at":…, modules:{…}}`.
  Each module gains a pure `snapshot()` (PHI-free) and `restore(blob)`:
  - `control_session`: scenario id/name/notes, selected_personas, avatar_personas,
    ehr_id, stage, room+encounter shells (ids, join codes, patient_persona_id).
  - `med_orders._SESSION_MEDS`, `med_errors._SESSION_ERRORS` (incl. the chart-restore
    snapshot slot), `handoff._HANDOFFS` **minus survey free-text** (store q-ids +
    a numeric self-rating only; the raw voice answer is trainee PHI → excluded).
  - voice/skin assignments.
- `persist()` debounced write; `load_latest()/resume()` on boot (behind
  `MEDSIM_RESUME=1`, default on); `clear()`.
- **Tests:** snapshot round-trips each module; PHI-free assertion (no trainee
  free-text in the blob); version tolerance (unknown keys ignored on restore);
  a simulated "restart" (clear in-memory → restore) rebuilds the session;
  corrupt/missing blob → clean empty start (never crashes boot).
- *No UI yet — but the classic control room immediately benefits (restart-safe).*

## G2 — Readiness / health API + preflight-as-a-service
**Files:** `portal/readiness.py` (new) · `portal/readiness_routes.py` (new, auth'd) ·
`tests/v8/test_readiness.py`
- `readiness.snapshot() -> {checks:[{id,label,status:green|amber|red,detail,actions[]}]}`
  covering: portal, network+cert (wrap the `preflight.sh`/`cert-doctor` logic in
  Python — SAN-covers-IP, CA-trust hint), voice (provider reachable + key set),
  speech model warm (room_stt), per character/station (paired? WS? model warm?),
  devices, EHR, session (resumable snapshot present?).
- Action hooks (auth'd POST): `test_all`, `warm_speech`, `restart_hint`,
  `recheck_cert` — reuse FR-010 direction + `room_stt` warm; restart of the
  portal stays a documented instructor action (never self-triggered).
- Routes: `GET /api/control/readiness`, `POST /api/control/readiness/action {id}`.
- **Tests:** each check maps inputs→status deterministically (stub seams);
  amber/red transitions; action dispatch; auth.

## G3 — Mission Control shell + classic fallback
**Files:** `portal/templates/console.html` (new) · `portal/static/console.js`,
`console.css` (new) · `portal/server.py` (route `/portal/console`) ·
`tests/v8/test_console_routes.py`
- 3-mode shell (Set up · Operate · Debrief) + a persistent top **readiness bar**
  (polls G2) + **"Switch to classic control room ↗"** on every screen (→
  `/portal/control/setup`). Mode state in the URL (`?mode=operate`).
- **Tests:** route renders auth'd; the classic-control link is present; readiness
  bar fetches G2.

## G4 — Operate (Readiness Cockpit)
**Files:** `console.js` (extend) · `tests/v8/test_console_routes.py` (extend)
- Tile grid from `GET /api/control/readiness`; each tile = traffic light + status
  + inline actions (Test · Warm · Re-pair/Show-QR · Open · Restart-hint). **Resume
  banner** when a snapshot exists (G1) → `POST /api/control/session/resume`. "Test
  all" → G2 action. Live mgmt cards (meds/staged-errors/handoff) embed the EXISTING
  control APIs (no new logic).
- **Tests (portal):** resume endpoint restores; readiness reflects state. Client
  logic kept DOM-light/testable where it grows.

## G5 — Set up (Launch Wizard)
**Files:** `console.js` (extend) · reuse `sample_scenarios.json`/activities +
`POST /portal/control/start`
- Stepper (Scenario ▾ → Patients & rooms ▾ → Characters → Review) with template
  auto-fill (the same roster source single-patient uses; reuse the FR-fix that
  pulls a sample's full personas). Live **readiness preview** gates Launch.
  Launch posts the existing start flow (opens the live session). Pull-down /
  preset-driven throughout.
- **Tests:** wizard payload builds the same body as the classic start; template
  auto-fill picks the full roster; launch gated until green (rule unit-tested).

## G6 — Set up (Ecosystem board)
**Files:** `console.js` (extend) · `console.css`
- The attached layered model, interactive: rows (shared characters · shared
  resources · rooms/patients), cards with per-entity readiness dots, click→popover
  config via pull-downs (station type, voice, skin, devices, "stage error here").
  Same session model as the Wizard (toggle between views).
- **Tests:** board reads/writes the same config endpoints; no logic divergence
  from the Wizard (shared builder).

## G7 — Resume-on-boot + restore UX
**Files:** `portal/server.py` (boot) · `console.js`
- On portal boot, `session_state.resume()` auto-restores the last session (G1);
  the cockpit's Resume banner shows "Resumed 'X' (saved HH:MM)". Schema-versioned
  + tolerant. Subsumes FR-010's post-restart intent.
- **Tests:** boot-with-snapshot restores; boot-without is clean; stale/corrupt →
  offer New, never crash.

## G8 — Field validation + accessibility
**Files:** `docs/GUI-field-script.md` (new) · a11y pass on `console.*`
- One-page script: cold start via Wizard < target time; restart → Resume restores
  everything; cockpit Test-all + Warm; classic-control fallback works. Keyboard
  nav, contrast + shape-not-color-only traffic lights, large touch targets.
- **Gates:** full portal + client; live curl drills; restart note.

---

## Sequencing & rationale
**Foundation-first:** G1 (resumability) + G2 (readiness API) ship BEFORE any new
pixels — they remove the worst friction (restart wipes everything; "is it
working?") and are reused by the classic control room too, so value lands even if
the GUI is paused. Then G3 shell → G4 Operate (the highest-value screen) → G5
Wizard → G6 Board → G7 resume UX → G8 validation. Each stage independently
gated/committed; the classic control room is the default throughout.

## Open questions for ratification
1. Resume default-on (`MEDSIM_RESUME=1`) vs prompt-to-resume — recommend auto-restore + a visible "start new" escape.
2. Handoff survey answers in the snapshot: exclude entirely (recommended, PHI) vs store only the numeric self-rating.
3. Console route auth: same instructor vault as the control room (recommended).
4. Is "restart the portal" ever a GUI button (with confirm) or strictly a documented manual action? (Recommend manual; the GUI detects + resumes.)
