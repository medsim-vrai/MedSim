"""V7 persistence layer — hardened.

The simulation's medical-records content (chart events, notes, orders,
vitals, comparison reports), the v6 device subsystem (device stations,
device events, character↔device assignments), and the v7 multi-patient
overlay (control_room, student, activity tables; encounter scoping
columns) are the system of record. They live in SQLite at
``~/.medsim/v7/medsim.db`` and **survive server restarts** — this is
what makes a paused simulation resumable without loss.

Storage modes (one public API either way — callers never branch):

- **SQLite** (normal): durable, the system of record. The DB file is
  created 0600 inside a 0700 ``~/.medsim/v7/`` directory.
- **In-memory** (degraded): only if the filesystem is genuinely not
  writable. This is logged LOUDLY to stderr and surfaced via
  ``storage_status()`` so the operator knows persistence is off.

Schema changes go through an ordered migration runner keyed on a
``schema_version`` table — never an ad-hoc ``CREATE TABLE`` so an older
DB upgrades cleanly instead of silently missing columns. Migration 4
in this file is the v7 multi-patient extension; v6 DBs upgrade in place
on first start, with legacy rows getting NULL room_id.
"""
from __future__ import annotations

import json
import os
import sqlite3
import sys
import threading
import time
import uuid
from pathlib import Path
from typing import Any

V7_DIR = Path.home() / ".medsim" / "v7"
DB_PATH = V7_DIR / "medsim.db"
SEEDS_DIR = V7_DIR / "seeds"
# Back-compat aliases — code/tests written against earlier versions may
# still reference V5_DIR or V6_DIR. We point them at the v7 directory
# so they keep resolving without forcing an audit of every reader.
V6_DIR = V7_DIR
V5_DIR = V7_DIR

_lock = threading.Lock()

# In-memory store — used ONLY when SQLite is unavailable (degraded mode).
_mem: dict[str, list[dict[str, Any]]] = {}
_mem_seeds: dict[str, dict[str, Any]] = {}
_mem_reports: dict[str, dict[str, Any]] = {}
_mem_catalog: list[dict[str, Any]] = []   # master catalog additions (degraded)

_db_ready = False
_shared: sqlite3.Connection | None = None
_degraded_reason: str | None = None   # None when SQLite is healthy


# ──────────────────────────────────────────────────────────────────────
# Schema migrations — ordered. Append new (version, sql) tuples; never
# edit a shipped migration. The runner applies every version greater
# than what the DB has already recorded in `schema_version`.
# ──────────────────────────────────────────────────────────────────────

