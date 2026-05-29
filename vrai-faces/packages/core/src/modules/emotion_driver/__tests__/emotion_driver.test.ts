import { describe, it, expect } from 'vitest';
import { emotionDriver } from '../index';

describe('emotion_driver (local lexicon)', () => {
  it('returns neutral when no affective cues are present', async () => {
    const out = await emotionDriver.inferBaseline({
      text: 'Tell me about your symptoms.',
      characterId: 'patient-001',
    });
    expect(out.label).toBe('neutral');
    expect(out.weights).toBeTypeOf('object');
  });

  it('detects pain and emits squint + frown weights', async () => {
    const out = await emotionDriver.inferBaseline({
      text: 'It hurts so much, the pain is unbearable.',
      characterId: 'p',
    });
    expect(out.label).toBe('pain');
    expect(out.weights.eyeSquintLeft ?? 0).toBeGreaterThan(0);
    expect(out.weights.mouthFrownLeft ?? 0).toBeGreaterThan(0);
  });

  it('detects fear and emits wide-eye weights', async () => {
    const out = await emotionDriver.inferBaseline({
      text: "I'm really scared and anxious about this.",
      characterId: 'p',
    });
    expect(out.label).toBe('fear');
    expect(out.weights.eyeWideLeft ?? 0).toBeGreaterThan(0);
  });

  it('reads affect from recent context utterances too', async () => {
    const out = await emotionDriver.inferBaseline({
      text: 'Yes.',
      characterId: 'p',
      context: ['I feel so much better now, thank you'],
    });
    expect(out.label).toBe('relieved');
    expect(out.weights.mouthSmileLeft ?? 0).toBeGreaterThan(0);
  });

  it('is deterministic for the same input', async () => {
    const input = { text: 'the throbbing ache is back', characterId: 'p' };
    const a = await emotionDriver.inferBaseline(input);
    const b = await emotionDriver.inferBaseline(input);
    expect(a).toEqual(b);
  });
});
