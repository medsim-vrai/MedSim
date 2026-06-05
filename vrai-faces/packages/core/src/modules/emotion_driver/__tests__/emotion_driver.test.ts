import { describe, it, expect } from 'vitest';
import { emotionDriver } from '../index';
import { moodForLabel, topLabel } from '../impl/create';

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

describe('emotion_driver hybrid (ADR-0019: model mapping + clinical override)', () => {
  it('maps model emotion labels onto moods (Ekman + GoEmotions)', () => {
    expect(moodForLabel('joy')?.label).toBe('relieved');
    expect(moodForLabel('sadness')?.label).toBe('sad');
    expect(moodForLabel('anger')?.label).toBe('anger');
    expect(moodForLabel('fear')?.label).toBe('fear');
    expect(moodForLabel('gratitude')?.label).toBe('relieved'); // GoEmotions vocab
    expect(moodForLabel('JOY')?.label).toBe('relieved');       // case-insensitive
    expect(moodForLabel('neutral')).toBeNull();
    expect(moodForLabel('curiosity')).toBeNull();              // unmapped → neutral
  });

  it('extracts the top label from transformers.js output shapes', () => {
    expect(topLabel([{ label: 'joy', score: 0.9 }])).toBe('joy'); // array form
    expect(topLabel({ label: 'fear', score: 0.8 })).toBe('fear'); // single object
    expect(topLabel([])).toBeNull();
    expect(topLabel(null)).toBeNull();
    expect(topLabel({ score: 0.5 })).toBeNull();                  // no label field
  });

  it('clinical affect (drowsy) overrides the general lexicon', async () => {
    const out = await emotionDriver.inferBaseline({
      text: 'I feel so dizzy and lightheaded, but also really happy.',
      characterId: 'p',
    });
    // pain/drowsy are clinical → they win over the general "happy"/relieved cue.
    expect(out.label).toBe('drowsy');
    // PERCLOS drowsiness drives sustained lid closure (eyesClosed / AU43), not blink.
    expect(out.weights.eyesClosed ?? 0).toBeGreaterThan(0);
  });
});
