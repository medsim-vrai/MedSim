# MedSim V8 / VRAI Faces — Functional Register

Functional **refinements & expansions** — the channel that turns testing feedback into
tracked, planned, shipped, and **validated** improvements. This is the deliberate
**continuous-improvement loop**: what's observed during a teaching/testing session enters
here, gets specced, lands in the build, and is closed out with a validation note — so
feedback is captured and developed rather than lost.

Dated 2026-06-07.

> **Scope:** clinical-interaction logic, character behavior, instructor tools, scenario
> engagement, and functional UX — **system-wide**: the control room (instructor), the
> portal / MedSim runtime (turn logic + clinical data), and the avatar device (`vrai-faces`).
> - **Performance** → `OPTIMIZATION-REGISTER.md`
> - **Gated enhancements** needing research → `research/RB-*`
> - **Architecture / product / clinical decisions** → ADRs (`Memory_management.MD §7`)
> - **Phases & critical path** → `ROADMAP.md`
> This register is the **functional counterpart to the optimization register**.

> ⚠️ **MedSim core scenario *content* is read-only.** Some items below change clinical
> turn-logic that lives in the MedSim runtime / authored clinical data. Scenario *files* are
> never mutated; behavior is driven by **authored clinical data + runtime code**, and any
> runtime-core change graduates to an **ADR** first. Each entry names where it lands.

---

## Field-test instrument (2026-06-13)

Expanded field validation runs against **`docs/field-test/`** — a 72-test matrix across all 13
core areas (network/pairing · avatar · audio station · voice loop · control room · say-as ·
med ordering · staged errors · EHR · multi-patient · devices · debrief · non-functional):
- **MedSimVRAI_Field-Test-Plan.pdf** — readable plan + coverage map + the Claude issue pipeline.
- **MedSimVRAI_Field-Test-Matrix.xlsx** — execution (dropdowns), a **Claude-ingestible Issue
  Log** (paste Status=New rows back to Claude for fixes), a live Coverage rollup, and an
  Environment inventory.
Fixes flow back here as FR/bugfix entries. Goal: no P1 row left "Not run" before broader rollout.

## The feedback → development loop

1. **Observe** — during testing or teaching, note a desired refinement/expansion (a behavior
   gap, a clinical-realism improvement, a new instructor capability, a UX friction).
2. **Capture** — add an `FR-NNN` row to the Summary table + a short entry. Low bar: a title +
   Source + one-line behavior is enough to not lose it.
3. **Spec** — fill behavior + acceptance criteria; flag **clinical-safety + PHI**; name the
   systems it touches. Real unknowns → spawn a `research/RB-*`. A dependency / data-flow /
   security / clinical-logic change → it graduates to an **ADR** before shipping.
4. **Plan** — slot it against a Roadmap phase / a release; set Priority.
5. **Build → Ship → Validate** — implement, then confirm the behavior **in a test session**
   and mark `Validated` with the note. That note + new feedback restart the loop.

**Planning gate.** Beyond ad-hoc planning (step 4), the open `FR-*` backlog is **pulled for a
formal review at the post-Track-4 planning checkpoint** (`PLAN-2026-06-07-remaining-development.md`)
— triaged + prioritized into the Track 5+ roadmap, and re-run each milestone. Keep filing rows
continuously; don't wait for the gate (it's for review/sequencing, not first capture).

Keep entries honest: when a refinement reveals a follow-on, **file the follow-on** rather
than expanding scope silently.

## How this fits

| System | Holds |
|---|---|
| **Roadmap** (`ROADMAP.md`) | Phases + critical path to ship. |
| **ADRs** (`Memory_management.MD §7`) | Architecture / product / clinical decisions. |
| **Research Briefs** (`research/RB-*`) | Gated enhancements needing a go/no-go. |
| **Optimization Register** (`OPTIMIZATION-REGISTER.md`) | Performance backlog. |
| **Functional Register** (this) | Functional refinements/expansions + the testing-feedback loop. |

## Lifecycle

`Proposed` → `Specced` → (if unknowns) `Researched` via RB → (if a decision) `Decided` via
ADR → `In-progress` → `Shipped` → `Validated` (confirmed in a test session). `Parked` /
`Deferred` for out-of-window items.

## Legend

- **Area:** clinical-logic · character-interaction · instructor-tools · scenario · UX
- **Source:** testing · instructor · clinical-SME · design · trainee
- **Status:** Proposed · Specced · Researched · Decided · In-progress · Shipped · Validated · Parked
- **Priority:** P1 (now) · P2 (next) · P3 (later)
- **Effort:** S ≤ ½ day · M ≤ 2 days · L > 2 days (`?` if unknown)
- **Lands in:** control-room · portal · runtime(core) · avatar · data

---

## Summary

