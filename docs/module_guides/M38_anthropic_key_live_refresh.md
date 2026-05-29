# M38 — Anthropic key live-refresh on station turn + friendlier 401

**Phase:** Phase 7 follow-on (post-M37, operator-reported bug fix)
**Status:** **DONE**
**Blocked by:** M35 (Engage flow exposed the bug)
**Blocks:** none
**Estimated effort:** 0.5 day

---

## 1. Purpose

Operator-reported after M37:

> "Respond by saying one sec, then this error message — System:
> AuthenticationError: Error code: 401 — {'type': 'error', 'error':
> {'type': 'authentication_error', 'message': 'invalid x-api-key'},
> 'request_id': '…'}"

Three problems wrapped in one report:

1. **Stale `sess.api_key`**. The encounter's Anthropic key is snapshotted
   at `/api/room/start` time from `vault.get("ANTHROPIC_API_KEY")`. If
   the operator later rotates the key (or the vault key was wrong all
   along), the snapshot is invalid and every Claude call from the
   station-turn route 401s. The operator's only previous fix was to
   end the room and start a new one — disruptive mid-session.

2. **No validation at room start**. When the vault has no Anthropic
   key, `/api/room/start` still succeeds (creating an encounter with
   `api_key=""`). The bug surfaces only on the first turn — far from
   the cause.

3. **Hostile error message**. The raw Python repr of the Anthropic
   401 exception (`"AuthenticationError: Error code: 401 - {...}"`)
   bubbles up into the chat verbatim. Doesn't tell the operator where
   to fix it.

The fix mirrors the ElevenLabs `_runtime_key` pattern already in
`portal/voices.py`: a process-wide cache that any operator-auth
route stamps when it reads the key from vault. The station-turn
route prefers the cache over `sess.api_key`, so updating
`/portal/credentials` propagates to live encounters without a
restart.

## 2. Structure

**Files touched:**
- `portal/server.py`:
  - New module-level `_anthropic_runtime_key: str = ""`.
  - New helper `_capture_anthropic_key(key)` — updates the cache.
    Empty strings never overwrite a previously-cached non-empty
    value (protects against accidental clears).
  - New helper `_resolve_anthropic_key(sess)` — returns the cache
    if set, otherwise `sess.api_key`. This is what the station-turn
    route uses to pick the best-known key.
  - Hooks: `_capture_anthropic_key(...)` is called from
    `/portal/credentials` (POST), `/portal/control/start` (single-
    patient room start), and `/api/room/start` (multi-patient room
    start). Each of those reads the vault key; the cache reflects
    that read.
  - `/api/room/start` now raises **400** with a clear message when
    the vault has no `ANTHROPIC_API_KEY`. Prevents the "filler
    plays, then 401 in chat" experience that triggered M38.
  - `/api/station/{join_code}/{station_id}/turn` now uses
    `_resolve_anthropic_key(sess)` instead of `sess.api_key`
    directly. It also keeps `sess.api_key` in sync with the cache
    (so other paths benefit). When the key is empty, returns a
    structured `{"ok": False, "error": "No Anthropic API key
    configured. Open /portal/credentials …"}`.
  - The Claude call inside the same route is wrapped in
    `try / except Exception` — a thrown `AuthenticationError` (401)
    or runtime error is caught and translated into a chat-friendly
    string that points at `/portal/credentials`. `runtime.take_turn`'s
    own `{"ok": False, "error": …}` return shape is also inspected
    for 401-shaped substrings and rewritten.

**No schema migration. No dataclass change.** The encounter still
carries `api_key` (the snapshot); we just don't blindly trust it.

## 3. Uses

### 3.1 Operator flow (the bug path that prompted the fix)

1. Operator stored an Anthropic key in `/portal/credentials` weeks
   ago. That key was later rotated (Anthropic admin console). The
   operator forgot to update the vault.
2. Operator starts a multi-patient room → encounters now carry
   `sess.api_key = "<stale key>"`.
3. Operator clicks Engage on the encounter console → lands on
   `/station/{join}/INST-{persona}`.
4. Operator presses PTT, speaks → STT result → POST `/turn`.
5. Filler audio plays through ElevenLabs (different key path — that
   one works).
6. Server calls `runtime.take_turn(...)` with the stale key →
   Anthropic returns 401.
7. **Before M38**: chat shows
   *"System: AuthenticationError: Error code: 401 - {…raw repr…}"*
   and the operator has no idea where to fix it.
8. **After M38**: chat shows
   *"Anthropic rejected the API key (401). Update
   ANTHROPIC_API_KEY at /portal/credentials and try again — the new
   key applies immediately."*

### 3.2 Operator flow (the recovery path)

1. Operator sees the friendly 401 chat error.
2. Operator opens `/portal/credentials` in a new tab, pastes the
   fresh Anthropic key, clicks Save → POST `/portal/credentials`.
3. The route's `_capture_anthropic_key(value.strip())` updates the
   process-wide cache.
4. Operator returns to the engage chat tab, presses PTT again.
5. `/api/station/.../turn` reads the cache via
   `_resolve_anthropic_key(sess)` → gets the new key.
6. Claude call succeeds. Operator is back in business — no room
   restart.

### 3.3 The cache-precedence rules

The cache is preferred for one reason: it reflects the latest
operator-confirmed key value. The encounter's snapshot is the
fallback for two cases:

