# M34 — Per-encounter instructor EHR launch button

**Phase:** Phase 7 follow-on (post-M33, operator-feedback fix)
**Status:** **DONE**
**Blocked by:** M2 (Encounter dataclass is a ControlSession), M22 (Per-Patient Console scaffold), M31 (per-encounter `ehr_id`)
**Blocks:** none
**Estimated effort:** 0.5 day

---

## 1. Purpose

Operator feedback after M33:

> "I need to be able to launch and access the medical records from
> the encounter page as the instructor, and launch the system into
> a new window."

The Per-Patient Console at `/portal/room/encounter/{id}` had every
instructor surface for a bed *except* a direct EHR launch. The
existing v6 route `/portal/control/launch_ehr` doesn't work in
multi-encounter rooms — it calls `control_session.get_active()`
which (per the M2 contract fix) returns `None` whenever the active
room has more than one encounter, dropping the instructor back at
the wizard.

M34 adds a v7-aware twin keyed to a specific encounter, and a
prominent **📋 Open EHR ({ehr_id})** button in the console header
that opens that route in a new browser tab. A second discovery
point lives inside the QR-codes card under the EHR station cell:
**📋 Open EHR on this device** — for instructors who arrive at the
QR card looking for how to get the chart up.

Both links use `target="_blank" rel="noopener"`, so the instructor
keeps the Per-Patient Console open on one monitor while the EHR
chart opens on another.

## 2. Structure

**Files touched:**
- `portal/server.py` — two new routes near the existing
  `control_launch_ehr_get/post`:
    - `GET /portal/room/encounter/{encounter_id}/launch_ehr` —
      303 redirect into `/ehr/{join_code}/{station_id}` after
      registering (or reusing) a control-room EHR station for that
      encounter. Reuses the existing `_launch_ehr_station(sess)`
      helper verbatim — the v7 `Encounter` dataclass *is* a
      `ControlSession` (M2 rename, not a re-implementation), so
      the helper accepts it as-is.
    - `POST /portal/room/encounter/{encounter_id}/launch_ehr` —
      JSON `{ok, url, ehr_id, station_id, encounter_id, reused}`
      flavor for programmatic callers.
- `portal/templates/encounter_console.html` —
    - Header now carries either a green primary `<a id="btn-launch-ehr">`
      action linking to the launch route (with `target="_blank"`), or
      a disabled `<span>` when the encounter has no EHR configured.
    - QR card's EHR cell carries a `📋 Open EHR on this device`
      link (`.qr-launch-here`) for inline discovery.
- `portal/static/encounter_console.css` — `.header-action` (green
  CTA) + `.header-action-disabled` (muted gray) + `.qr-launch-here`
  styles.

**No schema migration. No dataclass change.** The
`encounter.ehr_id` field has existed since M2.

## 3. Uses

### 3.1 Instructor flow

1. Instructor lands on `/portal/room/encounter/{id}` (the
   Per-Patient Console for one bed).
2. Header renders a green **📋 Open EHR (helix)** anchor (or
   whichever `ehr_id` is configured) — assuming the row has an EHR
   picked. Otherwise renders a muted **📋 No EHR configured** state
   with a tooltip pointing back at the wizard.
3. Click → `GET /portal/room/encounter/{id}/launch_ehr` opens in a
   new tab.
4. Server resolves the encounter from `_require_active_room().encounters`,
   calls `_launch_ehr_station(enc)`:
   - First time: creates a new `ES-{token}` station, attaches it to
     the encounter + writes through `ehr_db.register_station`.
   - Repeat call: finds the still-online station whose
     `device_label == "Control room (instructor)"` and reuses it
     (no station pile-up on repeated clicks).
5. 303 → `/ehr/{join_code}/{station_id}` — the unified EHR bundle
   loads. Same template + JSX the student-joined EHR stations use
   (`portal/ehr/_core/index.html` + `ehr_app.jsx`), themed by the
   bootstrap JSON's `EHR_ID`.

### 3.2 Side-by-side workflow

`target="_blank" rel="noopener"` means the EHR opens in its own
browser tab; the instructor can drag it to a second monitor and
keep the Per-Patient Console + EHR side by side. This was the
explicit operator ask — "launch the system into a new window".

### 3.3 The QR card discovery path

The QR card's EHR cell still shows the student-facing QR + join
URL, but adds a green `📋 Open EHR on this device` link
underneath. So an instructor who walks the QR card looking for
"how does the chart open" finds the button right where they're
already looking.

## 4. Functions (exported API surface)

