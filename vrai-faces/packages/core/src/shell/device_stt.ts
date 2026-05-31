// On-device push-to-talk STT (Phase 6, ADR-0026). Records mic audio and
// transcribes it ENTIRELY on the device with whisper-tiny.en via the
// already-bundled transformers.js (WebGPU, WASM fallback). Microphone audio
// NEVER leaves the device (ADR-0001 / ADR-0014) — this replaces the cloud
// Web Speech stopgap (ADR-0025).
//
// Lazy: transformers.js + the model load on first use, never at boot (kept out
// of the main bundle via dynamic import, like tts_provider + emotion_driver).
// The model is fetched once from HF then cached by transformers.js; bundling it
// local-first via setup:assets (like Kokoro) is a follow-up (ADR-0026).
//
// RB-002 caveat: every latency/WER/thermal figure in the research is
// laptop-measured — this is ship-gated on an on-device pilot (primary target:
// Android Chrome tablets; iOS Safari 26 secondary).

import { diag } from '@perf/diag';

const MODULE = 'shell.deviceStt';
const MODEL = 'onnx-community/whisper-tiny.en'; // MIT; fits the ~80 MB budget (ADR-0026)
const SAMPLE_RATE = 16000;                      // whisper input rate

// transformers.js is loosely typed; declare just the slice we call (no `any`).
type AsrPipeline = (audio: Float32Array) => Promise<unknown>;

/** Pilot metrics (ADR-0026 ship-gate): the backend actually used, the one-time
 *  model cold-load, and the last release→text latency. Nulls until measured. */
export interface DeviceSttMetrics {
  backend: string | null;     // 'webgpu' | 'wasm'
  loadMs: number | null;      // cold-load of the model (first time)
  lastMs: number | null;      // last take's release→transcript latency
  error: string | null;       // why the model failed to load (surfaced in the UI)
}

export interface DeviceSttHandle {
  /** Begin capturing mic audio (call on PTT press). No-op while already recording. */
  start(): Promise<void>;
  /** Stop capturing + transcribe the take on-device → text (call on PTT release). */
  stopAndTranscribe(): Promise<string>;
  /** True once the model has loaded (first load is lazy / may take seconds). */
  isReady(): boolean;
  /** Pilot measurements for the on-device validation (ADR-0026). */
  metrics(): DeviceSttMetrics;
  dispose(): void;
}

interface WindowAudio {
  AudioContext?: typeof AudioContext;
  webkitAudioContext?: typeof AudioContext;
}

function audioCtxCtor(): typeof AudioContext | null {
  const w = window as unknown as WindowAudio;
  return w.AudioContext ?? w.webkitAudioContext ?? null;
}

/** Pull the transcript string out of transformers.js's loosely-typed output. */
function textOf(raw: unknown): string {
  const first = Array.isArray(raw) ? raw[0] : raw;
  if (first && typeof first === 'object' && 'text' in first) {
    const t = (first as { text: unknown }).text;
    if (typeof t === 'string') return t.trim();
  }
  return '';
}

let asrPromise: Promise<AsrPipeline | null> | null = null;
// Pilot metrics (ADR-0026) — module-level since the ASR loads once per session.
let sttBackend: string | null = null;
let sttLoadMs: number | null = null;
let sttLastMs: number | null = null;
let sttError: string | null = null;

