// The first-touch warmup trick (Claude Code Guide §3.7). Wires the iOS
// silent prime (ADR-0008) and pre-warms the TTS + emotion models so the
// first speak feels instant.

import { audioPipeline } from '../modules/audio_pipeline';
import { lazyEmotion, lazyTts } from './lazy';
import { primeSpeechSynthesis } from './speechUnlock';

export function installFirstGestureWarmup(): void {
  const once = async (): Promise<void> => {
    window.removeEventListener('pointerdown', once);
    primeSpeechSynthesis();          // sync, in-gesture: unlock iOS speechSynthesis + warm voices
    await audioPipeline.primeOnUserGesture();
    const [{ ttsProvider }, { emotionDriver }] = await Promise.all([
      lazyTts(), lazyEmotion(),
    ]);
    void ttsProvider.warmup();
    void emotionDriver.warmup();
  };
  window.addEventListener('pointerdown', once, { once: true });
}
