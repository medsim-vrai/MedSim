# M35 — Master Start/Pause/End controls + instructor auto-stations + engage deep-link

**Phase:** Phase 7 follow-on (post-M34, operator-feedback fix)
**Status:** **DONE**
**Blocked by:** M2 (Encounter dataclass), M4 (room API), M5 (control_room dashboard), M22 (Per-Patient Console), M33 (Engage button)
**Blocks:** none
**Estimated effort:** 1 day

---

## 1. Purpose

Operator feedback after M34:

> "On encounter control need to have in the header, start scenario
> (launching all scenarios at the same time) pause (pause all
> scenarios) and end (end/stop all scenarios and launch debrief)
> and in the individual encounter have the same headers structure
> but only impacting the specific encounter. For the stop the
> debrief is not called up until the main control page for
> encounter has stopped all the debriefs. Also for the instructor
> engagement in an encounter the instructor has an engagement
> button, this should not launch Join a MEDSIM 2 session this
> should happen behind the scene when the scenario is started by
> the master control in the main encounter page."

Four asks bundled into one module:

1. **Master Start / Pause / End on `/portal/room`.** Three buttons in
   the Multi-Patient Control header. Start launches every encounter
   simultaneously. Pause pauses everything. End stops everything *and*
   fires the cohort debrief (existing behavior — just renamed).
2. **Per-encounter Start / Pause / End on `/portal/room/encounter/{id}`.**
   Same shape, scoped to one bed.
3. **Per-encounter End does NOT save the cohort debrief.** That only
   happens on master End. Operator can wrap up beds one-by-one as
   students finish, then hit master End once to save the combined
   PEARLS debrief at the point all beds are done.
4. **Engage skips the public /join page entirely.** Master Start
   auto-registers an `INST-<persona_id>` chat station for every
   persona on every encounter. The Engage button on the Per-Patient
   Console voice card now deep-links straight into that station, so
   the instructor lands on the chat UI without typing a name or
   picking a persona.

## 2. Structure

### 2.1 State machine

```
                    Start
   configured  ───────────────▶   running
                                   │  ▲
                              Pause│  │Start
                                   ▼  │
                                  paused
                                   │
                                   │End (master or per-enc)
                                   ▼
                                  ended
```

`configured` is the dataclass default for a freshly-created encounter
(after `POST /api/room/start`). Master Start (or per-encounter Start)
is the trigger that moves it into `running`.

### 2.2 Files touched

- `portal/ws_room.py` — two new emitters: `emit_start_all(room_code,
  encounter_count)` and `emit_encounter_state(room_code, encounter_id,
  state)`.
- `portal/server.py` — five new routes + two helpers:
    - `POST /api/room/start_all` — master Start.
    - `POST /api/encounter/{id}/start` — per-encounter Start.
    - `POST /api/encounter/{id}/pause` — per-encounter Pause.
    - `POST /api/encounter/{id}/end`   — per-encounter End (no debrief).
    - `GET  /portal/engage/{encounter_id}/{persona_id}` — instructor
      engage deep-link.
    - `_instructor_station_id_for(persona_id)` — deterministic
      `"INST-{pid}"` station id (so lookups are O(1), no scans).
    - `_ensure_instructor_stations(enc)` — for each persona in
      `enc.selected_personas`, ensure a chat station exists with id
      `INST-<pid>` (idempotent).
- `portal/templates/control_room.html` — header rewired: `btn-start-all`
  (new) + `btn-freeze` (relabeled "⏸ Pause all") + `btn-end`
  (relabeled "⏹ End all (debrief)") + existing `btn-scene` /
  `btn-debrief`. `btn-resume` removed from the visible header (Start
  handles both first-launch and resume-after-pause).
- `portal/static/control_room.js` — wires `btn-start-all` to
  `/api/room/start_all`. Master End now follows the cohort_debrief_url
  in the response — instructor lands on the PEARLS debrief
  immediately, no manual click.
- `portal/templates/encounter_console.html` — three new buttons in
  `.console-header-right`: `btn-enc-start` (primary), `btn-enc-pause`
  (secondary), `btn-enc-end` (danger, with confirm dialog explaining
  the no-debrief contract).
- `portal/static/encounter_console.js` — wires the three new buttons
  and **rewrites the Engage anchor `href`** in `bootVoices()` from
  `/join?code={joinCode}` to
  `/portal/engage/{encounterId}/{persona_id}`.

### 2.3 Instructor station shape

The instructor station is a regular `Station` dataclass row in
`enc.stations`, distinguished by two markers:

| Field | Value |
|-------|-------|
| `station_id` | `INST-{persona_id}` (deterministic, prefix `INST-`) |
| `persona_id` | the persona this station plays |
| `user_agent` | `"instructor-engage"` (informational tag) |

No schema change. The `Station` table is in-memory only (matches the
M2 contract — chat stations live as long as the singleton).

## 3. Uses

### 3.1 Master control flow

