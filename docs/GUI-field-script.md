# FR-011 Mission Control GUI — Field-Test Script

**Scope:** the educator GUI at `/portal/console` (Set up · Operate · Debrief) —
the Launch Wizard, the ecosystem Board, the readiness cockpit, the live **Operate
cards + room lifecycle**, the per-patient **encounter console** (PTT / handoff /
roster), the QR sheet incl. the **patient avatar rig**, the shared station,
resume-on-restart, Debrief, and accessibility. Run on the Mac (operator) + a
tablet or two. Mark each step PASS/FAIL; paste failures back to Claude Code with
the step #.

**Updated 2026-06-21** — now covers the field-test polish wave (Operate live
cards + pop-outs + room lifecycle, encounter-console PTT/handoff/roster, image
picker, card-first launch) and the recent fixes: PTT selected-voice + mic-prompt
+ interim-transcript (b8620c8), and the patient avatar-rig QR on controls +
printout (461111b).

**Companion:** the classic control room (`/portal/control`) stays the default
fallback and is linked top-right on every screen.

**Preflight (do first):** run `scripts/preflight.sh` — confirms router / IP /
cert / QR and reminds you to set **Private Wi-Fi Address OFF** on each tablet.
Never burn time on network drift.

---

## 0. Setup

| # | Step | Pass |
|---|---|---|
| 0.1 | Restart card-first: `pkill -TERM -f run_portal.py` then `MEDSIM_NO_BROWSER=1 MEDSIM_DEFAULT_VIEW=console MEDSIM_HOST=0.0.0.0 .venv/bin/python run_portal.py` (or `bash scripts/run_cards.sh`). |  |
| 0.2 | If the LAN IP drifted, re-mint the **leaf** cert (NEVER the CA): `python scripts/dev_cert.py <lan-ip>`, restart. The cockpit's TLS tile goes green. |  |
| 0.3 | Open `https://localhost:8765/`, log in → you land on **`/portal/console?mode=setup`** (card-first, not the classic home). The top **readiness bar** paints. |  |
| 0.4 | The **active mode tab is a filled coloured box with white text** (not an underline). |  |

## 1. Set up — Launch Wizard + Board  *(target: cold start < 90 s)*

| # | Step | Pass |
|---|---|---|
| 1.1 | **Patients & rooms:** one **EHR** dropdown (session-wide) + **Number of beds** (default 1). Set beds = 2. |  |
| 1.2 | **Scenario:** one picker per bed; pick a scenario each → the bed's patient is implied. Legacy v1 YAML (if any) shows "· legacy (no patient roster)". |  |
| 1.3 | **Characters:** **Scenario characters** per bed (patient locked; a recurring title across beds shows **· V1 / · V2**). **Shared characters** is a separate picker (common doctor, allied-health). |  |
| 1.4 | **Image picker:** each character row has an image swatch strip — pick a face → it is assigned (one image = the flat audio portrait AND the 3D-rig source photo). |  |
| 1.5 | **Devices:** per-bed Basic + Advanced pickers; the **Group → Nursing station** toggle appears (multi-bed). |  |
| 1.6 | **Review:** EHR, beds + patients, shared-cast count, device count; readiness pill shown; **Launch** blocked only on a red check. |  |
| 1.7 | **Launch** → opens the room dashboard; devices minted (QRs ready). Time from 1.1 → live: ______ s. |  |
| 1.8 | **Board:** Set up → Board layered cards (Scenario chars · Shared chars · Resources · Rooms/patients) match the Wizard; **Launch works from the Board** too. |  |

## 2. Operate — cockpit, live cards, room lifecycle

| # | Step | Pass |
|---|---|---|
| 2.1 | Switch to **Operate**. The **System status** appears as a small button/bar (not a wall of tiles). |  |
| 2.2 | Click **System status** → a **modal pops** (tiles: traffic light + shape glyph + detail). Close via X / Esc / backdrop-click → back to just the button; it never overlaps the cards below. |  |
| 2.3 | A **cold** Speech tile → tap **Warm speech model** → green on the next poll. **Test all** re-runs every check; the restart-hint shows the command (does NOT restart the portal). |  |
| 2.4 | **Operations cards:** one card per **bed/patient** (join + device + character counts), one per **shared character** (voice state + QR), the **med cart(s)**, and the **Nursing station**. |  |
| 2.5 | Each card has **Open** (in place) and **Pop out** (new window). Pop a card onto a **second monitor** — it stays fully live off the existing polls. |  |
| 2.6 | **Pop-out targets are correct:** patient → encounter console; shared char → shared station; **med cart → the device cart UI** (`/device/<join>/<cart>`); nursing → nursing station; medical records → records page. |  |
| 2.7 | **Room lifecycle bar:** **Start · Pause · Resume · Inject scene** (modal) **· Print QR · End all (debrief)** — Start arms a configured room, Pause/Resume gate student input, Inject scene posts a scene to every bed, End all builds the cohort debrief. |  |

## 3. Encounter console — patient drill-in  *(PTT / handoff / roster)*

*Open a patient's card in Operate (Open or Pop out) → the encounter console.*

