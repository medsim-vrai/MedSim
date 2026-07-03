"""FR-017 — scenario exchange: export/import a scenario + its dependencies between
MedSim VRAI installs (docs/FR-017-scenario-exchange.md).

Bundle = ONE `*.medsim-scenario.json` (spec v1: JSON now, zip later if avatars
ever embed) containing the scenario, every referenced character (local YAML or
AUTH-* authored persona), the FR-018 support documents (base64 — they postdate
the spec but are part of the teaching asset), and a `_manifest` with format
version, checksum, and the assets deliberately NOT embedded (portraits/skins are
consent-gated + path-bound; kb_scope local-context tags are install-specific).

Import is collision-safe and never overwrites: the scenario always lands under a
fresh id if its id is taken; a bundled character with a taken id is LINKED when
byte-identical, else imported under a suffixed id and remapped in the scenario.
The instructor gets a post-import checklist (avatars to reassign, kb_scope tags
to provide, characters that were remapped/linked).
"""
from __future__ import annotations

import base64
import hashlib
import json
import time
from typing import Any

from . import authored_content, scenario_docs, scenarios

FORMAT_VERSION = "1.0"
SOURCE = "medsim-v8"
FILE_SUFFIX = ".medsim-scenario.json"
_MAX_BUNDLE_BYTES = 64 * 1024 * 1024   # generous: PDFs/images ride base64


def _jdump(obj: Any, **kw: Any) -> str:
    """json.dumps that tolerates YAML-native types: scenarios are yaml.safe_load'd,
    so bare dates become datetime.date/… which json can't serialize — coerce to str."""
    return json.dumps(obj, default=str, ensure_ascii=False, **kw)


def _checksum(bundle: dict[str, Any]) -> str:
    """sha256 over the canonical bundle WITHOUT the checksum field itself."""
    manifest = {k: v for k, v in bundle.get("_manifest", {}).items() if k != "checksum"}
    body = {**bundle, "_manifest": manifest}
    return "sha256:" + hashlib.sha256(
        _jdump(body, sort_keys=True).encode("utf-8")).hexdigest()


def _safe_id(raw: str, fallback: str) -> str:
    """Sanitize an id from a FOREIGN bundle before it ever reaches the filesystem.
    Bundle-supplied ids are untrusted (an import can carry '../../evil'); reuse the
    same slug rule every native create path uses, so a bundle can never write a
    YAML file outside SCENARIOS_DIR/CHARACTERS_DIR."""
    clean = scenarios.slugify(str(raw or ""))
    return clean or scenarios.slugify(fallback) or "imported"


# ── export ───────────────────────────────────────────────────────────────────

def export_bundle(scenario_id: str) -> dict[str, Any] | None:
    """Assemble the shareable bundle, or None if the scenario doesn't exist."""
    scenario = scenarios.get_scenario(scenario_id)
    if scenario is None:
        return None

    characters: list[dict[str, Any]] = []
    personas: list[dict[str, Any]] = []
    unresolved: list[str] = []
    persona_by_id = {p.get("id"): p for p in authored_content.list_personas()}
    for cid in scenario.get("characters") or []:
        c = scenarios.get_character(cid)
        if c is not None:
            characters.append(c)
        elif cid in persona_by_id:
            personas.append(persona_by_id[cid])
        else:
            unresolved.append(cid)

    documents: list[dict[str, Any]] = []
    for d in scenario_docs.list_docs(scenario_id):
        p = scenario_docs.doc_path(scenario_id, d.get("id", ""))
        if p is None or not p.is_file():
            continue
        documents.append({
            "filename": d.get("filename", ""), "content_type": d.get("content_type", ""),
            "doc_type": d.get("doc_type", ""), "section": d.get("section", ""),
            "purpose": d.get("purpose", ""), "ai_mode": d.get("ai_mode", "context"),
            "summary": d.get("summary", ""),
            "data_base64": base64.b64encode(p.read_bytes()).decode("ascii"),
        })

    # Consent-gated / install-specific assets travel as MANIFEST NOTES, not bytes.
    external: list[dict[str, str]] = []
    try:
        from . import vrai_faces
        for entity in [*characters, *personas]:
            eid = entity.get("id", "")
            if eid and vrai_faces.has_portrait(eid):
                external.append({
                    "type": "portrait", "id": eid,
                    "reason": "avatar portraits are consent-gated + path-bound; "
                              "reassign on the importing system",
                })
    except Exception:  # noqa: BLE001 — portraits are best-effort metadata
        pass
    for tag in scenario.get("kb_scope") or []:
        external.append({"type": "local_context", "id": str(tag),
                         "reason": "install-specific local-context tag; provide it "
                                   "on the importing system (FR-013a)"})
    for cid in unresolved:
        external.append({"type": "missing_character", "id": cid,
                         "reason": "referenced by the scenario but not found on the "
                                   "exporting system"})

    bundle: dict[str, Any] = {
        "_manifest": {
            "format_version": FORMAT_VERSION,
            "source": SOURCE,
            "exported_at": time.time(),
            "scenario_id": scenario.get("id", scenario_id),
            "external_assets": external,
        },
        "scenario": scenario,
        "characters": characters,
        "personas": personas,
        "support_documents": documents,
    }
    bundle["_manifest"]["checksum"] = _checksum(bundle)
    return bundle


