import type { BlendshapeWeights, Lifecycle } from './shared';

/**
 * Deterministic blink + saccade + sway. Same seed → same sequence so
 * scenarios are reproducible (matters for the soak fixture).
 */
export interface IdleMotionModule extends Lifecycle {
  /** Set a deterministic seed for this character's idle loop. */
  setSeed(seed: number): void;

  /** Sample the additive contribution at the current frame time. */
  sample(nowMs: number, out: BlendshapeWeights): void;
}
