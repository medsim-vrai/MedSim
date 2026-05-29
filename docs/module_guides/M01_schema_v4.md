# M1 — Schema migration v4

**Phase:** 1 — Data
**Status:** DONE (2026-05-26)
**Blocked by:** M0
**Blocks:** M2, M14, M17, M19
**Estimated effort:** 1 day · **Actual:** 0.5 day

---

## 1. Purpose

Add the persistence layer for the V7 multi-patient extension: three
new tables (`control_room`, `student`, `activity`) and five new columns
on the existing `ehr_session` table. The migration is version-gated,
idempotent under repeated runs, and preserves every v6 data row on
upgrade — so an existing classroom-deployed v6 DB upgrades in place
without operator intervention.

## 2. Structure

**Files touched:**
- `portal/ehr_db.py` — appends migration tuple `(4, """…""")` to
  `SCHEMA_MIGRATIONS`. Adds CREATE TABLE for `control_room`,
  `student`, `activity`; ALTER TABLE ADD COLUMN for the five new
  `ehr_session` columns; supporting indexes.

**New tables:**

| Table | Purpose |
|-------|---------|
| `control_room` | One row per room. Holds room_code, status (active/frozen/ended), creation + end timestamps, optional Haiku rate / ElevenLabs char caps. |
| `student` | One row per learner registered to a room. `assigned_encounter_id` links to the encounter they're working in. |
| `activity` | Catalog of reusable case templates. `is_builtin=1` for the eight built-in activities, `0` for instructor-authored ones. |

**New `ehr_session` columns:**

| Column | Type | Default | Purpose |
|--------|------|---------|---------|
| `room_id` | TEXT | NULL | Owning ControlRoom (NULL on legacy v6 rows). |
| `label` | TEXT | NULL | Instructor-visible tag, e.g. "Bed 3 — Kowalski". |
| `activity_id` | TEXT | NULL | Source Activity catalog entry, if any. |
| `chart_mode` | TEXT NOT NULL | 'shared' | 'shared' or 'private_clone'. |
| `patient_persona_id` | TEXT | NULL | Canonical persona library reference. |

## 3. Uses

The migration runs automatically on first server start after the v7
upgrade — `ehr_db._open_db()` calls `_run_migrations()` which iterates
`SCHEMA_MIGRATIONS` and applies any version greater than
`MAX(schema_version)`. Subsequent starts no-op.

Downstream readers:
- M2 (`portal/control_room.py`) — the `ControlRoom`/`Student`
  dataclasses are the in-memory index over these tables.
- M8 — student-roster persistence reads/writes `student`.
- M11 — Activity catalog CRUD reads/writes `activity`.
- M14 — cohort debrief filters `ehr_session` by `room_id`.
- M17 — cost caps read `control_room.haiku_rate_cap` and `voice_char_cap`.
- M19 — capacity hardening counts rows in `ehr_session` by `room_id`.

## 4. Functions (exported API surface)

None. Migration 4 ships as a tuple inside
`ehr_db.SCHEMA_MIGRATIONS` and is applied by the existing
`ehr_db._run_migrations` runner. No new public functions in this
module.

CRUD helpers for the new tables land in M8 (student) and M11
(activity), not here.

## 5. Limitations

- The `chart_mode` ADD COLUMN uses `DEFAULT 'shared'`. SQLite applies
  the default to existing rows lazily on read; new rows from M13
  (private clone) explicitly write `'private_clone'`.
- No foreign-key constraints in the new tables. The codebase has
  historically used application-level integrity rather than SQLite
  FK enforcement; preserving that pattern.
- The migration does NOT backfill `room_id` for legacy v6 rows. Those
  rows remain NULL until the v7 wizard's "Open existing v6 session"
  flow lands (not in the current plan — a v7.1 candidate).
- `student.assigned_encounter_id` is a free TEXT, not constrained to
  a known `ehr_session.session_id`. M9 enforces validity at the route
  layer.

## 6. Test status

| Test file | Asserts | Status | Last run |
|-----------|---------|--------|----------|
| `tests/v7/test_migration_v4_idempotent.py` | Applying migrations twice is a no-op; schema_version row set unchanged on second pass. | PASS | 2026-05-26 |
| `tests/v7/test_migration_v4_preserves_v6_data.py` | A v6-snapshot DB (migrations 1-3 applied, sample ehr_session + chart_event rows) upgrades to v4 with legacy rows untouched, NULL room_id, default chart_mode='shared', byte-identical chart_event payload. | PASS | 2026-05-26 |
| `tests/v7/test_new_tables_exist.py` | After full migration, control_room/student/activity tables exist with documented columns; ehr_session has all 5 new columns; supporting indexes present. | PASS | 2026-05-26 |

## 7. Change list

| Date | Author | Change | Files |
|------|--------|--------|-------|
| 2026-05-26 | claude-code | Migration 4 appended with three new tables + five `ehr_session` columns + supporting indexes. 3 acceptance tests added under `tests/v7/`. | `portal/ehr_db.py`, `tests/v7/test_migration_v4_idempotent.py`, `tests/v7/test_migration_v4_preserves_v6_data.py`, `tests/v7/test_new_tables_exist.py` |

## 8. Open questions / known issues

- `student.last_seen` is nullable; the v6 station-online heartbeat
  pattern uses a non-null `last_seen`. M8 should pick a convention
  (likely: write `registered_at` to `last_seen` at create time and
  update on every student-bound request).
- `activity.seed_modules_json` is a JSON TEXT blob. Consider whether
  a normalized `activity_module` join table would help M12 search,
  but until search performance is a problem, the JSON blob keeps the
  read path simple.
- The migration adds ONE `chart_mode NOT NULL DEFAULT 'shared'` column.
  SQLite enforces NOT NULL strictly only on new INSERTs; existing
  rows take the default. Verify behavior on the LAN test in M21.
