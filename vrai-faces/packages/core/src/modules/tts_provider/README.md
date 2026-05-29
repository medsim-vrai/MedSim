# tts_provider

## Purpose
Pluggable TTS layer. Implements the tier→provider routing and failover
chain from ADR-0011..0015. Enforces the PHI guardrail (ADR-0014): only
BAA-covered providers ever receive trainee free-text.

## Public contract
See `src/types/tts_provider.ts`. Barrel: `ttsProvider`.

## Dependencies
- `@contracts/*`
- Provider SDKs (Azure Speech, ElevenLabs, Cartesia, HeadTTS, Piper) —
  each in its own sub-impl file, dynamically imported.

## Gotchas
- Source classification is fail-CLOSED. If `source: 'unknown'`, route as
  if it were trainee_input.
- Two consecutive cloud failures during a scenario lock voice to local
  for the rest of the scenario (ADR-0013).
- `activeProvider()` reports what WOULD be used; the actual provider for
  a specific request can shift on failure.

## Tests
`__tests__/tts_provider.test.ts` — `pickProvider` matrix: every tier ×
every source MUST resolve to a provider in the BAA pool when source is
not `scripted`.
