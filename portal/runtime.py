"""Minimal in-memory simulation runtime — v0 of B5+B6+B9 combined.

This exists so the portal's Launch button can produce a real, working chat
session right now, before the full block architecture lands. It deliberately
implements only the conversational core:

  - Per-session in-memory state (scenario + characters + history)
  - One Claude (Haiku 4.5) call per student turn
  - Character card → system prompt
  - No RAG, no filler manager, no validators, no debrief log
  - Streaming: `take_turn_stream` yields the reply as text deltas (OPT-008 Cut 2,
    so the avatar can start speaking at the first sentence boundary)

When B5/B6/B7/B8/B9/B10/B11/B12 land per the PDF, this file becomes the
"local mode" fallback and the proper orchestrator takes over the Launch
endpoint.
"""
from __future__ import annotations

import secrets
import time
from dataclasses import dataclass, field
from typing import Any

from . import scenarios

MODEL = "claude-haiku-4-5"
MAX_TOKENS = 400
HISTORY_WINDOW = 10  # last N turns sent to the model


@dataclass
class TurnRecord:
    addressee: str
    student_utterance: str
    character_response: str
    timestamp: float


@dataclass
class SimSession:
    id: str
    scenario_id: str
    scenario: dict[str, Any]
    characters: dict[str, dict[str, Any]]
    api_key: str
    history: list[TurnRecord] = field(default_factory=list)


_sessions: dict[str, SimSession] = {}


def create_session(scenario_id: str, api_key: str) -> SimSession | None:
    scenario = scenarios.get_scenario(scenario_id)
    if scenario is None:
        return None
    char_ids = scenario.get("characters") or []
    chars: dict[str, dict[str, Any]] = {}
    for cid in char_ids:
        c = scenarios.get_character(cid)
        if c:
            chars[cid] = c
    if not chars:
        return None
    sid = secrets.token_urlsafe(12)
    s = SimSession(
        id=sid,
        scenario_id=scenario_id,
        scenario=scenario,
        characters=chars,
        api_key=api_key,
    )
    _sessions[sid] = s
    return s


def create_session_from_data(
    *,
    scenario: dict[str, Any],
    characters: dict[str, dict[str, Any]],
    api_key: str,
) -> SimSession:
    """v2 factory — used by control-room sessions which build characters from
    the 24-persona library directly, bypassing the YAML scenario lookup."""
    sid = secrets.token_urlsafe(12)
    s = SimSession(
        id=sid,
        scenario_id=scenario.get("id", "control-session"),
        scenario=scenario,
        characters=dict(characters),
        api_key=api_key,
    )
    _sessions[sid] = s
    return s


def get_session(session_id: str) -> SimSession | None:
    return _sessions.get(session_id)


def end_session(session_id: str) -> None:
    _sessions.pop(session_id, None)


def take_turn(session_id: str, addressee: str, message: str) -> dict[str, Any]:
    session = _sessions.get(session_id)
    if session is None:
        return {"ok": False, "error": "Session not found (it may have expired)."}
    if addressee not in session.characters:
        return {"ok": False, "error": f"No character with ID '{addressee}' in this scenario."}
    if not message.strip():
        return {"ok": False, "error": "Empty message."}

    character = session.characters[addressee]
    system_prompt = _build_system_prompt(character, session.scenario)
    messages = _build_messages(session, addressee, message)

    try:
        from anthropic import Anthropic
        client = Anthropic(api_key=session.api_key)
        response = client.messages.create(
            model=MODEL,
            max_tokens=MAX_TOKENS,
            system=system_prompt,
            messages=messages,
        )
        # The response.content is a list of content blocks; pull the text.
        reply = "".join(
            block.text for block in response.content
            if getattr(block, "type", None) == "text"
        ).strip()
        if not reply:
            reply = "(no response)"
    except Exception as exc:  # noqa: BLE001
        return {"ok": False, "error": f"{type(exc).__name__}: {exc}"}

    record = TurnRecord(
        addressee=addressee,
        student_utterance=message.strip(),
        character_response=reply,
        timestamp=time.time(),
    )
    session.history.append(record)

    return {
        "ok": True,
        "character_id": addressee,
        "character_name": character.get("name", addressee),
        "reply": reply,
    }