| ID | Refinement / expansion | Area | Source | Pri | Status | Lands in |
|----|------------------------|------|--------|-----|--------|----------|
| **FR-001** | Best-practice med ordering (doctor) — random primary, min-dose, escalate to secondary | clinical-logic | instructor | P2 | **Shipped** (2026-06-10; field feedback: doctor must ORDER decisively w/ dose — fix planned) | runtime(core) · portal · data |
| **FR-002** | Pharmacist availability + alternatives; instructor "not available" flag | clinical-logic · instructor-tools | instructor | P2 | **Shipped** (2026-06-10) | control-room · portal · runtime(core) · data |
| **FR-003** | Instructor character prompting — speak in-context (emotion / mental status / role) | instructor-tools · character-interaction | instructor | P2 | **✅ Validated** (2026-06-10) | control-room · portal · avatar |
| **FR-004** | Zero-config wireless device pairing for production venues | UX · scenario | testing | P1 | Proposed | portal · avatar · kit/ops (+ADR) |
| **FR-005** | Two-stage control room — Setup page → Live-Operations window | instructor-tools · UX | instructor | P2 | **Shipped** (2026-06-10; live validation pending) | control-room · portal |
| **FR-006** | Per-character Avatar vs Audio-only stations — clear choice + flat-portrait lite app for low-cost tablets | instructor-tools · UX · avatar | instructor | P2 | **Shipped — OPEN ISSUE:** voice take fails on Android Chrome (see entry) | control-room · portal · avatar |
| **FR-007** | Unit-level shared staff characters — one tablet serves multiple patients; student must IDENTIFY the patient | character-interaction · clinical-logic · scenario | instructor | P2 | Proposed (investigate) | portal · runtime(core) · control-room · avatar |
| **FR-010** | Post-restart device readiness ping — health-check paired tablets (status / what they run / working?) + warm character tablets cold→warm | UX · instructor-tools · ops · avatar | instructor | P1 | Proposed (investigate) | portal · avatar · control-room |

---

## FR-001 — Best-practice medication ordering (doctor path)

**Area:** clinical-logic · **Source:** instructor · **Priority:** P2 · **Status:** Proposed ·
**Effort:** M–L · **Lands in:** runtime(core) + portal + data

**Goal.** When a trainee consults the doctor (AI character) for orders, make medication
selection realistic *and* pedagogically varied while staying clinically safe.

**Behavior.**
- When best practice offers **more than one primary medication**, select **one at random**
  from the authored primary set and present it (random = training variability, so repeat
  runs differ).
- **Dose defaults to the minimum** of the authored best-practice range for the chosen drug.
- If the patient is **already on** the presented medication → order a **different primary**
  (random among the remaining); if primaries are exhausted → escalate to the **secondary**
  set (random), again at the **minimum** dose.

**Acceptance criteria.**
- Medication options + dose ranges come **only from authored clinical data** (scenario med
  list / a formulary; `portal/data/drug_doses.json` + `clinical_ranges.json`) — the model
  **never invents** a drug or a dose.
- "Already on it" is checked against the patient's **active orders / MAR state**.
- Selection is random among authored options, with an optional **seed** for reproducible
  teaching runs.
- If **no authored option** fits → defer to the instructor (no AI-improvised medication).

**Clinical safety / PHI.** Authored-data-driven, **min-dose-first**, **instructor-in-the-loop**
(HIGH-RISK characters require it); never AI-invent meds/doses; trainee free-text stays PHI,
fail-closed (ADR-0014).

**Open questions.**
- Where the **primary/secondary taxonomy + ranges** are authored — per-scenario list vs a
  shared formulary in `portal/data`.
- How **active-medication state** (MAR/orders) is represented and read at turn time.
- Seeded vs true random; single pick per ask vs a short ranked offer.

---

## FR-002 — Pharmacist availability & alternatives

**Area:** clinical-logic · instructor-tools · **Source:** instructor · **Priority:** P2 ·
**Status:** Proposed · **Effort:** M · **Lands in:** control-room + portal + runtime(core) + data

**Goal.** Let the instructor create supply constraints and have the pharmacist coach the
trainee toward authored alternatives — exercising the doctor → pharmacist → doctor loop.

**Behavior.**
- The instructor can **flag a medication as "not available"** (per session/scenario).
- When the trainee consults the **pharmacist** about an unavailable med, the pharmacist
  offers **available primary** alternatives first, then **available secondary** if needed,
  each with a **minimum-of-range dose**, framed as *"take back to the doctor to review."*
- Availability is **session state** the instructor controls; flipping it takes effect for
  subsequent pharmacist interactions.

**Acceptance criteria.**
- A control-room control to mark specific meds unavailable (reuses the FR-001 formulary).
- Pharmacist alternatives are drawn from the **same authored primary/secondary sets** + ranges.
- Alternatives are presented as **options to discuss with the doctor**, not as a directive.

**Clinical safety / PHI.** Same posture as FR-001 (authored data, min-dose, instructor-in-loop).
The "not available" flag is an instructor teaching lever, not a clinical claim.

**Open questions.**
- Flag granularity — drug vs dose-form vs route.
- How the trainee reaches the **pharmacist** — a character on the same device/loop, or a
  separate station.
- Whether unavailability can be **pre-authored** in a scenario vs only set live.

---

## FR-003 — Instructor character prompting (in-context)

**Area:** instructor-tools · character-interaction · **Source:** instructor · **Priority:** P2 ·
**Status:** ✅ **Validated** (2026-06-10, in a test session) · **Effort:** M · **Lands in:** control-room + portal + avatar

**Shipped as (2026-06-10, `fe823b1`):** the Ops page's "🎤 Say as character" card → upgraded
`POST /api/face/{id}/speak` (auth'd). **Verbatim** is the default (exact words — predictable, no
LLM cost); **In character** runs `runtime.take_instructor_line` (the instructor's INTENT framed as
stage direction through the persona's full system prompt incl. `altered_state` → one in-character
utterance; requires the running scenario, 409 otherwise). Lines are voiced server-side (ElevenLabs,
first-sentence pipelined — the OPT-008 path) and logged to the operator transcript as instructor
lines. Open-questions resolved: default = verbatim; delivery affect = persona prompt (in-character)
+ device auto-emote (verbatim); endpoint = the existing /speak extended; encounter-memory note: the
device voice loop is currently stateless per turn — instructor lines enter the transcript but not a
persistent AI memory (none exists yet; file separately if needed).

