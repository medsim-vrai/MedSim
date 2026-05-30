# tts_provider

## Purpose
Pluggable TTS layer. Implements the tier→provider routing and failover
chain from ADR-0011..0015. Enforces the PHI guardrail (ADR-0014): only
BAA-covered providers ever receive trainee free-text.

## Public contract
See `src/types/tts_provider.ts`. Barrel: `ttsProvider`.

## Dependencies
- `@contracts/*`
- Provider engines swap in per-provider via the `synths` map: Kokoro/Piper
  (local — Phase 2.1) and Azure/ElevenLabs/Cartesia (cloud — v1.1). TODAY every
  provider uses the on-device synthetic stand-in, so failover never fires in
  production yet (the state machine + tests use injected failing providers).

## Gotchas
- Source classification is fail-CLOSED. If `source: 'unknown'`, route as
  if it were trainee_input.
- The failover state machine (`speak`) walks the request's chain, hopping on
  first-chunk failure. Two consecutive CLOUD failures lock voice to local for
  the rest of the session (ADR-0013); local failures just hop.
- Chain hops are SILENT to the trainee UI but surfaced to diagnostic_panel
  (warn = hop, error = locked-to-local) — provider names only, PHI-safe.
- `activeProvider()` reports what WOULD be used; the actual provider for a
  specific request can shift on failure (and reflects the local lock).

## Tests
`__tests__/tts_provider.test.ts` — `pickProvider`/`resolveChain` PHI matrix
(non-`scripted` resolves only to BAA providers; cartesia excluded for trainee
input); synthetic-stream format + determinism; and the ADR-0013 failover state
machine via injected synths (hop-on-failure + diag surfacing, lock after two
consecutive cloud failures, locked requests skip cloud, all-fail throws).
