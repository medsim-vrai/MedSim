# Plan — Doctor Orders Decisively + Two-Stage Control Room (2026-06-10)

Field feedback from the first FR-001/002 loop test, planned BEFORE building (per instructor request;
work is paused pending approval of this plan).

---

## Part 1 — FR-001 refinement: the doctor ORDERS (doesn't ask) — Effort S

**Observed.** In the live loop test the simulated doctor asked about availability / hedged instead of
placing a complete order with the dose.

**Root cause.** The prompt block says "recommend EXACTLY this order *if the trainee asks*" — passive
phrasing leaves the model room for its conversational habit (clarifying questions, menus). The
doctor's availability-blindness also wasn't paired with an explicit "never ask what's in stock."

**Change (portal/med_orders.py · doctor_prompt_block):**
1. Imperative ordering behavior: when the trainee requests orders OR describes the indication, the
   doctor **places the order in that same utterance**, complete: *"I'm ordering <drug> <dose>
   <route> <frequency>"* + at most one line of rationale, in voice.
2. Explicit prohibitions: never ask the trainee what is available/in stock (supply is pharmacy's
   problem and the teaching lever); never offer a menu of options; never name any drug/dose outside
   the injected selection; defer only in the exhausted case (all options already on board).
3. Approval path unchanged: when the trainee returns with the pharmacist's authored alternative, the
   doctor approves it decisively (again with the full dose/route/frequency restated).
4. Tests: engine tests assert the block carries the imperative phrasing + prohibitions; live re-run
   of the 3-step loop is the acceptance gate.

**Acceptance.** First reply to "what should I give him?" = one complete order including the dose;
the doctor never asks about stock; the approval turn restates the alternative's full order.

---

## Part 2 — FR-005 (new): two-stage control room — Setup page → Live Operations window — Effort M

**Observed.** One Ops page currently carries ~13 cards spanning two different jobs — preparing a
scenario and running it — which is confusing mid-encounter.

**Design (keyed to the EXISTING session lifecycle — `configured → running → paused → ended`):**

### Page A — "Scenario Setup" (`/portal/control/setup`) — session in `configured`
Everything done BEFORE the first trainee interaction:
- Scenario + characters selection (today's launch flow lands here; include the pharmacist when the
  med loop is intended)
- **Medication board** (FR-001/002): condition, what the cart holds, what pharmacy stocks,
  availability flags — "the instructor states what is available at the start" (level 1)
- Device pre-mint: create stations + show/print their QRs ahead of time
- Avatar skins + character voices assignment
- Chart seed report / medication checklist review
- Bottom: **▶ Start scenario** — sets state `running`, then `window.open('/portal/control/ops')`
  from the click handler (popup-safe), leaving Setup as a summary/reference tab

### Page B — "Live Operations" (`/portal/control/ops`, slimmed) — session in `running`
Only what's needed while the encounter runs:
- Live transcript · operator push-to-talk · 🎤 Say-as-character
- Connected stations + simulated devices (status, inject, alarms, assign)
- 💊 Medications as the existing **collapsed expander** (level-2 live edits: add meds, flip
  availability mid-scenario)
- Pause / resume / end controls

### Mechanics
- **Routing:** post-login + post-launch landing picks by session state (`configured` → Setup,
  `running` → Ops). Deep links keep working; no API changes — both pages reuse the existing
  endpoints (`/api/control/meds`, device register/roster, voices, etc.).
- **Template/JS split:** the per-card JS files (control_ops_voices.js, control_ops_devices.js, the
  meds/say-as inline blocks) move with their cards; element ids unchanged → minimal JS edits.
- **State:** no new state machinery — `control_session.set_state` already exists (pause/resume
  tests cover it).

### Stages (each independently shippable)
1. **S0** — finalize the card classification above with the instructor (10-min review of this doc).
2. **S1** — create the Setup page + move setup cards + the Start button/window-open flow.
3. **S2** — slim the Ops page to live cards; landing/routing by state.
4. **S3** — tests: both pages render (auth + state), setup cards absent from Ops and vice versa,
   start-flow sets `running`; existing device/med/control tests stay green.
5. **S4** — live validation: the instructor runs a full scenario through Setup → Start → new
   Ops window; acceptance = "less confusing while operating."

### Risks / notes
- Popup blockers: the new window MUST open from the user's click (it does, via the Start handler);
  fallback link shown if blocked.
- Some cards serve both stages (devices, meds) — they appear on both pages backed by the same APIs,
  with the Setup variant full-size and the Ops variant compact/collapsed.
- Existing bookmarks to `/portal/control/ops` keep working (state-based redirect to Setup when
  nothing is running yet).

---

## Sequence + effort
1. Part 1 (S — one sitting incl. live re-test) → unblocks correct med-loop teaching immediately.
2. Part 2 S0 review (10 min with the instructor) → S1–S4 (M, ~1–2 days).

**Status: PAUSED for instructor approval of this plan (requested 2026-06-10).**