**Goal.** Let the instructor put words in a character's mouth — delivered on **that
character's device**, **in the character's context** (emotion, mental status, professional
role, persona traits) and consistent with the scenario — to steer the encounter live.

**Behavior.**
- A control-room **per-character input** lets the instructor enter a line for the character
  loaded on a given device.
- The line is delivered to that device and **spoken (ElevenLabs) + animated** (lip-sync),
  with the character's **current emotion/affect + mental status** applied — e.g. a delirious
  patient's line comes out fragmented per the persona's `altered_state`; a calm clinician is
  professional.
- Two delivery modes:
  - **Verbatim** — speak the instructor's exact words, colored by the character's voice + affect.
  - **In-character** — the AI rephrases the instructor's *intent* through the persona +
    scenario lens (role, knowledge boundary, scene contract, `altered_state`).
- Honors the persona's defining aspects + the live scenario state; appears in the encounter
  history like any character turn.

**Acceptance criteria.**
- Correct **per-active-character routing** (right device/character).
- Emotion / mental-status applied via the existing `emotion_driver` + persona `altered_state`;
  verbatim mode bypasses the LLM, in-character mode runs it.
- Reuses the server-voice speak path (text + emotion frame → `speechConsumer` → audio + visemes).

**Clinical safety / PHI.** The instructor-authored line is **character speech (non-PHI)**,
like the AI reply — so the cloud-voice path is allowed (ADR-0037); no trainee PHI involved.

**Open questions.**
- Default mode — verbatim vs in-character.
- How **mental status / altered_state** maps to delivery (clinical lexicon override + persona affect).
- Does it consume a scenario "turn" / enter the AI's memory of the encounter.
- Endpoint — extend `/api/face/{id}/speak` (text+emotion exists) vs a dedicated instructor route.

---

## FR-004 — Zero-config wireless device pairing for production venues

**KIT ROUTER ✅ VALIDATED (2026-06-12):** tablet half passed — iPad (avatar) + Android (audio
station) both joined the Beryl, loaded green-lock with NO new trust step (the CA promise held
across routers), and the Android ran a live voice take over the kit LAN: `POST /api/face/stt
200 → POST /listen 200` — instructor reports the Android response now feels like the iPad.
This simultaneously **field-validates FR-006b room-local STT** on the real tablet. Remaining
hardening (queued, optional): static DHCP lease for the Mac; hostname QRs via Beryl dnsmasq.

**KIT ROUTER VALIDATION (2026-06-12, in progress):** Beryl AX (GL-MT3000) pocket router arrived
and is live — Mac at 192.168.8.181 behind it, internet flowing through it (Anthropic reachable →
AI turns work), leaf cert re-minted (leaf-only, CA untouched — the make-dev-cert FORCE guard
correctly refused a CA re-mint) with SAN covering the Beryl subnet + both prior home networks +
portal.medsim.lan, portal restarted, **preflight PASS (6/6)**, fresh QR minted. Tablet half
pending: join tablets to the Beryl SSID (per-network MAC privacy OFF), confirm green-lock with NO
new trust step (the CA promise), one room-STT voice take over the new LAN. Hardening queued:
(a) static DHCP lease for the Mac in the GL.iNet admin so the IP never drifts; (b) durable step —
Beryl dnsmasq entry portal.medsim.lan → Mac + QRs minted on the hostname (already in the SAN),
making the kit fully venue-independent.

**Area:** UX · scenario-ops · **Source:** testing (2026-06-09 field session) · **Priority:** P1 ·
**Status:** Proposed · **Effort:** M (kit) / L (relay, +ADR) · **Lands in:** portal + avatar + kit/ops

**Goal.** A facilitator at ANY venue gets the bedside loop running wirelessly with no IT work:
power on the kit → iPads connect → scan the QR → the avatar appears. No cables, no router
settings, no per-venue certificates, no IP addresses.

**Problem (field-proven, 2026-06-09).** Pairing is pinned to the portal Mac's LAN IP (QR URL +
TLS-cert SAN), and venue networks actively fight device-to-device traffic: the new home mesh
**isolates clients** (iPad packets never reach the portal — confirmed via the portal access log);
a carrier phone hotspot was **IPv6-only/CLAT** (no shared IPv4 at all). Institutional Wi-Fi
(hospital / university / conference) has client isolation on **by default**, so per-venue Wi-Fi
will fail at most real sites. A USB tether works on the bench but is not a product answer —
end users expect wireless.

**Options (trade-offs):**
1. **Kit travel router (recommended short-term, production-credible).** A pocket router in the
   demo kit broadcasts a fixed SSID (e.g. `MedSimNet`); the Mac + iPads join it once and never
   re-pair. Stable subnet + stable portal hostname → **one cert, one QR, forever**; isolation is
   under our control (off); venue internet (for AI/voice) arrives via the router's WAN (ethernet,
   venue Wi-Fi as WWAN, or a phone). Local-first preserved (PHI stays on the kit LAN, ADR-0001).
   ~$40–100 hardware, zero per-venue config, no code changes beyond pinning
   `MEDSIM_PUBLIC_HOST` + cert SAN to the kit hostname.
2. **Portal-hosted Wi-Fi (Mac as AP).** Zero extra hardware, but macOS Internet Sharing can't
   share Wi-Fi→Wi-Fi (needs ethernet upstream for internet) and is the least reliable macOS
   feature in the chain — acceptable fallback, not the plan.
