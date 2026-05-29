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
- JSON schema is validated by Zod at the seam — malformed LLM output
  is dropped, not coerced.
- Cache by `(characterId, text)` hash — speech often repeats lines
  during a scenario.
- Stub currently returns `{label: 'neutral', weights: {}}` so the
  runtime path is exercisable. Replace before any user-visible build.

## Tests
`__tests__/emotion_driver.test.ts` — barrel + stub returns neutral.
