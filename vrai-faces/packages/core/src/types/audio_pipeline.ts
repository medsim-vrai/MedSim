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

  /** Wake the OUTPUT device before a reply. On desktop the AudioContext can report 'running' while
   *  the OS output sink is dormant, so the FIRST audio after an idle gap renders silently (the
   *  intermittent turn-1 "no audio"). A brief windowed primer through the speech path keeps the sink
   *  rendering. Call from a user gesture (establish / hold-to-talk), a few seconds before the reply. */
  warmOutput(): void;

  /** Keep the OS hardware output (DAC) awake while a reply is being synthesized. The Web Audio sink
   *  renders the first reply correctly (its clock advances) but the physical DAC, asleep under the
   *  near-silent keep-alive, doesn't spin up in time and drops it (the turn-1 silence — confirmed:
   *  sink froz=0 yet no sound). A low continuous source from hold-to-talk RELEASE until the reply's
   *  audio arrives holds the DAC awake; it auto-stops when real audio is enqueued. Released (not
   *  recording) so it can't leak into the mic even with echo-cancellation off.
   *
   *  Call TWICE per turn so nothing audible is spoken until the student's prompt is confirmed:
   *   1. on hold-to-talk RELEASE with no args — starts only the inaudible keep-awake noise.
   *   2. once the transcript is confirmed, with ``fillers`` — plays ONE short "thinking" utterance
   *      (pcm16-24k clips in the character's voice, picked at random, lip-synced) over the synthesis
   *      wait; no repeating. The noise keeps running and is not restarted.
   *  Stopped the instant real reply audio is enqueued, so the answer cuts in cleanly without overlap. */
  warmHold(fillers?: ArrayBuffer[]): void;
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