3. **Cloud relay (the strategic fork — needs an ADR).** Portal (or a thin frame-relay) in the
   cloud; devices connect OUTBOUND over any internet (venue Wi-Fi, cellular) — isolation becomes
   irrelevant, pairing is a URL. This is the "SaaS-grade easy wireless" answer, but it moves the
   trainee-utterance path (PHI, ADR-0014) and the speech transport through the cloud →
   BAA-covered posture + encryption design required (fail-closed). File as the ADR alongside the
   Track-3 transport decisions; pairs naturally with the Capacitor native app (Track 4).
4. **Managed VPN overlay (Tailscale/MDM).** Works across any network with the PHI posture intact
   (still your-devices-only), at the cost of fleet enrollment overhead — viable for a managed
   institutional fleet, not for ad-hoc venue kits.

**Recommendation.** Ship **(1) the kit router** for pilots/demos now (+ stable hostname in cert
SAN so the QR never changes), and ratify **(3) cloud relay** as an ADR for the production scale-
out decision — they're complementary (on-prem kit vs SaaS deployment).

**Acceptance criteria.**
- A facilitator with no IT involvement gets an iPad paired at a *new* venue in under 2 minutes,
  wirelessly.
- The QR/launch URL is **identical across venues** (no IP in it; stable hostname).
- A network change (venue → venue) requires **zero** cert/QR regeneration.
- Trainee-utterance PHI posture re-verified for whichever transport ships (ADR-0014 fail-closed).

**Clinical safety / PHI.** Options 1/2/4 keep today's local-first posture. Option 3 moves PHI
transit into the cloud → explicit ADR + BAA/encryption review BEFORE build (fail-closed default).

**Open questions.** Router model/standardization for the kit · does the kit need to double as the
portal host (router + compute stick) · relay architecture (full portal vs thin WS frame relay) ·
how the stable hostname interacts with per-iPad CA trust at fleet scale (Track-4 hardening).

During a session, capture the minimum and triage later: **title + Source + one-line
behavior**. Attach objective signals where useful — the 🐞 debug overlay (`?debug`), the
diagnostics panel (`?diag=1`), and the transcript's `/listen` round-trip timer give numbers.
Don't lose feedback to "we'll remember it" — **file the row**, even terse.

## FR-006 — OPEN ISSUE (2026-06-10 night): voice loop fails on the Android lite station

**Status of validation.** The lite station itself works on the Android tablet (Chrome): flat
portrait + name + talk button render, fast load, no 3D — the FR-006 visual/UX goals hold. But the
VOICE side fails: push-to-talk takes end "(no speech detected)" / no audio. ⚠️ Context that
reframes the hunt: **every successful voice test so far was the iPad** — this is the FIRST run of
the on-device voice loop on Android Chrome at all (RB-002 always flagged Android tablets as the
unpiloted primary target), so this is likely an Android-platform issue, not a lite-mode issue.

