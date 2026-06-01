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
  // WS transport (ws.send_json) can't carry an ArrayBuffer, so the portal sends
  // server-synthesized audio as base64 here (ADR-0031); parseFrame hydrates it
  // into `audio`. The in-process BroadcastChannel transport may set `audio`
  // directly instead. Drop this from the schema and audio simply never arrives.
  audioB64: z.string().optional(),
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

/** Decode standard base64 → ArrayBuffer; null on malformed input. */
function b64ToArrayBuffer(b64: string): ArrayBuffer | null {
  try {
    const bin = atob(b64);
    const bytes = new Uint8Array(bin.length);
    for (let i = 0; i < bin.length; i += 1) bytes[i] = bin.charCodeAt(i);
    return bytes.buffer;
  } catch {
    return null;
  }
}

export function parseFrame(raw: unknown): FrameSchemaT | null {
  const out = frameSchema.safeParse(raw);
  if (!out.success) return null;
  const data = out.data;
  // WS path: hydrate the ArrayBuffer the rest of the app expects from base64.
  if (!data.audio && data.audioB64) {
    const buf = b64ToArrayBuffer(data.audioB64);
    if (buf) return { ...data, audio: buf };
  }
  return data;
}