SCHEMA_MIGRATIONS: list[tuple[int, str]] = [
    (1, """
    CREATE TABLE IF NOT EXISTS ehr_session (
      session_id TEXT PRIMARY KEY,
      join_code TEXT NOT NULL,
      ehr_id TEXT NOT NULL,
      persona_id TEXT,
      seed_json TEXT NOT NULL,
      created_at REAL NOT NULL,
      charting_locked_at REAL
    );
    CREATE TABLE IF NOT EXISTS ehr_station (
      ehr_station_id TEXT PRIMARY KEY,
      session_id TEXT NOT NULL,
      device_label TEXT,
      user_agent TEXT,
      joined_at REAL NOT NULL,
      last_seen REAL NOT NULL
    );
    CREATE TABLE IF NOT EXISTS chart_event (
      id INTEGER PRIMARY KEY AUTOINCREMENT,
      session_id TEXT NOT NULL,
      ehr_station_id TEXT NOT NULL,
      ts REAL NOT NULL,
      type TEXT NOT NULL,
      surface TEXT NOT NULL,
      payload_json TEXT NOT NULL
    );
    CREATE INDEX IF NOT EXISTS ix_chart_event_session_ts
      ON chart_event(session_id, ts);
    CREATE TABLE IF NOT EXISTS comparison_report (
      session_id TEXT PRIMARY KEY,
      built_at REAL NOT NULL,
      rules_json TEXT NOT NULL,
      rubric_json TEXT NOT NULL,
      score REAL,
      model TEXT,
      cost_cents INTEGER
    );
    """),
    (2, """
    -- V5 Phase 6: the extensible master order catalog. Custom supplies,
    -- services, and medications added at runtime live here and persist
    -- across server restarts. ehr_scope 'all' = available in every EHR.
    CREATE TABLE IF NOT EXISTS catalog_addition (
      id INTEGER PRIMARY KEY AUTOINCREMENT,
      category TEXT NOT NULL,
      code TEXT NOT NULL,
      label TEXT NOT NULL,
      ehr_scope TEXT NOT NULL DEFAULT 'all',
      added_by TEXT,
      added_at REAL NOT NULL
    );
    CREATE UNIQUE INDEX IF NOT EXISTS ux_catalog_addition
      ON catalog_addition(category, code, ehr_scope);
    """),
    (3, """
    -- V6 device subsystem: simulated medical devices (IV pumps, enteral
    -- pumps, dispensing cabinets) that join a session by QR. Mirrors the
    -- ehr_station / chart_event pattern: a station registry, an
    -- append-only event log folded into current state, plus an
    -- append-only assignment history so a device can be re-bound to a
    -- different character mid-scenario without losing the past binding.
    CREATE TABLE IF NOT EXISTS device_station (
      id TEXT PRIMARY KEY,
      session_id TEXT NOT NULL,
      device_kind TEXT NOT NULL,
      device_model TEXT NOT NULL,
      label TEXT,
      user_agent TEXT,
      joined_at REAL NOT NULL,
      last_seen REAL NOT NULL
    );
    CREATE INDEX IF NOT EXISTS ix_device_station_session
      ON device_station(session_id);
    CREATE TABLE IF NOT EXISTS device_event (
      id INTEGER PRIMARY KEY AUTOINCREMENT,
      session_id TEXT NOT NULL,
      station_id TEXT NOT NULL,
      ts REAL NOT NULL,
      type TEXT NOT NULL,
      surface TEXT NOT NULL,
      payload_json TEXT NOT NULL
    );
    CREATE INDEX IF NOT EXISTS ix_device_event_session_ts
      ON device_event(session_id, ts);
    CREATE INDEX IF NOT EXISTS ix_device_event_station_ts
      ON device_event(station_id, ts);
    CREATE TABLE IF NOT EXISTS device_assignment (
      id INTEGER PRIMARY KEY AUTOINCREMENT,
      session_id TEXT NOT NULL,
      station_id TEXT NOT NULL,
      character_id TEXT,
      assigned_at REAL NOT NULL,
      assigned_by TEXT NOT NULL
    );
    CREATE INDEX IF NOT EXISTS ix_device_assignment_station
      ON device_assignment(station_id, assigned_at);
    """),
    (4, """
    -- V7 multi-patient extension. A ControlRoom is the unit of instructor
    -- governance: one room contains N Encounters (formerly ControlSessions),
    -- each optionally seeded from an Activity catalog entry and assigned to
    -- a roster of Students. Single-patient mode is just a room of 1 created
    -- transparently by the wizard's "Single Patient" branch — every v6 code
    -- path keeps working because the room and its sole Encounter resolve
    -- through the same get_active()/get_by_join_code() entry points.
    --
    -- Legacy v6 rows: existing ehr_session rows survive with NULL room_id
    -- and chart_mode='shared'. The first time the v7 wizard finalizes a
    -- room-of-1 for one of those legacy sessions, control_room.create()
    -- backfills room_id and label.
    CREATE TABLE IF NOT EXISTS control_room (
      room_id TEXT PRIMARY KEY,
      room_code TEXT NOT NULL UNIQUE,
      label TEXT,
      status TEXT NOT NULL DEFAULT 'active',
      created_at REAL NOT NULL,
      ended_at REAL,
      haiku_rate_cap INTEGER,
      voice_char_cap INTEGER
    );
    CREATE INDEX IF NOT EXISTS ix_control_room_status
      ON control_room(status);

    CREATE TABLE IF NOT EXISTS student (
      student_id TEXT PRIMARY KEY,
      room_id TEXT NOT NULL,
      display_name TEXT NOT NULL,
      assigned_encounter_id TEXT,
      registered_at REAL NOT NULL,
      last_seen REAL
    );
    CREATE INDEX IF NOT EXISTS ix_student_room
      ON student(room_id);
    CREATE INDEX IF NOT EXISTS ix_student_assigned_encounter
      ON student(assigned_encounter_id);

    CREATE TABLE IF NOT EXISTS activity (
      activity_id TEXT PRIMARY KEY,
      label TEXT NOT NULL,
      seed_persona_id TEXT,
      seed_modules_json TEXT NOT NULL DEFAULT '[]',
      scenario_text TEXT,
      default_chart_mode TEXT NOT NULL DEFAULT 'shared',
      answer_key_json TEXT,
      is_builtin INTEGER NOT NULL DEFAULT 0,
      created_at REAL NOT NULL
    );
    CREATE INDEX IF NOT EXISTS ix_activity_builtin
      ON activity(is_builtin);

    -- Encounter-scoping columns on the existing ehr_session table. These
    -- are NULL on every legacy v6 row; v7 code paths that look them up
    -- must handle the NULL case as "single-patient legacy session" and
    -- treat it as a room of 1.
    ALTER TABLE ehr_session ADD COLUMN room_id TEXT;
    ALTER TABLE ehr_session ADD COLUMN label TEXT;
    ALTER TABLE ehr_session ADD COLUMN activity_id TEXT;
    ALTER TABLE ehr_session ADD COLUMN chart_mode TEXT NOT NULL DEFAULT 'shared';
    ALTER TABLE ehr_session ADD COLUMN patient_persona_id TEXT;

    CREATE INDEX IF NOT EXISTS ix_ehr_session_room
      ON ehr_session(room_id);
    """),
    (5, """
    -- V7 Phase 7 (M22+) — per-student role for the Nursing Station
    -- supervisor seat (M27). 'bedside' is the default — bedside
    -- students chat with the patient persona. 'nurse_station' is the
    -- in-sim charge-nurse role: multi-patient telemetry view, alarm
    -- board, intercom to any bed. Existing student rows default to
    -- 'bedside' so the migration is backwards-compatible.
    ALTER TABLE student ADD COLUMN role TEXT NOT NULL DEFAULT 'bedside';
    CREATE INDEX IF NOT EXISTS ix_student_role ON student(role);
    """),
    (6, """
    -- FR-011 G1 (ADR-0039) — portal resumability: ONE versioned, PHI-free
    -- structured snapshot of the live control session (config + med board +
    -- staged errors + handoff config) so a portal restart / crash / pause
    -- resumes instead of wiping. Single row (id=1) = the latest snapshot.
    CREATE TABLE IF NOT EXISTS session_state (
      id         INTEGER PRIMARY KEY CHECK (id = 1),
      saved_at   REAL NOT NULL,
      blob_json  TEXT NOT NULL
    );
    """),
]

SCHEMA_VERSION = SCHEMA_MIGRATIONS[-1][0]


# ──────────────────────────────────────────────────────────────────────
# Connection + migration
# ──────────────────────────────────────────────────────────────────────

def _ensure_dirs() -> bool:
    """Create the V7 storage dirs with tight perms. False if not writable."""
    try:
        V7_DIR.mkdir(parents=True, exist_ok=True)
        SEEDS_DIR.mkdir(parents=True, exist_ok=True)
        try:
            os.chmod(V7_DIR, 0o700)
        except OSError:
            pass  # perms are best-effort (e.g. on Windows)
        return True
    except OSError:
        return False


def _open_db() -> sqlite3.Connection | None:
    global _degraded_reason
    if not _ensure_dirs():
        _degraded_reason = f"cannot create {V7_DIR} (read-only filesystem?)"
        _warn_degraded()
        return None
    try:
        conn = sqlite3.connect(str(DB_PATH), isolation_level=None,
                               check_same_thread=False)
        conn.execute("PRAGMA journal_mode=WAL")
        conn.execute("PRAGMA synchronous=NORMAL")
        conn.execute("PRAGMA foreign_keys=ON")
        _run_migrations(conn)
        try:
            os.chmod(DB_PATH, 0o600)
        except OSError:
            pass
        return conn
    except sqlite3.Error as exc:
        _degraded_reason = f"SQLite error: {exc}"
        _warn_degraded()
        return None


