# medsim_adapter

## Purpose
The ONLY module that knows about MedSim. Reads scenario character records
(read-only) and owns the speech interop channel — BroadcastChannel for
same-origin, WebSocket for cross-app on a tablet. Memory_management.MD
§6 is the contract.

## Public contract
See `src/types/medsim_adapter.ts`. Barrel: `medsimAdapter`.

## Dependencies
- `@contracts/*`
- `zod` for wire validation
- Browser BroadcastChannel + WebSocket — both built-in.

## Gotchas
- MedSim scenario files MUST be read-only. Mutations are a contract break.
- Frames are dropped fail-closed: malformed JSON → drop + log; never coerce.
- `seq` is monotonic per utterance — drop frames whose seq ≤ lastSeq to
  defend against reconnect dupes.
- The schema version (`v: 1`) is bumped only on a breaking change. Adding
  optional fields does not bump.

## Tests
`__tests__/medsim_adapter.test.ts` — parseFrame happy + error paths.
