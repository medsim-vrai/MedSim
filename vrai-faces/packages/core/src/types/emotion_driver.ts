import type { BlendshapeWeights, Lifecycle } from './shared';

/**
 * LLM-driven baseline mood. Emits JSON blendshape weights — never free
 * text (ADR-0005). Runs locally via transformers.js by default;
 * cloud Claude is allowed if the scenario opts in.
 */
export interface EmotionDriverModule extends Lifecycle {
  warmup(): Promise<void>;

  /**
   * Given an utterance text + scenario context, return a target
   * baseline mood. The animation runtime will ease into it.
   */
  inferBaseline(input: EmotionInput): Promise<{
    label: string;
    weights: BlendshapeWeights;
  }>;
}

export interface EmotionInput {
  text: string;
  characterId: string;
  /** Optional last N utterances for short-term context. */
  context?: string[];
}
