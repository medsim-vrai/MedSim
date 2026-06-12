# FR-008 Field Validation Script — Staged Medication Errors (one page)

**Setup (5 min):** preflight (`scripts/preflight.sh`) → control room → Setup: patient +
doctor + Pharmacist Lee (audio) → START. Tablets: patient avatar + Lee's audio station.
Builder: Setup banner → **⚠️ Build a staged error**. Managing: Live window → **⚠️ Staged
errors** card. Disarm always restores the chart exactly; Stabilize walks vitals back.

| # | Drill (one per error type) | Arm it as | The student-visible signal to verify |
|---|---|---|---|
| 1 | **Sound-alike** | Transcription · verbal · during med pass · pick a pair (e.g. "Hespan" for Heparin) | Doctor SPEAKS the wrong drug once, defends once if questioned ("yes, Hespan"), CORRECTS when pressed with a read-back or the indication mismatch — and credits the catch |
| 2 | **Wrong dose** | Right med, wrong dose · document · charting | A progress note ("dose clarified with team as …") contradicts the MAR — the MAR stays right; student must spot the conflict |
| 3 | **Interaction** | Dangerous interaction · document · during med pass | A new med row appears on the MAR, due this pass, conflicting with something the patient is already on; pharmacist (Lee) answers honestly if called |
| 4 | **Allergy + impact** | Allergy oversight · verbal · med pass · impact: anaphylaxis / MODERATE / auto-on-administer | Doctor orders the allergy-conflicting drug. If the student administers it on the cart: patient becomes symptomatic (hives, tight chest) AND the chart's vitals tab shows the staged set (HR 112, SpO2 93, BP 98/60). Press **Stabilize** → vitals walk back, symptoms retire |
| 5 | **Administration error** | Administration error · document · prep | The MAR row carries the deviation (expired lot / wrong time / look-alike stocked) for the student to notice while pulling meds |

**For each drill, record:** caught or missed (the card's ✅/❌ + a one-line note) · did any
character hint it was staged (containment breach = file it) · did the doctor's correction arc
feel like a busy clinician (defend once → correct when pressed).

**Severe-impact check (optional, end of session):** re-arm drill 4 as SEVERE/manual — the
Live card must demand the second confirmation dialog before firing.

**Close:** resolve everything (caught/missed) → end session → open the debrief → confirm the
**⚠️ Staged medication errors** section shows the full arc (armed → delivered → impact →
stabilized → resolved times, outcome, notes). Missed rows are the debrief discussion anchors.

**Afterwards:** register the results in FUNCTIONAL-REGISTER FR-008 (✅ Validated, or file
what broke). Remaining reviews either way: the two DRAFT catalogs
(`portal/data/med_orders.json`, `portal/data/med_errors.json` incl. impact tiers).
