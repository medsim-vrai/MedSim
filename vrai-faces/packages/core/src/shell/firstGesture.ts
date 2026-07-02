// The first-touch warmup trick (Claude Code Guide §3.7). Wires the iOS
// silent prime (ADR-0008) and pre-warms the TTS + emotion models so the
// first speak feels instant.

import { audioPipeline } from '../modules/audio_pipeline';
import { lazyEmotion, lazyTts } from './lazy';
import { primeSpeechSynthesis } from './speechUnlock';

export function installFirstGestureWarmup(): void {
  let warmed = false;
  const handler = async (): Promise<void> => {
    primeSpeechSynthesis();          // sync, in-gesture: unlock iOS speechSynthesis + warm voices
    await audioPipeline.primeOnUserGesture();
    // Stop listening ONLY once the context is genuinely live. A first gesture can flip primed=true
    // yet leave the context 'suspended' (a desktop autoplay race) — so keep priming on later
    // gestures instead of unbinding after one (the old `{ once: true }`), or audio stays dead with
    // no retry. This is what let "tap once to enable audio" silently fail on desktop.
    const snap = audioPipeline.snapshot();
    const live = snap.primed && (snap.state === undefined || snap.state === 'running');
    if (!live) return;
    window.removeEventListener('pointerdown', handler);
    if (warmed) return;
    warmed = true;
    const [{ ttsProvider }, { emotionDriver }] = await Promise.all([
      lazyTts(), lazyEmotion(),
    ]);
    void ttsProvider.warmup();
    void emotionDriver.warmup();
  };
  window.addEventListener('pointerdown', handler);   // NOT { once }: retry until audio is live
}
