# diagnostic_panel

## Purpose
Dev-only overlay that reads from the `diag` singleton in `perf/diag.ts`
and renders module state, timeline events, and TTS failover hops
(ADR-0013 requires every fallback hop to be visible here).

## Public contract
See `src/types/diagnostic_panel.ts`. Barrel: `diagnosticPanel`.

## Dependencies
- `@contracts/*`
- `perf/diag.ts`

## Gotchas
- Must NOT mount DOM in production. `isAvailable()` is the gate.
- Reading from `diag` should be allocation-free per frame.
- A facilitator-visible "fallback voice" banner ALSO lives here, surfaced
  when ADR-0013's two-failure lock has tripped.

## Tests
`__tests__/diagnostic_panel.test.ts` — barrel shape only.
