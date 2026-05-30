# tts_provider

## Purpose
Pluggable TTS layer. Implements the tier→provider routing and failover
chain from ADR-0011..0015. Enforces the PHI guardrail (ADR-0014): only
BAA-covered providers ever receive trainee free-text.

## Public contract
See `src/types/tts_provider.ts`. Barrel: `ttsProvider`.

## Dependencies
- `@contracts/*`
- `kokoro-js` + `@huggingface/transformers` (onnxruntime-web) — the real
  `headtts-kokoro` engine (`impl/local_engine.ts`), dynamically imported (own
  code-split chunk), browser-only. Node smoke confirms q8 → 24 kHz audio.
- Cloud providers (Azure/ElevenLabs/Cartesia) still use the synthetic stand-in until
  v1.1. Piper was DROPPED (ADR-0021) — Kokoro on onnxruntime-web's WASM/CPU backend is
  the local floor (it falls back to `device:'wasm'` when WebGPU is absent), so a second
  CPU engine isn't needed. `DEFAULT_SYNTHS` picks the real engine per provider; the rest
  fall back to `synthVoice`.

## Gotchas
- Source classification is fail-CLOSED. If `source: 'unknown'`, route as
  if it were trainee_input.
- LOCAL-FIRST (ADR-0001): kokoro-js@1.2.1 hardcodes the browser model+voice URLs to
  huggingface.co; `public/kokoro-sw.js` (registered before load) intercepts them and
  serves the bundled `/assets/kokoro/` copies. Run `pnpm run setup:assets` to populate
  (~96 MB, git-ignored). The onnx WASM bundles via vite. On a missing SW/file it falls
  back to the HF network; on total failure the chain uses the synth stand-in. (Browser
  interception is QA-pending; the engine itself is Node-verified.)
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
