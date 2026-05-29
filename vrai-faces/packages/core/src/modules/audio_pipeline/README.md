# audio_pipeline

## Purpose
Owns the AudioWorklet ring buffer and the derived-viseme bridge
(HeadAudio). The ONLY acceptable audio path — never schedule audio from
`setTimeout` or `rAF` (Claude Code Guide §3.4).

## Public contract
See `src/types/audio_pipeline.ts`. Barrel: `audioPipeline`.

## Dependencies
- `@contracts/*`
- AudioWorklet (browser native) + HeadAudio bridge for derived visemes
- `tts_provider` indirectly via `enqueueAudio()`

## Gotchas
- `primeOnUserGesture()` MUST be called from a real user gesture or iOS
  Safari emits silence forever (ADR-0008). The Playwright iOS test
  enforces this.
- Backpressure policy is "drop oldest, never block" (Code Guide §3.5).
- If the active TTS provider emits native visemes, the bridge should be
  disabled to avoid double-counting (ADR-0015).

## Tests
`__tests__/audio_pipeline.test.ts` — barrel + prime/enqueue ordering.