def _run_migrations(conn: sqlite3.Connection) -> None:
    conn.execute(
        "CREATE TABLE IF NOT EXISTS schema_version "
        "(version INTEGER PRIMARY KEY, applied_at REAL NOT NULL)"
    )
    row = conn.execute("SELECT MAX(version) FROM schema_version").fetchone()
    current = (row[0] if row and row[0] is not None else 0)
    for version, sql in SCHEMA_MIGRATIONS:
        if version > current:
            conn.executescript(sql)
            conn.execute(
                "INSERT INTO schema_version (version, applied_at) VALUES (?, ?)",
                (version, time.time()),
            )


def _warn_degraded() -> None:
    print(
        f"\n*** MEDSIM V7 WARNING: EHR persistence is DEGRADED ***\n"
        f"    {_degraded_reason}\n"
        f"    Chart content will be kept in memory only and LOST on "
        f"server restart.\n",
        file=sys.stderr, flush=True,
    )


def _conn() -> sqlite3.Connection | None:
    global _db_ready, _shared
    if not _db_ready:
        with _lock:
            if not _db_ready:
                _shared = _open_db()
                _db_ready = True
    return _shared


def storage_status() -> dict[str, Any]:
    """Operator-facing storage health — used by /portal/ehr_admin."""
    db = _conn()
    return {
        "mode":            "sqlite" if db is not None else "memory",
        "durable":         db is not None,
        "db_path":         str(DB_PATH),
        "schema_version":  SCHEMA_VERSION,
        "degraded_reason": _degraded_reason,
    }


# ──────────────────────────────────────────────────────────────────────
# Sessions / stations
# ──────────────────────────────────────────────────────────────────────

def register_session(session_id: str, join_code: str, ehr_id: str,
                      persona_id: str | None, seed: dict[str, Any]) -> None:
    _mem_seeds[session_id] = seed
    db = _conn()
    if db is not None:
        with _lock:
            db.execute(
                "INSERT OR REPLACE INTO ehr_session "
                "(session_id, join_code, ehr_id, persona_id, seed_json, "
                " created_at, charting_locked_at) "
                "VALUES (?, ?, ?, ?, ?, ?, NULL)",
                (session_id, join_code, ehr_id, persona_id,
                 json.dumps(seed, default=str), time.time()),
            )
    # Mirror the seed JSON to disk for human inspection (best-effort).
    if _ensure_dirs():
        try:
            (SEEDS_DIR / f"{session_id}.json").write_text(
                json.dumps(seed, indent=2, default=str))
        except OSError:
            pass


def register_station(session_id: str, station_id: str, *,
                      device_label: str = "", user_agent: str = "") -> None:
    db = _conn()
    if db is None:
        return
    with _lock:
        db.execute(
            "INSERT OR REPLACE INTO ehr_station "
            "(ehr_station_id, session_id, device_label, user_agent, "
            " joined_at, last_seen) VALUES (?, ?, ?, ?, ?, ?)",
            (station_id, session_id, device_label, user_agent,
             time.time(), time.time()),
        )


def touch_station(station_id: str) -> None:
    db = _conn()
    if db is None:
        return
    with _lock:
        db.execute("UPDATE ehr_station SET last_seen=? WHERE ehr_station_id=?",
                   (time.time(), station_id))


# ──────────────────────────────────────────────────────────────────────
# Chart events (append-only)
# ──────────────────────────────────────────────────────────────────────

def append_event(session_id: str, station_id: str, *,
                  type: str, surface: str, payload: dict[str, Any]) -> int:
    ev = {
        "session_id": session_id,
        "ehr_station_id": station_id,
        "ts": time.time(),
        "type": type,
        "surface": surface,
        "payload": payload,
    }
    db = _conn()
    if db is None:
        # Degraded mode — keep it only in memory.
        with _lock:
            bucket = _mem.setdefault(session_id, [])
            ev["id"] = len(bucket) + 1
            bucket.append(ev)
            return ev["id"]
    with _lock:
        cur = db.execute(
            "INSERT INTO chart_event "
            "(session_id, ehr_station_id, ts, type, surface, payload_json) "
            "VALUES (?, ?, ?, ?, ?, ?)",
            (session_id, station_id, ev["ts"], type, surface,
             json.dumps(payload, default=str)),
        )
        return int(cur.lastrowid or 0)


def append_order(session_id: str, station_id: str, *,
                  patient_id: str, order: dict[str, Any]) -> int:
    """An order is a specialized chart_event. We stamp the order with a
    stable `order_id` so later order.modify events can target it, then
    append it as an `order.place` event."""
    order = dict(order or {})
    order.setdefault("order_id", "ord_" + uuid.uuid4().hex[:10])
    return append_event(session_id, station_id, type="order.place",
                        surface="orders",
                        payload={"patient_id": patient_id, "order": order})


def events(session_id: str) -> list[dict[str, Any]]:
    db = _conn()
    if db is None:
        return list(_mem.get(session_id, []))
    with _lock:
        rows = db.execute(
            "SELECT id, session_id, ehr_station_id, ts, type, surface, "
            "payload_json FROM chart_event WHERE session_id=? ORDER BY ts ASC, id ASC",
            (session_id,),
        ).fetchall()
    return [
        {"id": r[0], "session_id": r[1], "ehr_station_id": r[2], "ts": r[3],
         "type": r[4], "surface": r[5], "payload": json.loads(r[6] or "{}")}
        for r in rows
    ]


def orders(session_id: str) -> list[dict[str, Any]]:
    """All placed orders, time-ordered, with any modify events applied."""
    return fold(session_id)["orders"]


def seed(session_id: str) -> dict[str, Any]:
    if session_id in _mem_seeds:
        return _mem_seeds[session_id]
    db = _conn()
    if db is None:
        return {}
    with _lock:
        row = db.execute("SELECT seed_json FROM ehr_session WHERE session_id=?",
                         (session_id,)).fetchone()
    if row and row[0]:
        s = json.loads(row[0])
        _mem_seeds[session_id] = s
        return s
    return {}


def update_seed(session_id: str, new_seed: dict[str, Any]) -> None:
    """V6.1 — overwrite the frozen seed (e.g., after instructor toggles
    which MAR meds are included). Both the in-memory cache and the
    persisted JSON column are kept in sync so subsequent ehr bootstraps
    see the same shape."""
    _mem_seeds[session_id] = new_seed
    db = _conn()
    if db is None:
        return
    with _lock:
        db.execute("UPDATE ehr_session SET seed_json=? WHERE session_id=?",
                   (json.dumps(new_seed, default=str), session_id))


