# M33 — Character names + voice test + engage on the Per-Patient Console

**Phase:** Phase 7 follow-on (post-M32, operator-feedback fix)
**Status:** **DONE**
**Blocked by:** M30 (voice picker card scaffold), M31 (per-row persona multi-select)
**Blocks:** none
**Estimated effort:** 0.5 day

---

## 1. Purpose

Operator feedback on the Per-Patient Console:

> "On the individual encounter control pages, use the character
> names rather than the character code on the pull down for the
> selecting patient voices. Have a button to check voice sound.
> Also list all the characters for the scenario so that the
> instructor can engage the character from the control page for
> the encounter control page."

Three changes, all on the voice card (`#card-voice`):

1. **Display names instead of IDs.** Each row now reads `Mr. Hayes`
   (with a small role tag like `Hyperactive Delirium` and the raw
   `P-014` shown as a faint monospace pid below the name) — not
   the bare `P-014` it showed before.
2. **▶ Test button.** A per-row preview button synthesizes a sample
   phrase ("Hello, I'm Mr. Hayes. This is what my voice sounds like
   in the simulation.") via the selected ElevenLabs voice and plays
   it in the browser. Rows with no voice picked use browser
   SpeechSynthesis as a fallback so the instructor at least hears
   the default voice.
3. **💬 Engage button.** A per-row link opens
   `/join?code={join_code}` in a popup tab so the instructor can
   pick that character and chat as them — turning the encounter
   console into the launchpad for instructor-driven character
   role-play. The card's heading is renamed from
   *"🎙 Character voices"* to *"🎙 Characters · voices · engage"*
   to reflect the three-job role.

The card is now a single source-of-truth for the persona roster
on this encounter: list, pick voice, preview voice, engage. No
separate "Characters" card was added — the consolidation kept the
console grid tidy.

## 2. Structure

**Files touched:**
- `portal/server.py` — `api_encounter_voices_get` (route
  `GET /api/encounter/{id}/voices`) now hydrates each selected
  persona id through `library.get_persona()` and returns:
    - `personas` — array of `{id, name, role}` triples
    - `join_code` — the encounter's join code, echoed so the
      client can build the Engage link without an extra round-trip
  - Backward-compat fields `selected_personas`, `patient_persona_id`,
    `voice_assignments` are preserved exactly.
- `portal/templates/encounter_console.html` — `<h2>` of `#card-voice`
  renamed from "🎙 Character voices" to
  "🎙 Characters · voices · engage"; help paragraph rewritten to
  document the ▶ Test and 💬 Engage controls.
- `portal/static/encounter_console.js` — `bootVoices()` rebuilt:
  reads the new `personas` array (with name + role); each row now
  has a `.char-label` block (name + role tag + faint pid), the
  existing `<select>`, and a `.char-actions` block with `▶ Test`
  + `💬 Engage`. New `testVoiceForRow(btn)` function handles the
  preview (POST `/api/tts` for ElevenLabs voices, browser
  SpeechSynthesis as fallback).
- `portal/static/encounter_console.css` — `.voice-row` regridded to
  three columns (label | select | actions) with mobile collapse to
  one column; new `.char-name`, `.char-role-tag`,
  `.char-role-tag.patient`, `.char-pid`, `.char-actions`,
  `.char-test`, `.char-engage` styles.

**No schema migration.** No new dataclass fields.

## 3. Uses

### 3.1 Operator flow

1. Instructor opens `/portal/room/encounter/{id}` (the Per-Patient
   Console for a single bed).
2. Voice card boots — `bootVoices()` fetches `/api/voices` (the
   ElevenLabs voice catalog) and `/api/encounter/{id}/voices` (the
   per-encounter persona roster + saved assignments).
3. Card renders one row per persona, ordered by `selected_personas`.
   The patient's row is tagged with a `patient` role badge; non-
   patient rows show their persona-library role (e.g.
   `Anxious Spouse`, `Charge RN`, `Pediatric Patient`).
4. Instructor picks a voice → `change` handler POSTs to
   `/api/encounter/{id}/voices` and writes `enc.voice_assignments`
   (same path as M30).
5. Instructor clicks **▶ Test** → `testVoiceForRow()`:
   - If voice_id is set: `POST /api/tts` with the sample text +
     voice_id, gets back the audio stream, plays it via a transient
     `<audio>` element + `URL.revokeObjectURL` cleanup.
   - If voice_id is empty: uses `SpeechSynthesis` for an offline
     fallback preview.
6. Instructor clicks **💬 Engage** → opens `/join?code={join_code}`
   in a new tab (`target="_blank" rel="noopener"`); they pick the
   target persona from the join flow's existing picker and chat as
   that character.

### 3.2 Data flow

```
GET /api/encounter/{id}/voices
   ↳ library.get_persona(pid) per pid in enc.selected_personas
   ↳ {personas: [{id,name,role}], join_code, voice_assignments, ...}
       ↳ bootVoices() in encounter_console.js
            ↳ row-per-persona render
                ↳ select.change   → POST /api/encounter/{id}/voices
                ↳ ▶ Test          → POST /api/tts → <audio>.play()
                ↳ 💬 Engage       → window.open('/join?code=…')
```

## 4. Functions (exported API surface)

| Symbol | Where | Purpose |
|--------|-------|---------|
| `GET /api/encounter/{id}/voices` | `portal/server.py` | Extended response: adds `personas: [{id,name,role}]` + `join_code`. |
| `library.get_persona(pid)` | `portal/library.py` | (existing) Used by the route to hydrate id → {name, role}. |
| `bootVoices()` | `portal/static/encounter_console.js` | Rebuilt — renders rows by display name + Test + Engage. |
| `testVoiceForRow(btn)` (new) | `portal/static/encounter_console.js` | Preview helper: POST `/api/tts` for ElevenLabs voice, falls back to browser `SpeechSynthesis`. |

## 5. Limitations

- **No persona-name search in the voice dropdown.** With 12+
  ElevenLabs voices and a row per persona, the dropdown can get
  long. The voice catalog itself isn't filtered by gender / age
  to match the persona — instructor judgment for now. A future
  M34 could auto-recommend voices based on the persona's
  `voice_profile` slot.
- **Engage button does not pre-select the persona.** The link
  opens the generic `/join?code=…` page; the instructor still
  picks the target persona from the join-flow's dropdown. We
  considered adding `?persona={pid}` and a JS auto-select in
  `student_join.js`, but that touches the student-facing flow
  and was scoped out. Tracked as a follow-up.
- **No "Engage as patient" shortcut**. All rows get the same
  Engage button; the patient row isn't special-cased. The role
  badge makes the patient obvious enough.
- **Voice test reuses /api/tts (public, no auth)**. That route
  was already station-facing (audio src tags need to fetch
  without cookies). The Test button benefits from that. If a
  future revision tightens `/api/tts` to require a session token,
  M33 will need a dedicated `/api/encounter/{id}/voice_preview`
  wrapper.
- **Preview sample text is hard-coded English.** Personas with
  non-English voice profiles (none ship today) would need a
  localized greeting. Acceptable for v7.0.
- **Browser SpeechSynthesis voices vary by OS.** Fallback is
  best-effort — the instructor will hear "something", but the
  voice characteristics (gender, accent) are whatever the
  browser default is, not a per-persona match.

## 6. Test status

| Test file | Asserts | Status | Last run |
|-----------|---------|--------|----------|
| `tests/v7/test_encounter_characters_voices_engage.py::test_voices_endpoint_returns_personas_with_name_and_role` | `personas[]` has id+name+role, `join_code` echoed, backward-compat fields intact | PASS | 2026-05-27 |
| `…::test_voices_endpoint_defensive_when_persona_missing_from_library` | Unknown pid echoes id as name (no 500) | PASS | 2026-05-27 |
| `…::test_voice_card_h2_renamed_to_characters_voices_engage` | Console page contains the new card title | PASS | 2026-05-27 |
| `…::test_encounter_console_js_renders_name_test_and_engage` | JS source carries `char-name`, `▶ Test`, `💬 Engage`, `testVoiceForRow`, `SpeechSynthesis`, `/api/tts`, `/join?code=` markers | PASS | 2026-05-27 |
| `…::test_engage_link_url_serves_join_page` | The `/join?code={join}` URL the link targets serves 200/3xx (not 404) | PASS | 2026-05-27 |
| **Full v7 suite** | **209 passed, 1 skipped** (M20 Playwright skip — unchanged) | PASS | 2026-05-27 |

## 7. Change list

| Date | Author | Change | Files |
|------|--------|--------|-------|
| 2026-05-27 | claude-code | Initial M33 implementation: voices route hydrates name+role+join_code; voice card renamed; JS rebuild with name labels + ▶ Test + 💬 Engage; CSS reflow; 5 new tests | `portal/server.py`, `portal/templates/encounter_console.html`, `portal/static/encounter_console.{js,css}`, `tests/v7/test_encounter_characters_voices_engage.py` (new) |

## 8. Open questions / known issues

- **Engage button should ideally pre-select the persona.** Currently
  the instructor must pick the target persona again on the join
  page. Tracked: add `?persona={pid}` query-param honoring to
  `portal/static/student_join.js` so the join flow auto-selects.
- **What happens if the operator clicks Engage during a private-clone
  encounter?** The join code is the template encounter's; the join
  flow will spawn another clone for that "instructor student". The
  cohort debrief would surface this as an extra student. We may
  want a flag to mark instructor sessions and exclude them from
  the debrief facet metrics. Out of scope for M33.
- **Test button rate limiting.** Spamming ▶ Test would burn
  ElevenLabs character budget. The per-encounter voice budget
  (M17) covers this — when the budget runs out, the route returns
  the M17 "fall back to browser TTS" error and the JS surfaces it
  in `#voice-status`. Verify in LAN test.
- **Audio object cleanup.** `URL.revokeObjectURL(url)` fires on
  `ended` — if the instructor navigates away mid-playback, the
  blob URL leaks until tab close. Acceptable; the blob is small.

---

*Render this guide to PDF with `python docs/module_guides/render_pdfs.py`.*
