# M0 — Sibling clone v6 → v7

**Phase:** 0 — Foundation
**Status:** DONE (2026-05-26)
**Blocked by:** none
**Blocks:** every later module
**Estimated effort:** 0.5 day · **Actual:** 0.5 day

---

## 1. Purpose

Stand up a fresh `medsim_v7/` workspace alongside `medsim_v6/` that
builds, has clean storage at `~/.medsim/v7/`, and presents the V7
package identity (`medsim7`, version `7.0.0a0`) — without touching V6.
This is the foundation every later module sits on. Matches the
v4→v5→v6 sibling cadence operator already validated.

## 2. Structure

**Files touched (in v7 only):**
- `pyproject.toml` — package name `medsim7`, version `7.0.0a0`,
  description rewritten to call out the multi-patient extension.
- `portal/ehr_db.py` — `V6_DIR` → `V7_DIR` (`~/.medsim/v7/`); back-compat
  aliases `V6_DIR = V5_DIR = V7_DIR` preserved; module docstring
  updated; degraded-mode warning re-tagged as `V7`.
- `CLAUDE.md` — V7 header added above the V5/V6 baselines.

**Files NEW in v7:**
- `BUILD_STATE.md` — V7-specific build checkpoint (V6 version archived
  to `BUILD_STATE_V6.md`).
- `CONTINUATION.md` — pause/resume protocol.
- `docs/module_guides/` — per-module spec / status home (this file).

## 3. Uses

Every later module reads its imports from `portal.*` here. Every
runtime read/write goes through `~/.medsim/v7/medsim.db`. CI / dev
loops point their working directory at `medsim_v7/`. The V6 directory
stays untouched as fallback.

## 4. Functions (exported API surface)

No new public functions. The only behavior change is the storage path:

| Symbol | Old value | New value |
|--------|-----------|-----------|
| `ehr_db.V7_DIR` | (did not exist) | `~/.medsim/v7` |
| `ehr_db.DB_PATH` | `~/.medsim/v6/medsim.db` | `~/.medsim/v7/medsim.db` |
| `ehr_db.SEEDS_DIR` | `~/.medsim/v6/seeds` | `~/.medsim/v7/seeds` |
| `ehr_db.V6_DIR` (alias) | `~/.medsim/v6` | `~/.medsim/v7` (alias to `V7_DIR`) |
| `ehr_db.V5_DIR` (alias) | `~/.medsim/v6` | `~/.medsim/v7` (alias to `V7_DIR`) |

## 5. Limitations

- Does not create a v7 venv. The v6 venv (`../medsim_v6/.venv`) is
  reused because dependencies are identical; a dedicated v7 venv is a
  later-cleanup item.
- Does not migrate existing v6 SQLite content. V7 starts with a fresh
  `~/.medsim/v7/medsim.db`. If a user wants their v6 data carried
  over, they can `cp ~/.medsim/v6/medsim.db ~/.medsim/v7/medsim.db`
  and the migration runner will apply migration 4 in place (see M1).
- Does not change any runtime behavior beyond the path bump. The v6
  feature set is intact verbatim under single-patient mode.

## 6. Test status

| Test | Asserts | Status | Last run |
|------|---------|--------|----------|
| Smoke import | `ehr_db.V7_DIR` resolves; aliases work; `SCHEMA_VERSION` reachable | PASS | 2026-05-26 |

The full v6 test suite has not been re-run on v7 yet — that is M10's
job (MVP regression gate). Until M10, "the v7 codebase builds and the
new tests pass" is the per-module bar.

## 7. Change list

| Date | Author | Change | Files |
|------|--------|--------|-------|
| 2026-05-26 | claude-code | Initial sibling clone; pyproject + ehr_db path bump; CLAUDE.md V7 header; BUILD_STATE + CONTINUATION + docs/module_guides scaffolding | `pyproject.toml`, `portal/ehr_db.py`, `CLAUDE.md`, `BUILD_STATE.md`, `BUILD_STATE_V6.md`, `CONTINUATION.md`, `docs/module_guides/` |

## 8. Open questions / known issues

- The pyproject `[tool.setuptools.packages.find]` still globs
  `blocks*` and `portal*` from v6. If v7 introduces a top-level
  package (e.g. `medsim_v7_rooms/`), update that glob. Not required
  yet — v7 keeps the same package shape as v6.
- The launchers in `launchers/mac/` and `launchers/windows/` were not
  edited; they read no v6-specific path. Re-verify them when the
  manual LAN test happens in M21.
