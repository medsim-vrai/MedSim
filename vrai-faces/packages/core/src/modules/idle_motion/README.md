# idle_motion

## Purpose
Deterministic life — blink, micro-saccade, slow sway. Same seed yields
the same idle sequence so the soak fixture is reproducible.

## Public contract
See `src/types/idle_motion.ts`. Barrel: `idleMotion`.

## Dependencies
- `@contracts/*` only. Pure module.

## Gotchas
- `sample()` MUST be additive into the provided `out` weights — never
  overwrite. The runtime mixes idle on top of viseme + emotion.
- Use the local PRNG (mulberry32), not `Math.random()`. Determinism
  matters for tests.

## Tests
`__tests__/idle_motion.test.ts` — same seed produces same sequence.
