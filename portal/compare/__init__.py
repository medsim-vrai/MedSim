"""V3 hybrid comparison engine.

Triggered when the operator presses **Charting complete** in the ops view.
Three stages:

- **rules.py**   deterministic scan of transcript + chart for the items
                 named in each selected curriculum module (medications,
                 procedures, devices, redFlags, conditions, treatments).
- **rubric.py**  single Claude Haiku 4.5 call returning a 5-dimension
                 educational rubric as strict JSON.
- **score.py**   weighted composite (0.55 rules + 0.45 rubric_mean).

Inputs come from `portal.ehr_db.fold()` (chart projection) and the
ControlSession transcript. Output is persisted via
`ehr_db.save_comparison()` and consumed by the V3 debrief renderer.
"""

from . import rules, rubric, score  # re-exports

__all__ = ["rules", "rubric", "score"]