# ── import ───────────────────────────────────────────────────────────────────

def validate_bundle(bundle: Any) -> list[str]:
    """Structural problems (empty list = importable). Checksum mismatch is a
    WARNING entry prefixed 'warning:' — edited bundles still import."""
    problems: list[str] = []
    if not isinstance(bundle, dict):
        return ["not a scenario bundle (expected a JSON object)"]
    manifest = bundle.get("_manifest")
    if not isinstance(manifest, dict):
        return ["missing _manifest — not a MedSim scenario bundle"]
    if str(manifest.get("format_version", "")).split(".")[0] != FORMAT_VERSION.split(".")[0]:
        problems.append(f"unsupported format_version {manifest.get('format_version')!r} "
                        f"(this system reads {FORMAT_VERSION})")
    scenario = bundle.get("scenario")
    if not isinstance(scenario, dict) or not (scenario.get("name") or scenario.get("id")):
        problems.append("bundle has no scenario record")
    for key in ("characters", "personas", "support_documents"):
        if key in bundle and not isinstance(bundle[key], list):
            problems.append(f"'{key}' must be a list")
    if manifest.get("checksum") and not problems:
        if _checksum(bundle) != manifest["checksum"]:
            problems.append("warning: checksum mismatch — the bundle was edited "
                            "after export (importing anyway)")
    return problems


def _same_yaml(a: dict[str, Any], b: dict[str, Any]) -> bool:
    return json.dumps(a, sort_keys=True) == json.dumps(b, sort_keys=True)


