# emotion_driver

## Purpose
LLM-driven baseline mood. Given an utterance + scenario context, returns
ARKit-52 weight JSON (ADR-0005 — never free text). Runs locally via
transformers.js by default; cloud Claude allowed if scenario opts in.

## Public contract
See `src/types/emotion_driver.ts`. Barrel: `emotionDriver`.

## Dependencies
- `@contracts/*`
- `@huggingface/transformers` (lazy, code-split)
- Anthropic SDK (optional, scenario opt-in)

## Gotchas
- HYBRID (ADR-0019): clinical affects (pain/drowsy) are detected by the lexicon and
  OVERRIDE the model (general emotion models have no such label); general affect
  comes from the transformers.js model; the full lexicon is the fallback.
- The model loads in `warmup()` ONLY (never lazily in `inferBaseline`), so unit
  tests + non-browser envs run the deterministic lexicon path. `@huggingface/
  transformers` is dynamically imported (own chunk), out of the test graph.
- Output is always `{label, weights}` JSON, never free text (ADR-0005).
- Model = `SamLowe/roberta-base-go_emotions-onnx` (q8); bundled local-first via
  `setup:assets` + transformers env (Phase 3 — see ROADMAP). Cloud Claude stays a
  v1.1 opt-in behind the ADR-0014 PHI guardrail.

## Tests
`__tests__/emotion_driver.test.ts` — lexicon detection (pain/fear/relieved/drowsy,
context, determinism, neutral) + hybrid logic (`moodForLabel` Ekman/GoEmotions→mood,
`topLabel` output-shape extraction, clinical override beats the general cue). The
live model inference path is browser/Node-gated.
