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
- ADR-0015 viseme gating IS wired: `setVisemeSource('native')` suppresses the
  derived energy→`jawOpen` bridge (so provider-native visemes aren't doubled);
  `'derived'` (default) runs it. The consumer of `tts_provider.speak()` sets it
  per utterance from whether `TtsChunk.visemes` is present.

## Tests
`__tests__/audio_pipeline.test.ts` — barrel; prime/enqueue ordering (ADR-0008);
no-AudioContext state degrade + snapshot/restore; and ADR-0015 viseme-source
gating (default derived, native/derived round-trips, callable pre-prime). The
real audio graph + energy bridge are browser-gated.