# ──────────────────────────────────────────────────────────────────────
# Projection — fold the event log into a chart state
# ──────────────────────────────────────────────────────────────────────

def fold(session_id: str) -> dict[str, Any]:
    """Fold the append-only event log into a complete chart projection.

    Every event type in the §10 catalog that mutates chart state is
    folded. Notes are latest-write-wins by note_id; orders are keyed by
    order_id and carry their modify history; everything else is
    append-only and time-ordered.
    """
    notes_by_id: dict[str, dict[str, Any]] = {}
    orders_by_id: dict[str, dict[str, Any]] = {}
    vitals: list[dict[str, Any]] = []
    assessments: list[dict[str, Any]] = []
    comms: list[dict[str, Any]] = []
    flags: list[dict[str, Any]] = []
    meds_administered: list[dict[str, Any]] = []
    results_acknowledged: list[dict[str, Any]] = []
    intake: list[dict[str, Any]] = []
    output: list[dict[str, Any]] = []
    allergy_adds: list[str] = []
    allergy_removes: list[str] = []
    problem_adds: list[str] = []
    problem_removes: list[str] = []

    all_events = events(session_id)
    for ev in all_events:
        t = ev["type"]
        p = ev["payload"] or {}
        ts = ev["ts"]
        if t == "note.save":
            nid = p.get("note_id") or f"n_{ts}"
            notes_by_id[nid] = {
                "note_id":   nid,
                "note_type": p.get("note_type", "Progress"),
                "template":  p.get("template", ""),
                "body":      p.get("body", ""),
                "signed":    bool(p.get("signed")),
                "author":    p.get("author", ""),   # who wrote it
                "latest_ts": ts,
                "station_id": ev.get("ehr_station_id"),
                "addenda":   notes_by_id.get(nid, {}).get("addenda", []),
            }
        elif t == "note.addendum":
            base = p.get("addendum_to")
            if base in notes_by_id:
                notes_by_id[base].setdefault("addenda", []).append(
                    {"ts": ts, "body": p.get("body", "")})
        elif t == "order.place":
            order = dict(p.get("order") or {})
            oid = order.get("order_id") or f"ord_{ts}"
            orders_by_id[oid] = {
                "order_id":    oid,
                "ts":          ts,
                "station_id":  ev.get("ehr_station_id"),
                "patient_id":  p.get("patient_id", ""),
                "status":      "active",
                "order":       order,
                "modifications": orders_by_id.get(oid, {}).get("modifications", []),
            }
        elif t == "order.modify":
            oid = p.get("order_id")
            mod = {"ts": ts, "action": p.get("action", "modify"),
                   "detail": p.get("detail", "")}
            if oid in orders_by_id:
                orders_by_id[oid]["modifications"].append(mod)
                act = (p.get("action") or "").lower()
                if act in ("discontinue", "dc", "cancel"):
                    orders_by_id[oid]["status"] = "discontinued"
                elif act == "hold":
                    orders_by_id[oid]["status"] = "held"
                elif act == "resume":
                    orders_by_id[oid]["status"] = "active"
        elif t == "vitals.record":
            vitals.append({"ts": ts, **{k: v for k, v in p.items() if k != "ts"}})
        elif t == "assessment.update":
            assessments.append({"ts": ts, **{k: v for k, v in p.items() if k != "ts"}})
        elif t == "med.administer":
            meds_administered.append({"ts": ts, **{k: v for k, v in p.items() if k != "ts"}})
        elif t == "result.acknowledge":
            results_acknowledged.append({"ts": ts, "result_id": p.get("result_id", ""),
                                         "name": p.get("name", "")})
        elif t == "intake.record":
            intake.append({"ts": ts, **{k: v for k, v in p.items() if k != "ts"}})
        elif t == "output.record":
            output.append({"ts": ts, **{k: v for k, v in p.items() if k != "ts"}})
        elif t == "allergy.add":
            allergy_adds.append(p.get("substance") or p.get("name") or "")
        elif t == "allergy.remove":
            allergy_removes.append(p.get("substance") or p.get("name") or "")
        elif t == "problem.add":
            problem_adds.append(p.get("name") or "")
        elif t == "problem.remove":
            problem_removes.append(p.get("name") or "")
        elif t == "communication.log":
            comms.append({"ts": ts, **{k: v for k, v in p.items() if k != "ts"}})
        elif t == "flag.raise":
            flags.append({"ts": ts, **{k: v for k, v in p.items() if k != "ts"}})
        # chart.open / session.idle / session.resume don't mutate the chart.

    return {
        "notes":                sorted(notes_by_id.values(), key=lambda n: n["latest_ts"]),
        "orders":               sorted(orders_by_id.values(), key=lambda o: o["ts"]),
        "vitals":               vitals,
        "assessments":          assessments,
        "meds_administered":    meds_administered,
        "results_acknowledged": results_acknowledged,
        "intake":               intake,
        "output":               output,
        "allergies":            {"adds": allergy_adds, "removes": allergy_removes},
        "problems":             {"adds": problem_adds, "removes": problem_removes},
        "comms":                comms,
        "flags":                flags,
        "event_count":          len(all_events),
    }


# ──────────────────────────────────────────────────────────────────────
# Comparison report
# ──────────────────────────────────────────────────────────────────────

def save_comparison(session_id: str, rules: dict[str, Any], rubric: dict[str, Any],
                     score: float, *, model: str = "claude-haiku-4-5",
                     cost_cents: int = 0) -> None:
    report = {
        "rules": rules, "rubric": rubric, "score": score,
        "model": model, "cost_cents": cost_cents, "built_at": time.time(),
    }
    _mem_reports[session_id] = report
    db = _conn()
    if db is None:
        return
    with _lock:
        db.execute(
            "INSERT OR REPLACE INTO comparison_report "
            "(session_id, built_at, rules_json, rubric_json, score, model, cost_cents) "
            "VALUES (?, ?, ?, ?, ?, ?, ?)",
            (session_id, report["built_at"], json.dumps(rules, default=str),
             json.dumps(rubric, default=str), score, model, cost_cents),
        )
        db.execute("UPDATE ehr_session SET charting_locked_at=? WHERE session_id=?",
                   (time.time(), session_id))


