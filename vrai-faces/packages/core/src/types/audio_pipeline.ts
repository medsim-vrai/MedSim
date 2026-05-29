import type { Lifecycle, Resumable } from './shared';

export interface AudioPipelineModule extends Lifecycle, Resumable<AudioSnapshot> {
  /** Mandatory iOS "silent prime" — must be called from a user gesture. */
  primeOnUserGesture(): Promise<void>;

  /** Feed a PCM16 chunk arriving from the TTS provider. */
  enqueueAudio(chunk: ArrayBuffer, format: 'pcm16-24k' | 'opus' | 'mp3'): void;

  /** Subscribe to derived viseme weights for the audio playing now. */
  onViseme(handler: VisemeHandler): Unsubscribe;

  /** Drop everything and silence the worklet (e.g. end-of-utterance abort). */
  flush(): void;
}

export type VisemeHandler = (frame: { t: number; id: string; w: number }) => void;
export type Unsubscribe = () => void;

export interface AudioSnapshot {
  primed: boolean;
  queueDepth: number;
}
