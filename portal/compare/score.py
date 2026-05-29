"""Composite score for the V3 comparison report.

Blueprint §12 stage 4:

    composite = 0.55 * rules_score + 0.45 * (rubric_mean / 4.0)

where:
- rules_score = hits / (hits + misses)   (ignores speculative + out-of-scope)
- rubric_mean = mean of the five 1..4 dimensions

Both terms are clipped to [0, 1] before weighting.
"""
from __future__ import annotations

from typing import Any

W_RULES = 0.55
W_RUBRIC = 0.45

RUBRIC_DIMENSIONS = ("completeness", "accuracy", "sbar_quality", "prioritization", "safety")


def composite(rules: dict[str, Any], rubric: dict[str, Any]) -> float:
    rs = _rules_score(rules)
    rm = _rubric_mean(rubric) / 4.0
    return round(W_RULES * rs + W_RUBRIC * rm, 4)


def _rules_score(rules: dict[str, Any]) -> float:
    totals = rules.get("totals") or {}
    if "rules_score" in totals:
        try:
            return max(0.0, min(1.0, float(totals["rules_score"])))
        except (TypeError, ValueError):
            pass
    hits = len(rules.get("hits") or [])
    misses = len(rules.get("misses") or [])
    if (hits + misses) == 0:
        return 0.0
    return hits / (hits + misses)


def _rubric_mean(rubric: dict[str, Any]) -> float:
    vals: list[int] = []
    for k in RUBRIC_DIMENSIONS:
        v = rubric.get(k, 1)
        try:
            vals.append(max(1, min(4, int(v))))
        except (TypeError, ValueError):
            vals.append(1)
    return sum(vals) / len(vals) if vals else 1.0
