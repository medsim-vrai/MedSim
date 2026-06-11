# Plan — FR-008: Instructor-Staged Medication Errors (2026-06-12)

Implements the instructor's error-recognition design (FR-008 in FUNCTIONAL-REGISTER.md):
the instructor arms a **classified medication error** at a chosen **introduction vector** and
**encounter point**; the student's job is to catch it. Written at the planning gate;
**build starts only on instructor ratification** (established pattern).

## The three instructor axes (the spec)

| Axis | Values |
|------|--------|
| **Type** | 1 Transcription (sound-alike) · 2 Right med wrong dose (high/low) · 3 Dangerous interaction · 4 Allergy oversight · 5 Administration error (wrong med/time/dose, expired) |
| **Vector** | verbal/phone order · document conflict (existing order vs other notations/documents) — per-type allowed vectors per the taxonomy (type 1 verbal-only; type 5 document-only) |
| **Encounter point** | report · charting · preparing for med pass · during med pass |
| **Impact** (2026-06-12 amendment) | optional negative patient state if the error plays out — curated consequences per type (e.g. allergy → urticaria/anaphylaxis tiers; overdose → hypotension/sedation; interaction → bleeding signs), severity tier mild/moderate/severe, trigger mode |

**Impact amendment (instructor, 2026-06-12):** the instructor can inject the negative medical
state the error would cause in real life; the system provides a STRUCTURED PATH (wizard) so the
authored error stays bounded; the builder lives on its OWN page reached from the pre-start
(Setup) stage; type/mode/impact feed the debrief discussion.

## Architecture decisions (locked unless instructor objects)

1. **Errors are session-state only.** Document-vector edits go through the session's private
   chart record (`ehr_db.seed`/`update_seed` — the same read-modify-write the portal already
   uses). Authored scenario files stay READ-ONLY (standing constraint). Arming stores the
   original artifact slice in the armed-error record → disarm restores it byte-for-byte.
2. **One discrepancy, truth everywhere else.** Each armed error mutates exactly ONE artifact;
   the rest of the chart carries the truth. The conflict is the teachable signal — never
   rewrite both sides.
3. **Containment rule in every prompt block:** the character delivers the staged error
   realistically, defends it once if challenged (busy-clinician realism), re-checks if
   pressed — and NEVER invents additional errors beyond the staged one.
4. **Catalog is generic; suggestions are session-grounded.** `med_errors.json` holds generic
   clinical patterns; the engine intersects them with the session's formulary + MAR +
   documented allergies, so suggestions are always injectable in THIS scenario. No documented
   allergy → no allergy-error suggestions (with an explanatory hint), never auto-document one.
5. **STT must not un-teach the error.** When a transcription error is armed, BOTH sound-alike
   names join the recognizer hints (`room_stt.session_vocab` merge) — the student's repeat-back
   of either drug transcribes faithfully; the system never auto-corrects toward the "right" med.
6. **Impact composes EXISTING levers — no new physiology engine.** The bedside monitors
   already read vitals events (+ jitter) and the M7 scenes engine ships handlers
   (vitals.drop/rise, lab.result, pump.alarm, code.blue…); the patient character already takes
   prompt-block context (symptoms + emotion). An impact = a curated bundle of those, applied
   together, fully reversible.
7. **Impact triggers are explicit, never timed.** Primary: the instructor presses
   "Trigger impact" in the Live window. Optional per-error toggle: auto-trigger when the
   student ADMINISTERS the staged med (the system already records med.administer /
   cabinet.administer events). Severe-tier impacts require a second confirmation click.
   "Stabilize" reverts vitals toward baseline + clears the symptom block, transcript-stamped.
8. **Bounded by construction (the structured path):** every wizard step offers only
   catalog-grounded choices — no free-text clinical content anywhere (instructor note field
   excepted, and it is debrief-only). Review-and-arm shows a plain-English summary of exactly
   what will appear, where, and what the impact will do, before anything is staged.
9. **Defaults on the open questions** (flag at ratification): multiple errors may be armed but
   the UI nudges one-at-a-time · "caught/missed" is instructor-marked (transcript-inferred is
   a future lever) · debrief artifact = the full structured arc (type/vector/encounter/impact ·
   armed/delivered/triggered/resolved timestamps · caught/missed · instructor note) rendered in
   the existing debrief surface (portal/debrief.py) plus transcript stamps throughout.

## Encounter-point → artifact map (vector b: document conflict)

