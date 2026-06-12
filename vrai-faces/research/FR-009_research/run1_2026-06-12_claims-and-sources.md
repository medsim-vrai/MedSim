# FR-009 Deep Research — Run 1 evidence base (2026-06-12)

Reconstructed durable record of run 1 (`wf_82632781-47e`, 103 agents, 22 sources, 109 claims
extracted, 5 search angles). **Verification status in run 1: NOT COMPLETED** — all 75
verifier agents hit the session usage cap ("resets 8:20pm"); every claim below was killed by
3-abstain, i.e. *never actually examined*. Run 2 re-verification was launched 2026-06-11
~20:31 with a cache-busted verifier prompt (see README.md). The 25 claims below are the
verification targets, with their sources — the curated core of the evidence base.

## Search angles
1. Framework comparative evidence (broad/primary)
2. Validated assessment instruments and psychometrics (academic/technical)
3. Receiver-side behaviors and read-back (under-examined role)
4. Simulation training designs, failure modes, and self-vs-observed gap (practitioner)
5. Multi-patient and charge-nurse handoff (niche/scenario design)

## The 25 extracted claims (verification targets)

### Framework evidence — AHRQ Making Healthcare Safer IV (structured-handoff rapid review)
Source: effectivehealthcare.ahrq.gov/sites/default/files/related_files/structured-handoff-rapid-research.pdf
1. I-PASS: moderate-certainty evidence (10 studies / 9 implementations incl. 2 RCTs) of patient-safety benefit — the strongest rating of any handoff protocol in the review.
2. SBAR: low-certainty evidence rating for patient-safety outcomes (2 systematic reviews + 2 new studies incl. 1 RCT) — I-PASS outranks SBAR on certainty.
3. The outcome evidence base is almost entirely physician-to-physician in academic hospitals — applying I-PASS-over-SBAR to nursing shift report is an extrapolation; generalizability flagged.
4. Demonstrated I-PASS benefits came from a BUNDLE (2h workshop + 1h role-play/simulation + faculty development + observation tools), not the mnemonic alone.

### Framework evidence — BMJ Quality & Safety 2025 (MHS IV)
Source: pmc.ncbi.nlm.nih.gov/articles/PMC12232517/
5. MHS IV rates I-PASS certainty MODERATE for reducing errors/adverse events — strongest of 12 tools examined.
6. SBAR rated LOW certainty; a third of SBAR studies showed no benefit.
7. Evidence is profession-split: SBAR evidence predominantly nursing, I-PASS predominantly physician; cross-profession generalization not established.

### Nursing I-PASS adaptation — Journal of Advanced Nursing 2025 pilot
Source: onlinelibrary.wiley.com/doi/10.1111/jan.16896
8. Pilot used a nursing adaptation of I-PASS (Identification-Patient-Action-Situation-Synthesis) for oral end-of-shift bedside handover; evaluated feasibility/acceptability/effect on handover quality + patient trust.
9. Interrupted time series (Aug–Nov 2022, surgery + medicine wards, 831 evaluated handovers): statistically significant handover-quality improvement post-implementation.

### Handoff CEX — nursing validation (Yale)
Source: pmc.ncbi.nlm.nih.gov/articles/PMC3504166/
10. Paired instruments: one rates the GIVER, one the RECEIVER; receiver version omits the content domain.
11. Domains (setting, organization, communication, content, judgment, professionalism, overall) each 1–9 with anchors, banded unsatisfactory 1–3 / satisfactory 4–6 / superior 7–9.
12. Validated on NURSING shift-to-shift report (25 reports, 98 evaluations, 3 unit types); discriminated experience: >5 yrs mean 7.9 vs 6.9 overall (p=.03).

### Handoff CEX — multi-site validation
Source: pmc.ncbi.nlm.nih.gov/articles/PMC3621018/
13. Six subdomains + overall, 9-point banded; separate provider/recipient versions with own anchors; content omitted from recipient tool.
14. 675 evaluations / 97 individuals / 149 sessions (UChicago + Yale): inter-rater reliability modest (weighted kappa 0.28 setting … 0.59 organization).
15. External evaluators rated systematically LOWER than peers → peer ratings positively biased; tool best for external evaluation.
16. Receiver assessment performed worse (narrow range, low kappa) — authors: a fundamentally different approach may be needed for receivers.

