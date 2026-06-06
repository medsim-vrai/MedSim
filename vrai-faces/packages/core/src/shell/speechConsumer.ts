// Drives the avatar from MedSim speech frames (the receiving end of the
// portal's speak path, Phase 4.3 / ADR-0023).
//
// medsim_adapter delivers VRAISpeechFrames over the speech transport. Per the
// local-first design the portal sends TEXT + emotion only (no audio bytes), so
// this module synthesizes audio on-device:
//   - emotion        → animation_runtime.setEmotion (cross-fade)
//   - text           → tts_provider.speak → audio_pipeline (+ visemes)
//   - frame.audio    → audio_pipeline directly (other transports may pre-synth)
// and bridges audio_pipeline's energy-derived visemes into the animation
// runtime once, up front.
//
// All module deps are injected so the unit test runs without three.js / audio.

import type { AnimationRuntimeModule } from '@contracts/animation_runtime';
import type { AudioPipelineModule } from '@contracts/audio_pipeline';
import type { MedsimAdapterModule } from '@contracts/medsim_adapter';
import type { TtsChunk, TtsProviderModule } from '@contracts/tts_provider';
import type { TtsVoiceId, VRAISpeechFrame } from '@contracts/shared';
import { diag } from '@perf/diag';
import { dlog, dwarn, derror } from './debug';

export interface SpeechConsumerDeps {
  adapter: MedsimAdapterModule;
  audio: AudioPipelineModule;
  anim: AnimationRuntimeModule;
  /** Lazily load TTS on the first spoken line (keeps it out of first paint). */
  loadTts: () => Promise<TtsProviderModule>;
  /** Voice for synthesis; read per-utterance so a late bind is honored. */
  voice: () => TtsVoiceId | undefined;
}

const MODULE = 'shell.speechConsumer';
const EMOTION_EASE_MS = 180;

// On-device Kokoro (ONNX TTS) can die OUT-OF-BAND on some browsers — observed on
// iPad Safari as `TypeError: undefined is not a function` INSIDE the kokoro bundle
// that never throws into the for-await, so the generator just hangs and the
// browser-speech fallback never runs (the avatar goes silent). Watchdog each chunk
// so a stall becomes a catchable error; the caller then disables Kokoro for the
// session so every reply doesn't pay the timeout. Generous enough for a real
// first-chunk inference on hardware where Kokoro DOES run.
const FIRST_CHUNK_MS = 4000;

/** `iter.next()` racing a watchdog; rejects if no chunk arrives in time. Clears the
 *  timer either way so the loser never fires out-of-band. */
function nextOrTimeout(iter: AsyncIterator<TtsChunk>): Promise<IteratorResult<TtsChunk>> {
  let timer: ReturnType<typeof setTimeout> | undefined;
  const watchdog = new Promise<never>((_, reject) => {
    timer = setTimeout(
      () => reject(new Error(`on-device TTS produced no audio in ${FIRST_CHUNK_MS}ms`)),
      FIRST_CHUNK_MS,
    );
  });
  return Promise.race([iter.next(), watchdog]).finally(() => {
    if (timer !== undefined) clearTimeout(timer);
  });
}

/** Map provider/frame visemes ({t,id,w}) to animation-runtime frames. */
function toVisemeFrames(
  visemes: ReadonlyArray<{ t: number; id: string; w: number }>,
): Array<{ t: number; weights: Record<string, number> }> {
  return visemes.map((v) => ({ t: v.t, weights: { [v.id]: v.w } }));
}

/**
 * Wire speech frames to the avatar. Returns an unsubscribe that tears down both
 * the frame subscription and the derived-viseme bridge.
 */
