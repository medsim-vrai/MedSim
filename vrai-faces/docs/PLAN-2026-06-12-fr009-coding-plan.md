# FR-009 Coding Plan — Claude Code implementation grain (2026-06-12)

Companion to `PLAN-2026-06-12-fr009-shift-handoff.md` (design) and
`research/FR-009_shift-handoff-strategy.pdf` (verified evidence + strategy). This document is
the build script: per-stage files, shapes, signatures, tests, and gates — the same modular
stage→gate→commit method every MedSimVRAI feature has shipped with (FR-001…FR-008 precedent).
Worked samples of every artifact: `research/FR-009_samples.xlsx` + the two sample PDFs.

## Ground rules (house constraints, restated for this module)
- Authored scenario files READ-ONLY; all handoff state is session-private (memory + ehr_db).
- Authored clinical data ships DRAFT-gated for instructor review (like med_orders.json).
- Containment rule in every AI prompt block; plain-English names in all UI.
- Every stage: portal gate (`pytest tests/v8 tests/test_device_routes.py`) + client gate when
  touched (`typecheck · no-any · vitest · build`) green before commit; one commit per stage.

## Element model (shared by everything)

```python
# portal/handoff_core/model.py  (lives portal/ until SA1 extracts the package)
ELEMENTS = (  # id, display, high_risk
    ("identity",   "Identity & situation",            False),
    ("severity",   "Illness severity",                True),
    ("background", "Background incl. allergies + code status", True),
    ("assessment", "Current assessment",              False),
    ("meds",       "Medications & treatments",        True),
    ("access",     "Lines / drains / access",         True),
    ("pending",    "Pending items",                   True),
    ("safety",     "Safety risks",                    True),
    ("anticipate", "Anticipatory guidance",           True),
    ("synthesis",  "Receiver synthesis (read-back)",  True),
    ("transfer",   "Responsibility transfer",         False),
)
# Pack: {"patient": {...banner}, "elements": {id: {"content": str, "high_risk": bool}},
#        "vocab": [drug names...], "generated_at": ts, "sources": {...}}
# Session handoff state (per session, module-level dict like med_orders/_errors):
# {"mode": "offgoing"|"oncoming", "dial": "complete"|"typical_gaps"|"staged_error",
#  "packs": {persona_id: pack}, "order": [persona_id...], "phase": "handoff"|"survey"|"done",
#  "transcript_slice": [turn ids], "survey": {persona_id: [{q, answer_text, ts}]},
#  "coverage": {persona_id: {element_id: {"said": bool, "evidence": str, "confirmed": bool}}}}
```

## H1 — Context-pack generator
**Files:** `portal/handoff.py` (new) · `tests/v8/test_handoff_pack.py` (new)
- `build_pack(session_id, persona_id) -> dict` — composes from `ehr_db.seed` (banner, allergies,
  code_status, medications + admin history, vitals_baseline trend, iv_fluids, problem_list,
  safety_class), `ehr_db.orders/fold` (pending, meds_administered), `med_orders.get_state`
  (board deltas), condition profile (watch-fors), and `med_errors.state` (any ACTIVE staged
  discrepancy joins `anticipate`/`pending` ground truth AND flags the FR-008 probe).
- `severity_for(seed) -> "stable"|"watcher"|"unstable"` — vitals trend vs clinical_ranges
  (reuse `ehr_seed.CLINICAL_RANGES`; worsening/abnormal-latest → watcher/unstable; document
  the conservative mapping in code).
- `pack_vocab(pack) -> list[str]` — drug + allergen names → merged into `room_stt.session_vocab`
  during the handoff phase (same lever as FR-008 vocab_extras).
- **Tests:** golden-pack from the doc_session-style stub seed (the Margaret-Hale shape from the
  samples workbook); severity mapping table; staged-error join; missing-chart-section
  tolerance (each element degrades to "(not documented)" never KeyError); vocab content.

## H2 — Handoff session mode + AI counterpart
**Files:** `portal/handoff.py` (+prompts) · `portal/handoff_routes.py` (new) ·
`portal/vrai_faces.py` (one composition hook) · `tests/v8/test_handoff_mode.py`
- State: `start_handoff(session_id, *, mode, dial, persona_ids, counterpart_id)` /
  `end_handoff` / `state(session_id)`.