| # | Step | Pass |
|---|---|---|
| 3.1 | **Back** reads **"← Back to Mission Control"** and returns to `/portal/console?mode=operate` (NOT the classic room). |  |
| 3.2 | Every card **collapses** (caret / click the header) and **Pops out** to a solo window (one card, page chrome hidden, still live). |  |
| 3.3 | **Characters · voices:** pick an **ElevenLabs voice** per character (▶ Test previews it); **Engage** opens an in-console chat so you can play that character. |  |
| 3.4 | **PTT mic prompt:** click a character chip (or focus the type box / hold the button) → the browser **microphone prompt appears**; Allow it. *(If previously blocked: address-bar site icon → Microphone → Allow → reload.)* |  |
| 3.5 | **PTT uses the selected voice:** hold **Hold to talk**, say a line, release → the reply is **spoken in the character's assigned voice** (e.g. Callum for Mr. Hayes), not the browser default. |  |
| 3.6 | **Quick release still sends:** a fast hold-and-release (short utterance) still **fires the turn** (interim transcript captured) → reply + TTS. Holding with no speech shows "Didn't catch that…". |  |
| 3.7 | **Type fallback:** type a line + Enter → reply in the selected voice (works where the mic / STT does not, e.g. Safari). |  |
| 3.8 | **Patient avatar-rig QR cell:** a **Avatar · <patient> · patient (animated rig)** cell is present, with a **Pair tablet** link. |  |
| 3.9 | **Shift handoff card:** Start (mode + counterpart) → **engage the counterpart** via PTT → it gives/receives report → **Score** shows the SBAR coverage grid (check/cross) + self-vs-measured %. |  |
| 3.10 | **Connected stations card:** live per-bed student roster (online / platform / turns); instructor Engage stations are filtered out. |  |

## 4. QR sheet + tablets

| # | Step | Pass |
|---|---|---|
| 4.1 | Open the **QR sheet** (`/portal/control/qr_print`, or the 🖨 link from a bed). |  |
| 4.2 | **Patient avatar rig:** each patient page **leads** with a **Patient avatar (animated rig)** QR. Scan it on a bedside tablet → the **animated 3D rig loads** (not a flat portrait), bound to that patient. |  |
| 4.3 | **Per-patient:** chat / EHR / device stations + that bed's **scenario-character** avatar/voice QRs + bedside device QRs. |  |
| 4.4 | **Common page:** **shared characters** (avatar vs voice) + **common devices** (Nursing Station + med cart); the Nursing Station is **not** repeated on each patient page. |  |
| 4.5 | **Shared char — one tablet, many patients (FR-007 v2):** scan the **one** shared-character QR → push-to-talk / type about **Bed 1** → AI reply (no echo) in its voice → on the **same** tablet ask about **Bed 2** → it answers about the other patient (the doctor knows both). |  |
| 4.6 | **Shared-station PTT:** on the shared character page, **Hold to talk** works (mic prompt → STT → AI reply spoken in the assigned voice); the type fallback works too. |  |

## 5. Resume on restart  *(G7)*

| # | Step | Pass |
|---|---|---|
| 5.1 | With the room live, **gracefully restart** (`pkill -TERM`). Boot log shows `[resume] restored last session …`. |  |
| 5.2 | Re-login → Operate shows the resumed room intact (scenario, beds, devices, shared cast). **No echo** on the resumed room — the Anthropic key self-heals on the first readiness poll. |  |
| 5.3 | Launch a **fresh** scenario → the resumed state clears (a fresh launch is not a resume). |  |
| 5.4 | (Negative) corrupt / empty snapshot → boot is clean, cockpit offers **configure in Setup**, never crashes. |  |

## 6. Debrief

| # | Step | Pass |
|---|---|---|
| 6.1 | Switch to **Debrief** (tab = filled box). The panel links to **Open debriefs** (`/portal/debrief`). |  |
| 6.2 | From Operate's lifecycle bar, **End all (debrief)** → confirm → it builds the **cohort debrief** and opens it (`/portal/debrief/cohort/<room>`); connected students are disconnected. |  |
| 6.3 | The cohort debrief lists each bed's session for review (per-patient debrief reachable). |  |

## 7. Fallback + accessibility  *(G8)*

| # | Step | Pass |
|---|---|---|
| 7.1 | **"Switch to classic control room"** (top-right) is present on every mode and lands on `/portal/control/setup`. The classic sidebar also has **Mission Control (cards)** back. |  |
| 7.2 | **Keyboard:** Tab through the wizard / cockpit / encounter console — every control shows a **visible focus ring**; tabs + buttons activate with Enter/Space; the System-status modal traps focus and Esc closes it. |  |
| 7.3 | **Shape-not-colour:** readiness states read as glyphs (filled circle = green · triangle = amber · square = red), legible without colour. |  |
| 7.4 | **Touch:** on a tablet, tabs / steppers / checkboxes / the PTT button are comfortably tappable (no fat-finger misses). |  |
| 7.5 | **Contrast:** text is legible on the dark top bar + light panels in normal room light. |  |

---

### Notes for paste-back

When a step fails, paste: the **step #**, what you saw vs expected, the browser +
whether you **hard-refreshed** (Cmd+Shift+R drops a stale `console.js`), and any
console / `/tmp/medsim_portal.log` error. Claude fixes against the step.
