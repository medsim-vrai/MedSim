# M39 — Engage opens in-encounter modal, not a new tab

**Phase:** Phase 7 follow-on (post-M38, operator-feedback fix)
**Status:** **DONE**
**Blocked by:** M33 (Engage button on voice card), M35 (Engage deep-link route + instructor stations)
**Blocks:** none
**Estimated effort:** 0.5 day

---

## 1. Purpose

Operator feedback after M38:

> "The system audio is working but it jumps out of the encounter
> window to a station window. It should stay in the encounter
> window during the conversation if the conversation is prompted
> from the encounter module."

M33 + M35 wired the Engage button as `<a target="_blank">`, which
spawns a new browser tab. The instructor loses the encounter
console context (telemetry, ECG, devices, scene injector) the
moment they click into the chat. That's the wrong UX for an
instructor playing a character — the console is exactly where they
want to be when deciding what the character should say next.

M39 keeps the chat inside the encounter window via a modal
`<dialog>` containing an iframe pointed at the existing
`/portal/engage/{encounter_id}/{persona_id}` route. The iframe
inherits cookies, follows the 303 to `/station/{join}/INST-{pid}`,
and renders the same chat UI we already had — TTS / STT / heartbeat
all intact (M37 audio reset + M38 key live-refresh still apply
unchanged).

Closing the dialog blanks the iframe src so any in-flight audio
inside it stops cleanly. A "↗ Pop out" affordance inside the dialog
keeps the old new-window behavior available for operators who want
to drag the chat to a second monitor.

## 2. Structure

**Files touched:**
- `portal/templates/encounter_console.html` — appended a `<dialog
  id="engage-dialog">` element at the end of the content block
  (outside `.console-grid`). The dialog body is an
  `<iframe id="engage-dialog-frame" src="about:blank"
  allow="microphone; autoplay">`. Header carries the modal title
  (set dynamically to `💬 Engage · <persona name>`), a "↗ Pop out"
  link, and a "✕ Close" button.
- `portal/static/encounter_console.js`:
  - The engage element in the voice grid (rendered by
    `bootVoices()`) changed from `<a target="_blank" href=…>` to
    `<button class="char-engage">` with `data-persona`,
    `data-persona-name`, and `data-engage-href` attributes.
  - New click handler binds each button to `openEngageDialog(btn)`.
  - New `openEngageDialog(btn)` reads the button's data attrs, sets
    the iframe src + dialog title + popout href, and calls
    `dialog.showModal()` (with a fallback to `setAttribute("open")`
    for browsers that don't support the native modal API).
  - `DOMContentLoaded` handler wires the close button + the
    native `close` event to blank the iframe src.
- `portal/static/encounter_console.css` — `.engage-dialog`,
  `.engage-dialog::backdrop`, `.engage-dialog-header`,
  `.engage-dialog-actions`, `.engage-dialog-popout`,
  `.engage-dialog-close`, `.engage-dialog-frame` styles.
  Dialog is `min(900px, 92vw)` wide × `min(720px, 88vh)` tall,
  with a dark blue header bar (`#143b8a` matching the brand) and
  a translucent backdrop.

**No backend change.** The `/portal/engage/{eid}/{pid}` route is
unchanged (still 303s to `/station/{join}/INST-{pid}`). The
station chat template, JS, and TTS path are all unchanged.

**No schema migration. No new dataclass field.**

## 3. Uses

### 3.1 Instructor flow (in-encounter chat)

1. Instructor is on `/portal/room/encounter/{id}`.
2. Voice card lists every persona on the bed.
3. Click **💬 Engage** on a row.
4. `openEngageDialog(btn)` runs:
   - Reads `btn.dataset.engageHref` →
     `/portal/engage/{eid}/{persona_id}`.
   - Sets iframe `src` to that URL.
   - Sets dialog title to `💬 Engage · <persona display name>`.
   - Sets popout href to the same URL.
   - Calls `dialog.showModal()` — overlay appears centered on top
     of the console with a darkened backdrop.
5. Inside the iframe: the engage route 303s through to
   `/station/{join}/INST-{persona_id}`. Standard station chat UI
   loads (PTT button, mode toggle, chat log). Mic permission is
   inherited via `allow="microphone; autoplay"`.
6. Instructor presses PTT, speaks. STT → POST `/turn` → Haiku reply
   → TTS playback. M37 audio reset is in effect, M38 key live-
   refresh is in effect. Audio plays inside the iframe; the
   encounter console (telemetry, ECG, devices) remains visible
   behind the backdrop.
7. To return to the console: click **✕ Close** or press ESC. The
   `close` event handler sets `frame.src = "about:blank"` which
   tears down the in-flight `<audio>` element inside the iframe
   and the chat UI page itself — no zombie playback.

### 3.2 Pop-out path (preserved)

The "↗ Pop out" link inside the dialog header is a plain
`<a target="_blank">` pointing at the same engage URL. Operators
who want to drag the chat to a second monitor still can — they
just close the dialog and reopen the chat as a separate tab.

### 3.3 Multiple engages

Clicking Engage on a DIFFERENT persona while the dialog is open
sets the iframe to the new persona's URL — same dialog instance,
src swap. Setting iframe src on a live element triggers a full
page reload inside the frame; the previous chat session's mic
release + audio teardown happen naturally as the page unloads.

## 4. Functions (exported API surface)

| Symbol | Where | Purpose |
|--------|-------|---------|
| `openEngageDialog(btn)` (new) | `portal/static/encounter_console.js` | Read button data-attrs, set iframe src + dialog title + popout href, show the modal. |
| (close handlers) | same | Blank iframe src on `close` button click and on the native `<dialog>` `close` event (ESC key). |
| (rendered by `bootVoices`) | `<button class="char-engage" data-*>` | Per-persona engage triggers in the voice grid. |
| (markup) | `<dialog id="engage-dialog">` in `encounter_console.html` | Modal container with iframe + header (title + popout + close). |

## 5. Limitations

- **Iframe inherits the console's cookies + storage.** That's how
  the engage route's `require_vault` dependency authenticates.
  Acceptable; same-origin iframe is the simplest path.
- **Iframe height is fixed at 88vh — long chat logs scroll inside
  the iframe.** Acceptable; matches the station-page behavior. A
  future M40 could make the dialog vertically resizable.
- **The native `<dialog>` API ships in modern browsers
  (Chrome 37+, Firefox 98+, Safari 15.4+).** The JS uses
  `showModal()` if available with a fallback to
  `setAttribute("open")` for older engines (which renders the
  dialog non-modally — still visible, just without the focus
  trap). The fallback is unlikely to be exercised in practice
  given the operator workstation profile.
- **Iframe `<audio>` cleanup relies on src="about:blank" on close.**
  This works because navigating an iframe unloads the previous
  page, which fires the chat JS's pagehide listeners (and the
  browser tears down the `<audio>` element). If a future
  station_chat.js doesn't clean up on pagehide, audio could leak.
  Documented; not seen in practice today.