export function installSpeechConsumer(deps: SpeechConsumerDeps): () => void {
  // (1) Bridge energy-derived visemes → the animation runtime (one subscription).
  const offViseme = deps.audio.onViseme((v) => {
    deps.anim.pushVisemes([{ t: v.t, weights: { [v.id]: v.w } }]);
  });

  let ttsMod: TtsProviderModule | null = null;
  // Serialize utterances so chunks from two frames never interleave.
  let speaking: Promise<void> = Promise.resolve();
  // Once on-device TTS fails on this device it won't start working — latch it off so
  // every later reply goes straight to the browser voice (no per-reply timeout stall).
  let kokoroBroken = false;

  async function speakText(text: string, emotion?: string): Promise<void> {
    const voice = deps.voice();
    dlog('[speak] speakText', { voice, chars: text.length, emotion });
    if (!voice) { dwarn('[speak] no voice bound — nothing to speak'); return; }

    if (!kokoroBroken) {
      if (!ttsMod) { ttsMod = await deps.loadTts(); dlog('[speak] TTS module loaded'); }
      const req = {
        text, voice, tier: 'local' as const, source: 'scripted' as const,
        ...(emotion ? { emotion } : {}),
      };
      try {
        let chunks = 0;
        const iter = ttsMod.speak(req)[Symbol.asyncIterator]();
        try {
          for (let res = await nextOrTimeout(iter); !res.done; res = await nextOrTimeout(iter)) {
            const chunk = res.value;
            chunks++;
            const native = !!chunk.visemes && chunk.visemes.length > 0;
            // ADR-0015: native provider visemes suppress the derived jawOpen bridge.
            deps.audio.setVisemeSource(native ? 'native' : 'derived');
            deps.audio.enqueueAudio(chunk.audio, chunk.audioFormat);
            if (native && chunk.visemes) deps.anim.pushVisemes(toVisemeFrames(chunk.visemes));
          }
        } finally {
          // Abandon a hung/failed generator (don't await — return() can itself hang).
          try { void iter.return?.()?.catch(() => undefined); } catch { /* ignore */ }
        }
        dlog('[speak] done —', chunks, 'audio chunk(s) enqueued');
        if (chunks > 0) return;
      } catch (e) {
        kokoroBroken = true; // a TTS that can't run here won't recover — stop stalling on it
        dwarn('[speak] on-device TTS failed — disabled; using browser speech:', e);
        diag.push({
          t: performance.now(), moduleId: MODULE, kind: 'warn',
          message: 'on-device TTS failed; disabled, using browser-speech fallback',
          data: e instanceof Error ? e.message : String(e),
        });
      }
    }
    // Fallback: the browser's built-in speechSynthesis (e.g. the iOS system voice) so the
    // avatar still talks, with a coarse jaw oscillation for rough lip-sync. The real Kokoro
    // voice + native visemes need a browser where the on-device ONNX TTS runs (the iPad-Safari
    // TypeError above) — tracked as a known issue.
    await speakViaBrowser(text);
  }

  async function speakViaBrowser(text: string): Promise<void> {
    const synth = typeof window !== 'undefined' ? window.speechSynthesis : undefined;
    if (!synth || typeof SpeechSynthesisUtterance === 'undefined') {
      dwarn('[speak] no browser speechSynthesis available');
      return;
    }
    await new Promise<void>((resolve) => {
      const u = new SpeechSynthesisUtterance(text);
      u.lang = 'en-US';
      let jaw: number | null = null;
      let settled = false;
      const stop = (): void => {
        if (settled) return;
        settled = true;
        if (jaw !== null) { clearInterval(jaw); jaw = null; }
        deps.anim.pushVisemes([{ t: performance.now(), weights: { jawOpen: 0 } }]);
        resolve();
      };
      u.onstart = (): void => {
        dlog('[speak] browser onstart — speaking + jaw lip-sync');
        deps.audio.setVisemeSource('derived');
        jaw = window.setInterval((): void => {
          const open = 0.12 + 0.30 * Math.abs(Math.sin(performance.now() / 80));
          deps.anim.pushVisemes([{ t: performance.now(), weights: { jawOpen: open } }]);
        }, 60);
      };
      u.onend = (): void => { dlog('[speak] browser onend'); stop(); };
      u.onerror = (e: SpeechSynthesisErrorEvent): void => { dwarn('[speak] browser onerror:', e.error); stop(); };
      // If iOS SILENTLY refuses (neither onstart nor onerror fires) the utterance queue
      // would hang forever — bound it, and log the gesture-lock signature.
      window.setTimeout(() => {
        if (!settled) { dwarn('[speak] browser speech never started (iOS gesture lock?)'); stop(); }
      }, 5000);
      dlog('[speak] browser speak()', { chars: text.length, voices: synth.getVoices().length });
      try { synth.cancel(); synth.speak(u); } catch (e) { dwarn('[speak] browser speak threw:', e); stop(); }
    });
  }

  function handleFrame(f: VRAISpeechFrame): void {
    dlog('[speak] frame', { text: f.text?.slice(0, 50), hasAudio: !!f.audio, emotion: f.emotion?.label });
    if (f.emotion) deps.anim.setEmotion(f.emotion.weights, EMOTION_EASE_MS);

    if (f.audio) {
      // Pre-synthesized audio (not the portal's text-only path, but supported).
      const native = !!f.visemes && f.visemes.length > 0;
      deps.audio.setVisemeSource(native ? 'native' : 'derived');
      deps.audio.enqueueAudio(f.audio, f.audioFormat ?? 'pcm16-24k');
      if (native && f.visemes) deps.anim.pushVisemes(toVisemeFrames(f.visemes));
      return;
    }

    if (f.text) {
      const text = f.text;
      const emoLabel = f.emotion?.label;
      speaking = speaking
        .then(() => speakText(text, emoLabel))
        .catch((e: unknown) => {
          derror('[speak] speakText failed:', e);
          diag.push({
            t: performance.now(), moduleId: MODULE, kind: 'error',
            message: 'speakText failed', data: e instanceof Error ? e.message : String(e),
          });
        });
    }
  }

  const offFrame = deps.adapter.onSpeechFrame(handleFrame);
  return () => { offViseme(); offFrame(); };
}