1. Instructor finalizes the wizard → `/api/room/start` creates the
   room with N encounters all in state `configured`.
2. Instructor lands on `/portal/room`. Header shows
   *▶ Start all scenarios · ⏸ Pause all · ⚡ Inject scene · 📋 Cohort
   debrief · ⏹ End all (debrief)*.
3. Click **▶ Start all scenarios** → `POST /api/room/start_all`:
   - Every encounter's `state` becomes `running` (skipped if already
     `ended`).
   - For every persona in every encounter, an `INST-<pid>` station
     is created.
   - WS broadcast `start_all` so subscribed stations transition
     simultaneously.
   - Response: `{ok, status, encounter_count,
     instructor_stations_created}`.
4. Click **⏸ Pause all** → existing `POST /api/room/freeze_all`.
5. Click **⏹ End all (debrief)** → existing `POST /api/room/end` —
   saves cohort debrief, clears singleton, and (M35) the JS handler
   redirects directly to `cohort_debrief_url` in the response.

### 3.2 Per-encounter control flow

1. Instructor opens `/portal/room/encounter/{id}` (Per-Patient
   Console).
2. Header shows *▶ Start · ⏸ Pause · ⏹ End · 📋 Open EHR · ↗ Pop out*.
3. Click **▶ Start** → `POST /api/encounter/{id}/start`:
   - This encounter's `state` becomes `running`.
   - Instructor stations created for its personas.
   - State badge in the header updates live.
