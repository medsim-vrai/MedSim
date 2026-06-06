import type { Lifecycle, Resumable } from './shared';

export interface AudioPipelineModule extends Lifecycle, Resumable<AudioSnapshot> {
  /** Mandatory iOS "silent prime" — must be called from a user gesture. */
  primeOnUserGesture(): Promise<void>;

  /** Feed a PCM16 chunk arriving from the TTS provider. */
  enqueueAudio(chunk: ArrayBuffer, format: 'pcm16-24k' | 'opus' | 'mp3'): void;

  /** Subscribe to derived viseme weights for the audio playing now. */
  onViseme(handler: VisemeHandler): Unsubscribe;

  /**
   * ADR-0015: choose the viseme source. `'native'` (the provider streams its own
   * visemes — Azure / AWS Polly) SUPPRESSES the energy-derived `jawOpen` bridge so
   * provider visemes aren't doubled; `'derived'` (the default) runs the bridge for
   * any non-native provider. Set per utterance from whether `TtsChunk.visemes` is
   * present.
   */
  setVisemeSource(source: VisemeSource): void;

  /** Drop everything and silence the worklet (e.g. end-of-utterance abort). */
  flush(): void;
}

export type VisemeHandler = (frame: { t: number; id: string; w: number }) => void;
export type Unsubscribe = () => void;
export type VisemeSource = 'native' | 'derived';

export interface AudioSnapshot {
  primed: boolean;
  queueDepth: number;
  /** ADR-0015 viseme source; defaults to 'derived' on restore if absent. */
  visemeSource?: VisemeSource;
  /** Diagnostic only: live AudioContext.state ('running'|'suspended'|'interrupted'|'closed'). */
  state?: string;
}
