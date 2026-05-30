import type { KokoroTTS } from 'kokoro-js';
import type { TtsChunk, TtsRequest } from '@contracts/tts_provider';

/**
 * Kokoro on-device TTS (ADR-0020 primary local engine), wired as the
 * `headtts-kokoro` synth in the failover chain. Browser-only: kokoro-js runs on
 * onnxruntime-web (WASM/WebGPU), so this bails in jsdom/Node and the failover
 * machine drops to the next provider. The engine is verified (Node smoke: q8 →
 * 24 kHz audio); this is the browser path.
 *
 * Loaded via a DYNAMIC import so kokoro-js + @huggingface/transformers +
 * onnxruntime-web land in their own code-split chunk, never the main bundle or
 * the test graph.
 *
 * LOCAL-FIRST CAVEAT (ADR-0001): kokoro-js@1.2.1 hardcodes the browser voice URL
 * to huggingface.co (`/voices/<id>.bin`, Cache-API cached); the model itself can be
 * bundled, but voices currently fetch from HF on first use. Full offline operation
 * needs a voice-URL fix (lib patch / service-worker intercept / cache-prime) —
 * tracked as Phase 2.1 follow-up.
 */

const MODEL_ID = 'onnx-community/Kokoro-82M-v1.0-ONNX';

/**
 * Curated Kokoro voices (Phase 0: balanced set). Persona voice ids map onto these
 * deterministically. All names are real kokoro-js voice keys (the type-checker
 * enforces this against `GenerateOptions.voice`).
 */
const KOKORO_VOICES = [
  'af_heart', 'af_bella', 'af_nicole', 'af_sarah', 'af_sky', 'af_nova', 'am_adam', 'bf_emma',
] as const;

function hash32(s: string): number {
  let h = 5381;
  for (let i = 0; i < s.length; i++) h = (((h << 5) + h) ^ s.charCodeAt(i)) >>> 0;
  return h >>> 0;
}

function mapVoice(voiceId: string): (typeof KOKORO_VOICES)[number] {
  return KOKORO_VOICES[hash32(voiceId) % KOKORO_VOICES.length] ?? 'af_heart';
}

// Lazy singleton: load the model once per session (nulled on failure so it retries).
let kokoroPromise: Promise<KokoroTTS> | null = null;
async function loadKokoro(): Promise<KokoroTTS> {
  if (!kokoroPromise) {
    kokoroPromise = (async () => {
      const { KokoroTTS } = await import('kokoro-js');
      const device = typeof navigator !== 'undefined' && 'gpu' in navigator ? 'webgpu' : 'wasm';
      return KokoroTTS.from_pretrained(MODEL_ID, { dtype: 'q8', device });
    })().catch((e: unknown) => {
      kokoroPromise = null;
      throw e;
    });
  }
  return kokoroPromise;
}

/** Float32 [-1,1] @ 24 kHz → PCM16 ArrayBuffer (our pcm16-24k chunk payload). */
function f32ToPcm16(f32: Float32Array): ArrayBuffer {
  const pcm = new Int16Array(f32.length);
  for (let i = 0; i < f32.length; i++) {
    const s = f32[i] ?? 0;
    pcm[i] = Math.round((s < -1 ? -1 : s > 1 ? 1 : s) * 32767);
  }
  return pcm.buffer;
}

/**
 * Stream Kokoro audio as pcm16-24k chunks. Kokoro streams per sentence; we relay
 * each as a chunk and mark the final one `endOfUtterance`. Throws in non-browser
 * envs or on load failure so `tts_provider` fails over to the next chain entry.
 */
export async function* kokoroSynth(req: TtsRequest): AsyncGenerator<TtsChunk> {
  if (typeof AudioContext === 'undefined') {
    throw new Error('kokoro: non-browser env (no AudioContext)');   // → failover
  }
  const tts = await loadKokoro();
  const voice = mapVoice(req.voice);

  // One-ahead buffer so the last chunk carries endOfUtterance.
  let pending: ArrayBuffer | null = null;
  for await (const part of tts.stream(req.text, { voice })) {
    if (pending) yield { audio: pending, audioFormat: 'pcm16-24k', endOfUtterance: false };
    pending = f32ToPcm16(part.audio.audio);
  }
  yield { audio: pending ?? new ArrayBuffer(0), audioFormat: 'pcm16-24k', endOfUtterance: true };
}