4. Click **⏸ Pause** → `POST /api/encounter/{id}/pause`.
5. Click **⏹ End** → confirm dialog: *"End this encounter? The bed
   will be marked ended but the cohort debrief is NOT saved until you
   press 'End all (debrief)' on the master control."* → `POST
   /api/encounter/{id}/end` → state becomes `ended`, NO cohort
   debrief is saved, singleton stays alive.

### 3.3 Engage flow

1. Instructor opens Per-Patient Console → voice card lists every
   persona.
2. Click **💬 Engage** on (say) the *Anxious Parent (P-015)* row.
3. Browser navigates to
   `/portal/engage/{encounter_id}/P-015` (new tab via
   `target="_blank"`).
4. Server resolves the encounter, ensures `INST-P-015` exists in
   `enc.stations` (lazy-create if master Start hasn't fired yet),
   303 redirects to `/station/{join_code}/INST-P-015`.
5. Instructor lands on the standard chat-station UI bound to the
   parent persona. No /join handshake. No name typed. No persona
   picker.

## 4. Functions (exported API surface)

| Symbol | Where | Purpose |
|--------|-------|---------|
| `POST /api/room/start_all` | `portal/server.py` | Master Start. |
| `POST /api/encounter/{id}/start` | `portal/server.py` | Per-encounter Start. |
| `POST /api/encounter/{id}/pause` | `portal/server.py` | Per-encounter Pause. |
| `POST /api/encounter/{id}/end` | `portal/server.py` | Per-encounter End (no debrief). |
| `GET  /portal/engage/{eid}/{pid}` | `portal/server.py` | 303 → `/station/{join}/INST-{pid}`. Lazy-creates the station. |
| `_instructor_station_id_for(pid)` | `portal/server.py` | Returns `"INST-{pid}"`. |
| `_ensure_instructor_stations(enc)` | `portal/server.py` | Idempotent helper used by all Start paths. |
| `emit_start_all(room_code, encounter_count)` | `portal/ws_room.py` | Broadcasts `{type: "start_all"}` on the room channel. |
| `emit_encounter_state(room_code, encounter_id, state)` | `portal/ws_room.py` | Broadcasts `{type: "encounter_state", encounter_id, payload: {state}}`. |

## 5. Limitations

- **Per-encounter Pause does not stop the bedside chat UI from
  *appearing* to accept input.** The student's chat station polls
  state every 2s and reacts then; sub-poll-cycle latency is the
  same as M16's freeze_all behavior. WS push exists
  (`emit_encounter_state`) but bedside JS does not yet subscribe to
  it — that's a future M36.
- **Master Start is idempotent but does not re-broadcast** a fresh
  `start_all` WS message on every click. If an instructor clicks
  Start, then Start again, only the first click fires WS (the second
  click still calls the route and returns OK, but most subscribers
  won't see anything new).
- **The instructor station has no chat history at lazy-create time.**
  If an instructor clicks Engage before master Start, the persona
  may not have warmed-up state from a previous turn. Acceptable —
  this is the safety-net path; the normal flow is master Start
  first.
- **`INST-{persona_id}` collides with a student-typed station_id
  if a real student deliberately picked an id starting with `INST-`**.
  Student ids are generated server-side (`secrets.token_urlsafe`) so
  this won't happen in practice; documented for future-proofing.
- **Per-encounter End sets `state="ended"` but does NOT remove the
  encounter from the room.** The dashboard still shows it; the badge
  reads `ENDED`. Master End is still the path that nukes the
  singleton + saves the debrief. This is the user-explicit contract.
- **The `btn-resume` button was removed from the master header
  visually but its JS handler remains** (defensive — cached stale
  DOM won't error). The `/api/room/resume_all` route also stays for
  v6-compat scripts and the per-encounter Start path effectively
  replaces it.
- **The cohort debrief auto-redirect on master End runs from the
  control_room.js handler.** If the JS doesn't run (e.g. instructor
  hit End from a non-JS client), the response body still contains
  `cohort_debrief_url` so manual navigation works.

## 6. Test status

| Test file | Asserts | Status | Last run |
|-----------|---------|--------|----------|
| `tests/v7/test_master_controls_and_engage.py::test_master_start_all_transitions_every_encounter_to_running` | All beds → running; INST-<pid> stations created for every persona | PASS | 2026-05-27 |
| `…::test_master_start_all_is_idempotent` | Second Start creates 0 new stations | PASS | 2026-05-27 |
| `…::test_pause_all_after_start_all_marks_every_encounter_paused` | After Start then freeze_all every state = paused | PASS | 2026-05-27 |
| `…::test_master_end_saves_cohort_debrief_and_clears_singleton` | Master End contract intact | PASS | 2026-05-27 |
| `…::test_per_encounter_start_sets_running_and_creates_instructor_stations` | One-bed Start scoped correctly; other beds untouched | PASS | 2026-05-27 |
| `…::test_per_encounter_pause_sets_paused` | One-bed Pause scoped correctly | PASS | 2026-05-27 |
| `…::test_per_encounter_end_marks_ended_but_NO_cohort_debrief` | Per-encounter End → state=ended, NO cohort file, singleton alive | PASS | 2026-05-27 |
| `…::test_per_encounter_routes_404_unknown_encounter` | Unknown encounter id → 404 on all three actions | PASS | 2026-05-27 |
| `…::test_engage_redirects_to_instructor_station_after_master_start` | After Start, engage → 303 to /station/{join}/INST-{pid} | PASS | 2026-05-27 |
| `…::test_engage_lazy_creates_station_before_master_start` | Engage works pre-Start; station lazy-created | PASS | 2026-05-27 |
| `…::test_engage_rejects_persona_not_on_encounter` | Engage with wrong persona → 404 | PASS | 2026-05-27 |
| `…::test_multi_patient_control_header_has_start_pause_end_buttons` | Master header has Start all / Pause all / End all (debrief) | PASS | 2026-05-27 |
| `…::test_per_patient_console_header_has_start_pause_end_buttons` | Console header has btn-enc-start / pause / end + confirm copy | PASS | 2026-05-27 |
| `…::test_encounter_console_js_uses_portal_engage_url_not_join` | Engage anchor href uses /portal/engage/, not /join?code= | PASS | 2026-05-27 |
| (regression update) `…test_encounter_console_js_renders_name_test_and_engage` | Asserts updated from `/join?code=` to `/portal/engage/` | PASS | 2026-05-27 |
| **Full v7 suite** | **231 passed, 1 skipped** (M20 Playwright skip — unchanged) | PASS | 2026-05-27 |

## 7. Change list

| Date | Author | Change | Files |
|------|--------|--------|-------|
| 2026-05-27 | claude-code | Initial M35 implementation: 5 new routes + 2 WS emitters + 2 helpers; master header rewired (Start all / Pause all / End all (debrief)); per-encounter header gets Start / Pause / End; engage URL flipped from /join to /portal/engage; 14 new tests; 1 phrase-only regression update | `portal/ws_room.py`, `portal/server.py`, `portal/templates/control_room.html`, `portal/static/control_room.js`, `portal/templates/encounter_console.html`, `portal/static/encounter_console.js`, `tests/v7/test_master_controls_and_engage.py` (new), `tests/v7/test_encounter_characters_voices_engage.py` (assertion text only) |

## 8. Open questions / known issues

- **Should bedside stations auto-disable input on per-encounter Pause?**
  Currently the 2s state poll is the latency. M16 has `emit_freeze_all`
  for master pause; M35 added `emit_encounter_state` but bedside JS
  doesn't subscribe yet. Tracked as a future M36.
- **Should master Start prevent students who haven't joined yet from
  joining mid-scenario?** Currently no — students can `/join?code=X`
  at any state. Acceptable for v7.0; we may add a "lock roster" flag
  on Start later.
- **Cohort debrief auto-redirect** could be opt-in. Some instructors
  may want to stay on the dashboard after End to discuss before
  reviewing the debrief. Trivial follow-up: a "Skip debrief" confirm
  variant.
- **Per-encounter Start when the encounter is `ended` is a no-op**
  (returns success but doesn't change state). We may want to reject
  it with a 409 to surface the bug-vs-intentional ambiguity. Out of
  scope today.

---

*Render this guide to PDF with `python docs/module_guides/render_pdfs.py`.*
