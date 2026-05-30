import { describe, it, expect } from 'vitest';
import { ttsProvider } from '../index';
import { BAA_PROVIDERS, pickProvider, resolveChain, createImpl } from '../impl/create';
import type { TtsTier, TtsRequest, TtsChunk } from '@contracts/tts_provider';
import type { BootDeps, DiagHandle, TimelineEvent, TtsVoiceId } from '@contracts/shared';

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

describe('tts_provider.speak (synthetic stand-in)', () => {
  // tier 'primary' → azure-hd-v2 has no real engine yet, so it serves the synthetic
  // stand-in. ('local' is now Kokoro-only — browser-gated — per ADR-0021.)
  const REQ: TtsRequest = {
    tier: 'primary',
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

describe('tts_provider failover state machine (ADR-0013)', () => {
  function fakeDeps(): { deps: BootDeps; events: TimelineEvent[] } {
    const events: TimelineEvent[] = [];
    const diag: DiagHandle = { push(e) { events.push(e); }, set() { /* stats not under test */ } };
    return { deps: { diag, scenarioId: 'scn', characterId: 'chr' }, events };
  }
  const okChunk: TtsChunk = { audio: new Int16Array([7, 7, 7]).buffer, audioFormat: 'pcm16-24k', endOfUtterance: true };
  async function* okSynth(): AsyncGenerator<TtsChunk> { yield okChunk; }
  async function* failSynth(): AsyncGenerator<TtsChunk> { throw new Error('provider down'); }
  async function drain(stream: AsyncIterable<TtsChunk>): Promise<TtsChunk[]> {
    const out: TtsChunk[] = [];
    for await (const c of stream) out.push(c);
    return out;
  }
  const req = (tier: TtsTier): TtsRequest => ({ tier, source: 'scripted', text: 'hi', voice: VOICE });

  it('hops to the next provider on failure and surfaces the hop to diag', async () => {
    const { deps, events } = fakeDeps();
    const tts = createImpl({ synths: { 'azure-hd-v2': failSynth, 'headtts-kokoro': okSynth } });
    await tts.boot(deps);
    const chunks = await drain(tts.speak(req('primary')));    // azure fails → kokoro serves
    expect(chunks.length).toBeGreaterThan(0);
    expect(events.some((e) => e.kind === 'warn' && /failover: azure-hd-v2 → headtts-kokoro/.test(e.message))).toBe(true);
    tts.dispose();
  });

  it('locks to local after two consecutive cloud failures', async () => {
    const { deps, events } = fakeDeps();
    // hero chain = [elevenlabs-v3, azure-hd-v2, headtts-kokoro]; both cloud providers fail.
    const tts = createImpl({ synths: { 'elevenlabs-v3': failSynth, 'azure-hd-v2': failSynth, 'headtts-kokoro': okSynth } });
    await tts.boot(deps);
    const chunks = await drain(tts.speak(req('hero')));
    expect(chunks.length).toBeGreaterThan(0);                 // fell through to local
    expect(tts.activeProvider('primary')).toBe('headtts-kokoro');   // locked → local head
    expect(events.some((e) => e.kind === 'error' && /locked to local/.test(e.message))).toBe(true);
    tts.dispose();
  });

  it('once locked, a later request skips cloud entirely', async () => {
    const { deps } = fakeDeps();
    let azureCalls = 0;
    async function* azureSpy(): AsyncGenerator<TtsChunk> { azureCalls++; throw new Error('down'); }
    const tts = createImpl({ synths: { 'elevenlabs-v3': failSynth, 'azure-hd-v2': azureSpy, 'headtts-kokoro': okSynth } });
    await tts.boot(deps);
    await drain(tts.speak(req('hero')));        // elevenlabs + azure fail → lock
    const callsAfterLock = azureCalls;
    await drain(tts.speak(req('primary')));     // locked → local chain, azure not consulted
    expect(azureCalls).toBe(callsAfterLock);
    tts.dispose();
  });

  it('throws if every provider in the chain fails', async () => {
    const { deps } = fakeDeps();
    const tts = createImpl({ synths: { 'headtts-kokoro': failSynth } });   // local = [kokoro] only (ADR-0021)
    await tts.boot(deps);
    await expect(drain(tts.speak(req('local')))).rejects.toThrow(/all providers failed/);
    tts.dispose();
  });

  it('keeps the PHI filter under failover (non-BAA providers excluded)', () => {
    // cartesia-sonic-3 is NOT in the BAA pool → excluded for trainee_input.
    const chain = resolveChain({ tier: 'conversational', source: 'trainee_input', text: 'x', voice: VOICE }, false);
    expect(chain).not.toContain('cartesia-sonic-3');
    expect(chain.every((p) => BAA_PROVIDERS.has(p))).toBe(true);
  });
});
