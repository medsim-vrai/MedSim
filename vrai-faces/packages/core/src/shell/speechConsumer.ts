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
import type { TtsProviderModule } from '@contracts/tts_provider';
import type { TtsVoiceId, VRAISpeechFrame } from '@contracts/shared';
import { diag } from '@perf/diag';

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

  async function speakText(text: string, emotion?: string): Promise<void> {
    const voice = deps.voice();
    if (!voice) return; // not bound yet — nothing to speak as
    if (!ttsMod) ttsMod = await deps.loadTts();
    const req = {
      text, voice, tier: 'local' as const, source: 'scripted' as const,
      ...(emotion ? { emotion } : {}),
    };
    for await (const chunk of ttsMod.speak(req)) {
      const native = !!chunk.visemes && chunk.visemes.length > 0;
      // ADR-0015: native provider visemes suppress the derived jawOpen bridge.
      deps.audio.setVisemeSource(native ? 'native' : 'derived');
      deps.audio.enqueueAudio(chunk.audio, chunk.audioFormat);
      if (native && chunk.visemes) deps.anim.pushVisemes(toVisemeFrames(chunk.visemes));
    }
  }

  function handleFrame(f: VRAISpeechFrame): void {
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