# ── FR-011 G1 (ADR-0039) — resumability snapshot store ────────────────────────
# One PHI-free structured blob persisted to the SAME restart-durable SQLite the
# EHR chart already survives in. In-memory fallback keeps degraded mode working.
_mem_session_state: str | None = None


def save_session_state(blob_json: str) -> None:
    """Write/replace the single latest session-state snapshot."""
    global _mem_session_state
    _mem_session_state = blob_json
    db = _conn()
    if db is None:
        return
    with _lock:
        db.execute(
            "INSERT OR REPLACE INTO session_state (id, saved_at, blob_json) "
            "VALUES (1, ?, ?)", (time.time(), blob_json))


def load_session_state() -> str | None:
    """The latest snapshot JSON, or None."""
    db = _conn()
    if db is None:
        return _mem_session_state
    with _lock:
        row = db.execute("SELECT blob_json FROM session_state WHERE id=1").fetchone()
    return row[0] if row else _mem_session_state


def clear_session_state() -> None:
    global _mem_session_state
    _mem_session_state = None
    db = _conn()
    if db is None:
        return
    with _lock:
        db.execute("DELETE FROM session_state WHERE id=1")


def get_comparison(session_id: str) -> dict[str, Any] | None:
    if session_id in _mem_reports:
        return _mem_reports[session_id]
    db = _conn()
    if db is None:
        return None
    with _lock:
        row = db.execute(
            "SELECT built_at, rules_json, rubric_json, score, model, cost_cents "
            "FROM comparison_report WHERE session_id=?", (session_id,)).fetchone()
    if not row:
        return None
    return {
        "built_at": row[0], "rules": json.loads(row[1] or "{}"),
        "rubric": json.loads(row[2] or "{}"), "score": row[3],
        "model": row[4], "cost_cents": row[5],
    }


# ──────────────────────────────────────────────────────────────────────
# Master order catalog — extensible, persistent, shared by all 3 EHRs
# ──────────────────────────────────────────────────────────────────────

def add_catalog_item(category: str, code: str, label: str = "", *,
                      ehr_scope: str = "all", added_by: str = "") -> dict[str, Any] | None:
    """Add a custom supply / service / medication to the master order
    catalog. Persists across restarts. Idempotent on (category, code,
    ehr_scope). Returns the stored item, or None on invalid input."""
    item = {
        "category": (category or "").strip().lower(),
        "code":     (code or "").strip(),
        "label":    (label or code or "").strip(),
        "ehr_scope": (ehr_scope or "all").strip() or "all",
        "added_by": (added_by or "").strip(),
        "added_at": time.time(),
        "added":    True,
    }
    if not item["category"] or not item["code"]:
        return None
    db = _conn()
    if db is None:
        for x in _mem_catalog:
            if (x["category"] == item["category"]
                    and x["code"].lower() == item["code"].lower()
                    and x["ehr_scope"] == item["ehr_scope"]):
                return x
        _mem_catalog.append(item)
        return item
    with _lock:
        db.execute(
            "INSERT OR IGNORE INTO catalog_addition "
            "(category, code, label, ehr_scope, added_by, added_at) "
            "VALUES (?, ?, ?, ?, ?, ?)",
            (item["category"], item["code"], item["label"],
             item["ehr_scope"], item["added_by"], item["added_at"]),
        )
    return item


def catalog_additions(ehr_id: str | None = None) -> list[dict[str, Any]]:
    """Master-catalog additions visible to `ehr_id` (scope 'all' + that
    EHR). Pass ehr_id=None for every addition (admin view)."""
    db = _conn()
    if db is None:
        return [x for x in _mem_catalog
                if ehr_id is None or x["ehr_scope"] in ("all", ehr_id)]
    with _lock:
        if ehr_id is None:
            rows = db.execute(
                "SELECT id, category, code, label, ehr_scope, added_by, added_at "
                "FROM catalog_addition ORDER BY added_at").fetchall()
        else:
            rows = db.execute(
                "SELECT id, category, code, label, ehr_scope, added_by, added_at "
                "FROM catalog_addition WHERE ehr_scope IN ('all', ?) "
                "ORDER BY added_at", (ehr_id,)).fetchall()
    return [
        {"id": r[0], "category": r[1], "code": r[2], "label": r[3],
         "ehr_scope": r[4], "added_by": r[5], "added_at": r[6], "added": True}
        for r in rows
    ]


def remove_catalog_item(item_id: int) -> None:
    """Instructor prune of a master-catalog addition."""
    db = _conn()
    if db is None:
        return
    with _lock:
        db.execute("DELETE FROM catalog_addition WHERE id=?", (item_id,))


# ──────────────────────────────────────────────────────────────────────
# Purge
# ──────────────────────────────────────────────────────────────────────

def purge_session(session_id: str) -> None:
    _mem.pop(session_id, None)
    _mem_seeds.pop(session_id, None)
    _mem_reports.pop(session_id, None)
    _mem_device_events.pop(session_id, None)
    db = _conn()
    if db is not None:
        with _lock:
            db.execute("DELETE FROM chart_event       WHERE session_id=?", (session_id,))
            db.execute("DELETE FROM ehr_station       WHERE session_id=?", (session_id,))
            db.execute("DELETE FROM comparison_report WHERE session_id=?", (session_id,))
            db.execute("DELETE FROM device_event      WHERE session_id=?", (session_id,))
            db.execute("DELETE FROM device_station    WHERE session_id=?", (session_id,))
            db.execute("DELETE FROM device_assignment WHERE session_id=?", (session_id,))
            db.execute("DELETE FROM ehr_session       WHERE session_id=?", (session_id,))
    if _ensure_dirs():
        path = SEEDS_DIR / f"{session_id}.json"
        if path.exists():
            try:
                path.unlink()
            except OSError:
                pass


# ──────────────────────────────────────────────────────────────────────
# V6 device subsystem — registry, append-only event log, assignment
# history. Mirrors the chart_event API surface so callers and tests can
# rely on the same conventions.
# ──────────────────────────────────────────────────────────────────────