**Wrong-turn record (so it isn't repeated).** The first fix attempt assumed the iPadOS
Camera-app QR-handoff muted-mic quirk; the test device turned out to be Android. (The muted-track
wait + the hardening are still correct and kept.)

**What IS now in place (shipped `7239a12`, live):** every empty take names its cause on the
status line + ⚙ metrics — `recorder produced no audio` / `clip too short` / `mic captured
SILENCE (RMS≈0)` / `whisper heard no words (level ok)` / `speech model not ready` — computed from
blob size, clip duration, and RMS. **Next session starts by reading that line.**

**Next-session diagnostic sequence (in order):**
0. NEW (`&stt=` knob, shipped 2026-06-11): if step 1 reads "whisper heard no words (level ok)",
   reload the station URL with **`&stt=wasm`** appended — if takes then transcribe, the WebGPU
   fp16 encoder path is broken on this Android GPU (top code-side hypothesis; iPad-only validated)
   and the fix is per-device backend selection.
1. One deliberate take on the Android lite station → read the status/⚙ line → the named reason
   forks the investigation (capture vs silence vs model).
2. Split capture from playback: from the control room, send Lee a **Say-as-character** line — if
   the tablet SPEAKS it, playback is fine and the issue is capture-side only (and vice versa).
3. Same tablet, **avatar page** (any 🪞 character): does PTT work there? Isolates lite-mode vs
   Android-platform.
4. ⚙ line basics on that tablet: backend (`webgpu` vs `wasm`) + cold-load time; the 🐞 debug QR
   (launcher toggle — carries mode=audio now) for console errors; Chrome mic permission for the
   portal origin; crossOriginIsolated (COI=true shows in the debug console header).
5. Record the tablet model + Chrome version in this entry when known.

**RESOLVED CHAIN (2026-06-11, field-diagnosed step by step):** ① CA never trusted on the
Android tablet → Chrome silently blocks getUserMedia on cert-override pages (mic dead while the
page looked fine) → fixed by installing the root CA (downloaded via the https portal route after
one proceed-through; the :8766 helper is broken by Android Chrome's HTTPS-First upgrade — add an
https /onboard route, queued). ② "speech model not ready" → the ASR engine failed to init:
`[webgpu] not supported` (no GPU API on this tablet — expected) AND the CPU fallback hit ORT
"no available backend found" → the .asyncify ORT build's CPU EP doesn't register on this Chrome →
fixed by committing the build per device BEFORE first init (.asyncify only when navigator.gpu
exists; PLAIN threaded otherwise) + skipping the webgpu attempt entirely without navigator.gpu.
③ Then "Can't create a session … TransposeDQWeightsForMatMulNBits Missing required scale"
(qdq_actions.cc) — ORT **1.26-dev**'s CPU graph optimizer REWRITES the q8 DQ/MatMul patterns into
MatMulNBits and fails on embed_tokens; the model contains ZERO MatMulNBits ops (verified) — the
optimizer fabricates them → fixed with `session_options.graphOptimizationLevel='basic'` on the
wasm path only (skips the extended QDQ rewrite; iPad/WebGPU keeps full optimization).
Awaiting the post-③ tablet take. Lesson: dev-build ORT on the unpiloted platform = three stacked
failures, each only visible after the previous one fell.

**FR-008 S7 bugfix (2026-06-13) — multi-patient 'wrong dose' returned no suggestions.** The
staged-error engine grounds dose/admin/interaction candidates in the FR-001/002 med board
(med_orders.get_state). Single-patient lazily inits that board when the meds card loads;
multi-patient beds had no such trigger, so 'right med, wrong dose' on a bed came back "No
injectable suggestions." Fix: the staged-error routes now lazily create the board for the
resolved session (_ensure_board in _resolve — condition detected from the bed's patient, same
as med_routes), so single- AND multi-patient self-init. Caught a test gap: the S7 fixture
pre-initialized the board, masking this; added a regression test that clears it to reproduce
the real room flow.

**FR-008 S7 (2026-06-13) — per-encounter staged errors (multi-patient).** Field gap: the
builder only worked single-patient (its routes resolved "the session" via get_active(), which
returns None in a multi-bed room) and had no entry point on the per-bed console. Now the
staged-error API resolves a specific bed via `?bed=<encounter_id>` (the engine is already keyed
by session id and each encounter IS a session — so per-bed arming needed only route
resolution); single-patient still falls back to get_active(). The encounter console gained a
"⚠️ Staged medication errors" card per bed — a "Build a staged error for this bed ↗" launch
(opens the wizard scoped via ?bed=, its own window per bed) + the armed-errors management list
(trigger / stabilize / caught / missed / disarm), all scoped to that bed. The builder page
threads `bed` onto every API call and shows the bed label. Per-bed isolation tested (arming on
bed A never appears on bed B; lifecycle actions 404 on the wrong bed; unknown bed → 404).
Gate 101 (v8 subset). 

**FR-008 COMPLETE (2026-06-12): all six stages shipped.** S5 — the staged-error BUILDER
(own page off Setup: six-step bounded wizard, taxonomy-filtered, grounded suggestions only,
impact previews with exact staged vitals, severe double-confirm, review-and-arm) + the Live
window's staged-errors card (trigger / stabilize / caught / missed / disarm; 5s refresh) +
the instructor API with operator-transcript stamps at every lifecycle action. S6 — the
debrief now renders the full arc (⚠️ Staged medication errors section: what was planted,
where, impact, timeline, outcome; missed rows highlighted as discussion anchors) + the
one-page field script (`docs/FR-008-field-script.md`, five drills — one per error type —
incl. the auto-on-administer impact + stabilize check). Gates 95→96 portal / 126 client.
**✅ FIELD-VALIDATED (2026-06-13, partial):** in a live session the system **tracked an armed
medication error and the debrief correctly reported it as MISSED** — confirming the core
arm → resolve(missed) → debrief arc (S1 catalog · S5 builder · S6 debrief outcome). Still to
validate in a session: the verbal-vector delivery (doctor speaks the error → defend → correct),
the document-vector chart-discrepancy catch, and the patient-impact trigger/stabilize (the
remaining drills in `docs/FR-008-field-script.md`).

**Awaiting:** the remaining field drills (verbal / document / impact) + instructor clinical
review of the two DRAFT catalogs. ↓ History below.

**ROUTE RATIFIED + SHIPPED (2026-06-11, ADR-0038 — FR-006b):** instructor chose **room-local**
over cloud-primary. The portal Mac transcribes for audio stations: `POST /api/face/stt`
(faster-whisper **small.en** int8 — a bigger model than any tablet could run), device routing
`resolveSttRoute` (WebGPU→on-device unchanged; no-WebGPU→portal; `&stt=` pins), portal failure
arms the on-device wasm BACKUP, honest per-route privacy labels. Mac smoke: 3.4s spoken clip →
**1.34s cold / see warm below** vs 17.0s on-tablet (~13×), model boot-warmed in 1.0s.
~~Future accuracy lever~~ **SHIPPED 2026-06-12:** the active session's med-board drug names +
MAR meds ride along as recognizer hints (faster-whisper hotwords; names only — availability
state never leaks into recognition). A/B on the real engine: plain "seftriaxone" → hinted
"ceftriaxone"; live unhinted control heard "Ceph Trich Zone" — the lever targets exactly the
order-critical vocabulary. Same batch: audio station shows the persona display name (never the
internal id), https /onboard on the portal origin (Android HTTPS-First gap closed), and the
long-chipped placeholder-portrait test un-staled → BOTH GATES FULLY GREEN (126 client · 55
portal). **✅ FIELD-VALIDATED 2026-06-12**
on the Android tablet over the Beryl kit router (stt 200 → listen 200; instructor: Android now
responds like the iPad). FR-006 chain CLOSED.

**FIELD RESULT (2026-06-11): the Android loop WORKS end-to-end** — model loads, takes
transcribe, character answers with server voice. Remaining: **CPU transcription is far too slow**
(single-threaded wasm). Shipped same-day: multi-threaded inference (numThreads = min(4, cores),
`&sttthreads=N` A/B knob) — awaiting timed retest. If still slow, the decision menu (instructor
to ratify): Moonshine CPU model (OPT-002, designed for short clips, no 30s padding) · room-local
STT on the portal Mac (audio crosses the LAN to the instructor's machine only — no third party;
needs a small ADR) · cloud Web Speech as designated-station primary (trainee audio → Google;
contradicts the fail-closed PHI posture, ADR-0014/0025 — instructor sign-off + ADR required).

**Hypotheses ranked for Android Chrome:** (a) the threaded-WASM / WebGPU ASR path failing
quietly on this hardware (model loads but inference yields empty), (b) MediaRecorder
codec/decodeAudioData mismatch on this Chrome build, (c) mic permission/route to the wrong input,
(d) playback-side autoplay gating (if step 2 is also silent).

## BUGFIX 2026-06-13 — multi-patient bed only checked the patient, not the full roster

**Symptom (instructor):** in multi-patient (room) mode the characters checked off for a bed
differ from single-patient — e.g. Mr. Hayes should bring his charge nurse, RT, wife and doctor
(as single-patient does), but only Mr. Hayes was checked. **Root cause:** single-patient's
template picker checks the sample scenario's full `personas[]` roster; the room wizard's
per-row Activity picker checked only `seed_persona_id` (the patient). The room finalize already
sends each row's CHECKED persona boxes, so the gap was purely the auto-fill. **Fix
(client-only, no schema change):** when a bed's Activity is picked, match its label to the
same-named sample scenario and check that sample's full `personas[]` roster (single source of
truth = sample_scenarios.json), falling back to just the patient when no sample matches.
Operators can still tick/untick per bed. 2 data-contract tests (Hayes pulls the 5-persona
roster; every sample-backed activity's roster contains its patient). Gate 112.
**Known gap:** the 8th built-in activity (Med-surg · Acute respiratory failure) has no
matching sample → still seeds only its persona; that activity also seeds P-006 (a pharmacist)
as its patient — a pre-existing data oddity to clean up when a resp-failure sample is authored.

## BUGFIX 2026-06-13 — Medical Records opened in the same tab (Back reset the system)
Launch EHR used a bare target= (a tab, often the same one); switched to an explicit
sized window.open('medsim_ehr_window') with same-context-nav cancelled — closing the
EHR window returns to an intact control panel. Mirrors the Live Ops + error-builder windows.

## BUGFIX 2026-06-13 — Medical Record showed the DOCTOR as the patient

**Symptom (instructor):** single-patient session → open the Medical Record → the doctor is
listed as the patient character. **Root cause:** `ehr_seed.seed_from_session` built the chart
from `selected_personas[0]` blindly, and `create_session` never sets `patient_persona_id`, so
once a clinician is listed first (e.g. a doctor added for the FR-001/002 ordering loop) the
chart seeds from the CLINICIAN. The M58 resolver `patient_persona_id()` existed but its
fallback was also `[0]`. **Fix:** role-aware patient resolution — `patient_persona_id()` now
prefers the selected persona whose `roleGroup == "Patient"` before the legacy `[0]` fallback;
`seed_from_session` + the EHR `register_session` "primary" + the med-board condition detector
+ the add-device default all route through it. 4 regression tests (clinician-first resolves
the patient, explicit pick wins, chart seeds from the patient, all-clinician legacy fallback).
Gate 136/136. Note: requires the wizard to include a Patient-roleGroup persona (it always
does in single-patient mode).

## FR-009 (P1) — Shift turnover / handoff training (filed 2026-06-12, deep research commissioned)

**Asked (instructor, near-verbatim):** Critical training at the start and end of the shift:
SHIFT TURNOVER. For single-patient or multiple-patient sessions there needs to be an
end-of-shift handoff. This can be a scenario ITSELF, built using the other scenarios. The
existing portfolio (and the future expanded portfolio) provides the context — current patient
state, concerns, key medications and treatments, things to look out for. Used two ways: check
what follow-up questions a student GENERATES if oncoming, or how they RESPOND if off-going.
After the handoff, a STUDENT SURVEY the student answers with recorded VERBAL responses, then
evaluated: their perceptions versus what detail and questions actually came up, key gaps, and
whether any high-risk elements were missed that would put a patient at risk. The
oncoming/off-going nurse or charge nurse comes from the existing character list.

**Filed assets to build on:** chart seed already carries the handoff substance (chief
complaint, problems, MAR + admin history, vitals trend, allergies, care_team, notes incl. the
FR-008 staged SBAR note machinery); FR-008 report-encounter errors can be EMBEDDED in a
handoff (catch-the-discrepancy during turnover); room-local STT (FR-006b) records + transcribes
the verbal survey; the comparison/rubric store (ehr_db save_comparison) and debrief surface
exist; personas list carries nurse/charge-nurse characters; FR-007 (shared staff across
patients) intersects for the multi-patient mode.

**Status (2026-06-12):** Research DONE + VERIFICATION COMPLETE (25 targets: 20 confirmed at
full adversarial protocol, 3 closed by direct quote-verification at source, 2 refuted — both
from one excluded low-tier source; ZERO refutations against used material across four passes).
Report finalized with the quantified perception gap (8.1 vs 7.1, p<0.001), the receiver
read-back mandate + named observation tools, and a training-effectiveness source. Durability
pack: research/FR-009_research/. **PACKAGE COMPLETE (2026-06-12):** + worked samples
(FR-009_samples.xlsx — 6 sheets incl. the standalone authoring template; sample context-pack
PDF; sample evaluation/debrief PDF), + CODING PLAN at implementation grain
(docs/PLAN-2026-06-12-fr009-coding-plan.md: H1–H6 file-level + SA1–SA3 standalone extraction
— handoff_core package → handoff-lite app → packaged install; build-once-extract-never-fork),
+ dual-deployment strategy section in the report (§5b + Appendix A). All on the Desktop for
review. Build starts at FR-008 S5/S6 then H1, on ratification. Plan WRITTEN
(`docs/PLAN-2026-06-12-fr009-shift-handoff.md`, stages H1–H6) + **PDF strategy report
delivered** (`research/FR-009_shift-handoff-strategy.pdf`, copy on the Desktop). Design core:
SBAR skeleton + I-PASS severity/synthesis + contingencies as first-class high-risk element;
per-patient context pack as ground truth; off-going/oncoming modes; completeness dial;
6-question verbal survey via room STT; binary coverage scoring + perception delta, instructor-
confirmed, formative. Sequencing: FR-008 S5–S6 first (shared surfaces). **Build awaits
instructor review of the PDF.**

## FR-008 (P1) — Instructor-staged medication errors (error-recognition training)

**Asked (2026-06-12, instructor — taxonomy near-verbatim):** medication errors fall into
general areas, each with the vector(s) where it is realistically introduced:

| # | Error type | Introduced via |
|---|-----------|----------------|
| 1 | **Transcription** — different meds sounding the same | verbal/phone orders |
| 2 | **Right med, wrong dose** (high or low) | verbal/phone orders · OR an existing order in conflict with other notations/documents |
| 3 | **Dangerous medication interaction** | verbal/phone orders · OR existing order in conflict with notations/documents |
| 4 | **Allergic-reaction potential oversight** | verbal/phone orders · OR existing order in conflict with notations/documents |
| 5 | **Noticed administration error** — wrong med, wrong time, wrong dose, med out of date | existing order in conflict with notations/documents |

**Instructor selects three axes:** error TYPE × WHERE it is introduced (vector) × WHEN the
student encounters it — e.g. during report, charting, preparing for med pass, during a med pass.

**Design sketch (proposed, pre-plan):**
- **Error catalog (authored data, DRAFT-gated for clinical review like med_orders.json):**
  sound-alike pairs keyed to the formulary; dose-error transforms (10× high, ½ low, mg↔mcg);
  interaction pairs; allergen→med map; admin-error templates (expired, wrong-time, wrong-med).
- **Armed-error session state:** {type, vector, encounter_point, payload, caught?} — seeded
  suggestion, instructor override; one error armed at a time (multiples = open question).
- **Vector (a) verbal/phone order:** the ordering character SPEAKS the erroneous order at the
  staged moment — rides FR-003 say-as + the `_extra_context` prompt machinery.
- **Vector (b) document conflict:** mutate exactly ONE chart artifact while the rest of the
  chart carries the truth — the discrepancy IS the teachable signal. Artifact by encounter
  point: report → seed_report line · charting → notes_recent · prep med pass → med board
  cart/pharmacy + MAR · med pass → the MAR row at admin time.
- **Control room:** error card on Setup (type → vector → encounter point → payload → ARM);
  live caught/missed marking for debrief; transcript-stamped.
- **STT interplay (subtle):** when a transcription error is armed, BOTH sound-alike names go
  into the recognizer hints — the student's repeat-back of either drug must transcribe
  faithfully; the system must never auto-correct the student toward the "right" drug.
- **Open questions:** catalog authorship/clinical review · simultaneous errors? · caught =
  instructor-marked or transcript-inferred? · scoring/debrief artifact shape.

**Amendment (2026-06-12, instructor):** + optional **patient impact** — inject the negative
medical state the error would cause in real life (curated consequences per type, severity
tiers, instructor-triggered or auto-on-administration — med.administer events already exist);
+ **dedicated builder page** in the pre-start (Setup) stage — a structured wizard so the
authored error stays bounded (catalog-grounded choices only, review-and-arm summary);
+ type/mode/impact arc feeds the **debrief**. Impact composes existing levers (vitals events,
scenes handlers incl. pump.alarm/code.blue, patient prompt blocks) — no new physiology engine.

**Status:** Filed; detailed plan (S1–S6) written + amended, pending instructor ratification. Effort L–XL. Builds on FR-001/002
(med board), FR-003 (say-as), ehr_seed chart surfaces (allergies, MAR+admin history,
notes_recent, seed_report — all already exist).

## FR-007 — Unit-level shared staff characters (one tablet, many patients)

**Area:** character-interaction · clinical-logic · scenario · **Source:** instructor (2026-06-10) ·
**Priority:** P2 · **Status:** Proposed — *investigate before speccing* · **Effort:** L ·
**Lands in:** portal + runtime(core) + control-room + avatar

**Goal.** Mirror real staffing: ONE charge nurse / doctor / respiratory therapist / pharmacist
covers a whole unit of patients from a single tablet. The student must IDENTIFY which patient
they're discussing (by name — not assume a single shared patient), and the character then pulls
that patient's details (chart, condition, meds) and discusses them in depth exactly as the
per-patient characters do today.

**Behavior sketch.**
- A staff character is bound at the UNIT (room) level instead of to one encounter; its station
  serves all the room's patients. (Pairs naturally with the FR-006 🔊 audio-only station — one
  cheap tablet per unit role.)
