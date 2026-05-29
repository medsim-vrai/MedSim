# M11 — Activity catalog: dataclass + DB CRUD + 8 built-in activities

**Phase:** 7 — Activities
**Status:** DONE (2026-05-26)
**Blocked by:** M1
**Blocks:** M12, M14
**Estimated effort:** 1.5 days · **Actual:** 0.5 day

---

## 1. Purpose

Activities are persistent, instructor-curated case templates. The
wizard's room-mode editor (M12, next) lets the operator pick an
Activity for each encounter row, which then auto-fills the row's
label / persona / chart-mode / scenario text. Activities also carry
an optional answer key, which the cohort debrief (M14) consumes
when scoring student documentation against the case-author's
expected findings.

M11 ships the data layer:

1. **CRUD helpers** in ``portal/ehr_db.py`` for the `activity`
   table (M1 schema v4).
2. **The Activity dataclass + 8 built-in catalog entries** in
   ``portal/activities.py``. The first 7 mirror
   ``portal/data/sample_scenarios.json`` 1:1 so an Activity-picked
   encounter and a wizard-template-picked encounter produce
   identical seed material. The 8th (acute respiratory failure)
   extends curriculum coverage to pneumonia / hypoxemia / BiPAP —
   a gap in the v6 samples.
3. **`seed_builtins()`** — an idempotent first-start seeder that
   inserts every built-in row that isn't already in the DB.
   Instructor edits to a built-in are NOT overwritten on re-seed.

M12 will add the HTTP routes (`/api/activities` CRUD + wizard
integration); M11 is data layer only.

## 2. Structure

**New files:**
- `portal/activities.py` — `Activity` dataclass, `BUILTIN_ACTIVITIES`
  catalog (8 entries), `seed_builtins()`, `list_all()`, `get(id)`,
  `to_encounter_entry(id)` convenience wrappers.

**Files touched:**
- `portal/ehr_db.py` — adds a "V7 — Activity catalog (M11)" section
  with 5 CRUD helpers + an in-memory fallback bucket.

**No server.py changes** — routes land in M12.

## 3. Uses

- **M12 (wizard integration)** consumes:
  - `ehr_db.list_activities()` for the wizard's activity picker.
  - `activities.to_encounter_entry(id)` to translate a picked
    activity into the JSON shape `/api/room/start` accepts.
- **M14 (cohort debrief)** reads `activity.answer_key` for
  rubric-based scoring.
- **First-start hook** — `activities.seed_builtins()` should be
  called from `_run_migrations` (or a server-startup callback).
  Wiring lands in M12 alongside the route surface.
- **Operator workflow:**
  1. Server starts → `seed_builtins()` inserts the 8 built-ins on
     a fresh DB; no-op on subsequent starts.
  2. Instructor edits a built-in (M12 routes) → edit persists; re-
     seed does NOT roll back the edit.
  3. Instructor authors a new custom activity (M12) → row created
     with `is_builtin=False`.

## 4. Functions (exported API surface)

### `portal/ehr_db.py` (5 new CRUD helpers)

| Symbol | Signature | Purpose |
|--------|-----------|---------|
| `create_activity` | `(*, activity_id=None, label, seed_persona_id=None, seed_modules=None, scenario_text="", default_chart_mode="shared", answer_key=None, is_builtin=False) -> dict` | Insert. Auto-generates `act_<hex10>` id when not supplied. Returns the persisted row. |
| `get_activity` | `(activity_id) -> dict \| None` | Lookup by id. |
| `list_activities` | `(*, builtin_only=False) -> list[dict]` | Built-ins first, then custom; both alphabetical within each group. |
| `update_activity` | `(activity_id, **fields) -> dict \| None` | Patch allowed fields (label / seed_persona_id / seed_modules / scenario_text / default_chart_mode / answer_key). Unknown fields silently ignored (forward-compat). Returns None on unknown id. |
| `delete_activity` | `(activity_id) -> bool` | Hard delete. Built-in rows are protected — returns False without dropping. Idempotent (returns True if row was already absent). |

### `portal/activities.py`

| Symbol | Purpose |
|--------|---------|
| `Activity` dataclass | Typed shape: `activity_id`, `label`, `seed_persona_id`, `seed_modules`, `scenario_text`, `default_chart_mode`, `answer_key`, `is_builtin`. |
| `BUILTIN_ACTIVITIES: list[Activity]` | The 8-entry built-in catalog. |
| `seed_builtins() -> int` | Idempotent seed; returns count of rows inserted this call. |
| `list_all() -> list[dict]` | Pass-through to `ehr_db.list_activities()`. |
| `get(activity_id) -> dict \| None` | Pass-through to `ehr_db.get_activity`. |
| `to_encounter_entry(activity_id) -> dict \| None` | Translate to wizard's encounter-row JSON shape (matches `/api/room/start` body). |

### Built-in catalog