# Degraded-mode buckets, keyed exactly like _mem (by session_id).
_mem_device_events: dict[str, list[dict[str, Any]]] = {}
_mem_device_stations: dict[str, dict[str, Any]] = {}
_mem_device_assignments: list[dict[str, Any]] = []


def register_device_station(session_id: str, station_id: str, *,
                             device_kind: str, device_model: str,
                             label: str | None = None,
                             user_agent: str | None = None) -> None:
    now = time.time()
    db = _conn()
    if db is None:
        _mem_device_stations[station_id] = {
            "id": station_id, "session_id": session_id,
            "device_kind": device_kind, "device_model": device_model,
            "label": label, "user_agent": user_agent,
            "joined_at": now, "last_seen": now,
        }
        return
    with _lock:
        db.execute(
            "INSERT OR REPLACE INTO device_station "
            "(id, session_id, device_kind, device_model, label, "
            " user_agent, joined_at, last_seen) "
            "VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
            (station_id, session_id, device_kind, device_model,
             label, user_agent, now, now),
        )


def touch_device_station(station_id: str) -> None:
    now = time.time()
    if station_id in _mem_device_stations:
        _mem_device_stations[station_id]["last_seen"] = now
    db = _conn()
    if db is not None:
        with _lock:
            db.execute("UPDATE device_station SET last_seen=? WHERE id=?",
                       (now, station_id))


def device_stations(session_id: str) -> list[dict[str, Any]]:
    db = _conn()
    if db is None:
        return [s for s in _mem_device_stations.values()
                if s["session_id"] == session_id]
    with _lock:
        rows = db.execute(
            "SELECT id, session_id, device_kind, device_model, label, "
            "user_agent, joined_at, last_seen FROM device_station "
            "WHERE session_id=? ORDER BY joined_at ASC",
            (session_id,),
        ).fetchall()
    return [
        {"id": r[0], "session_id": r[1], "device_kind": r[2],
         "device_model": r[3], "label": r[4], "user_agent": r[5],
         "joined_at": r[6], "last_seen": r[7]}
        for r in rows
    ]


def get_device_station(station_id: str) -> dict[str, Any] | None:
    if station_id in _mem_device_stations:
        return dict(_mem_device_stations[station_id])
    db = _conn()
    if db is None:
        return None
    with _lock:
        row = db.execute(
            "SELECT id, session_id, device_kind, device_model, label, "
            "user_agent, joined_at, last_seen FROM device_station WHERE id=?",
            (station_id,),
        ).fetchone()
    if row is None:
        return None
    return {"id": row[0], "session_id": row[1], "device_kind": row[2],
            "device_model": row[3], "label": row[4], "user_agent": row[5],
            "joined_at": row[6], "last_seen": row[7]}


def append_device_event(session_id: str, station_id: str, *,
                         type: str, surface: str,
                         payload: dict[str, Any]) -> dict[str, Any]:
    """Append an immutable device event. Returns the persisted row
    (including id, ts) so callers can broadcast it on the WebSocket."""
    ev = {
        "session_id": session_id, "station_id": station_id,
        "ts": time.time(), "type": type, "surface": surface,
        "payload": payload,
    }
    db = _conn()
    if db is None:
        with _lock:
            bucket = _mem_device_events.setdefault(session_id, [])
            ev["id"] = len(bucket) + 1
            bucket.append(ev)
            return dict(ev)
    with _lock:
        cur = db.execute(
            "INSERT INTO device_event "
            "(session_id, station_id, ts, type, surface, payload_json) "
            "VALUES (?, ?, ?, ?, ?, ?)",
            (session_id, station_id, ev["ts"], type, surface,
             json.dumps(payload, default=str)),
        )
        ev["id"] = int(cur.lastrowid or 0)
    return dict(ev)


def device_events(*, session_id: str | None = None,
                    station_id: str | None = None) -> list[dict[str, Any]]:
    """Time-ordered device events. Filter by session, station, or both."""
    if session_id is None and station_id is None:
        raise ValueError("device_events: pass session_id or station_id")
    db = _conn()
    if db is None:
        rows = []
        for sess, bucket in _mem_device_events.items():
            if session_id and sess != session_id:
                continue
            for r in bucket:
                if station_id and r["station_id"] != station_id:
                    continue
                rows.append(dict(r))
        rows.sort(key=lambda r: (r["ts"], r.get("id", 0)))
        return rows
    where, args = [], []
    if session_id is not None:
        where.append("session_id=?"); args.append(session_id)
    if station_id is not None:
        where.append("station_id=?"); args.append(station_id)
    sql = (
        "SELECT id, session_id, station_id, ts, type, surface, payload_json "
        "FROM device_event WHERE " + " AND ".join(where) +
        " ORDER BY ts ASC, id ASC"
    )
    with _lock:
        rows = db.execute(sql, tuple(args)).fetchall()
    return [
        {"id": r[0], "session_id": r[1], "station_id": r[2], "ts": r[3],
         "type": r[4], "surface": r[5], "payload": json.loads(r[6] or "{}")}
        for r in rows
    ]


def record_assignment(session_id: str, station_id: str, *,
                       character_id: str | None,
                       assigned_by: str = "instructor") -> dict[str, Any]:
    """Bind (or unbind, with character_id=None) a device to a character.
    Append-only: previous assignments stay for debrief replay."""
    now = time.time()
    row = {"session_id": session_id, "station_id": station_id,
           "character_id": character_id, "assigned_at": now,
           "assigned_by": assigned_by}
    db = _conn()
    if db is None:
        _mem_device_assignments.append(row)
        return dict(row)
    with _lock:
        db.execute(
            "INSERT INTO device_assignment "
            "(session_id, station_id, character_id, assigned_at, assigned_by) "
            "VALUES (?, ?, ?, ?, ?)",
            (session_id, station_id, character_id, now, assigned_by),
        )
    return dict(row)


def current_assignment(station_id: str) -> dict[str, Any] | None:
    """Latest assignment row, or None if never assigned."""
    db = _conn()
    if db is None:
        rows = [r for r in _mem_device_assignments
                if r["station_id"] == station_id]
        return dict(rows[-1]) if rows else None
    with _lock:
        row = db.execute(
            "SELECT session_id, station_id, character_id, assigned_at, "
            "assigned_by FROM device_assignment WHERE station_id=? "
            "ORDER BY assigned_at DESC, id DESC LIMIT 1",
            (station_id,),
        ).fetchone()
    if row is None:
        return None
    return {"session_id": row[0], "station_id": row[1],
            "character_id": row[2], "assigned_at": row[3],
            "assigned_by": row[4]}