| Encounter | Mutated artifact (in the session seed) |
|-----------|------------------------------------------|
| Report | `notes_recent` + one "Shift Handoff (SBAR)" note (off-going RN) — *S2 correction: `seed_report` turned out to be the operator QA card, not the handoff; the handoff is realistically a note* |
| Charting | `notes_recent` + one progress/clarification note contradicting the MAR |
| Preparing for med pass | `medications` — ONE row's preparation fields (dose, expired-lot tag, stocked-with tag) |
| During med pass | `medications` — ONE row's administration fields (dose/time + due-now tag; interaction/allergy plant the new row) |

*S2 field note:* the student chart = event fold + stored seed (`projection["seed"]`), so
`update_seed` is exactly the student-visible path. S2 also surfaced and fixed a latent FR-001
bug: `active_med_names` read chart key `meds` but ChartSeed stores `medications` — the doctor's
already-on exclusions were silently empty from the seeded MAR.

Vector a (verbal/phone): the ordering character (doctor/charge nurse per encounter) speaks the
staged order via the existing `_extra_context` prompt machinery (FR-001/002) and the FR-003
say-as path; "delivered" stamps when the staged payload first appears in a character reply.

## Stages

**S1 — Catalog + engine core.** `portal/data/med_errors.json` (DRAFT-gated: sound-alike pairs,
dose-error transforms (10× high, ½ low, mg↔mcg swap, double), interaction pairs, allergen→med
map, admin-error templates) + `portal/med_errors.py` (per-session armed list; `suggest(type,
vector, encounter)` seeded-RNG over catalog∩session; `arm/disarm/resolve/state`; original-slice
snapshot). Tests: suggestion grounding, arm/restore round-trip, no-allergy⇒no-suggestions, RNG
determinism. *No UI, no behavior change unarmed.*

**S2 — Document vector.** Seed mutation per the encounter map via `ehr_db.seed`→`update_seed`;
disarm restores. Tests: single-artifact mutation with truth intact elsewhere; each encounter
point; restore fidelity; unarmed sessions byte-identical.

**S3 — Verbal vector + STT interplay.** Error block into `prompt_block_for` for the ordering
character (with the containment rule); delivered-stamping in the turn/speak paths;
`med_errors.vocab_extras()` merged into `room_stt.session_vocab` (both sound-alike names).
Tests: block content + containment text, delivered detection, vocab merge.

**S4 — Impact engine.** Consequence catalog (curated per error type, severity tiers) +
`med_errors.trigger_impact/stabilize`: applies the bundle — vitals events the monitors read,
patient-character symptom block via `_extra_context` (with emotion cue), optional pump.alarm /
code.blue for severe tier — and reverts cleanly. Auto-trigger hook on med.administer of the
staged med (per-error opt-in). *Stage recon note:* confirm the v8 control-session event path
the bedside devices poll (vs the M7 multi-encounter room path) and target that one. Tests:
bundle apply/revert round-trip, auto-trigger match, severe-tier double-confirm flag, unarmed
sessions untouched.

**S5 — Builder page + live controls.** NEW auth'd page `/portal/control/errors` (linked
prominently from the Setup stage banner): a 6-step wizard — 1 Type → 2 Vector (taxonomy-
filtered) → 3 Encounter point → 4 Payload (grounded suggestions) → 5 Impact (optional:
consequence, severity, trigger mode) → 6 Review-and-arm (plain-English summary). Live window
gets a compact status chip per armed error: state (armed/delivered/triggered) + Trigger impact ·
Stabilize · Caught · Missed + note. Auth'd routes (`GET /api/control/mederrors`,
`POST …/arm|disarm|trigger|stabilize|resolve`). Tests: route auth, taxonomy filtering, wizard
payload validation, transcript stamps.

**S6 — Debrief + ship.** Staged-error section in the debrief surface (the full arc with
timestamps); registers; restart; Mac-side verification (pytest + curl drills incl. a
staged-report read-back and an impact trigger/stabilize round-trip); one-page instructor field
script (arm each type once; the expected student-visible signal per encounter point + impact).

Each stage gates (client 126 + portal 55, both currently fully green) and commits separately.
S1–S3 are unchanged by the amendment; the impact arm is additive (S4) and the builder page
(S5) replaces the earlier inline-card plan — a card remains only as the Live status chip.

## Out of scope (filed, not built)

Auto-detection of "caught" from the transcript · scoring rubrics · multi-patient error
distribution (FR-007 interplay) · authored per-condition error presets.

## Risks

- **Clinical correctness of the catalog** — shipped DRAFT-gated like med_orders.json;
  requires instructor review before teaching use (the register will say so).
- **Prompt leakage** (characters hinting at the staged error): containment rule + tests
  asserting the block's exact instructions; field validation watches for spills.
- **Seed-shape drift**: mutations target named keys (`seed_report`, `notes_recent`, `meds`);
  S2 tests pin the shapes so an ehr_seed change breaks loudly, not silently.