- Turn pipeline: detect the referenced patient from the utterance (name match against the room
  roster); on ambiguity or no match the character asks, in role, "Which patient?" — and may
  REQUIRE proper identification (name + second identifier), which is itself a teaching point.
- Once identified: that encounter's context loads for the turn — chart fold/MAR, condition,
  FR-001/002 med board — and the reply/transcript log attribute to THAT encounter.
- Switching patients mid-conversation re-anchors context ("Now about Mr. Doyle…").

**Why investigate first (the architectural questions).**
1. Today a turn = (scenario, character) + the single active session's context; v7 ROOM mode
   already gives per-bed encounters — the staff turn must select an encounter per utterance.
2. Patient-name detection: deterministic roster match vs LLM-assisted resolution; confirmation
   policy on ambiguity; misidentification as a logged teaching event?
3. Per-encounter med boards (FR-001/002 state is currently one-per-session).
4. Memory/attribution: one station's transcript fanning into N encounter transcripts.
5. QR/binding shape: unit-level channel + how push_speech routes replies back to the one tablet.
6. PHI posture unchanged (sim patients), but identification discipline should mirror two-identifier
   practice as a curriculum touchpoint.

**Acceptance (draft).** One charge-nurse tablet in a 3-bed room: asking about each patient by
name yields patient-correct details; an unnamed/ambiguous ask gets an in-role identification
request; transcripts land on the right encounters.