def take_instructor_line(session_id: str, addressee: str, intent: str) -> dict[str, Any]:
    """FR-003 "in character" mode: the INSTRUCTOR directs the character to convey something,
    and the model rephrases that intent through the persona — voice, knowledge boundary,
    scene contract, and current altered_state all apply via the same system prompt as a
    normal turn. Unlike `take_turn`, the user message is framed as STAGE DIRECTION (the
    trainee said nothing), so the reply is the character addressing the trainee."""
    session = _sessions.get(session_id)
    if session is None:
        return {"ok": False, "error": "Session not found (it may have expired)."}
    if addressee not in session.characters:
        return {"ok": False, "error": f"No character with ID '{addressee}' in this scenario."}
    if not intent.strip():
        return {"ok": False, "error": "Empty direction."}

    character = session.characters[addressee]
    system_prompt = _build_system_prompt(character, session.scenario)
    name = character.get("name", addressee)
    direction = (
        "[INSTRUCTOR STAGE DIRECTION — the trainee did NOT say anything. Convey the "
        f"following to the trainee, speaking as {name} in your current state, as ONE "
        f"natural in-character utterance:]\n{intent.strip()}"
    )
    messages = _build_messages(session, addressee, direction)
    try:
        from anthropic import Anthropic
        client = Anthropic(api_key=session.api_key)
        response = client.messages.create(
            model=MODEL,
            max_tokens=MAX_TOKENS,
            system=system_prompt,
            messages=messages,
        )
        reply = "".join(
            block.text for block in response.content
            if getattr(block, "type", None) == "text"
        ).strip() or "(no response)"
    except Exception as exc:  # noqa: BLE001
        return {"ok": False, "error": f"{type(exc).__name__}: {exc}"}

    session.history.append(TurnRecord(
        addressee=addressee,
        student_utterance=f"[instructor direction] {intent.strip()}",
        character_response=reply,
        timestamp=time.time(),
    ))
    return {"ok": True, "character_id": addressee,
            "character_name": name, "reply": reply}


def take_turn_stream(session_id: str, addressee: str, message: str):
    """OPT-008 Cut 2: the same character turn as `take_turn`, but STREAMED — returns a sync
    generator of text deltas so the caller can voice the first sentence while the rest is
    still generating. Validation errors raise ValueError up front (no generator); a transport
    error mid-stream raises from the generator. On clean completion the TurnRecord is appended
    exactly as the blocking path does."""
    session = _sessions.get(session_id)
    if session is None:
        raise ValueError("Session not found (it may have expired).")
    if addressee not in session.characters:
        raise ValueError(f"No character with ID '{addressee}' in this scenario.")
    if not message.strip():
        raise ValueError("Empty message.")

    character = session.characters[addressee]
    system_prompt = _build_system_prompt(character, session.scenario)
    messages = _build_messages(session, addressee, message)

    def _gen():
        from anthropic import Anthropic
        client = Anthropic(api_key=session.api_key)
        parts: list[str] = []
        with client.messages.stream(
            model=MODEL,
            max_tokens=MAX_TOKENS,
            system=system_prompt,
            messages=messages,
        ) as stream:
            for delta in stream.text_stream:
                parts.append(delta)
                yield delta
        reply = "".join(parts).strip() or "(no response)"
        session.history.append(TurnRecord(
            addressee=addressee,
            student_utterance=message.strip(),
            character_response=reply,
            timestamp=time.time(),
        ))

    return _gen()


# ---------------------------------------------------------------------------
# Prompt construction
# ---------------------------------------------------------------------------

