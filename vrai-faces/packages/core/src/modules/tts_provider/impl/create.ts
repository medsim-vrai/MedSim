import type {
  ProviderName,
  TtsChunk,
  TtsProviderModule,
  TtsRequest,
  TtsTier,
} from '@contracts/tts_provider';
import type { BootDeps } from '@contracts/shared';
import { kokoroSynth } from './local_engine';

/**
 * Tier → ordered provider chain (ADR-0011..0015).
 * The router walks the chain on failure; chain hops are silent to UI but
 * always surfaced to diagnostic_panel + telemetry (ADR-0013).
 */
export const TIER_CHAIN: Record<TtsTier, ProviderName[]> = {
  primary:        ['azure-hd-v2',     'headtts-kokoro', 'piper-wasm'],
  hero:           ['elevenlabs-v3',   'azure-hd-v2',    'headtts-kokoro'],
  conversational: ['cartesia-sonic-3','azure-hd-v2',    'headtts-kokoro'],
  local:          ['headtts-kokoro',  'piper-wasm'],
};

/** PHI-safe providers per ADR-0014 (BAA pool). */
export const BAA_PROVIDERS: ReadonlySet<ProviderName> = new Set<ProviderName>([
  'azure-hd-v2',
  'elevenlabs-v3',
  'deepgram',
  'aws-polly',
  'resemble',
  'headtts-kokoro',
  'piper-wasm',
]);

/** On-device providers — they never count toward the cloud-failure lock (ADR-0013). */
const LOCAL_PROVIDERS: ReadonlySet<ProviderName> = new Set<ProviderName>([
  'headtts-kokoro',
  'piper-wasm',
]);
function isLocalProvider(p: ProviderName): boolean { return LOCAL_PROVIDERS.has(p); }

/**
 * The providers allowed for this request, in chain order. ADR-0014: trainee_input +
 * unknown route ONLY through the BAA pool. When `lockedToLocal`, the local chain is
 * used regardless of the requested tier (ADR-0013).
 */
export function resolveChain(req: TtsRequest, lockedToLocal: boolean): ProviderName[] {
  const chain = TIER_CHAIN[lockedToLocal ? 'local' : req.tier];
  return chain.filter((p) => (req.source === 'scripted' ? true : BAA_PROVIDERS.has(p)));
}

/** First allowed provider for a request (no failover state). */
export function pickProvider(req: TtsRequest): ProviderName | null {
  return resolveChain(req, false)[0] ?? null;
}

/**
 * Local synthetic voicing — a stand-in until real engines land.
 *
 * Every provider currently uses this on-device synthetic waveform: a glottal-ish
 * tone (fundamental + two harmonics) under a syllabic amplitude envelope, framed
 * as PCM16-24k. It is NOT speech, but it is the right format/duration with
 * speech-like energy dynamics, so audio_pipeline → viseme → jaw is exercisable.
 * PHI-safe: the text never leaves the device; it only seeds pitch (a one-way hash).
 * Real engines — Kokoro/Piper (local, Phase 2.1) and Azure/etc. (cloud, v1.1) —
 * swap in per-provider via the synth map below; the failover machine is unchanged.
 */
const SAMPLE_RATE = 24000;
const FRAME_SECONDS = 0.24;               // ~240 ms streaming frames
const SECONDS_PER_CHAR = 0.06;
const MIN_SECONDS = 0.3;
const MAX_SECONDS = 8;
const SYLLABLE_HZ = 3.5;

/** djb2 string hash → unsigned 32-bit. One-way; used only for pitch variety. */
function hash32(s: string): number {
  let h = 5381;
  for (let i = 0; i < s.length; i++) h = (((h << 5) + h) ^ s.charCodeAt(i)) >>> 0;
  return h >>> 0;
}

