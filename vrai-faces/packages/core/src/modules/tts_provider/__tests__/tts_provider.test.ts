import { describe, it, expect } from 'vitest';
import { ttsProvider } from '../index';
import { BAA_PROVIDERS, pickProvider } from '../impl/create';
import type { TtsTier, TtsRequest, TtsChunk } from '@contracts/tts_provider';
import type { TtsVoiceId } from '@contracts/shared';

const VOICE = 'voice-x' as TtsVoiceId;
const TIERS: TtsTier[] = ['primary', 'hero', 'conversational', 'local'];

describe('tts_provider barrel', () => {
  it('reports an active provider for every tier', () => {
    for (const tier of TIERS) {
      expect(ttsProvider.activeProvider(tier)).toBeTruthy();
    }
  });
});

describe('pickProvider PHI guardrail (ADR-0014)', () => {
  it('trainee_input and unknown route ONLY to BAA pool', () => {
    for (const tier of TIERS) {
      for (const source of ['trainee_input', 'unknown'] as const) {
        const req: TtsRequest = { tier, source, text: 'x', voice: VOICE };
        const picked = pickProvider(req);
        expect(picked).not.toBeNull();
        expect(BAA_PROVIDERS.has(picked!)).toBe(true);
      }
    }
  });
});

describe('tts_provider.speak (local synthetic stand-in)', () => {
  const REQ: TtsRequest = {
    tier: 'local',
    source: 'scripted',
    text: 'Hello there, how are you feeling today?',
    voice: VOICE,
  };

  const collect = async (): Promise<TtsChunk[]> => {
    const out: TtsChunk[] = [];
    for await (const c of ttsProvider.speak(REQ)) out.push(c);
    return out;
  };

  it('streams pcm16-24k chunks and ends with endOfUtterance', async () => {
    const chunks = await collect();
    expect(chunks.length).toBeGreaterThan(0);
    expect(chunks.every((c) => c.audioFormat === 'pcm16-24k')).toBe(true);
    expect(chunks.some((c) => c.audio.byteLength > 0)).toBe(true);
    expect(chunks[chunks.length - 1]!.endOfUtterance).toBe(true);
    // exactly one end-of-utterance marker
    expect(chunks.filter((c) => c.endOfUtterance).length).toBe(1);
  });

  it('is deterministic for the same request', async () => {
    const a = await collect();
    const b = await collect();
    expect(new Int16Array(a[0]!.audio)).toEqual(new Int16Array(b[0]!.audio));
  });
});