- **The encounter console's polling continues while the dialog is
  open** (telemetry, transcript, state). Acceptable; the dialog
  doesn't pause the console, and a backdrop-click does not close
  the dialog (only the explicit Close button or ESC), so the
  instructor can't accidentally lose chat context.
- **No keyboard shortcut to open Engage.** Operators must click.
  Out of scope; clicks are also what the iPad operator uses.
- **The dialog title shows only the persona name + display name.**
  Could also show role/voice id, but visual noise wasn't worth
  it. Refine in a future M40 if operators ask.

## 6. Test status

| Test file | Asserts | Status | Last run |
|-----------|---------|--------|----------|
| `tests/v7/test_engage_modal_dialog.py::test_encounter_console_includes_engage_dialog_markup` | Console carries `<dialog id="engage-dialog">` + iframe + close + popout + mic-allow attrs | PASS | 2026-05-27 |
| `…::test_engage_dialog_starts_with_blank_iframe_src` | iframe initial `src="about:blank"` (no eager chat-session preload) | PASS | 2026-05-27 |
| `…::test_engage_js_uses_button_and_opens_dialog_not_new_tab` | Engage element is `<button>` (no `target="_blank"`), `openEngageDialog` function exists, click handler wired, `showModal` + `close` + frame-blanking present | PASS | 2026-05-27 |
| `…::test_engage_dialog_popout_link_uses_engage_href` | The "↗ Pop out" anchor's href is set from `btn.dataset.engageHref` inside `openEngageDialog` | PASS | 2026-05-27 |
| `…::test_engage_button_carries_required_data_attributes` | Rendered button has `data-persona`, `data-persona-name`, `data-engage-href` so the click handler can wire the dialog | PASS | 2026-05-27 |
| **Full v7 suite** | **255 passed, 1 skipped** (M20 Playwright skip — unchanged) | PASS | 2026-05-27 |

## 7. Change list

| Date | Author | Change | Files |
|------|--------|--------|-------|
| 2026-05-27 | claude-code | Initial M39 implementation: dialog markup + iframe; bootVoices renders engage as `<button>`; openEngageDialog + close handlers; dialog CSS; 5 new tests | `portal/templates/encounter_console.html`, `portal/static/encounter_console.{js,css}`, `tests/v7/test_engage_modal_dialog.py` (new) |

## 8. Open questions / known issues

- **Should backdrop-click close the dialog?** Today only explicit
  Close button + ESC close. Backdrop-click would match common
  modal UX but risks losing chat state on accidental clicks. Stuck
  with safer default for now.
- **Should the dialog persist its position/size across opens?**
  Probably not — operators rarely customize. The fixed centered
  placement is fine.
- **A "↘ Minimize" toggle (collapse the chat to a corner pill)
  could be useful** for an operator who wants to inject scenes from
  the console without closing the chat. Out of scope for M39; a
  future M40 could add it.
- **The iframe currently re-loads the chat UI from scratch on each
  Engage click.** That means the chat history (stored in
  `enc.stations[INST-pid].history`) is server-side persistent —
  good, you don't lose context — but the visible chat-log resets
  to whatever the chat template renders on load. Operators may
  expect to "pick up where we left off"; verify in LAN test
  whether this needs additional state-restore on the chat UI.

---

*Render this guide to PDF with `python docs/module_guides/render_pdfs.py`.*