async function* synthVoice(req: TtsRequest): AsyncGenerator<TtsChunk> {
  const seconds = Math.min(MAX_SECONDS, Math.max(MIN_SECONDS, req.text.length * SECONDS_PER_CHAR));
  const total = Math.floor(seconds * SAMPLE_RATE);
  const f0 = 90 + (hash32(`${req.voice}|${req.text}`) % 80);   // 90..169 Hz
  const frame = Math.floor(SAMPLE_RATE * FRAME_SECONDS);

  for (let off = 0; off < total; off += frame) {
    await Promise.resolve();              // yield to the loop — behave like a stream
    const n = Math.min(frame, total - off);
    const pcm = new Int16Array(n);
    for (let i = 0; i < n; i++) {
      const t = (off + i) / SAMPLE_RATE;
      const syllable = 0.5 - 0.5 * Math.cos(2 * Math.PI * SYLLABLE_HZ * t);
      const attack = Math.min(1, t / 0.05);
      const release = Math.min(1, (seconds - t) / 0.08);
      const env = 0.6 * syllable * Math.max(0, Math.min(attack, release));
      const tone =
        Math.sin(2 * Math.PI * f0 * t) +
        0.5 * Math.sin(2 * Math.PI * 2 * f0 * t) +
        0.25 * Math.sin(2 * Math.PI * 3 * f0 * t);
      const v = (tone / 1.75) * env;       // normalize partials, apply envelope
      pcm[i] = Math.round((v < -1 ? -1 : v > 1 ? 1 : v) * 32767);
    }
    yield {
      audio: pcm.buffer,
      audioFormat: 'pcm16-24k',
      endOfUtterance: off + frame >= total,
    };
  }
}

/** A per-provider synthesizer. Today all map to `synthVoice`; tests inject failures. */
type Synth = (req: TtsRequest) => AsyncIterable<TtsChunk>;

/** Real default engine per provider; the rest use the synthetic stand-in for now. */
const DEFAULT_SYNTHS: Partial<Record<ProviderName, Synth>> = {
  'headtts-kokoro': kokoroSynth,   // ADR-0020 primary local (Phase 2.1)
};

const CONSECUTIVE_CLOUD_FAILS_TO_LOCK = 2;   // ADR-0013

export function createImpl(overrides?: { synths?: Partial<Record<ProviderName, Synth>> }): TtsProviderModule {
  let _deps: BootDeps | null = null;

  // Failover state — session-scoped (ADR-0013).
  let consecutiveCloudFailures = 0;
  let lockedToLocal = false;

  const synthFor = (p: ProviderName): Synth => overrides?.synths?.[p] ?? DEFAULT_SYNTHS[p] ?? synthVoice;

  function note(kind: 'info' | 'warn' | 'error', message: string): void {
    _deps?.diag.push({ t: performance.now(), moduleId: 'tts_provider', kind, message });
  }

  function reset(): void { consecutiveCloudFailures = 0; lockedToLocal = false; }

  /**
   * Walk the request's provider chain, hopping on first-chunk failure. Each hop is
   * surfaced to diag (silent to the trainee UI per ADR-0013). Two consecutive CLOUD
   * failures lock the session to local providers. Mid-stream errors (after the first
   * chunk) propagate — failover is for provider availability, not partial outages.
   */
  async function* speakWithFailover(req: TtsRequest): AsyncGenerator<TtsChunk> {
    const chain = resolveChain(req, lockedToLocal);
    if (chain.length === 0) {
      throw new Error(`tts_provider: no allowed provider for tier ${req.tier} / source ${req.source}`);
    }

    let lastErr: unknown = null;
    for (let i = 0; i < chain.length; i++) {
      const provider = chain[i]!;
      try {
        const it = synthFor(provider)(req)[Symbol.asyncIterator]();
        const first = await it.next();                 // throws here ⇒ provider unavailable ⇒ failover
        if (!isLocalProvider(provider)) consecutiveCloudFailures = 0;  // cloud recovered
        if (!first.done) yield first.value;
        for (let n = await it.next(); !n.done; n = await it.next()) yield n.value;
        return;                                          // streamed to completion
      } catch (err) {
        lastErr = err;
        if (!isLocalProvider(provider)) {
          consecutiveCloudFailures++;
          if (consecutiveCloudFailures >= CONSECUTIVE_CLOUD_FAILS_TO_LOCK && !lockedToLocal) {
            lockedToLocal = true;
            note('error', `voice locked to local — ${consecutiveCloudFailures} consecutive cloud failures (ADR-0013)`);
          }
        }
        const next = chain[i + 1];
        if (next) note('warn', `voice failover: ${provider} → ${next}`);
      }
    }
    throw new Error(`tts_provider: all providers failed for tier ${req.tier}: ${String(lastErr)}`);
  }

  return {
    async boot(deps) { _deps = deps; reset(); },
    dispose() { _deps = null; reset(); },

    async warmup() { /* local synth — nothing to load; real engines warm here */ },

    speak(req: TtsRequest): AsyncIterable<TtsChunk> {
      return speakWithFailover(req);
    },

    activeProvider(tier: TtsTier): ProviderName | null {
      return TIER_CHAIN[lockedToLocal ? 'local' : tier][0] ?? null;
    },
  };
}
