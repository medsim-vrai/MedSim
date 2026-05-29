"""NCJMM cognitive-cycle tagger — ported verbatim from Voice4MedSim_v6.

Every transcript turn is tagged with one of 6 NCSBN Clinical Judgment
Measurement Model steps so the debrief can show which steps of the
cognitive cycle the learner exercised.

Six steps (NCSBN model, Voice4MedSim strategy doc §4):

    recognize-cues          — noticing salient information
    analyze-cues            — interpreting / linking cues to physiology
    prioritize-hypotheses   — ranking what's most likely / most dangerous
    generate-solutions      — proposing actions / interventions
    take-action             — executing an intervention
    evaluate-outcomes       — reassessing after action

Pure-Python keyword classifier — no LLM call, ~tens of microseconds per
turn. Highest-score wins; ties prefer the earlier step in the cognitive
cycle (when in doubt, learner is earlier than later).
"""
from __future__ import annotations

import re

NCJMM_STEPS: list[str] = [
    "recognize-cues",
    "analyze-cues",
    "prioritize-hypotheses",
    "generate-solutions",
    "take-action",
    "evaluate-outcomes",
]


def _pat(s: str) -> re.Pattern:
    return re.compile(s, re.IGNORECASE)


_RECOGNIZE = [
    (_pat(r"\b(tell\s+me|describe|how\s+(are|do)\s+you|what'?s\s+(going|happening)|notice|observ|see|feel)\b"), 2),
    (_pat(r"\b(pain|hurt|ache|sore|tired|dizzy|nause|short(ness)?\s+of\s+breath|sob)\b"), 1),
    (_pat(r"\b(when\s+did|onset|start(ed)?|began)\b"), 1),
    (_pat(r"\b(rate|scale|out\s+of\s+10|0\s+to\s+10)\b"), 1),
    (_pat(r"\b(vitals?|blood\s+pressure|bp|pulse|hr|temperature|temp|spo2|sat|o2)\b"), 1),
]

_ANALYZE = [
    (_pat(r"\b(why|because|due\s+to|caused\s+by|relat(ed|ing)\s+to|consistent\s+with)\b"), 2),
    (_pat(r"\b(suggests?|indicates?|points?\s+to|likely\s+(means|cause)|differential)\b"), 2),
    (_pat(r"\b(connect|link|correlate|pattern|trend)\b"), 1),
    (_pat(r"\b(history|comorbid|baseline|chronic|acute\s+on\s+chronic)\b"), 1),
    (_pat(r"\b(lab|wbc|hgb|cbc|chem|lactate|troponin|d[\s-]?dimer|abg)\b"), 1),
]

_PRIORITIZE = [
    (_pat(r"\b(most\s+(likely|concerning|dangerous|urgent)|priority|prioriti[sz]e|first\s+thing)\b"), 2),
    (_pat(r"\b(rule\s+out|r/o|life[\s-]?threat|abc(de)?|airway|red\s+flag)\b"), 2),
    (_pat(r"\b(rank|order|sequence|which\s+(is|comes)\s+first)\b"), 1),
    (_pat(r"\b(critical|emergent|stat|now)\b"), 1),
]

_GENERATE = [
    (_pat(r"\b(could|should|might|would|consider|option|plan|approach|strategy)\b"), 2),
    (_pat(r"\b(suggest|recommend|propose|let'?s|we\s+(could|should|need\s+to))\b"), 2),
    (_pat(r"\b(intervention|treatment|protocol)\b"), 1),
    (_pat(r"\b(if\b.*\bthen\b|alternative|instead)\b"), 1),
]

_TAKE_ACTION = [
    (_pat(r"\b(give|push|administer|start(ing)?|stop(ping)?|hold|deliver|insert|place)\b"), 2),
    (_pat(r"\b(call|page|notify|escalate|activate|page\s+the)\b"), 2),
    (_pat(r"\b(naloxone|epinephrine|ativan|insulin|bolus|drip|fluid)\b"), 2),
    (_pat(r"\b(turn|reposition|raise|lower|sit\s+up|lay\s+down|roll)\b"), 1),
    (_pat(r"\b(now|immediately|right\s+away|right\s+now|stat)\b"), 1),
]

_EVALUATE = [
    (_pat(r"\b(reassess|reevaluat|recheck|repeat|follow[\s-]?up|after\s+(the|that)|since)\b"), 2),
    (_pat(r"\b(better|worse|improv|deteriorat|change(d)?|response|tolerat)\b"), 2),
    (_pat(r"\b(post[\s-]?(intervention|treatment|admin)|outcome|result(s|ed))\b"), 2),
    (_pat(r"\b(now\s+(is|feels|looks)|since\s+(we|you|the)|how\s+(are\s+you\s+now|is\s+(she|he|it)\s+now))\b"), 1),
]

_PATTERNS_BY_STEP: dict[str, list[tuple[re.Pattern, int]]] = {
    "recognize-cues":         _RECOGNIZE,
    "analyze-cues":           _ANALYZE,
    "prioritize-hypotheses":  _PRIORITIZE,
    "generate-solutions":     _GENERATE,
    "take-action":            _TAKE_ACTION,
    "evaluate-outcomes":      _EVALUATE,
}


def tag(utterance: str, reply: str = "") -> str:
    """Return one of NCJMM_STEPS describing the cognitive step this turn
    represents. `reply` improves classification when present."""
    text = f"{utterance or ''} {reply or ''}".strip()
    if not text:
        return "recognize-cues"
    scores = score(text)
    return _argmax_with_tiebreak(scores)


def score(text: str) -> dict[str, int]:
    """Return raw keyword scores per step. Exposed for debugging / tests."""
    out = {step: 0 for step in NCJMM_STEPS}
    for step, pats in _PATTERNS_BY_STEP.items():
        for pat, w in pats:
            if pat.search(text):
                out[step] += w
    return out


def _argmax_with_tiebreak(scores: dict[str, int]) -> str:
    """Highest score wins; on tie prefer earlier step in cognitive cycle."""
    best = "recognize-cues"
    best_score = -1
    for step in NCJMM_STEPS:           # NCJMM_STEPS is in cycle order
        if scores[step] > best_score:
            best = step
            best_score = scores[step]
    return best
