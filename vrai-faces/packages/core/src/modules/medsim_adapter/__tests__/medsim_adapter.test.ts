import { describe, it, expect } from 'vitest';
import { medsimAdapter } from '../index';
import { parseFrame } from '../impl/parse';
import { parseCharacterCard, voiceIdFromProfile } from '../impl/medsim_character';

describe('medsim_adapter parseFrame', () => {
  it('accepts a minimal valid frame', () => {
    const f = parseFrame({ v: 1, characterId: 'c1', seq: 1 });
    expect(f).not.toBeNull();
    expect(f?.characterId).toBe('c1');
  });

  it('rejects a frame with wrong version', () => {
    expect(parseFrame({ v: 2, characterId: 'c1', seq: 1 })).toBeNull();
  });

  it('rejects a viseme weight out of range', () => {
    expect(
      parseFrame({
        v: 1, characterId: 'c1', seq: 1,
        visemes: [{ t: 0, id: 'jawOpen', w: 1.5 }],
      }),
    ).toBeNull();
  });
});

describe('medsim_adapter barrel', () => {
  it('exposes the expected surface', () => {
    expect(typeof medsimAdapter.boot).toBe('function');
    expect(typeof medsimAdapter.onSpeechFrame).toBe('function');
    expect(typeof medsimAdapter.transport).toBe('function');
  });
});

describe('medsim_adapter bindFromCharacter', () => {
  // Tiny stand-in portrait (a data: URI is decoded locally — no network, no PHI
  // egress). These tests never boot(), so no BroadcastChannel is opened.
  const PORTRAIT = 'data:image/png;base64,aGVsbG8=';

  it('parses a full payload into a binding', async () => {
    const b = await medsimAdapter.bindFromCharacter({
      characterId: 'patient-007',
      sourcePhoto: PORTRAIT,
      voiceProfile: 'en-US-warm',
      opacityLevel: 1.4,                                   // out of range → clamps to 1
      baselineMood: { mouthSmileLeft: 2, browInnerUp: 0.3 }, // 2 clamps to 1
    });
    expect(b.characterId).toBe('patient-007');
    expect(b.sourcePhoto).toBeInstanceOf(Blob);
    expect(b.voiceProfile as string).toBe('en-US-warm');
    expect(b.opacityLevel).toBe(1);
    expect(b.baselineMood.mouthSmileLeft ?? 0).toBe(1);
    expect(b.baselineMood.browInnerUp ?? 0).toBeCloseTo(0.3);
  });

  it('applies defaults for voice and opacity and accepts alt keys', async () => {
    const b = await medsimAdapter.bindFromCharacter({
      id: 'p2',          // alt key for characterId
      photo: PORTRAIT,   // alt key for the portrait
    });
    expect(b.characterId).toBe('p2');
    expect(b.opacityLevel).toBeCloseTo(0.66);
    expect(b.voiceProfile as string).toBe('default');
    expect(b.baselineMood).toEqual({});
  });

  it('rejects a payload with no characterId', async () => {
    await expect(
      medsimAdapter.bindFromCharacter({ sourcePhoto: PORTRAIT }),
    ).rejects.toThrow(/characterId/);
  });

  it('rejects a payload with no usable portrait', async () => {
    await expect(
      medsimAdapter.bindFromCharacter({ characterId: 'p3' }),
    ).rejects.toThrow(/portrait/);
  });
});

describe('medsim_adapter real character card (schemas/character.json, §9)', () => {
  const PORTRAIT = 'data:image/png;base64,aGVsbG8=';
  const REAL_CARD = {
    id: 'rn-amy', name: 'Amy', role: 'bedside RN',
    voice: { register: 'warm', sentence_length: 'medium', examples: ['Hi there.', 'How are you?', "Let's check."] },
    knowledge_boundary: 'nursing scope', scene_contract: ['no diagnosis'],
    identity: { mood_today: 'tired but kind' },
    voice_profile: { gender: 'female', language: 'en-US', voice_hints: ['Samantha'] },
  };

  it('validates a real card and rejects an incomplete one', () => {
    expect(parseCharacterCard(REAL_CARD)?.id).toBe('rn-amy');
    expect(parseCharacterCard({ id: 'x' })).toBeNull();   // missing required fields
  });

  it('maps voice_profile → a stable, gender-encoded voice id', () => {
    expect(voiceIdFromProfile({ gender: 'female', voice_hints: ['Samantha'] }) as string).toBe('female:Samantha');
    expect(voiceIdFromProfile({ gender: 'male', language: 'en-GB' }) as string).toBe('male:en-GB');
    expect(voiceIdFromProfile(undefined) as string).toBe('neutral:en-US');
  });

  it('binds a real card (+ attached portrait + ghost tint) into a binding', async () => {
    const b = await medsimAdapter.bindFromCharacter({ ...REAL_CARD, sourcePhoto: PORTRAIT, ghostColor: '#cfe8ff' });
    expect(b.characterId).toBe('rn-amy');
    expect(b.voiceProfile as string).toBe('female:Samantha');   // from voice_profile, not default
    expect(b.ghostColor).toBe('#cfe8ff');                       // per-scenario tint (decision 4)
    expect(b.baselineMood).toEqual({});                         // card has no weights; emotion_driver owns live mood
  });
});
