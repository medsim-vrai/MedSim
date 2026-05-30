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
  LAUNCH by the portal: `GET {api}/api/face/{id}/binding` inlines a `data:` URI
  under `sourcePhoto` (`portal/vrai_faces.py`, ADR-0022) — consented local file or
  a neutral placeholder. The bind doc also carries `speechWsUrl` + `ghostColor`.
  Live mood is owned by `emotion_driver`.
- Speech arrives as text+emotion only (no audio bytes — ADR-0023); the tablet
  synthesizes locally (Kokoro). The portal's `POST /api/face/{id}/speak` /
  `push_speech` emit those frames over `WS /ws/face/{scenario}/{id}`.
- Transport is chosen per binding: `speechWsUrl` set → WebSocket (cross-app,
  ADR-0007) with auto-reconnect; else BroadcastChannel (same-origin). WS carries
  JSON text frames; the seq-dedup defends against reconnect replays. A `WsLike`
  factory is injectable for tests (`createImpl({ wsFactory })`).
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
