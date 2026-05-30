import type { EmotionDriverModule, EmotionInput } from '@contracts/emotion_driver';
import type { BlendshapeWeights, BootDeps } from '@contracts/shared';

/**
 * HYBRID emotion driver (ADR-0019, ratified):
 *   1. CLINICAL OVERRIDE — a lexicon detects pain / drowsiness, which general
 *      emotion models have no label for; these are the most clinically salient
 *      affects in a patient sim, so they win outright.
 *   2. MODEL — an on-device transformers.js text-classification model maps the
 *      utterance to a general emotion (handles paraphrase / negation / intensity
 *      a keyword map can't). Loaded in `warmup()`, never on the hot path.
 *   3. LEXICON FALLBACK — when the model isn't loaded (no warmup, non-browser,
 *      load failure) the full keyword lexicon stands in, so behavior degrades
 *      gracefully and is deterministic.
 *
 * Output is always JSON weights + a short label, never free text (ADR-0005). The
 * model + tokenizer load via @huggingface/transformers (already a dependency);
 * a DYNAMIC import keeps it in its own code-split chunk, out of the test graph.
 * Cloud Claude stays a per-scenario opt-in for v1.1 (ADR-0014 fail-closed PHI).
 */

interface Mood {
  label: string;
  keywords: ReadonlyArray<string>;
  weights: BlendshapeWeights;
  /** Clinical affects (pain/drowsy) override the model; general affects don't. */
  clinical?: boolean;
}

// Priority order resolves ties: earlier entries win.
const MOODS: ReadonlyArray<Mood> = [
  {
    label: 'pain', clinical: true,
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
    label: 'drowsy', clinical: true,
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

const MOOD_BY_LABEL = new Map(MOODS.map((m) => [m.label, m]));
const WORD = /[a-z']+/g;

/** Highest-scoring mood by keyword hits; `clinicalOnly` restricts to pain/drowsy. */
function classify(input: EmotionInput, clinicalOnly = false): Mood | null {
  const hay = [input.text, ...(input.context ?? [])].join(' ').toLowerCase();
  const tokens = new Set(hay.match(WORD) ?? []);
  let best: Mood | null = null;
  let bestScore = 0;
  for (const mood of MOODS) {
    if (clinicalOnly && !mood.clinical) continue;
    let score = 0;
    for (const kw of mood.keywords) if (tokens.has(kw)) score++;
    if (score > bestScore) { bestScore = score; best = mood; }
  }
  return bestScore > 0 ? best : null;
}

/**
 * Map a model emotion label onto one of our moods. Covers the Ekman set and the
 * GoEmotions vocabulary; anything unmapped (incl. 'neutral') yields null → neutral.
 */
const LABEL_TO_MOOD: Readonly<Record<string, string>> = {
  joy: 'relieved', happiness: 'relieved', admiration: 'relieved', amusement: 'relieved',
  gratitude: 'relieved', relief: 'relieved', excitement: 'relieved', love: 'relieved',
  optimism: 'relieved', approval: 'relieved', caring: 'relieved', pride: 'relieved',
  anger: 'anger', annoyance: 'anger', disapproval: 'anger', disgust: 'anger',
  fear: 'fear', nervousness: 'fear',
  sadness: 'sad', grief: 'sad', disappointment: 'sad', remorse: 'sad', embarrassment: 'sad',
};

export function moodForLabel(label: string): Mood | null {
  const key = LABEL_TO_MOOD[label.toLowerCase()];
  return key ? MOOD_BY_LABEL.get(key) ?? null : null;
}

/** Minimal callable view of a transformers.js text-classification pipeline. */
interface TextClassifier {
  (text: string, options?: { top_k?: number }): Promise<unknown>;
}

/** The on-device model (HF id; bundled local-first via setup:assets — Phase 3). */
const EMOTION_MODEL = 'SamLowe/roberta-base-go_emotions-onnx';

async function loadClassifier(): Promise<TextClassifier | null> {
  try {
    const { pipeline } = await import('@huggingface/transformers');
    const pipe = await pipeline('text-classification', EMOTION_MODEL, { dtype: 'q8' });
    return (text, options) => pipe(text, options);
  } catch {
    return null; // non-browser/Node-without-runtime, missing model, etc. → lexicon
  }
}

/** Pull the top {label} out of transformers.js's loosely-typed output. */
export function topLabel(raw: unknown): string | null {
  const first = Array.isArray(raw) ? raw[0] : raw;
  if (first && typeof first === 'object' && 'label' in first) {
    const label = (first as { label: unknown }).label;
    if (typeof label === 'string') return label;
  }
  return null;
}

function result(mood: Mood | null): { label: string; weights: BlendshapeWeights } {
  return mood ? { label: mood.label, weights: { ...mood.weights } } : { label: 'neutral', weights: {} };
}

export function createImpl(): EmotionDriverModule {
  let _deps: BootDeps | null = null;
  let classifier: TextClassifier | null = null;

  return {
    async boot(deps) { _deps = deps; },
    dispose() { _deps = null; classifier = null; },

    async warmup() {
      classifier = await loadClassifier();   // off the hot path; null ⇒ lexicon-only
    },

    async inferBaseline(input: EmotionInput) {
      void _deps;
      // 1. Clinical override — the model can't see pain/drowsy.
      const clinical = classify(input, true);
      if (clinical) return result(clinical);

      // 2. Model for general affect, when warmed.
      if (classifier) {
        try {
          const label = topLabel(await classifier(input.text, { top_k: 1 }));
          if (label) return result(moodForLabel(label));
        } catch {
          /* fall through to the lexicon */
        }
      }

      // 3. Lexicon fallback (deterministic).
      return result(classify(input));
    },
  };
}