### SBAR-LA learner-assessment rubric
Source: ncbi.nlm.nih.gov/pmc/articles/PMC8520891/
17. 10 items (4 S, 3 B, 1 A, 2 R), each binary 0/1, max 10, plus separate 3-level global rating not summed.
18. 7 faculty raters on video performances: Krippendorff's alpha .672 total; 8/10 items good/fair Fleiss' kappa, 2 weak (need rater training).
19. Developers ABANDONED a 0–2 partial-credit scale: raters could not reliably distinguish partial from full completion → binary scoring design lesson.

### SBAR change-of-shift instrument (content validation)
Source: ncbi.nlm.nih.gov/pmc/articles/PMC9749775/
20. Ten expert judges, Delphi-style; CVI 91.7% (threshold ≥80%); content validity only — no alpha / inter-rater coefficients reported.
21. Assessment-section element checklist: vitals, oxygenation/ventilation, level of consciousness, mobility, drains/catheters/probes, exams, nutrition, dressings, eliminations, medications, complications; allergies + comorbidities under Background.

### Simulated-signout failure modes (Geneva 2024, secondary analysis)
Source: ncbi.nlm.nih.gov/pmc/articles/PMC11430516/
22. 177 simulated internal-medicine signouts / 30 physicians: 'Situation awareness / contingency planning' omitted in 54% overall (up to 84% per case) — dominant high-risk omission.
23. Receiver synthesis (second S of I-PASS) almost never spontaneous: receivers asked questions but none systematically read back; 1 of 30 performed a synthesis, once.
24. Untrained signouts vs expert checklist: mean relevance 37.2%, completeness 51.9%; relevance↔completeness strongly correlated (R²=0.91) → checklist completeness is a defensible automated quality proxy.

### TeamSTEPPS 3.0
Source: ahrq.gov/teamstepps-program/curriculum/communication/tools/handoff.html
25. Handoff = transfer of information AND authority/responsibility → rubrics must treat explicit responsibility transfer as a core element.

## All 22 sources (run-1 fetch set)
| Source | Quality | Claims extracted |
|---|---|---|
| effectivehealthcare.ahrq.gov …structured-handoff-rapid-research.pdf | primary | 5 |
| onlinelibrary.wiley.com/doi/10.1111/jan.16896 | primary | 5 |
| jurnal.globalhealthsciencegroup.com …/6437 | secondary | 5 |
| pmc.ncbi.nlm.nih.gov/articles/PMC3504166/ | primary | 5 |
| pmc.ncbi.nlm.nih.gov/articles/PMC3621018/ | primary | 5 |
| ncbi.nlm.nih.gov/pmc/articles/PMC8520891/ | primary | 5 |
| ncbi.nlm.nih.gov/pmc/articles/PMC9749775/ | primary | 5 |
| pmc.ncbi.nlm.nih.gov/articles/PMC12232517/ | primary | 5 |
| ncbi.nlm.nih.gov/pmc/articles/PMC11430516/ | primary | 5 |
| ahrq.gov/teamstepps-program/…/handoff.html | primary | 5 |
| ncbi.nlm.nih.gov/pmc/articles/PMC11044331/ | primary | 5 |
| ncbi.nlm.nih.gov/books/NBK2649/ | primary | 5 |
| pmc.ncbi.nlm.nih.gov/articles/PMC4079746/ | primary | 5 |
| pmc.ncbi.nlm.nih.gov/articles/PMC8199372/ | primary | 5 |
| link.springer.com/article/10.1186/s12909-023-04495-8 | primary | 5 |
| pmc.ncbi.nlm.nih.gov/articles/PMC9996978/ | primary | 5 |
| sciencedirect.com/…/S0260691711002681 | primary | 5 |
| sciencedirect.com/…/S1471595324001653 | primary | 5 |
| sciencedirect.com/…/S1876139921001377 | primary | 4 |
| pubmed.ncbi.nlm.nih.gov/29454873/ | primary | 5 |
| sciencedirect.com/…/S1876139923000622 | primary | 5 |
| sciencedirect.com/…/S147159532300032X | primary | 5 |

Run-1 stats: 5 angles · 22 sources · 109 claims extracted · 25 selected for verification ·
0 verified (quota) · run cost ~931k subagent tokens / 103 agents / ~14 min.
