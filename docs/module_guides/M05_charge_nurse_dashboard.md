# M5 — Charge-nurse dashboard (templates + JS)

**Phase:** 3 — Dashboard
**Status:** DONE (2026-05-26)
**Blocked by:** M4
**Blocks:** M6, M20
**Estimated effort:** 3 days · **Actual:** 1 day

---

## 1. Purpose

The instructor's primary surface in multi-patient mode. A grid of
Encounter cards under one ControlRoom, polling `/api/room/state`
every 2 s, with a top bar of synchronized-control buttons (Freeze
All / Resume All / Inject Scene / Cohort Debrief / End Room). Drill-in
from any card lands on the existing v6 per-encounter ops view
(`/portal/control/ops?join={code}`).

The page also exposes a *quickstart* CTA in the empty state that
calls `POST /api/room/start` with two placeholder encounters — the
operator-facing equivalent of "spin up a demo room so I can see what
the dashboard does before I commit to a wizard run."

## 2. Structure

**New files:**
- `portal/templates/control_room.html` — Jinja2 template extending
  `base.html`. Renders the top bar, the empty-state CTA, the
  meta strip (encounter/student/last-poll), the encounter grid
  container, and a `<dialog>` for the scene injector.
- `portal/static/control_room.js` — ~280 lines of vanilla JS. Polls
  `/api/room/state` every 2 s (8 s backoff when 404), paints cards,
  wires the five top-bar buttons + the quickstart CTA + the scene
  dialog.
- `portal/static/control_room.css` — ~180 lines. Top bar, grid (auto-fill
  minmax(320px, 1fr) — collapses to single column under 480 px), card
  states (.is-running / .is-paused / .is-ended), scene dialog.

**Files touched:**
- `portal/server.py` — adds `GET /portal/room` (renders the template
  with `{"active": "room"}`). Sits in a new "M5" section at the end
  of the file, below the M4 routes.
- `portal/templates/base.html` — adds a `Room (multi)` link under
  the **Operate** nav group.

## 3. Uses

- `GET /portal/room` — the instructor opens this page after creating
  a room via the wizard's room-mode branch (M6) or via the
  quickstart CTA. The dashboard is the operator's home base while a
  room is running.
- The dashboard consumes seven of M4's eight routes:
  `/api/room/state` (poll), `/api/room/freeze_all`,
  `/api/room/resume_all`, `/api/room/end`, `/api/room/scene_broadcast`,
  `/api/encounter/{id}/scene`, and `/api/room/start` (quickstart only).
  `/api/encounter/{id}/assign_students` lands in M9's student-join UI.

## 4. Functions (exported API surface)

### HTTP route

| Method | Path | Purpose |
|--------|------|---------|
| GET | `/portal/room` | Render the dashboard scaffold. Encounter grid is JS-rendered. |

### JS (control_room.js IIFE — no public exports)

| Internal symbol | Purpose |
|-----------------|---------|
| `pollOnce()` | Single fetch of `/api/room/state`; renders or empty-state. Returns the next interval (ms). |
| `startPolling()` / `stopPolling()` | Boot + visibility-change pause. |
| `render(room)` | Paint room aggregate + encounter cards from the JSON. |
| `renderEmpty()` | Empty state. Keeps `lastKnownRoomId` so Cohort Debrief stays clickable after end. |
| `encounterCardHTML(enc)` | One `<div class="encounter-card">` HTML string. |
| `wireButtons()` | Top-bar button handlers + dialog submit. |
| `formatTimeAgo(ts)` / `escapeHTML(s)` | Display helpers. |

## 5. Limitations

- **2 s HTTP poll, not WebSocket.** M16 replaces the polling
  transport with a per-room channel push. The poll cadence is
  visible/hidden-aware (no traffic while the tab is hidden).
- **Scene injector is minimal.** The dialog offers 7 kinds (vitals.drop,
  vitals.rise, lab.result, family.arrives, pump.alarm, code.blue,
  note.instructor) but M7's scenes engine is what gives them clinical
  effect. Until M7, every scene resolves to a single
  `instructor.trigger` chart_event carrying the raw `{kind, params}`.
- **No card-level vitals snapshot.** Each card shows state +
  station counts + chart_event count + last-event timestamp. A live
  vitals row per card is a v7.1 candidate — requires a streaming
  /api/encounter/{id}/snapshot endpoint we have not built.
