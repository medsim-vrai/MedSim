import type {
  ProviderName,
  TtsChunk,
  TtsProviderModule,
  TtsRequest,
  TtsTier,
} from '@contracts/tts_provider';
import type { BootDeps } from '@contracts/shared';

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

export function pickProvider(req: TtsRequest): ProviderName | null {
  const chain = TIER_CHAIN[req.tier];
  // ADR-0014: trainee_input + unknown route ONLY through BAA pool.
  const filter = (p: ProviderName) =>
    req.source === 'scripted' ? true : BAA_PROVIDERS.has(p);
  return chain.find(filter) ?? null;
}

/**
 * Local synthetic voicing — a stand-in until a real provider lands.
 *
 * No real engine is wired yet: cloud tiers (azure/elevenlabs/…) need the
 * ADR-0014 BAA guardrail, and the on-device engines in the chain
 * (headtts-kokoro, piper-wasm) are WASM models not yet on the approved tools
 * sheet (each needs its own ADR). So `speak` synthesizes a placeholder voiced
 * waveform entirely on-device: a glottal-ish tone (fundamental + two
 * harmonics) under a syllabic amplitude envelope, framed as PCM16-24k. It is
 * NOT speech — but it is the right format, the right rough duration, and has
 * speech-like energy dynamics, so the audio_pipeline → viseme → jaw path is
 * exercisable end-to-end. PHI-safe by construction: the text never leaves the
 * device; it only seeds pitch and sizes the clip (a one-way hash, not stored).
 * Swapping in a real provider is contract-preserving — only this body changes.
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

export function createImpl(): TtsProviderModule {
  let _deps: BootDeps | null = null;
  return {
    async boot(deps) { _deps = deps; },
    dispose() { _deps = null; },

    async warmup() { /* local synth — nothing to load; a WASM engine would warm here */ },

    speak(req: TtsRequest): AsyncIterable<TtsChunk> {
      void _deps;
      return synthVoice(req);
    },

    activeProvider(tier: TtsTier): ProviderName | null {
      return TIER_CHAIN[tier][0] ?? null;
    },
  };
}
