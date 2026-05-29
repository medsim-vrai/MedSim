# animation_runtime

## Purpose
The 60 Hz tick. Sums viseme + emotion + idle weights, clamps, and writes
to `mesh.morphTargetInfluences`. Owns the rAF loop (or the OffscreenCanvas
worker tick if available).

## Public contract
See `src/types/animation_runtime.ts`. Barrel: `animationRuntime`.

## Dependencies
- `three`
- `idle_motion` (sampled additively in the tick)
- `@contracts/*`

## Gotchas
- HOT LOOP — see Claude Code Guide §3.1. No `new`, no closures, no array
  literals per frame. Pre-allocate `Float32Array(52)` buffers at boot.
- `pushVisemes` accepts pre-time-stamped frames; the tick interpolates,
  it does not resample.
- Pause must NOT release buffers — only stop the tick. Buffers are
  released in `dispose()`.
- Emotion has THREE weight sets: `emotion` is the cross-fade TARGET (the
  only one `snapshot()` persists), `emotionCurrent` is what each tick
  actually applies, and `emotionFrom` is the applied set frozen when a
  fade starts. `setEmotion(weights, easeMs)` with `easeMs > 0` cross-fades
  `emotionCurrent → emotion` over `easeMs` (smoothstep eased); `easeMs ≤ 0`
  (or omitted) snaps. `restore()` lands on the target instantly — a restore
  is not a fade.
- The fade is anchored to the renderer clock on its FIRST tick (not at
  `setEmotion` time), so `easeMs` maps to wall-clock and a paused tick can't
  burn the fade. `blendEmotion` is allocation-free (mutates `emotionCurrent`
  in place) and prunes keys that reach 0 to keep the applied set sparse.

## Tests
`__tests__/animation_runtime.test.ts` — snapshot/restore round-trip is
asserted (the smoke test for ADR-0017); diag fps/lastTickMs reporting is
asserted past the REPORT_EVERY boundary; the emotion cross-fade is covered
by pure-helper unit tests (`smoothstep`, `blendEmotion`) plus an integration
test that eases a fake mesh's `mouthSmileLeft` 0 → 0.2 → 0.4 across a 200 ms
window (idle motion only touches eye shapes, so index 0 stays clean).