---

## FR-010 — Post-restart device readiness ping (health-check + warm cold→warm)

**Area:** UX · instructor-tools · ops · avatar · **Source:** instructor (2026-06-13) ·
**Priority:** P1 · **Status:** Proposed — *investigate before speccing* · **Effort:** L ·
**Lands in:** portal + avatar + control-room

**Asked (instructor, near-verbatim):** To make the system easier to use, after a tablet has
been cached with a character or device — once the system is started back up, can it ping the
devices to: (a) check status — ready to go or not; (b) check what device or character they
have; (c) check it's working OK; (d) for a character, push text and activate the mic to warm
the system from cold to warm.

**Goal.** A one-glance readiness board after any portal restart: the instructor sees every
previously-paired tablet, what it's running, whether it's healthy, and can warm the character
tablets so the first real interaction isn't slow — instead of re-walking to each tablet.

**Behavior (target).**
- **(a) Status ready/not** — per tablet: paired · reconnected-since-restart · model loaded ·
  last-seen fresh → a green/amber/red readiness pill.
- **(b) What it runs** — character (which persona, avatar vs audio) or device (kind/model),
  read from the persisted pairing.
- **(c) Working OK** — a round-trip health ping over the tablet's live channel (ack + report:
  WS connected, model state, mic-permission state, errors).
