# FR-009 Field Validation Script — Shift Handoff Training (one page)

**Setup (5 min):** preflight (`scripts/preflight.sh` → 6/6) → control room → Setup: a patient
(e.g. Mr. Hayes) + a **nurse / charge-nurse** persona (the AI counterpart) → START. On the
Live page, open the **🔄 Shift handoff** card. (Single-patient runs from this card; the engine
also supports multi-patient charge-nurse turnover via the API — UI on the per-bed console is a
follow-on.)

---

## Drill 1 — OFF-GOING (student GIVES report; the AI nurse receives + probes)

| # | Step | Verify |
|---|---|---|
| 1 | Handoff card → Mode = **Student GIVES report** → pick the counterpart → **Start handoff** | Card shows "offgoing · handoff" |
| 2 | Student gives report to the counterpart tablet, **deliberately omitting** the allergy/code status and the watch-fors | The AI nurse listens, then **asks follow-up questions about the gaps, high-risk first** (allergy? code status? anything to watch for?) and asks for a **read-back** before accepting |
| 3 | Send the student's tablet to the survey: append **`&survey=1`** to its URL | The station becomes a voice questionnaire; student answers ~6 questions by voice (rate yourself 0–10, top three, what you missed, watch-fors, chart-vs-report, …) |
| 4 | Handoff card → **🧮 Score the handoff** | Per-element coverage appears; the omitted items show **✗ in red (high-risk miss)**; the perception line reads **Self X% vs measured Y% → OVERESTIMATE** when they rated high but covered little |
| 5 | Review the coverage lines; **tick to confirm**, or untick/override any you disagree with | Only confirmed lines render to the student; overriding a miss raises the measured % |
| 6 | **Open debrief ↗** | The "Shift handoff" debrief section shows coverage, high-risk misses, the perception delta, and auto-generated discussion prompts (led by the overestimate prompt) |

## Drill 2 — ONCOMING (student RECEIVES report; the AI nurse gives it)

| # | Step | Verify |
|---|---|---|
| 1 | Start a fresh handoff → Mode = **Student RECEIVES** → completeness = **Typical gaps** → counterpart → Start | The AI nurse **gives** a structured report but under-covers the watch-fors / a pending item |
| 2 | Student asks questions + reads back | A good student asks about the gaps and **summarizes back** |
| 3 | (Optional) Arm an FR-008 **report-encounter** error first, then run with completeness = **Staged-error embedded** | The report carries the discrepancy; the survey's "did anything not match?" question probes whether the student caught it |
| 4 | Survey (`&survey=1`) → **Score** → debrief | Receiver metrics: which elements their questions touched, whether they did a **read-back synthesis**, and whether the staged discrepancy was **caught** |

---

**For each drill record:** did the counterpart probe the *right* (high-risk) gaps · did the
perception delta expose an overestimate / blind spot when warranted · did any character break
containment (hint it was staged) · did the survey transcribe the drug names correctly.

**Close:** End handoff → end session → read the debrief section through. Register the result in
FUNCTIONAL-REGISTER FR-009 (✅ Validated, or file what broke via the field-test Issue Log).

**Honest scope note:** coverage scoring defaults to a deterministic keyword/evidence heuristic
(works offline, reproducible). If it mis-scores an element, the instructor override (step 5)
is the gate — and note it; the AI-scorer hook is the planned refinement.