- `prompt_block_for(session_id, card) -> str` — the counterpart character only (role match on
  the chosen `counterpart_id`, NOT role-string guessing):
  - **offgoing mode (AI receives):** full pack + behavior arc: listen → probe 2–4 omissions
    (high-risk first; compare what the student SAID — the engine passes a live "still-unsaid"
    list each turn) → request synthesis if absent → explicit acceptance. Containment block.
  - **oncoming mode (AI gives):** pack filtered by `dial`:
    `complete` → all elements · `typical_gaps` → drop `anticipate` + one `pending` item (the
    evidence-backed omissions) · `staged_error` → require an armed FR-008 report-encounter
    error; deliver per its payload. Answer follow-up questions honestly FROM THE PACK.
- Composition hook in vrai_faces (both turn paths, beside med_orders/med_errors):
  `_ctx = join(med_ctx, err_ctx, handoff_ctx)`.
- "Still-unsaid" tracking: `note_student_utterance(session_id, text)` — binary keyword/element
  matcher (coarse, recall-biased; the REAL scoring is H5's job) feeding the receiver's probes.
- **Tests:** block targeting (counterpart only; patient/doctor get ""), dial filtering, probe
  list shrinks as elements are said, containment text, staged_error dial requires an armed
  error (ValueError otherwise), state lifecycle.

## H3 — Multi-patient sequencing (charge-nurse mode)
**Files:** `portal/handoff.py` (extend) · `tests/v8/test_handoff_multi.py`
- `start_handoff(..., persona_ids=[...])` (cap 3, ratified) → per-patient packs + an `order`
  cursor; counterpart prompt gains the sequence frame ("next patient when this one closes with
  a synthesis") + the cross-patient element: after the LAST patient, ask "who first and why" —
  `expected_priority(packs) -> [persona_id]` ranks by severity tier then high-risk count
  (document the tiebreak; the instructor sees + can override in H6 UI).
- **Tests:** order cursor, per-patient pack isolation, expected_priority table incl. the
  samples-workbook case (post-op soft BP outranks improving pneumonia), cap enforcement.

## H4 — Verbal survey on the station
**Files (client):** `vrai-faces/packages/core/src/shell/survey_station.ts` (new) ·
`main.ts` (mount when `?survey=1` arrives via portal push or URL) · reuse `device_stt`
(portal route — survey answers ride room STT) · `__tests__/survey_flow.test.ts`
**Files (portal):** `portal/handoff_routes.py` — `GET /api/face/{cid}/survey` (questions for
this session/mode) + `POST .../survey/answer {q, text}` (stores into session state; ADR-0027
token posture like /listen).
- Question set (ratified v1, from the strategy report §4.4); oncoming-only Q6 filtered by mode.
- Station flow: question card → hold-to-talk → transcribed answer shown → confirm/redo → next;
  finish → "handoff complete, see your instructor." No scoring shown on-station (formative,
  instructor-gated).
- `pack_vocab` + survey-phase terms stay in the STT hints during survey.
- **Tests (portal):** question filtering by mode, answer storage, token enforcement, 409
  without an active handoff. **(client):** flow state machine with mocked fetch+stt.

## H5 — Evaluation engine + debrief section
**Files:** `portal/handoff_eval.py` (new) · `portal/debrief.py` (one new section builder) ·
`tests/v8/test_handoff_eval.py`
- `score_coverage(session_id, persona_id) -> {element_id: {"said", "evidence", "confidence"}}`
  — AI-assisted (the existing comparison-store pattern: haiku-class model, prompt = pack
  element vs handoff transcript slice, BINARY verdict + quoted evidence; SBAR-LA design
  lesson). Stored via `ehr_db.save_comparison` shape; every line `confirmed: false` until the
  instructor toggles it (H6 UI); only confirmed lines render to the student.
- `perception_delta(session_id, persona_id) -> [{survey_q, answer, record, verdict}]` — rule
  layer first (self-rating vs coverage %, claimed-covered vs map, self-identified gaps vs
  actual misses), AI assist only for the free-text matching.
- Receiver metrics (oncoming): questions-asked mapped to gap list, synthesis y/n, planted
  gap/discrepancy caught y/n (joins FR-008 resolve).
- `debrief.build` gains a "Shift handoff" section: pack, coverage map (confirmed lines),
  high-risk misses, survey table, prioritization result, auto-generated debrief prompts
  (template per miss class — see the sample evaluation PDF).
- **Tests:** scoring stubbed-model path (fake client like med-errors' fake engine), binary
  enforcement, instructor-confirm gating, delta rules table (the workbook's sample case as the
  golden test), receiver metrics, debrief section render.

## H6 — Control-room integration + field script
**Files:** `portal/templates/control_ops.html` (Setup card + Live chip) · `portal/server.py`
(stage wiring) · `portal/handoff_routes.py` (instructor endpoints:
`POST /api/control/handoff/start|end`, `GET /api/control/handoff`, `POST .../confirm`
(coverage-line toggles), `POST .../priority_override`) · `tests/v8/test_handoff_routes.py`
- Setup: "🔄 Shift handoff" card — mode, dial, patient pick (≤3), counterpart pick (nurse /
  charge-nurse personas), survey on/off → staged into session; START unchanged (FR-005).
- Live: status chip (phase, per-patient progress) + "Begin handoff" / "Begin survey" /
  "End handoff" + the coverage-confirm panel (after scoring) + debrief link.
- Field validation script (one page, like FR-008's): one off-going run + one oncoming run with
  typical-gaps + survey + instructor confirm + debrief read-through.
- **Gates:** full portal + client suites; live curl drills; restart note (Python changes).

## Dual deployment — the standalone "Handoff Trainer"

**Principle: build once inside MedSimVRAI (H1–H6), then EXTRACT, never fork.**

**SA1 — extract `handoff_core`.** Move the pure logic — element model, pack builder (chart-
dict in → pack out, ehr_db access behind a thin `ChartSource` protocol), prompts, scoring
rules, survey definitions — into `handoff_core/` (own pyproject, zero portal imports; portal
keeps thin adapters). Tests move with it; medsim_v8 gate must stay green (the adapters prove
the extraction). *Gate: both suites + an import-isolation test (`handoff_core` imports no
`portal.*`).*

**SA2 — `handoff-lite` app.** New top-level `handoff_lite/` FastAPI app: login (single
instructor password) · patient authoring by **importing the samples-workbook format**
(sheet 2 = one patient per sheet; openpyxl reader → pack) or pasting a chart summary · the AI
counterpart loop (Anthropic key, same runtime pattern) · browser voice page reusing the
audio-station + room-STT pieces (faster-whisper local — same ADR-0038 posture: audio stays on
the host machine) · survey + scoring + a printable evaluation (the sample-PDF template).
No avatars, no devices, no EHR sim. *Gate: its own pytest suite + a scripted end-to-end smoke
(synthesized voice clip → transcript → scored map).*

**SA3 — packaging.** `pip install handoff-trainer` / zip-run (`python -m handoff_lite`),
config file (key, port, TLS optional), README + instructor quick-start, the workbook template
bundled as the authoring starter. Version pinned to handoff_core; CHANGELOG.
*Gate: clean-machine install drill (fresh venv) + smoke.*

## Sequencing & effort

| Order | Stage | Effort | Depends on |
|---|---|---|---|
| 0 | FR-008 S5 (builder page) + S6 (debrief) | M+M | — (shared surfaces) |
| 1 | H1 pack generator ✅ SHIPPED 2026-06-13 | M | — |
| 2 | H2 session mode + counterpart ✅ SHIPPED 2026-06-13 | M | H1 |
| 3 | H4 survey station ✅ SHIPPED 2026-06-13 | M | H2 |
| 4 | H3 multi-patient ✅ SHIPPED 2026-06-13 | M | H2 |
| 5 | H5 evaluation + debrief ✅ SHIPPED 2026-06-13 | L | H2, H4 |
| 6 | H6 control room + field script ✅ SHIPPED 2026-06-13 | M | all |
| 7 | SA1 extract handoff_core | M | H1–H6 field-validated |
| 8 | SA2 handoff-lite | L | SA1 |
| 9 | SA3 packaging | S | SA2 |

Each stage: plan-conformance check → code → tests → gates → commit → register update.
Field validation after H6 and again after SA2 (the standalone's own smoke).
