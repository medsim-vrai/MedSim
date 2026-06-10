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
| **FR-001** | Best-practice med ordering (doctor) — random primary, min-dose, escalate to secondary | clinical-logic | instructor | P2 | **Shipped** (2026-06-10, draft data pending review) | runtime(core) · portal · data |
| **FR-002** | Pharmacist availability + alternatives; instructor "not available" flag | clinical-logic · instructor-tools | instructor | P2 | **Shipped** (2026-06-10) | control-room · portal · runtime(core) · data |
| **FR-003** | Instructor character prompting — speak in-context (emotion / mental status / role) | instructor-tools · character-interaction | instructor | P2 | **✅ Validated** (2026-06-10) | control-room · portal · avatar |
| **FR-004** | Zero-config wireless device pairing for production venues | UX · scenario | testing | P1 | Proposed | portal · avatar · kit/ops (+ADR) |

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

## Adding an entry

1. Grab the next `FR-NNN`; add a Summary row + a section.
2. Fill **Area, Source, Priority, Status, Lands in, Goal, Behavior, Acceptance, Clinical
   safety / PHI, Open questions**.
3. Real unknowns → `research/RB-*`. A dependency / data-flow / security / clinical-logic
   change → an **ADR** before `Shipped`.
4. On ship, **validate in a test session** and move to `Validated` with the note.
