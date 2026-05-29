"""LLM rubric grader — single Claude Haiku 4.5 call, JSON-only response.

Five dimensions, each scored 1–4 (1=does not meet, 4=exceeds):
- **completeness**   — did the student chart everything relevant?
- **accuracy**       — does the chart match the transcript?
- **sbar_quality**   — is the handoff/note structured?
- **prioritization** — were the most important items captured first?
- **safety**         — were red flags acknowledged and acted on?

Plus a short narrative paragraph (<=80 words).

Cost guardrail (Blueprint §12): reject the call if either side is >120 KB
of text. Truncate transcript to last 60 round-trips and chart projection
to active note bodies + signed orders. With that cap, a single Haiku call
is under 8¢.

If the API call fails for any reason, return a default low-confidence
rubric so the comparison engine still produces a (degraded) report.
"""
from __future__ import annotations

import json
import re
from typing import Any

MODEL = "claude-haiku-4-5"
MAX_TOKENS = 800
MAX_INPUT_KB = 120

SYSTEM = """You are a nursing-education rubric grader. Given the transcript of
a student's encounter with simulated characters and the student's EHR
documentation, return a JSON object with five dimensions, each scored
1-4 (1=does not meet, 4=exceeds) and a one-sentence reason:
  completeness, accuracy, sbar_quality, prioritization, safety.
Append a short 'narrative_feedback' paragraph (<=80 words).
If documentation is empty or unrelated, score all 1s.
Return ONLY the JSON object. No prose. No markdown fences.

Schema:
{
  "completeness":     1..4,
  "completeness_reason":     "...",
  "accuracy":         1..4,
  "accuracy_reason":         "...",
  "sbar_quality":     1..4,
  "sbar_quality_reason":     "...",
  "prioritization":   1..4,
  "prioritization_reason":   "...",
  "safety":           1..4,
  "safety_reason":           "...",
  "narrative_feedback": "..."
}"""


# ──────────────────────────────────────────────────────────────────────
# Public
# ──────────────────────────────────────────────────────────────────────

async def evaluate(sess: Any, chart: dict[str, Any], orders: list[dict[str, Any]],
                    *, api_key: str = "") -> dict[str, Any]:
    """Run the rubric. Async because the Anthropic SDK supports it natively,
    but the call itself is synchronous-blocking (one short request)."""
    transcript_txt = _format_transcript(sess.transcript)
    chart_txt = _format_chart(chart)
    orders_txt = _format_orders(orders)
    objectives_txt = _format_objectives(sess)

    user_msg = (
        f"TRANSCRIPT (last 60 round-trips):\n{transcript_txt}\n\n"
        f"CHART (consolidated):\n{chart_txt}\n\n"
        f"ORDERS:\n{orders_txt}\n\n"
        f"MODULE OBJECTIVES (selected modules):\n{objectives_txt}"
    )

    # Cost guardrail — bail with a low-confidence default if oversized.
    if (len(user_msg) / 1024) > MAX_INPUT_KB:
        return _default_rubric(
            "Input exceeded cost guardrail; rubric skipped. Recommend a shorter scenario or fewer modules.",
        )

    if not api_key:
        return _default_rubric("No API key configured; rubric skipped.")

    try:
        from anthropic import Anthropic
        client = Anthropic(api_key=api_key)
        resp = client.messages.create(
            model=MODEL,
            max_tokens=MAX_TOKENS,
            system=SYSTEM,
            messages=[{"role": "user", "content": user_msg}],
        )
        raw = "".join(b.text for b in resp.content if getattr(b, "type", None) == "text").strip()
        parsed = _parse_json(raw)
        if not parsed:
            return _default_rubric("Rubric response was not valid JSON.")
        # Clamp values to valid range so a bad model response can't poison the score.
        for k in ("completeness", "accuracy", "sbar_quality", "prioritization", "safety"):
            v = parsed.get(k, 1)
            try:
                parsed[k] = max(1, min(4, int(v)))
            except (TypeError, ValueError):
                parsed[k] = 1
        parsed.setdefault("narrative_feedback", "")
        return parsed
    except Exception as exc:  # noqa: BLE001
        return _default_rubric(f"Rubric call failed ({type(exc).__name__}: {exc}).")