def assignment_history(station_id: str) -> list[dict[str, Any]]:
    """Every assignment row for this station, oldest first."""
    db = _conn()
    if db is None:
        rows = [dict(r) for r in _mem_device_assignments
                if r["station_id"] == station_id]
        rows.sort(key=lambda r: r["assigned_at"])
        return rows
    with _lock:
        rows = db.execute(
            "SELECT session_id, station_id, character_id, assigned_at, "
            "assigned_by FROM device_assignment WHERE station_id=? "
            "ORDER BY assigned_at ASC, id ASC",
            (station_id,),
        ).fetchall()
    return [{"session_id": r[0], "station_id": r[1], "character_id": r[2],
             "assigned_at": r[3], "assigned_by": r[4]} for r in rows]


# ──────────────────────────────────────────────────────────────────────
# V7 — Student roster (M8)
#
# Rows in the `student` table (M1 migration v4) survive server
# restarts. The ControlRoom is in-memory only; students reload on
# demand via students_for_room(room_id), which the wizard's
# room-finalize and the M9 student-join flow call when rehydrating
# a room's state after a restart.
# ──────────────────────────────────────────────────────────────────────

# In-memory fallback for degraded mode (SQLite unavailable).
_mem_students: dict[str, dict[str, Any]] = {}


def register_student(room_id: str, *, display_name: str,
                      student_id: str | None = None,
                      assigned_encounter_id: str | None = None,
                      role: str = "bedside") -> dict[str, Any]:
    """Insert a new student row. Returns the persisted row dict.

    `student_id` is generated if not supplied. `assigned_encounter_id`
    may be None at registration; M9's join flow sets it once the
    student picks their encounter on the join page.

    `role` is 'bedside' (default — M9 student) or 'nurse_station'
    (Phase 7 M27 — supervisor role with multi-patient view + alarm
    board + intercom).
    """
    if role not in ("bedside", "nurse_station"):
        role = "bedside"
    sid = student_id or ("stu_" + uuid.uuid4().hex[:10])
    now = time.time()
    row = {
        "student_id":            sid,
        "room_id":               room_id,
        "display_name":          display_name,
        "assigned_encounter_id": assigned_encounter_id,
        "registered_at":         now,
        "last_seen":             now,
        "role":                  role,
    }
    db = _conn()
    if db is None:
        _mem_students[sid] = row
        return dict(row)
    with _lock:
        db.execute(
            "INSERT OR REPLACE INTO student "
            "(student_id, room_id, display_name, assigned_encounter_id, "
            " registered_at, last_seen, role) "
            "VALUES (?, ?, ?, ?, ?, ?, ?)",
            (sid, room_id, display_name, assigned_encounter_id, now, now,
             role),
        )
    return dict(row)


def update_student_assignment(student_id: str,
                                encounter_id: str | None) -> None:
    """Set or clear a student's assigned_encounter_id."""
    db = _conn()
    if db is None:
        if student_id in _mem_students:
            _mem_students[student_id]["assigned_encounter_id"] = encounter_id
        return
    with _lock:
        db.execute(
            "UPDATE student SET assigned_encounter_id=? WHERE student_id=?",
            (encounter_id, student_id),
        )


def touch_student(student_id: str) -> None:
    """Bump last_seen to now — used by the student heartbeat in M9."""
    db = _conn()
    now = time.time()
    if db is None:
        if student_id in _mem_students:
            _mem_students[student_id]["last_seen"] = now
        return
    with _lock:
        db.execute(
            "UPDATE student SET last_seen=? WHERE student_id=?",
            (now, student_id),
        )


_STUDENT_COLS = ("student_id, room_id, display_name, "
                  "assigned_encounter_id, registered_at, last_seen, role")


def _row_to_student(r: Any) -> dict[str, Any]:
    return {"student_id":            r[0], "room_id":               r[1],
            "display_name":          r[2], "assigned_encounter_id": r[3],
            "registered_at":         r[4], "last_seen":             r[5],
            "role":                  r[6] if len(r) > 6 else "bedside"}


def students_for_room(room_id: str) -> list[dict[str, Any]]:
    """All students registered to a room, oldest first. Used at room
    rehydrate time and by the M5 dashboard's roster panel (when it
    lands)."""
    db = _conn()
    if db is None:
        rows = [dict(s) for s in _mem_students.values()
                if s["room_id"] == room_id]
        # Ensure 'role' is set for legacy in-memory rows.
        for r in rows:
            r.setdefault("role", "bedside")
        rows.sort(key=lambda s: s["registered_at"])
        return rows
    with _lock:
        rows = db.execute(
            f"SELECT {_STUDENT_COLS} FROM student WHERE room_id=? "
            "ORDER BY registered_at ASC",
            (room_id,),
        ).fetchall()
    return [_row_to_student(r) for r in rows]


def students_for_encounter(encounter_id: str) -> list[dict[str, Any]]:
    """All students currently assigned to a specific encounter."""
    db = _conn()
    if db is None:
        rows = [dict(s) for s in _mem_students.values()
                if s.get("assigned_encounter_id") == encounter_id]
        for r in rows:
            r.setdefault("role", "bedside")
        rows.sort(key=lambda s: s["registered_at"])
        return rows
    with _lock:
        rows = db.execute(
            f"SELECT {_STUDENT_COLS} FROM student WHERE assigned_encounter_id=? "
            "ORDER BY registered_at ASC",
            (encounter_id,),
        ).fetchall()
    return [_row_to_student(r) for r in rows]


def get_student(student_id: str) -> dict[str, Any] | None:
    """Lookup one student by id. None when unknown."""
    db = _conn()
    if db is None:
        s = _mem_students.get(student_id)
        if not s:
            return None
        out = dict(s)
        out.setdefault("role", "bedside")
        return out
    with _lock:
        r = db.execute(
            f"SELECT {_STUDENT_COLS} FROM student WHERE student_id=?",
            (student_id,),
        ).fetchone()
    if r is None:
        return None
    return _row_to_student(r)