| Symbol | Where | Purpose |
|--------|-------|---------|
| `GET  /portal/room/encounter/{id}/launch_ehr` | `portal/server.py` | 303 redirect into the EHR bundle for THIS encounter. Falls back to console with `?ehr=unconfigured` when no EHR is configured. |
| `POST /portal/room/encounter/{id}/launch_ehr` | `portal/server.py` | JSON `{ok, url, ehr_id, station_id, encounter_id, reused}`. 409 when no EHR; 404 when encounter is unknown. |
| `_launch_ehr_station(sess)` | `portal/server.py` | (existing, M9-era) Register or reuse the control-room EHR station for a given ControlSession/Encounter. Reused verbatim. |

## 5. Limitations

- **Header label hard-codes the `ehr_id` string** (e.g. "Open EHR
  (helix)"). The EHR `name` from the `ehrs` catalog (e.g. "Helix
  EMR") would read nicer; the encounter dataclass only carries the
  short id today. A future M35 could pass the catalog entry down.
- **Repeat-launch reuses the station only while it is `online`.**
  If the instructor closes the EHR tab and the heartbeat times out,
  the next launch will allocate a fresh `ES-` station instead of
  reviving the old one. That's the M9 contract — `_launch_ehr_station`
  scans `sess.ehr_stations.values()` filtering `s.online`. Acceptable
  for instructor stations; we don't surface them in the cohort
  debrief facets anyway.
- **No popup-blocker fallback.** The header button is an `<a>` with
  `target="_blank"`, which all major browsers allow as a direct user
  gesture. We are not using `window.open` from JS, so popup blockers
  don't see this as a popup. No fallback path needed.
- **Disabled state still shows even when the encounter is frozen.**
  If we ever want to grey out the launch action mid-freeze, we'd
  add an `encounter.state == "frozen"` check in the template. Out of
  scope today — freezing pauses input but does not lock the chart.

## 6. Test status

| Test file | Asserts | Status | Last run |
|-----------|---------|--------|----------|
| `tests/v7/test_encounter_launch_ehr.py::test_per_encounter_launch_ehr_redirects_to_chart` | GET returns 303 → `/ehr/{join}/<ES-…>` | PASS | 2026-05-27 |
| `…::test_per_encounter_launch_ehr_post_returns_url_json` | POST returns `{ok, url, ehr_id, station_id, encounter_id, reused}` | PASS | 2026-05-27 |
| `…::test_per_encounter_launch_ehr_reuses_station_on_repeat` | Second launch returns same station_id + `reused=true` | PASS | 2026-05-27 |
| `…::test_per_encounter_launch_ehr_no_ehr_redirects_to_console` | GET → 303 back to console with `?ehr=unconfigured`; POST → 409 | PASS | 2026-05-27 |
| `…::test_per_encounter_launch_ehr_unknown_encounter_returns_404` | Unknown encounter id → 404 on both methods | PASS | 2026-05-27 |
| `…::test_console_header_renders_open_ehr_button` | Header has `#btn-launch-ehr` linking to the route, `target=_blank`, label mentions ehr_id | PASS | 2026-05-27 |
| `…::test_console_header_shows_disabled_state_when_no_ehr` | No-EHR encounter → header shows muted "No EHR configured" span instead | PASS | 2026-05-27 |
| `…::test_qr_card_shows_open_ehr_on_this_device_link` | QR card carries the inline `.qr-launch-here` link | PASS | 2026-05-27 |
| **Full v7 suite** | **217 passed, 1 skipped** (M20 Playwright skip — unchanged) | PASS | 2026-05-27 |

## 7. Change list

| Date | Author | Change | Files |
|------|--------|--------|-------|
| 2026-05-27 | claude-code | Initial M34 implementation: GET+POST per-encounter launch_ehr routes; header button + disabled state; QR-card inline link; CSS; 8 new tests | `portal/server.py`, `portal/templates/encounter_console.html`, `portal/static/encounter_console.css`, `tests/v7/test_encounter_launch_ehr.py` (new) |

## 8. Open questions / known issues

- **Should the launch route honor `private_clone` chart mode?**
  Today it launches the instructor against the template encounter's
  chart. If the bed is in `private_clone` mode, each student has
  their own clone — the instructor's launch hits the template, not
  any one student's chart. That matches the v6 ops-view behavior
  but may surprise a new instructor. Tracked as a potential M35
  follow-up: optionally let the launch button pick a clone.
- **Disabled state copy is operator-friendly but not actionable.**
  We could turn the disabled span into a link to the wizard with
  the encounter id pre-selected — but only if the room is still in
  setup state, which after `/api/room/start` is never. So a
  configured-after-start workflow would need a "change EHR for
  this bed" surface (out of scope).
- **The `?ehr=unconfigured` query hint is set but not consumed.**
  The console JS does not display a toast for it today. Adding one
  is a 10-line change; deferred until an instructor actually trips
  the case in practice.

---

*Render this guide to PDF with `python docs/module_guides/render_pdfs.py`.*
