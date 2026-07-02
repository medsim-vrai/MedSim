import type {
  AudioPipelineModule,
  AudioSnapshot,
  Unsubscribe,
  VisemeHandler,
  VisemeSource,
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

// Awaiting AudioContext.resume() OFF-gesture HANGS on iOS (ADR-0037), so there the resume must be
// fire-and-forget and the keep-alive source carries the anti-suspend guarantee. On desktop Chrome/
// Edge/Safari resume() resolves promptly and SHOULD be awaited — otherwise a reply that arrives
// seconds after the gesture can schedule into a still-suspended context and play SILENTLY (the
// desktop "character replied, no audio" symptom). Gate the behavior on platform.
const IS_IOS = typeof navigator !== 'undefined'
  && (/iPad|iPhone|iPod/.test(navigator.userAgent)
    || (navigator.platform === 'MacIntel' && (navigator.maxTouchPoints ?? 0) > 1));

export function createImpl(): AudioPipelineModule {
  let _deps: BootDeps | null = null;
  let primed = false;
  let queueDepth = 0;
  let visemeSource: VisemeSource = 'derived';   // ADR-0015: 'native' suppresses the derived bridge
  const visemeHandlers = new Set<VisemeHandler>();

  // Web Audio graph (all null until primed in a real browser).
  let ctx: AudioContext | null = null;
  let analyser: AnalyserNode | null = null;
  let playhead = 0;                       // next gapless start time (ctx clock, s)
  const active = new Set<AudioBufferSourceNode>();
  let rafId: number | null = null;
  // A looping silent source kept playing so iOS never idle-suspends the context between
  // utterances (ADR-0037): async replies arrive seconds after the priming gesture, and
  // awaiting resume() off-gesture hangs on iOS — so we keep the graph continuously running.
  let keepAlive: AudioBufferSourceNode | null = null;
  // A LOUDER-than-keepalive source held during the pending-reply window (release → reply) to keep the
  // OS hardware DAC awake, so the first reply isn't dropped while the DAC spins up. Stopped the moment
  // real reply audio is enqueued (see warmHold / stopWarmHold).
  let warmHoldSrc: AudioBufferSourceNode | null = null;
  let fillerSrc: AudioBufferSourceNode | null = null;  // audible "thinking" utterance during that window
  let warmHoldTimer: ReturnType<typeof setTimeout> | null = null;  // safety auto-stop if no reply comes
  // Frames can arrive BEFORE the first user gesture: the portal voices the opening line on
  // WS-connect, before anyone has tapped. Audio can't play until that gesture, but we must NOT drop
  // the frame (that was the silent-opening bug — the character "started" with no voice). Buffer
  // pre-prime frames here and flush them the instant audio unlocks. Capped so a client that never
  // gestures can't grow it without bound.
  let pending: Array<{ chunk: ArrayBuffer; format: 'pcm16-24k' | 'opus' | 'mp3' }> = [];
  const PENDING_MAX = 16;

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
    if (visemeSource !== 'derived') return;   // ADR-0015: native visemes → no derived bridge
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
    // Wake the context before scheduling. On iOS awaiting resume() off-gesture HANGS, so there it is
    // fire-and-forget and the keep-alive source is the real anti-suspend guard. On desktop resume()
    // resolves at once and we AWAIT it, so this buffer never starts into a suspended context and
    // plays silently (the "character replied, no audio" desktop symptom).
    if (ctx.state !== 'running') {
      if (IS_IOS) void ctx.resume();
      else { try { await ctx.resume(); } catch { /* start() below is still best-effort */ } }
    }
    if (!ctx || !analyser) { queueDepth = Math.max(0, queueDepth - 1); return; }
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

  function stopWarmHold(): void {
    if (warmHoldTimer !== null) { clearTimeout(warmHoldTimer); warmHoldTimer = null; }
    if (fillerSrc) {
      try { fillerSrc.stop(); } catch { /* already stopped */ }
      fillerSrc.disconnect();
      fillerSrc = null;
    }
    if (warmHoldSrc) {
      try { warmHoldSrc.stop(); } catch { /* already stopped */ }
      warmHoldSrc.disconnect();
      warmHoldSrc = null;
    }
  }

  return {
    async boot(deps) { _deps = deps; },
    dispose() {
      stopVisemeLoop();
      stopWarmHold();
      if (keepAlive) { try { keepAlive.stop(); } catch { /* already stopped */ } keepAlive.disconnect(); keepAlive = null; }
      for (const s of active) { try { s.stop(); } catch { /* already stopped */ } s.disconnect(); }
      active.clear();
      if (ctx) { void ctx.close(); ctx = null; }
      analyser = null;
      visemeHandlers.clear();
      pending = [];
      queueDepth = 0;
      playhead = 0;
      primed = false;
      visemeSource = 'derived';
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
      // KEEP-ALIVE: a looping silent source so the context stays 'running' between
      // utterances (iOS idle-suspends an idle graph; the reply then plays into silence —
      // the "no audio, no animation" symptom). Not routed through the analyser, so it
      // adds no energy; negligible cost. Held in `keepAlive` so it isn't GC'd.
      try {
        const ka = ctx.createBufferSource();
        const kbuf = ctx.createBuffer(1, Math.max(1, Math.round(ctx.sampleRate * 0.5)), ctx.sampleRate);
        const kd = kbuf.getChannelData(0);
        // Inaudible noise floor (~-80 dB), NOT digital silence: iOS still idle-suspends a
        // context whose only output is pure silence (confirmed on device — state went
        // 'suspended' with a silent keep-alive), so give it a real-but-inaudible signal.
        for (let i = 0; i < kd.length; i++) kd[i] = (Math.random() * 2 - 1) * 1e-4;
        ka.buffer = kbuf;
        ka.loop = true;
        ka.connect(ctx.destination);
        ka.start();
        keepAlive = ka;
      } catch { /* best-effort */ }
      // Flush frames that arrived before this gesture (the opening voiced on WS-connect) so the
      // character actually speaks its first line instead of opening in silence.
      if (pending.length) {
        const buffered = pending;
        pending = [];
        for (const p of buffered) {
          queueDepth++;
          void decodeAndSchedule(p.chunk, p.format).catch(() => { queueDepth = Math.max(0, queueDepth - 1); });
        }
      }
    },

    enqueueAudio(chunk, format) {
      stopWarmHold();  // real reply audio now keeps the DAC awake; end the warm-hold placeholder
      if (!primed) {
        // Pre-gesture frame (the opening, voiced on WS-connect). Buffer it instead of dropping —
        // primeOnUserGesture() flushes `pending` the moment the user taps, so the line is spoken,
        // not lost. (ADR-0008 used to throw here; that silently killed the opening on desktop.)
        pending.push({ chunk, format });
        if (pending.length > PENDING_MAX) pending.shift();
        return;
      }
      if (!ctx) return;                    // non-browser: no graph, drop silently
      if (ctx.state !== 'running') void ctx.resume();  // wake from iOS auto-suspend ASAP
      queueDepth++;
      void decodeAndSchedule(chunk, format).catch(() => {
        queueDepth = Math.max(0, queueDepth - 1);
      });
    },

    onViseme(handler): Unsubscribe {
      visemeHandlers.add(handler);
      return () => visemeHandlers.delete(handler);
    },

    setVisemeSource(source) {
      visemeSource = source;
      // ADR-0015: native → kill the derived bridge now; derived → resume if audio is live.
      if (source === 'native') stopVisemeLoop();
      else if (active.size > 0) startVisemeLoop();
    },

    flush() {
      stopWarmHold();
      for (const s of active) { try { s.stop(); } catch { /* already stopped */ } s.disconnect(); }
      active.clear();
      stopVisemeLoop();
      queueDepth = 0;
      playhead = ctx ? ctx.currentTime : 0;
    },

    warmOutput() {
      // Desktop Chrome can keep the AudioContext 'running' while the OS output sink idles, so the
      // first speech after a gap plays silently (intermittent turn-1 "no audio"; confirmed via
      // getOutputTimestamp not advancing). Play a tiny windowed primer through the SAME speech path
      // (→ analyser → destination) so the sink is actively rendering when the reply arrives. The
      // Hann window avoids a click; ~40 ms at low level is at most a faint tick on the press.
      if (!primed || !ctx || !analyser) return;
      if (ctx.state !== 'running') void ctx.resume();
      try {
        const n = Math.max(1, Math.round(ctx.sampleRate * 0.04));
        const buf = ctx.createBuffer(1, n, ctx.sampleRate);
        const ch = buf.getChannelData(0);
        for (let i = 0; i < n; i++) {
          const w = n > 1 ? 0.5 - 0.5 * Math.cos((2 * Math.PI * i) / (n - 1)) : 1; // Hann
          ch[i] = (Math.random() * 2 - 1) * 0.02 * w;
        }
        const src = ctx.createBufferSource();
        src.buffer = buf;
        src.connect(analyser);
        const at = Math.max(ctx.currentTime, playhead);
        src.start(at);
        playhead = at + buf.duration;
      } catch { /* best-effort — never block the turn */ }
    },

    warmHold(fillers) {
      // Hold the OS hardware output (DAC) awake during the pending-reply window. Called TWICE per turn so
      // nothing audible is spoken until the student's prompt is confirmed:
      //   1. on hold-to-talk RELEASE with no args — starts only the faint keep-awake noise, spinning the
      //      DAC up while the take is transcribed. The DAC, asleep under the ~-80 dB keep-alive, otherwise
      //      drops the first reply (the turn-1 silence). Nothing audible plays yet.
      //   2. once stopAndTranscribe returns text, with the filler clips — plays ONE short "thinking"
      //      utterance (the character's voice, lip-synced) over the synthesis wait. The noise from step 1
      //      keeps running underneath and is NOT restarted (a restart briefly drops the DAC).
      // ONE clip only — no repeating. stopWarmHold() (from enqueueAudio) ends both the instant real reply
      // audio arrives, so the answer cuts in cleanly without overlapping the filler.
      if (!primed || !ctx) return;
      if (ctx.state !== 'running') void ctx.resume();
      try {
        if (!warmHoldSrc) {                          // step 1: start the keep-awake noise (idempotent)
          const n = Math.max(1, Math.round(ctx.sampleRate * 0.25));
          const buf = ctx.createBuffer(1, n, ctx.sampleRate);
          const ch = buf.getChannelData(0);
          for (let i = 0; i < n; i++) ch[i] = (Math.random() * 2 - 1) * 0.005;
          const src = ctx.createBufferSource();
          src.buffer = buf;
          src.loop = true;
          src.connect(ctx.destination);
          src.start();
          warmHoldSrc = src;
        }
        const pcm = fillers && fillers.length
          ? (fillers[Math.floor(Math.random() * fillers.length)] ?? fillers[0])
          : null;
        if (pcm && pcm.byteLength > 1 && analyser && !fillerSrc) {   // step 2: ONE filler, once prompt is in
          const i16 = new Int16Array(pcm, 0, Math.floor(pcm.byteLength / 2));
          const fbuf = ctx.createBuffer(1, Math.max(1, i16.length), 24000);
          const fch = fbuf.getChannelData(0);
          for (let i = 0; i < i16.length; i++) fch[i] = (i16[i] ?? 0) / 32768;
          const fsrc = ctx.createBufferSource();
          fsrc.buffer = fbuf;
          fsrc.connect(analyser);
          fsrc.onended = () => { if (fsrc === fillerSrc) fillerSrc = null; };
          fsrc.start();
          fillerSrc = fsrc;
          if (visemeSource === 'derived') startVisemeLoop();
        }
        // Safety: if no reply ever arrives (an empty take), stop the hold so the next warmHold is clean.
        if (warmHoldTimer !== null) clearTimeout(warmHoldTimer);
        warmHoldTimer = setTimeout(stopWarmHold, 12000);
      } catch { /* best-effort */ }
    },

    // --- Resumable ---
    async pause()  { stopVisemeLoop(); if (ctx) await ctx.suspend(); },
    async resume() { if (ctx) await ctx.resume(); if (active.size > 0) startVisemeLoop(); },
    snapshot(): AudioSnapshot {
      return { primed, queueDepth, visemeSource, ...(ctx ? { state: ctx.state } : {}) };
    },
    async restore(s) { primed = s.primed; queueDepth = s.queueDepth; visemeSource = s.visemeSource ?? 'derived'; },
  };
}