def _build_system_prompt(character: dict[str, Any], scenario: dict[str, Any]) -> str:
    name = character.get("name") or character.get("id", "the character")
    role = character.get("role") or ""
    voice = character.get("voice") or {}
    identity = character.get("identity") or {}

    lines: list[str] = []
    lines.append(f"You are {name}" + (f", {role}." if role else "."))
    lines.append("You are a character inside a clinical teaching simulation. The")
    lines.append("user is a student nurse, in role. Speak ONLY as your character.")
    lines.append("Never break the fourth wall. Never identify yourself as an AI.")
    lines.append("Never apologize for limitations. Respond as your character would.")
    lines.append("")

    if identity.get("years_experience") or identity.get("mood_today"):
        bits = []
        if identity.get("years_experience"):
            bits.append(f"{identity['years_experience']} years of experience")
        if identity.get("mood_today"):
            bits.append(f"mood today: {identity['mood_today']}")
        lines.append("IDENTITY: " + "; ".join(bits))

    if voice.get("register"):
        lines.append(f"VOICE: {voice['register']}")
    if voice.get("sentence_length"):
        lines.append(f"Sentence length: {voice['sentence_length']}.")
    examples = voice.get("examples") or []
    if examples:
        lines.append("Example utterances (match this register; do not repeat verbatim):")
        for ex in examples[:5]:
            lines.append(f"  - {ex}")
    never = voice.get("never_says") or []
    if never:
        lines.append("Never say:")
        for ns in never[:5]:
            lines.append(f"  - {ns}")

    if character.get("knowledge_boundary"):
        lines.append("")
        lines.append(f"KNOWLEDGE BOUNDARY: {character['knowledge_boundary']}")
        lines.append("If asked something outside this boundary, defer in-role.")

    if character.get("teaching_stance"):
        lines.append("")
        lines.append(f"TEACHING STANCE: {character['teaching_stance']}")

    contract = character.get("scene_contract") or []
    if contract:
        lines.append("")
        lines.append("SCENE CONTRACT (HARD RULES — do not violate):")
        for c in contract:
            lines.append(f"  - {c}")

    # Scenario context
    lines.append("")
    lines.append(f"SCENARIO: {scenario.get('name', 'unnamed')}")
    patient = scenario.get("patient") or {}
    if patient:
        bits = []
        if patient.get("age") not in (None, ""):
            bits.append(f"{patient['age']}y")
        if patient.get("sex"):
            bits.append(patient["sex"])
        if patient.get("history"):
            bits.append(patient["history"])
        if bits:
            lines.append("Patient: " + " · ".join(str(b) for b in bits))
        vitals = patient.get("baseline_vitals") or {}
        if vitals:
            lines.append("Baseline vitals: " + ", ".join(f"{k} {v}" for k, v in vitals.items()))

    # FR-007 v2 — a shared "one tablet, many patients" character covers the whole
    # room: give it every bed's patient so it answers as ONE instance spanning beds.
    room_patients = scenario.get("room_patients") or []
    if room_patients:
        lines.append("")
        lines.append("You are covering MULTIPLE patients in this room. When the student")
        lines.append("refers to a patient, answer about THAT patient; ask which patient")
        lines.append("if it's unclear. PATIENTS IN THIS ROOM:")
        for rp in room_patients[:12]:
            lbl = rp.get("label") or rp.get("name") or "patient"
            hist = (rp.get("history") or "").strip()
            lines.append(f"  - {lbl}" + (f": {hist}" if hist else ""))

    curriculum = scenario.get("curriculum") or {}
    touchpoints = curriculum.get("touchpoints") or []
    if touchpoints:
        lines.append("")
        lines.append("Curriculum touchpoints the learner should hit:")
        for tp in touchpoints[:6]:
            lines.append(f"  - {tp}")
        lines.append("Do not name these touchpoints to the student. Behave in")
        lines.append("character; let the student work the problem.")

    # FR-001/002 — callers may inject role-specific context (e.g. the medication
    # board for doctor/pharmacist personas) without touching the card schema.
    extra = character.get("_extra_context")
    if extra:
        lines.append("")
        lines.append(str(extra))

    lines.append("")
    lines.append("Respond with one short, in-character utterance. No stage directions.")
    return "\n".join(lines)


def _build_messages(
    session: SimSession,
    addressee: str,
    new_message: str,
) -> list[dict[str, Any]]:
    """Build the Claude messages array.

    We send the recent dialogue history with the user's lines verbatim. For
    assistant turns we only include responses from the SAME character we're
    addressing now — otherwise the model gets confused about who it is. Other
    characters' lines are flattened into the user content as scene context.
    """
    recent = session.history[-HISTORY_WINDOW:]
    messages: list[dict[str, Any]] = []
    for turn in recent:
        if turn.addressee == addressee:
            messages.append({"role": "user", "content": turn.student_utterance})
            messages.append({"role": "assistant", "content": turn.character_response})
        else:
            other_name = session.characters.get(turn.addressee, {}).get("name", turn.addressee)
            messages.append({
                "role": "user",
                "content": (
                    f"[Scene: the student said to {other_name}: "
                    f"'{turn.student_utterance}' and {other_name} replied: "
                    f"'{turn.character_response}']\n\n"
                    "Acknowledge if relevant, or wait. Do not impersonate the other character."
                ),
            })
            # Skip the assistant turn — let the model decide whether to respond.
            # But Anthropic API requires alternating roles, so we must add
            # something. Add a minimal assistant beat.
            messages.append({"role": "assistant", "content": "(listening)"})
    messages.append({"role": "user", "content": new_message})
    return messages
