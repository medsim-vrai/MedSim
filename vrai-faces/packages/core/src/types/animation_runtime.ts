import type { BlendshapeWeights, Lifecycle, Resumable } from './shared';

export interface AnimationRuntimeModule extends Lifecycle, Resumable<AnimationSnapshot> {
  /** Bind a mesh to drive every tick. */
  attach(meshId: string): void;
  detach(meshId: string): void;

  /** Push viseme weights for the active utterance. */
  pushVisemes(frames: Array<{ t: number; weights: BlendshapeWeights }>): void;

  /** Update the emotional baseline. Cross-fades over `easeMs`. */
  setEmotion(weights: BlendshapeWeights, easeMs?: number): void;

  /** Start / stop the 60 Hz tick. */
  start(): void;
  stop(): void;

  /**
   * Run one tick. Called by the renderer once per rAF, before
   * `renderer.render()`. No-op when stopped. Sums viseme + emotion +
   * idle, clamps, and writes to each attached mesh's
   * `morphTargetInfluences`.
   */
  tick(nowMs: number): void;

  /** Last measured frame time in ms (rolling average). */
  lastFrameMs(): number;
}

export interface AnimationSnapshot {
  attached: string[];
  emotionWeights: BlendshapeWeights;
  /** Visemes currently buffered ahead of `now`. */
  pendingVisemes: Array<{ t: number; weights: BlendshapeWeights }>;
}
