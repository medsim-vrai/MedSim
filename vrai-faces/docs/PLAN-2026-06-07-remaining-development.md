# Remaining Development Plan — 2026-06-07

Active plan for the MedSim V8 / `vrai-faces` bedside-avatar system. Supersedes the
2026-05-31 next-steps note. Grounded in `ROADMAP.md`, `research/RB-003_findings.md`,
`OPTIMIZATION-REGISTER.md`, and `FUNCTIONAL-REGISTER.md`.

## Status

End-to-end bedside loop **validated on iPad**: per-identity face → on-device PTT STT → AI
turn → ElevenLabs voice → synced lip-sync + emotion, served **one-origin**, latency
acceptable. Real ARKit-52 rig (RB-001/ADR-0034), local+cloud voice, emotion, MedSim
integration, CI, and the one-origin launcher fix are in. Remaining = **fidelity, scale-out,
open decisions, productionization** — then a **register-driven continuous-improvement** phase.

---

## Path to production-ready (Tracks 1–4)

Detail lives in the source docs; this is the sequence.

### Track 1 — Avatar visual fidelity (RB-003) · *active, believability-critical*
Engine prereq (three.js → r181) + per-expression jaggies (morph-normals) done. Remaining,
all offline-bake + drop-in: **inner-mouth opaque dome** (S) · **tongueOut** sub-mesh (S) ·
**eye/lip ΔUV** corrections (M). Deferred Phase-2: mesh subdivision, ICT teeth, mouthClose
re-bake. → `research/RB-003_findings.md`.

### Track 2 — Device & performance validation
**Galaxy Tab S9** head-to-head (ADR-0032, hw-blocked; iPad validated) · **OPT-004** bundle
split · **OPT-005** capability-gated precache · latency profiling (AI-turn / TTS / streaming STT).

### Track 3 — Open decisions to ratify (ADRs)
Client **Kokoro TTS** path keep/drop · **audio transport** (base64 vs fetch URL) · **service
worker** (hand-rolled vs vite-plugin-pwa) · make **portal one-origin serve the default** for
deployed devices.

### Track 4 — Productionization & fleet
Bundle **whisper-tiny.en local-first** (`setup:assets`) · **Capacitor** native `.ipa`/`.apk`
(Mac/SDK) · fleet hardening (**MEDSIM_PUBLIC_HOST** stable name + per-iPad **CA trust**) ·
**name-gated** voice activation · live nightly **e2e/soak** on real hardware.

---

## ▶ Planning Gate — after Track 4  *(the review checkpoint)*

**When Track 4 completes, before committing to Track 5, run a backlog review:**

1. **Pull** every open item from the **Functional Register** (`FR-*`, `FUNCTIONAL-REGISTER.md`)
   and the **Optimization Register** (`OPT-*`, `OPTIMIZATION-REGISTER.md`), plus accumulated
   **testing-feedback** intake.
2. **Review & triage** each: still relevant? priority (P1/P2/P3)? effort? Does it need a
   `research/RB-*` (unknowns) or an **ADR** (dependency / data-flow / security / clinical
   decision) before build? For `FR-*`, re-check **clinical-safety + PHI**.
3. **Sequence** the survivors into the **Track 5+ roadmap** — the prioritized items *become*
   the forward plan. Park or drop the rest with a one-line reason.
4. **Record** the outcome (a dated review section here, or a fresh `PLAN-YYYY-MM-DD`) and
   update `ROADMAP.md`.

**This is a standing checkpoint, not one-time** — re-run it at each major milestone so the
registers + field feedback continuously feed the roadmap (the continuous-improvement loop).

**Inputs at the gate today** (will grow as testing adds rows):
- Functional: **FR-001** (doctor med ordering), **FR-002** (pharmacist availability/alts),
  **FR-003** (instructor in-context character prompting).
- Optimization: **OPT-004** (bundle split), **OPT-005** (capability precache), **OPT-006**
  (decoder tuning) + exploration areas (streaming/partial STT, TTS + AI-turn latency, render
  cost at full res / multi-patient, three.js memory churn on re-pair).

---

## Track 5 and beyond — register-driven continuous improvement

**Defined *by* the gate above, not pre-fixed.** Expected themes from today's backlog:
clinical-interaction realism (FR-001/002), instructor tooling (FR-003), perceived-latency +
bundle/footprint perf (OPT-*), and whatever testing surfaces. Each milestone re-runs the gate.

## Ongoing (parallel, not a track)

- Keep filing `FR-*` / `OPT-*` rows + testing feedback **as it surfaces** — don't wait for
  the gate to capture; the gate is for *review/sequencing*, not first capture.
- Refresh `ROADMAP.md` / `BUILD_STATE.md` to current reality (real rig, ElevenLabs voice,
  one-origin launcher fix, RB-003 progress, validated OPTs).