| activity_id | label | seed_persona | modules |
|---|---|---|---|
| `builtin_ed_sepsis_delirium` | ED · Sepsis with hyperactive delirium | P-014 | M32, M08, M02 |
| `builtin_msurg_postop_pain` | Med-surg · Postop pain — RN/LPN delegation | P-012 | M08, M06, M02 |
| `builtin_mh_passive_si` | Mental health · Goals-of-care + passive SI | P-019 | M39, M02 |
| `builtin_substance_etoh_withdrawal` | Substance · Alcohol withdrawal (CIWA-Ar) | P-016 | M06, M02, M39 |
| `builtin_peds_febrile_child` | Peds · Febrile child, anxious parent | P-003 | M06, M07, M03, M02 |
| `builtin_geri_goals_of_care` | Geri · Goals-of-care with grieving family | P-013 | M42, M02 |
| `builtin_msurg_dka` | Med-surg · DKA management | P-005 | M22, M06, M02 |
| `builtin_msurg_resp_failure` | Med-surg · Acute respiratory failure | P-006 | M07, M06, M02 |

## 5. Limitations

- **No HTTP surface yet.** M12 adds `/api/activities` CRUD routes
  and the wizard-side picker. Until M12 lands, only the server can
  read/write the catalog (e.g. via a Python shell or a future
  bulk-import script).
- **`seed_builtins()` is not called from server startup yet.** M12
  wires it into the server boot path.
- **`update_activity` patches a whitelist of fields.** Unknown
  fields are silently ignored to preserve forward-compat with
  M12+. If a future field needs editing, add it to the
  `allowed` set.
- **No referential integrity on `seed_persona_id`.** If a future
  build removes a persona from the library, activities pointing
  at it still exist. M12 should add a validation step at wizard
  finalize time (warn-but-allow).
- **Answer key shape is open-ended JSON.** No schema enforced;
  M14 cohort debrief will pin down a structure when it
  implements scoring. Current built-ins don't ship answer keys.
- **Built-in protection is hard at the data layer.**
  `delete_activity` of a built-in returns False — there is no
  "force delete" path. To reset a built-in to its pristine
  catalog version, M12 should add a "Reset to defaults" route
  that overwrites the row from `BUILTIN_ACTIVITIES`.
- **In-memory fallback uses `_mem_activities`** when SQLite is
  unavailable. Matches the rest of `ehr_db`'s degraded-mode
  contract.

## 6. Test status

### Automated (`tests/v7/test_activity_*.py`)

| Test file | Cases | Status | Last run |
|-----------|-------|--------|----------|
| `test_activity_create_get_list_update_delete.py` | 4 — CRUD round-trip, built-in delete protection, list ordering, bare-create defaults. | PASS | 2026-05-26 |
| `test_activity_seed_8_built_in_activities_present.py` | 5 — 8 rows inserted, seed is idempotent (8 + 0 + 0), instructor edits preserved on re-seed, `to_encounter_entry` mapping, catalog covers expected curriculum areas. | PASS | 2026-05-26 |

9/9 PASS. **Full v7 suite: 67/67 passing** (up from 58 — +9 M11
tests). **Full v6 regression on v7: 178 passed**, same 6 env-flaky
pre-existing failures, **0 v7 regressions**.

### Manual

None for M11 (data layer only). M12 will land the UI flow.

## 7. Change list

| Date | Author | Change | Files |
|------|--------|--------|-------|
| 2026-05-26 | claude-code | New `portal/activities.py` with 8-entry built-in catalog + `seed_builtins()` + `to_encounter_entry()` helpers. 5 CRUD helpers in `ehr_db.py` (create/get/list/update/delete) with SQLite + in-memory fallback. 9 acceptance tests across 2 files. | `portal/activities.py`, `portal/ehr_db.py`, `tests/v7/test_activity_create_get_list_update_delete.py`, `tests/v7/test_activity_seed_8_built_in_activities_present.py` |

## 8. Open questions / known issues

- `seed_persona_id` for the built-ins picks ONE persona from each
  v6 sample's `personas[]` list — the patient. The v6 samples
  include 3-5 personas each (patient + family + staff). When M12
  finalizes an encounter from an Activity, only the patient
  persona transfers. The other personas (family / staff) can be
  added manually in the wizard's Step 4 OR through a v7.1 "scene
  cast" extension.
- Built-in `scenario_text` is copied from the v6 samples
  verbatim. If a sample is edited in `sample_scenarios.json`, the
  Activity catalog will diverge. Two options for keeping in sync:
  (a) load BUILTIN_ACTIVITIES from `sample_scenarios.json` at
  import time, or (b) accept the drift since Activities are
  meant to be editable. M11 went with (b); M12 may revisit.
- The 8th activity (`builtin_msurg_resp_failure`) is M11-authored,
  not from the v6 samples. If the operator prefers the v6 sample
  set verbatim, they can delete it via M12 and `seed_builtins`
  won't re-insert it during normal operation. (It would re-insert
  on the NEXT fresh DB; a permanent removal requires editing
  `BUILTIN_ACTIVITIES` in code.)
- `answer_key` JSON shape is unconstrained. When M14 lands the
  cohort-debrief scorer, freeze the shape with a Pydantic model
  and document it here.