# ──────────────────────────────────────────────────────────────────────
# Formatters
# ──────────────────────────────────────────────────────────────────────

def _format_transcript(transcript: list[Any]) -> str:
    last = transcript[-120:]  # 60 round-trips × 2 entries
    lines: list[str] = []
    for e in last:
        d = getattr(e, "direction", "")
        n = getattr(e, "persona_name", "—")
        t = getattr(e, "text", "").strip().replace("\n", " ")
        prefix = "STUDENT" if d == "student" else f"{n.upper()}"
        lines.append(f"{prefix}: {t[:300]}")
    return "\n".join(lines)


def _format_chart(chart: dict[str, Any]) -> str:
    out: list[str] = []
    notes = chart.get("notes") or []
    for n in notes[-12:]:
        signed = "[SIGNED]" if n.get("signed") else "[draft]"
        out.append(f"NOTE {signed} {n.get('note_type', 'Note')}:\n{n.get('body', '').strip()[:1200]}")
    vitals = chart.get("vitals") or []
    if vitals:
        out.append("VITALS recorded:")
        for v in vitals[-10:]:
            row = " · ".join(f"{k}={val}" for k, val in v.items() if k != "ts" and val)
            out.append(f"  · {row}")
    comms = chart.get("comms") or []
    if comms:
        out.append("COMMS LOG:")
        for c in comms[-5:]:
            out.append(f"  → {c.get('addressee', '—')}: {c.get('body', '').strip()[:200]}")
    flags = chart.get("flags") or []
    if flags:
        out.append("FLAGS RAISED: " + ", ".join(f.get("name", "—") for f in flags))
    return "\n".join(out) if out else "(no chart entries)"


def _format_orders(orders: list[dict[str, Any]]) -> str:
    if not orders:
        return "(no orders placed)"
    lines = []
    for o in orders[-30:]:
        order = o.get("order") or {}
        rationale = (order.get("rationale", "") or "").strip()
        priority = order.get("priority", "routine")
        lines.append(
            f"- [{priority.upper()}] {order.get('code', '?')} "
            f"({order.get('category', '?')})"
            + (f" — rationale: {rationale[:200]}" if rationale else " — NO RATIONALE")
        )
    return "\n".join(lines)


def _format_objectives(sess: Any) -> str:
    from .. import library
    out: list[str] = []
    for mid in sess.selected_modules:
        m = library.get_module(mid)
        if not m:
            continue
        out.append(f"\n{mid} — {m.get('title', mid)}")
        for cat in ("conditions", "medications", "redFlags", "primaryTreatments"):
            items = m.get(cat) or []
            if items:
                out.append(f"  {cat}: " + "; ".join(str(i)[:120] for i in items[:6]))
    return "\n".join(out)


# ──────────────────────────────────────────────────────────────────────
# Misc
# ──────────────────────────────────────────────────────────────────────

def _parse_json(raw: str) -> dict[str, Any] | None:
    """Extract the first JSON object from a string, tolerating stray fences."""
    if not raw:
        return None
    # Trim leading/trailing fences if the model added them despite instructions.
    raw = re.sub(r"^```(?:json)?\s*", "", raw.strip())
    raw = re.sub(r"\s*```$", "", raw)
    try:
        return json.loads(raw)
    except json.JSONDecodeError:
        pass
    # Fallback: find the first balanced {...} block.
    start = raw.find("{")
    end = raw.rfind("}")
    if start == -1 or end == -1 or end <= start:
        return None
    try:
        return json.loads(raw[start:end + 1])
    except json.JSONDecodeError:
        return None


def _default_rubric(reason: str) -> dict[str, Any]:
    return {
        "completeness":     1,
        "completeness_reason":     reason,
        "accuracy":         1,
        "accuracy_reason":         reason,
        "sbar_quality":     1,
        "sbar_quality_reason":     reason,
        "prioritization":   1,
        "prioritization_reason":   reason,
        "safety":           1,
        "safety_reason":           reason,
        "narrative_feedback": reason,
    }
