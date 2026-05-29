import { z } from 'zod';

/**
 * Wire schema for VRAISpeechFrame (Memory_management.MD §6.2).
 * Bump the literal `v` when this breaks compatibility.
 */
export const frameSchema = z.object({
  v: z.literal(1),
  characterId: z.string(),
  seq: z.number().int(),
  audio: z.instanceof(ArrayBuffer).optional(),
  audioFormat: z.enum(['pcm16-24k', 'opus', 'mp3']).optional(),
  visemes: z
    .array(z.object({ t: z.number(), id: z.string(), w: z.number().min(0).max(1) }))
    .optional(),
  text: z.string().optional(),
  endOfUtterance: z.boolean().optional(),
  emotion: z
    .object({ label: z.string(), weights: z.record(z.string(), z.number()) })
    .optional(),
});

export type FrameSchemaT = z.infer<typeof frameSchema>;

export function parseFrame(raw: unknown): FrameSchemaT | null {
  const out = frameSchema.safeParse(raw);
  return out.success ? out.data : null;
}