1. **Fresh process, no operator route has read vault yet.** Cache
   is empty, snapshot is whatever room-start stamped. Use snapshot.
2. **Cache somehow got cleared** (defensive). We protect against
   `_capture_anthropic_key("")` overwriting the cache, but in case
   of future code paths that clear it, the snapshot is the lifeboat.

`_resolve_anthropic_key(sess)` returns whichever exists; only when
BOTH are empty does the route return the friendly 503-style
fallback message.

## 4. Functions (exported API surface)

| Symbol | Where | Purpose |
|--------|-------|---------|
| `_anthropic_runtime_key` (module var) | `portal/server.py` | Process-wide cache of the latest Anthropic key seen by an operator-auth route. |
| `_capture_anthropic_key(key)` | `portal/server.py` | Update the cache. Empty strings are no-ops. |
| `_resolve_anthropic_key(sess)` | `portal/server.py` | Best-known key for a station-turn callsite: cache → session snapshot → "". |
| (refresh hooks) | `/portal/credentials` POST, `/portal/control/start`, `/api/room/start` | Each calls `_capture_anthropic_key` after resolving the vault key. |
| (translation) | `/api/station/{join}/{station}/turn` | Catches 401 / authentication errors and returns a friendly chat message. |

## 5. Limitations

- **The cache is per-process and lost on restart.** A server restart
  must read the key from vault to repopulate. The first operator
  route after restart does that.
- **`_capture_anthropic_key("")` is a no-op.** If the operator
  deletes the key from `/portal/credentials`, the cache retains the
  prior value until the process restarts. This is intentional —
  better to keep working with the prior key than to immediately
  break every live encounter. The OPERATOR can sidestep this by
  setting the key to an obviously-invalid value (e.g. `"sk-ant-x"`),
  but the normal flow is to update to a valid key.
- **No test for the catch-401-during-turn path.** That would need
  Anthropic credentials and a real 401 response. Verified by
  inspection. The friendly "no key configured" path IS tested.
- **The first turn after room start may still use the stale
  snapshot** if the operator has NOT visited any cache-priming
  route in the same process lifetime. `/api/room/start` itself is a
  priming route, so this is essentially never an issue: the room
  start call seeds the cache.
- **ElevenLabs key path was already correct** (it has its own
  `_runtime_key` in `voices.py`). M38 only touches the Anthropic
  side. The two caches are independent — symmetric design.
- **The friendly 401 message hard-codes "/portal/credentials".** If
  the route ever moves, the message goes stale. Acceptable risk.

## 6. Test status

| Test file | Asserts | Status | Last run |
|-----------|---------|--------|----------|
| `tests/v7/test_anthropic_key_live_refresh.py::test_room_start_400s_when_no_anthropic_key_in_vault` | Missing vault key → 400 with `/portal/credentials` hint | PASS | 2026-05-27 |
| `…::test_room_start_seeds_anthropic_runtime_cache` | Successful room-start seeds the cache | PASS | 2026-05-27 |
| `…::test_credentials_post_refreshes_anthropic_runtime_cache` | `/portal/credentials` update refreshes the cache live | PASS | 2026-05-27 |
| `…::test_resolve_anthropic_key_prefers_runtime_cache_over_snapshot` | Cache wins when both are set | PASS | 2026-05-27 |
| `…::test_resolve_anthropic_key_falls_back_to_session_snapshot` | Empty cache falls back to snapshot | PASS | 2026-05-27 |
| `…::test_capture_does_not_overwrite_cache_with_empty` | Empty `_capture_anthropic_key("")` is a no-op | PASS | 2026-05-27 |
| `…::test_station_turn_returns_friendly_message_when_no_key` | Empty cache + empty snapshot → friendly 200 JSON, not a raise | PASS | 2026-05-27 |
| **Full v7 suite** | **250 passed, 1 skipped** (M20 Playwright skip — unchanged) | PASS | 2026-05-27 |

## 7. Change list

| Date | Author | Change | Files |
|------|--------|--------|-------|
| 2026-05-27 | claude-code | Initial M38 implementation: process-wide Anthropic key cache + 3 refresh hooks + fail-fast room start + friendly 401 in station turn; 7 new tests | `portal/server.py`, `tests/v7/test_anthropic_key_live_refresh.py` (new) |

## 8. Open questions / known issues

- **Should the operator turn route also use `_resolve_anthropic_key`?**
  It currently does the right thing in a slightly different way:
  `live_key = vault.get("ANTHROPIC_API_KEY") or sess.api_key`. Since
  the operator route has vault access, it can read fresh on every
  call — no need for the cache there. Acceptable redundancy.
- **Cache invalidation when the key is deleted.** Currently we
  preserve the old cached value. If the operator wants to FORCE all
  live encounters to fail (e.g. wind down a classroom), they need
  to restart the process. A future M39 could add an explicit
  "purge cache" route gated behind require_instructor.
- **The friendly message in `/api/station/.../turn` checks
  substrings like "401", "invalid x-api-key", "authentication".**
  If Anthropic changes the wording, the friendly translation
  silently degrades to the generic `"Turn failed: …"`. Tracked.
- **Validation at room start could also test the key with a
  cheap probe call** (the existing `/portal/credentials/test`
  endpoint does this for the same key). Skipped here to keep
  `/api/room/start` latency low — the friendly station-turn 401
  is the safety net.

---

*Render this guide to PDF with `python docs/module_guides/render_pdfs.py`.*
