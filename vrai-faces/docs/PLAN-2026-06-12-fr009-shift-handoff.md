# Plan — FR-009: Shift Turnover / Handoff Training (2026-06-12)

Implements the instructor's requirement (FR-009): end-of-shift handoff as critical training,
single- or multi-patient, composable as a scenario itself from existing scenarios; the student
gives (off-going) or receives (oncoming) report with an AI nurse/charge-nurse; afterward a
VERBAL survey is recorded and evaluated — perceptions vs what actually came up, key gaps, and
missed high-risk elements. Companion: `research/FR-009_shift-handoff-strategy.pdf` (the
research report + strategy for instructor review). **Build awaits ratification.**

## Research grounding (full detail + citations in the PDF)

- **Framework:** SBAR dominates nursing practice/education; I-PASS carries the strongest
  patient-safety outcome evidence but from physician handoffs (profession-split evidence).
  Recommended: an **SBAR-skeleton checklist enriched with I-PASS's two safety-critical
  elements** — an up-front illness-severity statement and a closing receiver SYNTHESIS
  (read-back) — plus contingency/anticipatory guidance as a first-class element and an
  explicit responsibility-transfer moment (TeamSTEPPS).
- **Assessment:** validated instruments (Handoff CEX 6 domains/9-point with provider AND
  recipient versions; SBAR-LA's 10 binary items) teach two design lessons: (1) **binary
  element-coverage scoring** is the reliable automatable core (raters can't reliably score
  "partial" coverage); (2) receiver competence needs its own approach (question quality +
  synthesis, not content recall alone).
- **Failure modes to target:** anticipatory guidance omitted in ~half of untrained simulated
  handoffs; receiver synthesis almost never spontaneous; untrained completeness ≈ 50% —
  and completeness correlates strongly with overall quality (supports checklist scoring).
- **Perception gap:** self/peer ratings run high vs external evaluation — exactly the gap the
  instructor's verbal survey is designed to expose (predict-then-compare).
- *Verification caveat:* the automated adversarial-verification stage hit a usage cap;
  findings are cited primary sources flagged for instructor spot-check, not formally
  cross-verified.

## The platform design (summary — full strategy in the PDF)

1. **Handoff context pack (the ground truth).** Generated per patient from the session's
   chart + events + med board + staged errors: identity/situation · illness severity ·
   background (dx, ALLERGIES, CODE STATUS) · current assessment (latest vitals + trend, key
   labs) · meds & treatments (new/changed/held/due-soon, infusions) · lines/drains/access ·
   pending items · safety risks · anticipatory guidance ("watch for…") · synthesis checkpoint ·
   responsibility transfer. High-risk flags: allergies, code status, high-alert meds (ISMP
   classes already tagged in ehr_seed), pending criticals, contingencies, and any ACTIVE
   FR-008 staged discrepancy (handoff = the "report" encounter point — direct synergy).
2. **Two student roles.** OFF-GOING: student gives report; the AI oncoming nurse (persona
   list) holds the ground-truth pack and probes 2–4 omissions, prioritizing high-risk ones;
   ends by asking for/offering synthesis. ONCOMING: the AI off-going nurse delivers report at
   an instructor-set completeness dial (complete / typical-gaps / staged-error embedded);
   the student's QUESTIONS are the assessed behavior; AI answers honestly from the chart.
3. **Multi-patient (charge-nurse) mode.** Sequential packs + a cross-patient prioritization
   element (who first and why) — FR-007 shared-staff synergy.
4. **Verbal survey (post-handoff, on the station, PTT → room STT).** ~6 questions: overall
   completeness self-rating + why · "the three most important things you handed off/heard" ·
   "what do you think you missed?" · "what should be watched for tonight?" · "anything in the
   chart that didn't match what you heard?" (FR-008 probe) · (oncoming) "your first action?"
5. **Evaluation engine.** Binary element-coverage map of the handoff transcript vs the pack
   (AI-assisted scoring on the existing comparison-store pattern, instructor confirms);
   high-risk misses called out; survey transcript compared against the coverage map →
   perception-vs-performance delta; all of it a debrief section (+ printable).
6. **Composition.** Handoff runs as a phase appended to a live scenario OR as a standalone
   "shift handoff" session built FROM existing scenario charts (the instructor's
   "scenario built using the other scenarios").

## Stages (each gated + committed separately)

| Stage | Scope | Builds on | Effort |
|------|-------|-----------|--------|
| H1 | Context-pack generator + high-risk tagging + ground-truth element list | ehr_seed/fold, med board, FR-008 state | M |
| H2 | Handoff session mode + AI counterpart prompts (receiver-probe / giver-with-gaps + containment) + responsibility-transfer + synthesis ask | FR-001/002/003 prompt machinery, persona list | M |
| H3 | Multi-patient sequencing + prioritization element (charge nurse) | H1/H2, FR-007 | M |
| H4 | Verbal survey flow on the station (question sequence, PTT answers, storage) | FR-006b room STT, audio station | M |
| H5 | Evaluation engine (coverage map, survey comparison, perception delta, instructor confirm) + debrief section | comparison store, debrief.py | L |
| H6 | Control-room integration (setup: handoff phase/role/dial/characters; live controls) + field validation script | FR-005 two-stage control room | M |

Sequencing note: FR-008 S5 (builder page) + S6 (debrief) remain queued; H5/H6 share those
surfaces — build FR-008 S5–S6 first, then FR-009 H1.

## Open questions for ratification

1. Formative vs summative: recommend FORMATIVE (feedback artifact, not a grade) given
   automated-scoring validity limits; instructor confirmation gates everything shown.
2. Survey timing: immediately on-station (recommended) vs at debrief on the control room.
3. The completeness dial's "typical-gaps" preset: which gaps (suggest: anticipatory guidance
   + one pending item — the evidence-backed common omissions).
4. Multi-patient count cap for v1 (suggest 2–3).
