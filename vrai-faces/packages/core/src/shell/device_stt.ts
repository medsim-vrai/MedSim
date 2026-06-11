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
import { derror } from './debug';

const MODULE = 'shell.deviceStt';
const MODEL = 'onnx-community/whisper-tiny.en'; // MIT; fits the ~80 MB budget (ADR-0026)
const SAMPLE_RATE = 16000;                      // whisper input rate

// transformers.js is loosely typed; declare just the slice we call (no `any`).
type AsrPipeline = (audio: Float32Array) => Promise<unknown>;

/** Pilot metrics (ADR-0026 ship-gate): the backend actually used, the one-time
 *  model cold-load, and the last release→text latency. Nulls until measured. */
/** Per-take latency breakdown (ms) — splits the release→text time into its phases
 *  so the pilot can see where the ~2s goes (and confirm whisper inference is the
 *  dominant cost) before optimizing it (ADR-0026 latency chase). */
export interface SttStageTimings {
  recMs: number;       // PTT release → MediaRecorder.onstop flush
  decodeMs: number;    // decodeAudioData (compressed → PCM)
  resampleMs: number;  // downmix + resample to 16 kHz mono
  inferMs: number;     // whisper inference (suspected dominant cost)
  clipMs: number;      // captured clip duration (whisper pads to 30s regardless)
}

