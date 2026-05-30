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
- The REAL MedSim card (`schemas/character.json`, §9) carries NO portrait and NO
  ARKit weights. `parseCharacterCard` (Zod) validates it; `voice_profile` → a
  gender-encoded `TtsVoiceId` the TTS layer maps to a Kokoro voice; `ghostColor`
  rides the binding (Phase 0 decision 4). The avatar's portrait is attached at
  LAUNCH (the portal merges it into the payload — Phase 4.3); live mood is owned by
  `emotion_driver`.
- WebSocket transport (cross-app tablet) is still a follow-up — BroadcastChannel
  (same-origin) is the only LIVE transport today.
- Frames are dropped fail-closed: malformed JSON → drop + log; never coerce.
- `seq` is monotonic per utterance — drop frames whose seq ≤ lastSeq to
  defend against reconnect dupes.
- The schema version (`v: 1`) is bumped only on a breaking change. Adding
  optional fields does not bump.

## Tests
`__tests__/medsim_adapter.test.ts` — parseFrame happy/error paths; tolerant
`bindFromCharacter` (synthetic payloads); and the real character card
(`parseCharacterCard` validate/reject, `voiceIdFromProfile` mapping, binding a real
card + attached portrait + `ghostColor`).
