"""Deterministic comparison rules.

For each selected curriculum module, scan the conversation transcript
and the student's chart for evidence of every item in the module's
objective categories (medications, procedures, devices, redFlags,
conditions, primaryTreatments, alternateTreatments).

Four buckets per item:

- **Hit**          — surfaced in conversation AND charted by student
- **Miss**         — surfaced in conversation but NOT charted
- **Speculative**  — charted but never surfaced in conversation
- **Out of scope** — neither; ignored

Detection is regex-and-synonym based. Synonym table lives in
`portal/compare/synonyms.json` — kept small on purpose so instructors
can read and curate it.
"""
from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Any

from .. import library

_SYN_PATH = Path(__file__).resolve().parent / "synonyms.json"

OBJECTIVE_CATEGORIES = (
    "conditions",
    "medications",
    "devices",
    "procedures",
    "primaryTreatments",
    "alternateTreatments",
    "redFlags",
)


_synonyms_cache: dict[str, list[str]] | None = None


def _synonyms() -> dict[str, list[str]]:
    global _synonyms_cache
    if _synonyms_cache is None:
        try:
            doc = json.loads(_SYN_PATH.read_text())
        except (OSError, json.JSONDecodeError):
            doc = {}
        _synonyms_cache = {
            k.lower(): list(v) for k, v in doc.items()
            if not k.startswith("_") and isinstance(v, list)
        }
    return _synonyms_cache


# ──────────────────────────────────────────────────────────────────────
# Public
# ──────────────────────────────────────────────────────────────────────

def evaluate(sess: Any, chart: dict[str, Any], orders: list[dict[str, Any]],
             seed: dict[str, Any]) -> dict[str, Any]:
    """Run the rule scan against this session.

    Returns a dict of {hits, misses, speculative, by_module, totals}.
    """
    transcript = _concat_transcript(sess.transcript)
    chart_text = _concat_chart(chart)
    orders_text = _concat_orders(orders)
    seed_text = _concat_seed(seed)

    syn = _synonyms()

    hits: list[dict[str, Any]] = []
    misses: list[dict[str, Any]] = []
    speculative: list[dict[str, Any]] = []
    by_module: list[dict[str, Any]] = []

    seen_pairs: set[tuple[str, str, str]] = set()

    for mid in sess.selected_modules:
        module = library.get_module(mid)
        if not module:
            continue
        mod_hits: list[str] = []
        mod_misses: list[str] = []
        mod_spec: list[str] = []
        for cat in OBJECTIVE_CATEGORIES:
            items = module.get(cat) or []
            for item in items:
                short = _short(item)
                if not short:
                    continue
                key = (mid, cat, short.lower())
                if key in seen_pairs:
                    continue
                seen_pairs.add(key)

                in_talk  = _mentions(transcript, short, syn)
                in_chart = _mentions(chart_text, short, syn) or _mentions(orders_text, short, syn)
                in_seed  = _mentions(seed_text, short, syn)

                row = {"item": short, "module": mid, "cat": cat}
                if in_talk and in_chart:
                    hits.append(row); mod_hits.append(short)
                elif in_talk and not in_chart:
                    misses.append(row); mod_misses.append(short)
                elif in_chart and not in_talk and not in_seed:
                    # Speculative = charted by student, never raised in convo,
                    # and not pre-seeded baseline.
                    speculative.append(row); mod_spec.append(short)
                # else: out of scope or already pre-populated — ignore.

        total = len(mod_hits) + len(mod_misses)
        coverage = round(100 * len(mod_hits) / total) if total else 0
        by_module.append({
            "module_id":     mid,
            "module_title":  module.get("title", mid),
            "hits":          mod_hits,
            "misses":        mod_misses,
            "speculative":   mod_spec,
            "coverage_pct":  coverage,
        })

    totals = {
        "hits":        len(hits),
        "misses":      len(misses),
        "speculative": len(speculative),
        "rules_score": round(len(hits) / (len(hits) + len(misses)), 3)
                        if (len(hits) + len(misses)) > 0 else 0.0,
    }
    return {
        "hits": hits, "misses": misses, "speculative": speculative,
        "by_module": by_module, "totals": totals,
    }


# ──────────────────────────────────────────────────────────────────────
# Concat helpers — turn structured objects into a single lowercased blob
# ──────────────────────────────────────────────────────────────────────

def _concat_transcript(transcript: list[Any]) -> str:
    return " ".join(getattr(e, "text", "") for e in transcript).lower()


def _concat_chart(chart: dict[str, Any]) -> str:
    parts: list[str] = []
    for n in chart.get("notes") or []:
        parts.append(n.get("body", ""))
    for v in chart.get("vitals") or []:
        for k, val in v.items():
            if k == "ts":
                continue
            parts.append(f"{k} {val}")
    for a in chart.get("assessments") or []:
        parts.append(json.dumps(a, default=str))
    for c in chart.get("comms") or []:
        parts.append(c.get("body", "")); parts.append(c.get("addressee", ""))
    for f in chart.get("flags") or []:
        parts.append(f.get("name", "")); parts.append(f.get("reason", ""))
    add_drop = chart.get("allergies") or {}
    parts.extend(add_drop.get("adds") or [])
    parts.extend(add_drop.get("removes") or [])
    pd = chart.get("problems") or {}
    parts.extend(pd.get("adds") or [])
    parts.extend(pd.get("removes") or [])
    return " ".join(str(p) for p in parts).lower()


def _concat_orders(orders: list[dict[str, Any]]) -> str:
    parts: list[str] = []
    for o in orders:
        order = o.get("order") or {}
        parts.append(order.get("code", ""))
        parts.append(order.get("label", ""))
        parts.append(order.get("rationale", ""))
        parts.append(order.get("category", ""))
    return " ".join(str(p) for p in parts).lower()


def _concat_seed(seed: dict[str, Any]) -> str:
    """The pre-populated baseline — used to distinguish 'student charted X'
    from 'X was already in the seed'."""
    parts: list[str] = []
    for cond in seed.get("problem_list") or []:
        parts.append(cond.get("name", "") if isinstance(cond, dict) else str(cond))
    for med in seed.get("medications") or []:
        parts.append(med.get("name", "") if isinstance(med, dict) else str(med))
    for note in seed.get("notes_recent") or []:
        parts.append(note.get("body", "") if isinstance(note, dict) else str(note))
    return " ".join(parts).lower()


# ──────────────────────────────────────────────────────────────────────
# Matching
# ──────────────────────────────────────────────────────────────────────

def _short(item: str) -> str:
    """Reduce a long module item like 'Furosemide (loop diuretic), 20-80 mg'
    to a clean search lemma ('furosemide')."""
    if not item:
        return ""
    base = re.split(r"[,;:()/]", item, maxsplit=1)[0].strip()
    return base.lower() if 2 <= len(base) <= 80 else base[:80].lower()


def _mentions(haystack: str, needle: str, syn_table: dict[str, list[str]]) -> bool:
    if not haystack or not needle:
        return False
    n = needle.lower()
    if _word_in(haystack, n):
        return True
    for alt in syn_table.get(n, []):
        if _word_in(haystack, alt.lower()):
            return True
    return False


def _word_in(haystack: str, needle: str) -> bool:
    # Multi-word needles → substring is fine because they're already
    # specific. Single-word needles → require a word boundary so 'k'
    # doesn't match 'okay'.
    if " " in needle or "-" in needle:
        return needle in haystack
    pattern = r"\b" + re.escape(needle) + r"\b"
    return bool(re.search(pattern, haystack))