export interface DeviceSttMetrics {
  backend: string | null;     // 'webgpu' | 'wasm'
  loadMs: number | null;      // cold-load of the model (first time)
  lastMs: number | null;      // last take's release→transcript latency
  error: string | null;       // why the model failed to load (surfaced in the UI)
  lastStages: SttStageTimings | null; // breakdown of lastMs (null until a take runs)
  /** WHY the last take produced no text (null after a successful take) — turns the
   *  generic "(no speech detected)" into a diagnosable cause (FR-006 field fix). */
  emptyReason: string | null;
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
  /** Debug-only thermal-soak probe (ADR-0032, docs/OPTIMIZATION-REGISTER.md OPT-007):
   *  one inference on a fixed silent buffer → its latency (ms), -1 if not ready.
   *  Constant workload, so any rise over a long run is throttling, not input variance. */
  soakStep?(): Promise<number>;
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
let sttLastStages: SttStageTimings | null = null;
let sttEmptyReason: string | null = null;

/** FR-006 Android diagnosis: `&stt=wasm` / `&stt=webgpu` pins the ASR backend from the
 *  URL so a misbehaving WebGPU path (e.g. the fp16 encoder on an unvalidated GPU — every
 *  prior validation was the iPad) can be ruled in or out in seconds, no rebuild. */
function backendOrder(): ReadonlyArray<'webgpu' | 'wasm'> {
  if (typeof location !== 'undefined') {
    const m = (location.search + location.hash).match(/[?&#]stt=(wasm|webgpu)/);
    if (m) return [m[1] === 'wasm' ? 'wasm' : 'webgpu'];
  }
  return ['webgpu', 'wasm'];
}

/** Lazy-load the ASR pipeline once. WebGPU first, WASM (CPU) fallback (override: &stt=). */
async function loadAsr(): Promise<AsrPipeline | null> {
  if (!asrPromise) {
    asrPromise = (async (): Promise<AsrPipeline | null> => {
      const t0 = performance.now();
      let lastErr = '';
      let wasmErr = '';
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
          wasmFlags.numThreads = 1;
          wasmFlags.proxy = false;
        }
        tf.env.allowLocalModels = true;          // default false in-browser; enables the bundled model
        tf.env.localModelPath = '/assets/models/';
        const { pipeline } = tf;
        // FR-006 Android fix (2026-06-11, v2). Two field-learned constraints shape this:
        //  (1) ORT consumes wasmPaths ONCE at its first initialization — per-attempt
        //      re-pointing is ignored, so the build variant must be committed BEFORE
        //      any pipeline() call.
        //  (2) The variants differ by capability: .asyncify is REQUIRED for the WebGPU
        //      EP (`webgpuInit` — iPad), but its CPU EP failed to register on a
        //      no-WebGPU Android Chrome ("no available backend found", COI+SAB true);
        //      the PLAIN threaded build is the canonical CPU path.
        // So: detect WebGPU availability UP FRONT (navigator.gpu), skip the webgpu
        // attempt entirely when the API is absent, and pick the ORT build for the
        // first (= deciding) attempt. Use the OBJECT form {wasm,mjs} — it triggers
        // transformers' wasm pre-load + backend registration.
        const hasWebGpu = typeof navigator !== 'undefined'
          && !!(navigator as unknown as { gpu?: unknown }).gpu;
        const requested = backendOrder();
        const order = requested.filter((d) => d === 'wasm' || hasWebGpu);
        const effective: ReadonlyArray<'webgpu' | 'wasm'> =
          order.length > 0 ? order : ['wasm'];
        if (wasmFlags) {
          const variant = effective[0] === 'webgpu'
            ? 'ort-wasm-simd-threaded.asyncify'
            : 'ort-wasm-simd-threaded';
          wasmFlags.wasmPaths = {
            wasm: `/assets/ort/${variant}.wasm`,
            mjs: `/assets/ort/${variant}.mjs`,
          };
          diag.push({
            t: performance.now(), moduleId: MODULE, kind: 'info',
            message: `STT init v2: webgpu=${hasWebGpu ? 'present' : 'ABSENT (skipped)'} `
              + `order=[${effective.join(',')}] build=${variant}`,
          });
        }
        for (const device of effective) {
          try {
            // OPT-001 (docs/OPTIMIZATION-REGISTER.md): the fp16 *merged decoder* is an
            // invalid ORT model — its subgraph returns `logits` from outer scope, so
            // session creation fails ("invalid model … add an Identity node"). But the
            // ENCODER is the 30s-window hog (~99% of PTT latency), so on WebGPU run the
            // encoder in fp16 (GPUs run half-precision fast; there's no fast int8 WebGPU
            // kernel) and keep the q8 merged decoder, which loads fine. WASM/CPU stays
            // all-q8. Mixed-precision is a supported transformers.js config; all files
            // are bundled locally (setup:assets) → offline / COEP-safe.
            const dtag = device === 'webgpu' ? 'fp16enc·q8dec' : 'q8';
            const pipe = await pipeline('automatic-speech-recognition', MODEL, {
              device,
              dtype: device === 'webgpu'
                ? { encoder_model: 'fp16', decoder_model_merged: 'q8' }
                : 'q8',
            });
            sttBackend = `${device}·${dtag}`; // surfaced in the metrics line for the pilot
            sttLoadMs = Math.round(performance.now() - t0);
            sttError = null;
            diag.push({
              t: performance.now(), moduleId: MODULE, kind: 'info',
              message: `on-device STT ready (whisper-tiny.en, ${device}/${dtag}, cold-load ${sttLoadMs}ms)`,
            });
            // OPT-003 (docs/OPTIMIZATION-REGISTER.md): warm-up inference. The FIRST real
            // inference compiles the WebGPU compute pipelines (~250 ms first-take penalty
            // measured on the iPad). Run one now on a short silent buffer so the trainee's
            // first take is already warm. Backgrounded (loadAsr is fire-and-forget at
            // construction) and non-fatal — a warm-up failure must never break STT.
            try {
              const tw = performance.now();
              await (pipe(new Float32Array(SAMPLE_RATE)) as Promise<unknown>); // 1s silence (padded to 30s)
              diag.push({
                t: performance.now(), moduleId: MODULE, kind: 'info',
                message: `STT warm-up done (${Math.round(performance.now() - tw)}ms)`,
              });
            } catch (e) {
              derror('[STT] warm-up failed (non-fatal):', e);
            }
            return (audio: Float32Array) => pipe(audio) as Promise<unknown>;
          } catch (e) {
            lastErr = e instanceof Error ? e.message : String(e);
            if (device === 'wasm') wasmErr = lastErr;
            // Route the FULL error object (message + stack + cause) to the debug
            // console so the on-device 🐞 console captures it — diag.push alone is
            // not visible there. Gated with the 🐞 console behind ?debug.
            derror(`[STT] ${device} init failed:`, e);
            diag.push({
              t: performance.now(), moduleId: MODULE, kind: 'warn',
              message: `STT ${device} init failed; trying next backend`, data: lastErr,
            });
          }
        }
        // Prefix the isolation status so a failure is self-diagnosing on-device:
        // COI=false/SAB=false ⇒ the page is NOT cross-origin isolated (usually a
        // stale cached app or missing COOP/COEP) → the threaded wasm can't start.
        const iso = `[COI=${String(crossOriginIsolated)} SAB=${typeof SharedArrayBuffer !== 'undefined'}]`;
        // Show the [wasm] portion of ORT's aggregated error — it leads with the
        // expected [webgpu] no-adapter note on a no-WebGPU tablet, which masks the
        // real wasm reason.
        const full = wasmErr || lastErr || 'no STT backend available';
        const w = full.indexOf('[wasm]');
        sttError = `${iso} ${w >= 0 ? full.slice(w) : full}`;
        return null;
      } catch (e) {
        sttError = e instanceof Error ? e.message : String(e);
        derror('[STT] transformers load failed:', e);
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
      lastStages: sttLastStages, emptyReason: sttEmptyReason,
    }),

    async soakStep(): Promise<number> {
      const a = await loadAsr();
      if (!a) return -1;
      const audio = new Float32Array(SAMPLE_RATE * 2); // 2 s of silence (whisper pads to 30 s)
      const t = performance.now();
      await a(audio);
      return Math.round(performance.now() - t);
    },

    async start(): Promise<void> {
      if (recorder && recorder.state === 'recording') return;
      stream = await navigator.mediaDevices.getUserMedia({ audio: true });
      // iPadOS hands Safari a MUTED audio track right after a Camera-app QR handoff
      // (the camera still holds the audio session) — recording then captures pure
      // silence and the take reads "(no speech detected)" (FR-006 field bug). Wait
      // briefly for the track to unmute before recording; warn if it never does.
      const track = stream.getAudioTracks()[0];
      if (track && track.muted) {
        await new Promise<void>((resolve) => {
          const timer = setTimeout(resolve, 800);
          track.onunmute = () => { clearTimeout(timer); resolve(); };
        });
        if (track.muted) {
          diag.push({
            t: performance.now(), moduleId: MODULE, kind: 'warn',
            message: 'mic track still MUTED at record start (another app holding the mic?)',
          });
        }
      }
      chunks = [];
      recorder = new MediaRecorder(stream);
      recorder.ondataavailable = (e: BlobEvent) => { if (e.data.size > 0) chunks.push(e.data); };
      recorder.start();
    },

    async stopAndTranscribe(): Promise<string> {
      const rec = recorder;
      if (!rec) { sttEmptyReason = 'no recording was started'; return ''; }
      const t0 = performance.now(); // release → transcript latency (ADR-0026 pilot)
      const stopped = new Promise<void>((resolve) => { rec.onstop = () => resolve(); });
      if (rec.state !== 'inactive') rec.stop();
      await stopped;
      // Release the mic at once (privacy + battery).
      stream?.getTracks().forEach((t) => t.stop());
      stream = null;
      recorder = null;
      const tRec = performance.now(); // recorder flush complete

      const type = chunks[0]?.type || 'audio/webm';
      const blob = new Blob(chunks, { type });
      chunks = [];
      if (blob.size === 0) {
        sttEmptyReason = 'recorder produced no audio (held too briefly?)';
        return '';
      }

      const Ctor = audioCtxCtor();
      const asr = await loadAsr();
      if (!Ctor || !asr) { sttEmptyReason = 'speech model not ready'; return ''; }
      const ctx = new Ctor();
      try {
        const decoded = await ctx.decodeAudioData(await blob.arrayBuffer());
        const tDecode = performance.now();
        const audio = await to16kMono(decoded);
        const tResample = performance.now();
        const text = textOf(await asr(audio));
        const tInfer = performance.now();
        sttLastMs = Math.round(tInfer - t0);
        // Split the budget so we can see which phase dominates the ~2s warm take
        // (ADR-0026 latency chase): recorder flush, decode, resample, inference.
        sttLastStages = {
          recMs: Math.round(tRec - t0),
          decodeMs: Math.round(tDecode - tRec),
          resampleMs: Math.round(tResample - tDecode),
          inferMs: Math.round(tInfer - tResample),
          clipMs: Math.round(decoded.duration * 1000),
        };
        if (text) {
          sttEmptyReason = null;
          return text;
        }
        // Empty text from a completed pipeline — name the cause (FR-006 field fix):
        // a near-zero RMS means the mic CAPTURED silence (muted track / another app
        // holding the mic — e.g. arriving straight from the Camera-app QR scan).
        let sumSq = 0;
        for (let i = 0; i < audio.length; i++) { const v = audio[i] ?? 0; sumSq += v * v; }
        const rms = Math.sqrt(sumSq / Math.max(1, audio.length));
        if (decoded.duration < 0.4) {
          sttEmptyReason = `clip too short (${Math.round(decoded.duration * 1000)}ms)`;
        } else if (rms < 1e-4) {
          sttEmptyReason = 'mic captured SILENCE — mic muted or another app holds it '
            + '(close the Camera app, then retry)';
        } else {
          sttEmptyReason = `whisper heard no words (clip ${decoded.duration.toFixed(1)}s, level ok)`;
        }
        diag.push({
          t: performance.now(), moduleId: MODULE, kind: 'warn',
          message: `empty transcription: ${sttEmptyReason}`,
          data: `rms=${rms.toExponential(2)} clip=${Math.round(decoded.duration * 1000)}ms`,
        });
        return '';
      } catch (e) {
        sttEmptyReason = 'audio decode/transcription failed';
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
