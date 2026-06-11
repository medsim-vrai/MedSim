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
6. **Defaults on the open questions** (flag at ratification): multiple errors may be armed but
   the UI nudges one-at-a-time · "caught/missed" is instructor-marked (transcript-inferred is
   a future lever) · debrief artifact = transcript entries at arm/deliver/resolve.

## Encounter-point → artifact map (vector b: document conflict)

| Encounter | Mutated artifact (in the session seed) |
|-----------|------------------------------------------|
| Report | `seed_report` — one handoff line carries the discrepancy |
| Charting | `notes_recent` — a note contradicting the active order |
| Preparing for med pass | med board cart/pharmacy state (+ optional `expired`/lot tag on a cart item) or an order row |
| During med pass | the due MAR row (`meds`) — wrong time/dose/med/expired |

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

**S4 — Control room.** "⚠️ Staged errors" collapsible card (auto-expanded on Setup, minimized
in Live — same behavior as the med checklist): type → vector (filtered per taxonomy) →
encounter → Suggest → pick → ARM; live status chip + Caught/Missed + note; transcript entries
at arm/deliver/resolve. Auth'd routes in `med_routes.py` (`GET /api/control/mederrors`,
`POST …/arm|disarm|resolve`). Tests: route auth, taxonomy filtering, transcript stamps.

**S5 — Ship + field script.** Registers, restart, Mac-side verification (pytest + curl drills
incl. a staged-report curl read-back), and a one-page instructor validation script (arm each
type once; expected student-visible signal per encounter point).

Each stage gates (client 126 + portal 55, both currently fully green) and commits separately.

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
