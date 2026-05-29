import type {
  AudioPipelineModule,
  AudioSnapshot,
  Unsubscribe,
  VisemeHandler,
} from '@contracts/audio_pipeline';
import type { BootDeps } from '@contracts/shared';

/**
 * Real Web Audio playback graph with energy-derived visemes.
 *
 * Pipeline: TTS chunk → AudioBuffer → AudioBufferSourceNode → AnalyserNode →
 * destination. Buffers are scheduled gaplessly off a running `playhead`, so a
 * stream of small chunks plays as one continuous utterance. The AnalyserNode
 * is tapped every animation frame; short-term RMS energy maps to a `jawOpen`
 * weight, giving lip-flap that tracks the audio without phoneme alignment.
 * (Provider-native visemes, when present, arrive on the speech frame and are
 * applied by animation_runtime — this path is the audio-only fallback.)
 *
 * Browser-only by nature (no AudioContext in Node/jsdom). Every Web Audio call
 * is guarded so unit tests and SSR degrade to a no-op graph: `primed` still
 * flips, `enqueueAudio` becomes a silent drop, and nothing throws. iOS audio is
 * unlocked from a user gesture via `primeOnUserGesture` (ADR-0008). We use the
 * unprefixed `AudioContext` only (Safari has shipped it since iOS 14.5).
 */

function clamp01(n: number): number { return n < 0 ? 0 : n > 1 ? 1 : n; }

// RMS-energy → jawOpen gain. Conversational speech sits around 0.05–0.2 RMS;
// this lifts that into a visible open range without clipping wide-open on peaks.
const JAW_GAIN = 3.2;
const ANALYSER_FFT = 1024;

export function createImpl(): AudioPipelineModule {
  let _deps: BootDeps | null = null;
  let primed = false;
  let queueDepth = 0;
  const visemeHandlers = new Set<VisemeHandler>();

  // Web Audio graph (all null until primed in a real browser).
  let ctx: AudioContext | null = null;
  let analyser: AnalyserNode | null = null;
  let playhead = 0;                       // next gapless start time (ctx clock, s)
  const active = new Set<AudioBufferSourceNode>();
  let rafId: number | null = null;

  /** Decode a chunk to an AudioBuffer. PCM16-24k is raw (no container) so it is
   *  framed by hand; opus/mp3 go through the platform decoder. */
  async function toAudioBuffer(
    chunk: ArrayBuffer,
    format: 'pcm16-24k' | 'opus' | 'mp3',
  ): Promise<AudioBuffer | null> {
    if (!ctx) return null;
    if (format === 'pcm16-24k') {
      const i16 = new Int16Array(chunk, 0, Math.floor(chunk.byteLength / 2));
      const buf = ctx.createBuffer(1, Math.max(1, i16.length), 24000);
      const ch = buf.getChannelData(0);
      for (let i = 0; i < i16.length; i++) ch[i] = (i16[i] ?? 0) / 32768;
      return buf;
    }
    // decodeAudioData detaches its input, so hand it a copy.
    return ctx.decodeAudioData(chunk.slice(0));
  }

  function startVisemeLoop(): void {
    if (rafId !== null) return;
    if (typeof requestAnimationFrame === 'undefined' || !analyser) return;
    const td = new Float32Array(analyser.fftSize);
    const tick = (): void => {
      if (!analyser || !ctx) { rafId = null; return; }
      analyser.getFloatTimeDomainData(td);
      let sum = 0;
      for (let i = 0; i < td.length; i++) { const s = td[i] ?? 0; sum += s * s; }
      const rms = Math.sqrt(sum / td.length);
      const jaw = clamp01(rms * JAW_GAIN);
      const t = ctx.currentTime * 1000;
      for (const h of visemeHandlers) h({ t, id: 'jawOpen', w: jaw });
      rafId = requestAnimationFrame(tick);
    };
    rafId = requestAnimationFrame(tick);
  }

  function stopVisemeLoop(): void {
    if (rafId !== null && typeof cancelAnimationFrame !== 'undefined') {
      cancelAnimationFrame(rafId);
    }
    rafId = null;
  }

  async function decodeAndSchedule(
    chunk: ArrayBuffer,
    format: 'pcm16-24k' | 'opus' | 'mp3',
  ): Promise<void> {
    const buf = await toAudioBuffer(chunk, format);
    if (!buf || !ctx || !analyser) { queueDepth = Math.max(0, queueDepth - 1); return; }
    const src = ctx.createBufferSource();
    src.buffer = buf;
    src.connect(analyser);
    const startAt = Math.max(ctx.currentTime, playhead);
    src.start(startAt);
    playhead = startAt + buf.duration;
    active.add(src);
    src.onended = () => {
      active.delete(src);
      src.disconnect();
      queueDepth = Math.max(0, queueDepth - 1);
      if (active.size === 0) stopVisemeLoop();
    };
    startVisemeLoop();
  }

  return {
    async boot(deps) { _deps = deps; },
    dispose() {
      stopVisemeLoop();
      for (const s of active) { try { s.stop(); } catch { /* already stopped */ } s.disconnect(); }
      active.clear();
      if (ctx) { void ctx.close(); ctx = null; }
      analyser = null;
      visemeHandlers.clear();
      queueDepth = 0;
      playhead = 0;
      primed = false;
      _deps = null;
    },

    async primeOnUserGesture() {
      void _deps;
      primed = true;
      if (ctx || typeof AudioContext === 'undefined') return;   // already primed, or non-browser
      ctx = new AudioContext();
      analyser = ctx.createAnalyser();
      analyser.fftSize = ANALYSER_FFT;
      analyser.connect(ctx.destination);
      playhead = ctx.currentTime;
      // iOS unlock: play one silent sample from within the gesture, then resume.
      const silent = ctx.createBufferSource();
      silent.buffer = ctx.createBuffer(1, 1, 22050);
      silent.connect(ctx.destination);
      silent.start(0);
      await ctx.resume();
    },

    enqueueAudio(chunk, format) {
      if (!primed) {
        throw new Error(
          'audio_pipeline: must call primeOnUserGesture() before enqueueAudio() (ADR-0008).',
        );
      }
      if (!ctx) return;                    // non-browser: no graph, drop silently
      queueDepth++;
      void decodeAndSchedule(chunk, format).catch(() => {
        queueDepth = Math.max(0, queueDepth - 1);
      });
    },

    onViseme(handler): Unsubscribe {
      visemeHandlers.add(handler);
      return () => visemeHandlers.delete(handler);
    },

    flush() {
      for (const s of active) { try { s.stop(); } catch { /* already stopped */ } s.disconnect(); }
      active.clear();
      stopVisemeLoop();
      queueDepth = 0;
      playhead = ctx ? ctx.currentTime : 0;
    },

    // --- Resumable ---
    async pause()  { stopVisemeLoop(); if (ctx) await ctx.suspend(); },
    async resume() { if (ctx) await ctx.resume(); if (active.size > 0) startVisemeLoop(); },
    snapshot(): AudioSnapshot { return { primed, queueDepth }; },
    async restore(s) { primed = s.primed; queueDepth = s.queueDepth; },
  };
}
