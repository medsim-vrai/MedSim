# FR-011 Mission Control GUI — Field-Test Script

**Scope:** the educator GUI at `/portal/console` (Set up · Operate · Debrief) —
the Launch Wizard, the ecosystem Board, the readiness cockpit, resume-on-restart,
the QR sheet, and accessibility. Run on the Mac (operator) + a tablet or two.
Mark each step ✅/❌; paste failures back to Claude Code with the step #.

**Companion:** `vrai-faces/docs/PLAN-2026-06-13-gui-mission-control.md` (G1–G8).
The classic control room (`/portal/control`) stays the default fallback and is
linked top-right on every screen.

---

## 0. Setup

| # | Step | Pass |
|---|---|---|
| 0.1 | Restart on current code: `pkill -TERM -f run_portal.py` then `MEDSIM_NO_BROWSER=1 MEDSIM_HOST=0.0.0.0 .venv/bin/python run_portal.py`. | ☐ |
| 0.2 | If the LAN IP drifted, re-mint the **leaf** cert (NEVER the CA): `python scripts/dev_cert.py <lan-ip>`, restart. The cockpit's TLS tile should go green. | ☐ |
| 0.3 | Open `https://localhost:8765/portal/console`, log in. Top **readiness bar** paints (overall + per-check chips). | ☐ |

## 1. Set up — Launch Wizard  *(target: cold start < 90 s)*

| # | Step | Pass |
|---|---|---|
| 1.1 | **Patients & rooms:** one **EHR** dropdown (session-wide) + **Number of beds** (default 1). Set beds = 2. | ☐ |
| 1.2 | **Scenario:** one picker per bed; pick a scenario each → the bed's patient is implied. | ☐ |
| 1.3 | **Characters:** **Scenario characters** group per bed (patient locked); a recurring title across beds shows **· V1 / · V2**. **Shared characters** is a separate picker (common doctor, allied-health). | ☐ |
| 1.4 | **Devices:** per-bed Basic + Advanced pickers; **Group → Nursing station** toggle appears (multi-bed). | ☐ |
| 1.5 | **Review:** EHR, beds + patients, shared-cast count, device count. Readiness pill shown; **Launch** blocked only on a red check. | ☐ |
| 1.6 | **Launch** → opens the room dashboard; devices were minted (QRs ready in the cockpit / classic ops). Time from 1.1 → live: ____ s. | ☐ |

## 2. Operate — readiness cockpit

| # | Step | Pass |
|---|---|---|
| 2.1 | Switch to **Operate**. Tile per subsystem (traffic light + **shape glyph** + detail). | ☐ |
| 2.2 | A **cold** Speech tile → tap **Warm speech model**; it goes green on the next poll. | ☐ |
| 2.3 | **Test all** re-runs every check. **Restart-hint** shows the command (does NOT restart the portal). | ☐ |
| 2.4 | Live cards (Medications / Staged errors / Handoff) reflect the active session + link to the classic surfaces. | ☐ |

## 3. Resume on restart  *(G7)*

| # | Step | Pass |
|---|---|---|
| 3.1 | With the room live, **gracefully restart** (`pkill -TERM`). Boot log: `[resume] restored last session …`. | ☐ |
| 3.2 | Re-login → Operate shows a green **"Resumed '…' (saved HH:MM)"** note; the scenario, beds, devices, shared cast are intact. | ☐ |
| 3.3 | Launch a **fresh** scenario → the "Resumed" note clears (a fresh launch is not a resume). | ☐ |
| 3.4 | (Negative) corrupt/empty snapshot → boot is clean, cockpit offers **configure in Setup**, never crashes. | ☐ |

## 4. Board + QR sheet

| # | Step | Pass |
|---|---|---|
| 4.1 | **Set up → Board:** layered cards (Scenario characters · Shared characters · Resources · Rooms/patients) reflect the same config as the Wizard; Launch works from the Board. | ☐ |
| 4.2 | Open the **QR sheet** (`/portal/control/qr_print`): each patient page groups under the **character name** (chat/EHR/device + that bed's **scenario-character** avatar/voice QRs + bedside devices). | ☐ |
| 4.3 | A final **Common** page: **common characters** (shared cast — avatar vs voice) + **common devices** (Nursing Station + med cart). Nursing Station is NOT repeated on each patient page. | ☐ |

## 4b. Shared character — one tablet, many patients  *(FR-007 v2)*

| # | Step | Pass |
|---|---|---|
| 4b.1 | Launch a multi-bed room with a **shared character** (e.g. a common doctor in the Characters step; audio-only is fine). On the QR sheet's **Common characters**, scan the **one** shared-character QR (voice/avatar — "one tablet, all beds") on a single tablet. | ☐ |
| 4b.2 | Push-to-talk / type about **Bed 1's** patient → the avatar/voice **replies with AI logic** (no longer an echo) about that patient, in its assigned voice. | ☐ |
| 4b.3 | On the SAME tablet, ask about **Bed 2's** patient → one instance answers about the other patient (conversation spans beds; the doctor knows both). | ☐ |

## 5. Fallback + accessibility  *(G8)*

| # | Step | Pass |
|---|---|---|
| 5.1 | **"Switch to classic control room ↗"** (top-right) is present on every mode and lands on `/portal/control/setup`. | ☐ |
| 5.2 | **Keyboard:** Tab through the wizard / cockpit — every control shows a **visible focus ring**; tabs + buttons activate with Enter/Space. | ☐ |
| 5.3 | **Shape-not-colour:** readiness states read as glyphs (● green · ▲ amber · ■ red), legible without colour. | ☐ |
| 5.4 | **Touch:** on a tablet, tabs / steppers / checkboxes are comfortably tappable (no fat-finger misses). | ☐ |
| 5.5 | **Contrast:** text is legible on the dark top bar + light panels in normal room light. | ☐ |

---

### Notes for paste-back
When a step fails, paste: the **step #**, what you saw vs expected, the browser +
whether you **hard-refreshed** (Cmd+Shift+R drops a stale `console.js`), and any
console / `/tmp/medsim_portal.log` error. Claude fixes against the step.
