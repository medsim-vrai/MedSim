# Next-Steps Plan — 2026-06-09

Forward development plan for MedSim V8 / `vrai-faces`, written at the **planning gate** after the
avatar-fidelity track closed out. Re-sequences the surviving backlog from
`PLAN-2026-06-07-remaining-development.md` (its Track structure still holds). Grounded in
`OPTIMIZATION-REGISTER.md` (OPT-*), `FUNCTIONAL-REGISTER.md` (FR-*), `research/RB-003_phase2-plan.md`,
and the 2026-06-09 on-device latency profiling.

## Where we are (validated on iPad)

End-to-end bedside loop works: per-identity face → on-device PTT STT → portal AI turn → ElevenLabs
voice → synced lip-sync + emotion, served one-origin. **Since 2026-06-07:**
- **Avatar fidelity (RB-003) — done.** Full eyelid treatment (feather + real-skin lids + crease +
  bulge); open-mouth teeth (whole-tooth split · jaw-follow on the jaw vertex · transparent open-mouth
  WINDOW · matte enamel · independently-placed lower arch); inner-mouth cavity + tongue; eye/lip ΔUV.
- **OPT-004 validated** — the two big mesh JSONs fetch at runtime; cold-load JS shell **836 KB → 144 KB**.
- **Latency profiled** — perceived turn **~3.5–5.2 s** warm: STT ~1.1–1.5 s (dialed; OPT-001/003), the
  **server turn (LLM + ElevenLabs) ~2.4–4.1 s is the dominant + variable link** (grows with reply length).

## Future improvements (open backlog, by theme)

### A. Perceived responsiveness — *how the interaction feels*
- **OPT-008 · stream the reply (first-sentence TTS).** Biggest UX lever: start speaking in ~1–2 s
  (first words) vs waiting 3.5–5 s for the full reply, and the variability disappears. Portal-side
  (`/listen` streams the LLM + sentence-chunks ElevenLabs; transport pushes partial frames; the app
  already serializes multi-chunk speech). **Effort L · highest-impact single item.**
- Streaming/partial STT (interim text while recording) — smaller front-of-loop win; pairs with OPT-008.

### B. Functional / clinical depth — *what the encounter teaches* (instructor asks, all P2)
- **FR-003 · instructor character prompting (in-context).** Instructor puts a line in a character's
  mouth on that device, with the persona's emotion/altered-state (verbatim or in-character). **Reuses
  the server-voice speak path → lowest-effort functional win (M).** Natural first FR.
- **FR-001 · best-practice med ordering (doctor).** Authored-data random-primary · min-dose ·
  escalate-to-secondary; never AI-invents a drug/dose. **M–L** · runtime(core)+portal+data.
- **FR-002 · pharmacist availability + alternatives.** Instructor flags a med unavailable; pharmacist
  coaches authored alternatives — the doctor→pharmacist→doctor loop. **M** · reuses FR-001's formulary.

### C. Open decisions to ratify (ADRs — these gate productionization)
- **Kokoro TTS keep/drop.** Profiling confirmed every device is on the **ElevenLabs server-voice route**
  (ADR-0037; on-device Kokoro doesn't run on iPad Safari). Decide: keep Kokoro for Android/desktop, or
  drop it → simplifies the build (removes the 2.2 MB lazy chunk) + the speak path (one failure mode fewer).
- Audio transport (base64 vs fetch URL) · service worker (hand-rolled vs vite-plugin-pwa) · make the
  portal one-origin serve the **default** for deployed devices.

### D. Productionization & fleet — *to deploy*
- Bundle whisper-tiny.en local-first (`setup:assets`) · **Capacitor** native `.ipa`/`.apk` (needs Mac/SDK)
  · fleet hardening (`MEDSIM_PUBLIC_HOST` stable name + per-iPad CA trust) · **name-gated voice
  activation** (wake word, deferred ADR-0026) · nightly e2e/soak on real hardware.
- **OPT-005 · capability-gated model precache** (before offline-install; avoid precaching both whisper
  variants). **M.**

### E. Avatar polish (opportunistic, low priority)
- **Open-mouth teeth shading** (spawned task) — forward lower crowns read hot/uneven (transmission
  depth-attenuation + emissive/leak); a dim **mouth fill light** or depth-compensated emissive. **S–M.**
- `transformedNormalView` → `normalView` deprecation in the translucent shader (future-proofing). **S.**
- RB-003 parked: Item 2 lip-subdivision (needs the on-device console error) · re-add gums to cover tooth
  roots · iris-match eyeballs.

### F. Blocked / waiting
- **Galaxy Tab S9 head-to-head** (ADR-0032) — no Android device on hand.

## Recommended sequence

**Phase 1 — make it feel instant + give the instructor a live lever (highest value):**
1. **OPT-008 streaming** — scope the `/listen` handler + transport first, then ship. The biggest single
   UX improvement, and it gates how every spoken turn feels.
2. **FR-003 instructor prompting** — rides the same speak path; high instructor value, modest effort.

**Phase 2 — clinical depth (the doctor↔pharmacist loop):**
3. **FR-001 med ordering**, then **FR-002 pharmacist** (shares FR-001's formulary). Settle their Open
   Questions first — where the primary/secondary taxonomy + ranges are authored, and how active-med
   (MAR) state is read at turn time.

**Phase 3 — decisions → productionization (to deploy to the fleet):**
4. Ratify the Track-3 ADRs — start with **Kokoro keep/drop** (simplifies the build + speak path).
5. Track-4: Capacitor native wrap + fleet hardening (stable host + per-iPad CA trust) + OPT-005 precache
   + name-gated voice; stand up nightly e2e/soak on real hardware.

**Ongoing (parallel, low cost):** the avatar-polish cleanups (teeth shading, the deprecation) make good
warm-ups; keep filing FR-*/OPT-* rows from testing; refresh `ROADMAP.md` / `BUILD_STATE.md` to current
reality. Re-run this gate at each milestone.

## Immediate next action
**OPT-008** or **FR-003**. Recommend starting with an **OPT-008 scoping pass** (the portal `/listen`
handler + the speech transport — confirm where to chunk the LLM + ElevenLabs and how partial frames ride
the transport), since it gates the loop's feel and the FRs ride the same speak path. FR-003 is the
fastest standalone win if a functional feature is preferred first.