def students_by_role(room_id: str, role: str) -> list[dict[str, Any]]:
    """Filter students by role within a room. M27's Nursing Station
    join flow uses this to find the active nurse-station student."""
    return [s for s in students_for_room(room_id) if s.get("role") == role]


def remove_student(student_id: str) -> None:
    """Drop a student row. Used by M9's roster-management UI; not used
    on normal end-of-room (we keep the audit trail)."""
    db = _conn()
    if db is None:
        _mem_students.pop(student_id, None)
        return
    with _lock:
        db.execute("DELETE FROM student WHERE student_id=?", (student_id,))


# ──────────────────────────────────────────────────────────────────────
# V7 — Activity catalog (M11)
#
# Activities are persistent, instructor-curated case templates that
# seed an Encounter when picked from the wizard's room-mode editor.
# Stored in the `activity` table (M1 schema v4); the built-in
# activities are seeded on first connect by ``portal.activities``.
# ──────────────────────────────────────────────────────────────────────

_mem_activities: dict[str, dict[str, Any]] = {}


def _row_to_activity(r: Any) -> dict[str, Any]:
    return {
        "activity_id":         r[0],
        "label":               r[1],
        "seed_persona_id":     r[2],
        "seed_modules":        json.loads(r[3] or "[]"),
        "scenario_text":       r[4] or "",
        "default_chart_mode":  r[5],
        "answer_key":          json.loads(r[6]) if r[6] else None,
        "is_builtin":          bool(r[7]),
        "created_at":          r[8],
    }


def create_activity(
    *,
    activity_id: str | None = None,
    label: str,
    seed_persona_id: str | None = None,
    seed_modules: list[str] | None = None,
    scenario_text: str = "",
    default_chart_mode: str = "shared",
    answer_key: dict[str, Any] | None = None,
    is_builtin: bool = False,
) -> dict[str, Any]:
    """Insert an Activity. Returns the persisted row dict. ``activity_id``
    is generated when not supplied (``act_<hex10>``)."""
    aid = activity_id or ("act_" + uuid.uuid4().hex[:10])
    now = time.time()
    row = {
        "activity_id":         aid,
        "label":               label,
        "seed_persona_id":     seed_persona_id,
        "seed_modules":        list(seed_modules or []),
        "scenario_text":       scenario_text,
        "default_chart_mode":  default_chart_mode,
        "answer_key":          answer_key,
        "is_builtin":          bool(is_builtin),
        "created_at":          now,
    }
    db = _conn()
    if db is None:
        _mem_activities[aid] = row
        return dict(row)
    with _lock:
        db.execute(
            "INSERT OR REPLACE INTO activity "
            "(activity_id, label, seed_persona_id, seed_modules_json, "
            " scenario_text, default_chart_mode, answer_key_json, "
            " is_builtin, created_at) "
            "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)",
            (aid, label, seed_persona_id,
             json.dumps(list(seed_modules or []), default=str),
             scenario_text, default_chart_mode,
             json.dumps(answer_key, default=str) if answer_key else None,
             1 if is_builtin else 0, now),
        )
    return dict(row)


def get_activity(activity_id: str) -> dict[str, Any] | None:
    db = _conn()
    if db is None:
        a = _mem_activities.get(activity_id)
        return dict(a) if a else None
    with _lock:
        r = db.execute(
            "SELECT activity_id, label, seed_persona_id, seed_modules_json, "
            " scenario_text, default_chart_mode, answer_key_json, "
            " is_builtin, created_at "
            "FROM activity WHERE activity_id=?",
            (activity_id,),
        ).fetchone()
    return _row_to_activity(r) if r else None


def list_activities(*, builtin_only: bool = False) -> list[dict[str, Any]]:
    """All activities ordered by built-in first, then alphabetically by
    label. ``builtin_only=True`` restricts to the seeded catalog."""
    db = _conn()
    if db is None:
        rows = [dict(a) for a in _mem_activities.values()]
        if builtin_only:
            rows = [r for r in rows if r["is_builtin"]]
        rows.sort(key=lambda r: (not r["is_builtin"], r["label"]))
        return rows
    with _lock:
        sql = ("SELECT activity_id, label, seed_persona_id, "
               " seed_modules_json, scenario_text, default_chart_mode, "
               " answer_key_json, is_builtin, created_at FROM activity ")
        params: tuple = ()
        if builtin_only:
            sql += "WHERE is_builtin=1 "
            params = ()
        sql += "ORDER BY is_builtin DESC, label ASC"
        rows = db.execute(sql, params).fetchall()
    return [_row_to_activity(r) for r in rows]


def update_activity(activity_id: str, **fields: Any) -> dict[str, Any] | None:
    """Patch an existing activity. Unknown fields are silently ignored
    (forward-compat). Returns the updated row, or None if unknown id."""
    existing = get_activity(activity_id)
    if existing is None:
        return None
    allowed = {"label", "seed_persona_id", "seed_modules", "scenario_text",
                "default_chart_mode", "answer_key"}
    patched = {**existing}
    for k, v in fields.items():
        if k in allowed:
            patched[k] = v
    db = _conn()
    if db is None:
        _mem_activities[activity_id] = patched
        return dict(patched)
    with _lock:
        db.execute(
            "UPDATE activity SET label=?, seed_persona_id=?, "
            " seed_modules_json=?, scenario_text=?, "
            " default_chart_mode=?, answer_key_json=? "
            "WHERE activity_id=?",
            (patched["label"], patched["seed_persona_id"],
             json.dumps(list(patched["seed_modules"] or []), default=str),
             patched["scenario_text"], patched["default_chart_mode"],
             (json.dumps(patched["answer_key"], default=str)
              if patched["answer_key"] else None),
             activity_id),
        )
    return dict(patched)


def delete_activity(activity_id: str) -> bool:
    """Drop a row. Built-in activities are protected — returns False if
    the row is built-in. Returns True when a non-builtin row was deleted
    or already absent."""
    existing = get_activity(activity_id)
    if existing is None:
        return True   # idempotent — nothing to do
    if existing["is_builtin"]:
        return False
    db = _conn()
    if db is None:
        _mem_activities.pop(activity_id, None)
        return True
    with _lock:
        db.execute("DELETE FROM activity WHERE activity_id=?",
                    (activity_id,))
    return True