- **(d) Warm cold→warm (character)** — trigger model/pipeline warmup (ASR load + room-STT
  connect + a TTS test line pushed over the speech WS), so the first turn is warm.

**Why investigate first (the hard constraints).**
1. **Persistence across restart.** A restart wipes the in-memory control session and drops
   paired stations (the repeated "fresh Setup after restart" pain). Pinging "cached" tablets
   first requires persisting the roster (which station, what character/device, last-seen) and
   re-adopting it on boot. `ehr_db.register_station` already persists some of this — scope
   what must survive + a boot-time re-adopt path.
2. **Reverse channel (portal→tablet).** Tablets currently PULL (poll/heartbeat). A push ping +
   warmup needs a portal→device channel. The avatar app already holds a speech WebSocket
   (push_speech, ADR-0007 auto-reconnect) — readiness = "has the WS reconnected since the
   restart?"; health = a round-trip over it. Audio/device stations may need an equivalent.
3. **Browser gesture wall on (d).** Browsers BLOCK starting the mic (getUserMedia) and audio
   playback without a user gesture on the tablet — the portal cannot force-open the mic
   remotely. So warmup can preload the model + connect room-STT + push a line, but the mic
   stream itself likely needs a one-tap "Ready" handshake on the tablet. Design a low-friction
   tablet-side "tap to arm" that the instructor's ping prompts (a single tap warms everything).
4. **Health semantics + security.** Define "working OK" precisely (WS up · model loaded ·
   mic-permission granted · last error). Keep the ping auth'd (ADR-0027 token posture) so a
   stray LAN client can't enumerate/drive tablets.

**Acceptance (draft).** After a portal restart with 3 previously-paired tablets (2 characters,
1 device): the control room shows all three with correct identity + a readiness pill within
~10 s of each reconnecting; a "Warm" action on a character tablet loads its model and pushes a
test line; an unreachable tablet reads red with a reason. No second walk to the tablets for
status; at most one tap per character tablet to fully arm the mic (browser constraint, noted).

**Builds on.** Speech WS + push_speech (ADR-0007) · station registry + heartbeat
(`/api/device/{id}/heartbeat`, `/api/ehr/state` roster poll) · room-STT warm path (ADR-0038) ·
the avatar app's reconnect/warm hooks (`installFirstGestureWarmup`) · device-token posture
(ADR-0027). **Note:** directly addresses the standing restart-wipes-the-session friction.

---

## Adding an entry

1. Grab the next `FR-NNN`; add a Summary row + a section.
2. Fill **Area, Source, Priority, Status, Lands in, Goal, Behavior, Acceptance, Clinical
   safety / PHI, Open questions**.
3. Real unknowns → `research/RB-*`. A dependency / data-flow / security / clinical-logic
   change → an **ADR** before `Shipped`.
4. On ship, **validate in a test session** and move to `Validated` with the note.