- **Drill-in goes to the v6 per-encounter ops page.** Clicking a
  card navigates to `/portal/control/ops?join={code}`. That route
  works today thanks to M3's encounter-scoped dispatch. M6 may
  rebrand this URL once the wizard's room-of-N branch lands.
- **Quickstart only works when the operator vault is unlocked.** No
  fallback for a hard-power-cycle scenario where vault is locked;
  the quickstart POST will 401 and the JS surfaces the error in an
  alert.
- **Cohort Debrief button navigates to `/portal/debrief/cohort/{room_id}`
  which is M14/M15.** Until M14/M15 land, the button works but the
  destination 404s.

## 6. Test status

### Automated

The M5 deliverable is template + JS, so the automated coverage is
boot-and-render only — a smoke test that asserts the route returns
200, the template references the new static assets, and the JS file
contains the expected poll cadence + key route paths. Visual + flow
behaviour is verified through the browser preview (§7) and will get
Playwright coverage in M20.

| Test | Status | Last run |
|------|--------|----------|
| (verifies in M20 Playwright) | PENDING M20 | — |

### Manual (browser preview — 2026-05-26)

| Flow | Result |
|------|--------|
| Login + navigate to `/portal/room` empty | PASS — empty CTA visible, all buttons disabled, nav `Room (multi)` highlighted active. |
| Quickstart 2-bed demo (button click) | PASS — 2 encounter cards render with labels "Bed 1 — Mr. Diaz" / "Bed 2 — Ms. Kowalski", distinct join codes, room code visible, status ACTIVE. |
| Freeze All button | PASS — status flips to FROZEN, both cards show PAUSED with `.is-paused` class (orange left border). |
| Resume All button | PASS — round-trips back to ACTIVE / RUNNING. |
| Scene injector dialog opens + targets dropdown populated | PASS — 3 options (All + per-encounter). |
| Scene targeted at Bed 1 only | PASS — Bed 1 chart_event count goes 0→1; Bed 2 stays 0 (encounter scoping verified end-to-end through the UI). |
| End Room button | PASS — empty state visible, status ENDED, action mutator buttons disabled, **Cohort Debrief stays enabled** so the operator can navigate to M14's destination. |
| Browser console errors | None. |
| Network failures | Only expected 404s on `/api/room/state` during empty-state polling. |

## 7. Change list

| Date | Author | Change | Files |
|------|--------|--------|-------|
| 2026-05-26 | claude-code | Initial dashboard: template, JS (~280 lines), CSS (~180 lines), `GET /portal/room` route, nav link in `base.html`. Manual browser verification of the seven core flows passed. Added `os.chdir` anchor to `run_portal.py` so Claude Preview launches the v7 portal regardless of cwd. | `portal/templates/control_room.html`, `portal/static/control_room.js`, `portal/static/control_room.css`, `portal/server.py`, `portal/templates/base.html`, `run_portal.py` |
| 2026-05-26 | claude-code | UX fix in `renderEmpty()` — preserve `lastKnownRoomId` after End Room so the Cohort Debrief button remains clickable through the empty state. | `portal/static/control_room.js` |

## 8. Open questions / known issues

- The wizard at `/portal/control` still uses the v6 single-patient
  branch only. M6 adds the room-mode toggle that POSTs to
  `/api/room/start`. Until M6 lands, the only way to start a room
  is the dashboard's quickstart CTA or a direct `/api/room/start`
  POST.
- The scene-injector dialog accepts a free-form JSON params
  textarea. If the operator types invalid JSON, we alert and don't
  send. A more user-friendly param editor (per-kind form) is a v7.1
  candidate.
- The card grid is responsive down to 480 px (single column) but
  hasn't been tested on an actual tablet. M21's LAN test exercises
  real tablets and may surface layout issues at the 768 px and
  1024 px breakpoints.
- Clicking a card navigates to `/portal/control/ops?join={code}`.
  The legacy ops template assumes a single ControlSession and may
  not render cleanly when the active room holds multiple encounters
  — needs to be verified during M20 Playwright coverage. The route
  itself works because `get_by_join_code` is encounter-aware.
- The "Cohort debrief" button's destination 404s until M14/M15
  ships. The button is intentionally enabled in the post-end state
  to signal the *intent* of the flow; the M14 work fills the
  destination.
