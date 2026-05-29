# memory_state

## Purpose
Owns the pause / resume persistence layer per ADR-0017. Other modules
register `SnapshotHooks`; `pauseAll()` snapshots every registered module
and writes one aggregate `SessionState` to IndexedDB. `resumeAll()`
restores from disk and calls each module's `resume()`.

## Public contract
See `src/types/memory_state.ts`. Barrel: `memoryState`.

## Dependencies
- `@contracts/*`
- IndexedDB (browser native — no library)

## Gotchas
- NEVER store PHI free-text — only structured runtime state.
- Snapshots MUST be structured-clone-safe (no class instances with
  methods, no closures, no DOM refs).
- Pause is async per module and must complete before the next module is
  paused — order matters. Resume is the reverse.
- If IndexedDB is unavailable (private mode, quota), fall back to a
  memory-only persistence stub and log a `vrai:error` event.

## Tests
`__tests__/memory_state.test.ts` — barrel shape only at unit level; the
real round-trip lives in `test/e2e/pause-resume.spec.ts`.