/** Lazy-load the ASR pipeline once. WebGPU first, WASM (CPU) fallback. */
async function loadAsr(): Promise<AsrPipeline | null> {
  if (!asrPromise) {
    asrPromise = (async (): Promise<AsrPipeline | null> => {
      const t0 = performance.now();
      let lastErr = '';
      try {
        const tf = await import('@huggingface/transformers');
        // Local-first runtime + model (ADR-0026), both served from OUR origin — no
        // jsdelivr and no HuggingFace at runtime (offline / PHI-contained capable):
        //  • wasmPaths    → the ORT runtime bundled at /assets/ort/ (setup:assets).
        //  • localModelPath → the whisper model bundled at /assets/models/ (q8).
        // The only onnxruntime-web wasm build is THREADED (shared memory), so the
        // page must be cross-origin isolated for SharedArrayBuffer — the portal
        // sends COOP+COEP on /face (a no-WebGPU tablet has no other backend).
        // numThreads=1 + proxy off keep the CPU path simple; WebGPU is still tried
        // first when an adapter exists. Falls back to CDN/HF if the bundles are absent.
        const wasmFlags = tf.env?.backends?.onnx?.wasm;
        if (wasmFlags) {
          wasmFlags.wasmPaths = '/assets/ort/';
          wasmFlags.numThreads = 1;
          wasmFlags.proxy = false;
        }
        tf.env.allowLocalModels = true;          // default false in-browser; enables the bundled model
        tf.env.localModelPath = '/assets/models/';
        const { pipeline } = tf;
        for (const device of ['webgpu', 'wasm'] as const) {
          try {
            const pipe = await pipeline('automatic-speech-recognition', MODEL, { device, dtype: 'q8' });
            sttBackend = device;
            sttLoadMs = Math.round(performance.now() - t0);
            sttError = null;
            diag.push({
              t: performance.now(), moduleId: MODULE, kind: 'info',
              message: `on-device STT ready (whisper-tiny.en, ${device}, cold-load ${sttLoadMs}ms)`,
            });
            return (audio: Float32Array) => pipe(audio) as Promise<unknown>;
          } catch (e) {
            lastErr = e instanceof Error ? e.message : String(e);
            diag.push({
              t: performance.now(), moduleId: MODULE, kind: 'warn',
              message: `STT ${device} init failed; trying next backend`, data: lastErr,
            });
          }
        }
        sttError = lastErr || 'no STT backend available';
        return null;
      } catch (e) {
        sttError = e instanceof Error ? e.message : String(e);
        diag.push({
          t: performance.now(), moduleId: MODULE, kind: 'error',
          message: 'transformers.js load failed', data: sttError,
        });
        return null;
      }
    })();
  }
  return asrPromise;
}

/** Resample/downmix an AudioBuffer to 16 kHz mono Float32 (whisper input). */
async function to16kMono(buf: AudioBuffer): Promise<Float32Array> {
  if (buf.sampleRate === SAMPLE_RATE && buf.numberOfChannels === 1) {
    return buf.getChannelData(0).slice();
  }
  const frames = Math.max(1, Math.ceil(buf.duration * SAMPLE_RATE));
  const off = new OfflineAudioContext(1, frames, SAMPLE_RATE);
  const src = off.createBufferSource();
  src.buffer = buf;
  src.connect(off.destination);
  src.start();
  const rendered = await off.startRendering();
  return rendered.getChannelData(0).slice();
}

export function createDeviceStt(): DeviceSttHandle {
  let stream: MediaStream | null = null;
  let recorder: MediaRecorder | null = null;
  let chunks: Blob[] = [];
  let ready = false;

  // Warm the model in the background so the first PTT release isn't blocked on
  // the full model download.
  void loadAsr().then((a) => { ready = a !== null; });

  return {
    isReady: () => ready,
    metrics: (): DeviceSttMetrics => ({
      backend: sttBackend, loadMs: sttLoadMs, lastMs: sttLastMs, error: sttError,
    }),

    async start(): Promise<void> {
      if (recorder && recorder.state === 'recording') return;
      stream = await navigator.mediaDevices.getUserMedia({ audio: true });
      chunks = [];
      recorder = new MediaRecorder(stream);
      recorder.ondataavailable = (e: BlobEvent) => { if (e.data.size > 0) chunks.push(e.data); };
      recorder.start();
    },

    async stopAndTranscribe(): Promise<string> {
      const rec = recorder;
      if (!rec) return '';
      const t0 = performance.now(); // release → transcript latency (ADR-0026 pilot)
      const stopped = new Promise<void>((resolve) => { rec.onstop = () => resolve(); });
      if (rec.state !== 'inactive') rec.stop();
      await stopped;
      // Release the mic at once (privacy + battery).
      stream?.getTracks().forEach((t) => t.stop());
      stream = null;
      recorder = null;

      const type = chunks[0]?.type || 'audio/webm';
      const blob = new Blob(chunks, { type });
      chunks = [];
      if (blob.size === 0) return '';

      const Ctor = audioCtxCtor();
      const asr = await loadAsr();
      if (!Ctor || !asr) return '';
      const ctx = new Ctor();
      try {
        const decoded = await ctx.decodeAudioData(await blob.arrayBuffer());
        const audio = await to16kMono(decoded);
        const text = textOf(await asr(audio));
        sttLastMs = Math.round(performance.now() - t0);
        return text;
      } catch (e) {
        diag.push({
          t: performance.now(), moduleId: MODULE, kind: 'error',
          message: 'on-device transcription failed', data: e instanceof Error ? e.message : String(e),
        });
        return '';
      } finally {
        void ctx.close();
      }
    },

    dispose(): void {
      try { if (recorder && recorder.state !== 'inactive') recorder.stop(); } catch { /* noop */ }
      stream?.getTracks().forEach((t) => t.stop());
      stream = null;
      recorder = null;
      chunks = [];
    },
  };
}