def import_bundle(bundle: dict[str, Any]) -> dict[str, Any]:
    """Land the bundle collision-safely. Returns a report:
    {scenario_id, scenario_name, characters: [{id, action, as}], personas: [...],
     documents: int, checklist: [str], warnings: [str]}."""
    problems = validate_bundle(bundle)
    hard = [p for p in problems if not p.startswith("warning:")]
    if hard:
        raise ValueError("; ".join(hard))
    warnings = [p.removeprefix("warning: ") for p in problems if p.startswith("warning:")]

    scenario = dict(bundle["scenario"])
    id_map: dict[str, str] = {}
    char_report: list[dict[str, str]] = []
    persona_report: list[dict[str, str]] = []

    # Characters: link when identical, suffix-import when different, keep when new.
    # ids from a foreign bundle are sanitized (traversal-safe) BEFORE any disk write.
    for char in bundle.get("characters") or []:
        char = dict(char)
        raw = char.get("id") or char.get("name", "character")
        cid = _safe_id(char.get("id", ""), char.get("name", "character"))
        existing = scenarios.get_character(cid)
        if existing is None:
            char["id"] = cid
            scenarios.save_character(char)
            char_report.append({"id": raw, "action": "imported", "as": cid})
        elif _same_yaml(existing, char):
            if cid != raw:
                id_map[raw] = cid
            char_report.append({"id": raw, "action": "linked", "as": cid})
        else:
            new_id = scenarios._unique_id(scenarios.CHARACTERS_DIR, cid)
            char["id"] = new_id
            scenarios.save_character(char)
            id_map[raw] = new_id
            char_report.append({"id": raw, "action": "imported (renamed — a "
                                "different character already uses this id)", "as": new_id})

    # Authored personas: AUTH-* uuids are effectively collision-free; remap if not.
    # Build the id index ONCE (was an O(n²) list_personas() per persona).
    persona_index = {p.get("id"): p for p in authored_content.list_personas()}
    for persona in bundle.get("personas") or []:
        persona = dict(persona)
        pid = persona.get("id")
        if not pid:                       # validate_bundle can't see per-item shape
            warnings.append("a persona entry had no id — skipped")
            continue
        existing = persona_index.get(pid)
        if existing is None:
            authored_content.save_persona(persona)
            persona_report.append({"id": pid, "action": "imported", "as": pid})
        elif _same_yaml(existing, persona):
            persona_report.append({"id": pid, "action": "linked", "as": pid})
        else:
            new_id = authored_content._new_persona_id()
            id_map[pid] = new_id
            authored_content.save_persona({**persona, "id": new_id})
            persona_report.append({"id": pid, "action": "imported (renamed)", "as": new_id})

    # Scenario: never overwrite — a taken (sanitized) id lands under a fresh suffix.
    sid = _safe_id(scenario.get("id", ""), scenario.get("name", "scenario"))
    if scenarios.get_scenario(sid) is not None:
        sid = scenarios._unique_id(scenarios.SCENARIOS_DIR, sid)
    scenario["id"] = sid
    scenario["characters"] = [id_map.get(c, c) for c in (scenario.get("characters") or [])]
    scenarios.save_scenario(scenario)

    # Support documents (FR-018) — decode + land under the (possibly new) id. A bad
    # doc (corrupt base64 OR an unsupported extension save_doc rejects) is SKIPPED
    # with a warning, never aborting an import whose scenario already landed.
    doc_count = 0
    for doc in bundle.get("support_documents") or []:
        fname = doc.get("filename") or "document"
        try:
            data = base64.b64decode(doc.get("data_base64", ""))
            if not data:
                continue
            scenario_docs.save_doc(
                sid, fname, data, doc_type=doc.get("doc_type", ""),
                section=doc.get("section", ""), purpose=doc.get("purpose", ""),
                ai_mode=doc.get("ai_mode", "context"), summary=doc.get("summary", ""))
            doc_count += 1
        except Exception as exc:  # noqa: BLE001 — one bad doc must not fail the import
            warnings.append(f"document {fname!r} could not be imported ({exc}) — skipped")

    checklist = []
    for asset in (bundle.get("_manifest", {}).get("external_assets") or []):
        a_type, a_id = asset.get("type", ""), asset.get("id", "")
        if a_type == "portrait":
            checklist.append(f"Assign an avatar for '{id_map.get(a_id, a_id)}' "
                             "(portraits don't travel — consent is per-system)")
        elif a_type == "local_context":
            checklist.append(f"Provide local-context tag '{a_id}' (Settings → Local "
                             "context) or remove it from the scenario's kb_scope")
        elif a_type == "missing_character":
            checklist.append(f"Character '{a_id}' was missing on the EXPORTING system "
                             "— recreate or remove it from the scenario")
    for c in char_report:
        if "renamed" in c["action"]:
            checklist.append(f"Character '{c['id']}' imported as '{c['as']}' — review it")

    return {"scenario_id": sid, "scenario_name": scenario.get("name", sid),
            "characters": char_report, "personas": persona_report,
            "documents": doc_count, "checklist": checklist, "warnings": warnings}
