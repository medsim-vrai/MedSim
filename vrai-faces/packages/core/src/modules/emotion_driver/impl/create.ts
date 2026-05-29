import type { EmotionDriverModule, EmotionInput } from '@contracts/emotion_driver';
import type { BlendshapeWeights, BootDeps } from '@contracts/shared';

/**
 * First-cut emotion driver: a LOCAL, deterministic lexicon classifier.
 *
 * The contract envisions an LLM (transformers.js on-device, or cloud Claude
 * if the scenario opts in — ADR-0005). Both are deferred here: transformers.js
 * is not yet an approved dependency (would need an ADR + a line in the tools
 * sheet), and the cloud path must clear the PHI guardrail (ADR-0014 — only
 * BAA-covered providers may ever receive trainee free-text). A keyword map
 * needs no model, adds zero dependencies, and is PHI-safe by construction —
 * nothing leaves the device — so it stands in until the LLM slice lands behind
 * its ADR. Output is JSON weights + a short label, never free text (ADR-0005).
 *
 * Swapping in the real driver later is contract-preserving: only the body of
 * `inferBaseline` changes.
 */

interface Mood {
  label: string;
  keywords: ReadonlyArray<string>;
  weights: BlendshapeWeights;
}

// Priority order resolves ties: earlier entries win. Pain and fear are the
// most clinically salient affects in a patient sim, so they rank first.
const MOODS: ReadonlyArray<Mood> = [
  {
    label: 'pain',
    keywords: ['hurt', 'hurts', 'hurting', 'pain', 'painful', 'ache', 'aching',
      'sore', 'agony', 'burning', 'stabbing', 'throbbing', 'ouch', 'ow'],
    weights: {
      browDownLeft: 0.5, browDownRight: 0.5, browInnerUp: 0.3,
      eyeSquintLeft: 0.55, eyeSquintRight: 0.55,
      mouthFrownLeft: 0.4, mouthFrownRight: 0.4,
      mouthStretchLeft: 0.35, mouthStretchRight: 0.35, jawOpen: 0.1,
    },
  },
  {
    label: 'fear',
    keywords: ['scared', 'afraid', 'fear', 'terrified', 'panic', 'panicking',
      'anxious', 'worried', 'nervous', 'frightened'],
    weights: {
      browInnerUp: 0.6, browOuterUpLeft: 0.35, browOuterUpRight: 0.35,
      eyeWideLeft: 0.5, eyeWideRight: 0.5,
      mouthStretchLeft: 0.3, mouthStretchRight: 0.3, jawOpen: 0.15,
    },
  },
  {
    label: 'anger',
    keywords: ['angry', 'mad', 'furious', 'rage', 'annoyed', 'irritated',
      'frustrated', 'frustrating'],
    weights: {
      browDownLeft: 0.7, browDownRight: 0.7,
      noseSneerLeft: 0.4, noseSneerRight: 0.4,
      mouthPressLeft: 0.45, mouthPressRight: 0.45,
      eyeSquintLeft: 0.3, eyeSquintRight: 0.3,
    },
  },
  {
    label: 'sad',
    keywords: ['sad', 'crying', 'cry', 'tears', 'depressed', 'hopeless',
      'miserable', 'grief', 'unhappy', 'upset'],
    weights: {
      browInnerUp: 0.6, mouthFrownLeft: 0.5, mouthFrownRight: 0.5,
      mouthLowerDownLeft: 0.2, mouthLowerDownRight: 0.2,
    },
  },
  {
    label: 'drowsy',
    keywords: ['dizzy', 'drowsy', 'sleepy', 'tired', 'faint', 'woozy',
      'groggy', 'lightheaded', 'exhausted'],
    weights: {
      eyeBlinkLeft: 0.35, eyeBlinkRight: 0.35, browInnerUp: 0.2,
      jawOpen: 0.08, mouthFrownLeft: 0.1, mouthFrownRight: 0.1,
    },
  },
  {
    label: 'relieved',
    keywords: ['better', 'great', 'relieved', 'relief', 'happy', 'glad',
      'wonderful', 'thank', 'thanks'],
    weights: {
      mouthSmileLeft: 0.5, mouthSmileRight: 0.5,
      cheekSquintLeft: 0.3, cheekSquintRight: 0.3,
      eyeSquintLeft: 0.2, eyeSquintRight: 0.2,
    },
  },
];

const WORD = /[a-z']+/g;

/** Pick the highest-scoring mood by keyword hits; null when nothing matches. */
function classify(input: EmotionInput): Mood | null {
  const hay = [input.text, ...(input.context ?? [])].join(' ').toLowerCase();
  const tokens = new Set(hay.match(WORD) ?? []);
  let best: Mood | null = null;
  let bestScore = 0;
  for (const mood of MOODS) {
    let score = 0;
    for (const kw of mood.keywords) if (tokens.has(kw)) score++;
    if (score > bestScore) { bestScore = score; best = mood; }
  }
  return bestScore > 0 ? best : null;
}

export function createImpl(): EmotionDriverModule {
  let _deps: BootDeps | null = null;
  return {
    async boot(deps) { _deps = deps; },
    dispose() { _deps = null; },

    async warmup() {
      // Local lexicon — nothing to load. The transformers.js path would warm
      // its model here (deferred, ADR-0005).
    },

    async inferBaseline(input: EmotionInput) {
      void _deps;
      const mood = classify(input);
      if (!mood) return { label: 'neutral', weights: {} };
      return { label: mood.label, weights: { ...mood.weights } };
    },
  };
}
