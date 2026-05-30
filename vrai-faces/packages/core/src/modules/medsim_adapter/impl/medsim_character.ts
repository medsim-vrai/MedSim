import { z } from 'zod';
import type { TtsVoiceId } from '@contracts/shared';

/**
 * The REAL MedSim V8 character card — `medsim_v8/schemas/character.json` (§9
 * confirmed). This is the canonical shape the portal sends; the adapter validates
 * against it.
 *
 * NOTE: the card carries NO portrait and NO ARKit weights. The avatar's
 * `sourcePhoto` is attached at launch (the portal merges a portrait into the
 * payload — Phase 4.3), and per-utterance mood is owned by `emotion_driver`. So
 * we map only what the card actually provides: `id` and `voice_profile`.
 * `.passthrough()` tolerates extra fields (an attached portrait, scope_of_action…).
 */
export const characterCardSchema = z
  .object({
    id: z.string().min(1),
    name: z.string(),
    role: z.string(),
    voice: z.object({
      register: z.string(),
      sentence_length: z.enum(['short', 'medium', 'long']).optional(),
      examples: z.array(z.string()),
      never_says: z.array(z.string()).optional(),
    }),
    knowledge_boundary: z.string(),
    scene_contract: z.array(z.string()),
    identity: z.object({ mood_today: z.string().optional() }).passthrough().optional(),
    voice_profile: z
      .object({
        gender: z.enum(['female', 'male', 'neutral']).optional(),
        language: z.string().optional(),
        pitch: z.number().optional(),
        rate: z.number().optional(),
        voice_hints: z.array(z.string()).optional(),
      })
      .optional(),
  })
  .passthrough();

export type CharacterCard = z.infer<typeof characterCardSchema>;

/** Validate a real MedSim character card; null if it doesn't match (fail-closed). */
export function parseCharacterCard(raw: unknown): CharacterCard | null {
  const out = characterCardSchema.safeParse(raw);
  return out.success ? out.data : null;
}

/**
 * Map a card's `voice_profile` → a stable `TtsVoiceId`. Encodes gender (so the
 * TTS layer can pick a matching voice) with the first voice hint (or language)
 * riding along. Deterministic per character.
 */
export function voiceIdFromProfile(vp: CharacterCard['voice_profile']): TtsVoiceId {
  const gender = vp?.gender ?? 'neutral';
  const hint = vp?.voice_hints?.[0] ?? vp?.language ?? 'en-US';
  return `${gender}:${hint}` as TtsVoiceId;
}
