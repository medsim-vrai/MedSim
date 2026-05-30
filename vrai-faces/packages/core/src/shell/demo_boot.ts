// Boots a demo avatar end-to-end: synthesizes a placeholder portrait,
// runs it through face_ingest → mesh_builder → shader_translucent, and
// hands the result to the renderer.
//
// This is the fixture path. In production the binding comes from
// `medsim_adapter.bindFromCharacter(...)`; that wiring is parallel and
// will swap in once a scenario is bound. For now this lets the user
// see translucency working without uploading a photo.

import { buildAvatarFromBlob, type BuiltAvatar } from './avatar_build';
import type { RendererHandle } from './renderer';

const PORTRAIT_SIZE = 512;

/**
 * Procedurally generate a 512×512 portrait so the demo path has
 * something to ingest without external assets. The "face" is a warm
 * gradient circle with two eye dots and a mouth arc — recognizable as
 * face-ish when wrapped onto the placeholder sphere.
 */
function syntheticPortrait(): Promise<Blob> {
  const canvas = typeof OffscreenCanvas !== 'undefined'
    ? new OffscreenCanvas(PORTRAIT_SIZE, PORTRAIT_SIZE)
    : (() => {
        const c = document.createElement('canvas');
        c.width = PORTRAIT_SIZE; c.height = PORTRAIT_SIZE;
        return c;
      })();
  const ctx = canvas.getContext('2d') as
    | CanvasRenderingContext2D
    | OffscreenCanvasRenderingContext2D
    | null;
  if (!ctx) throw new Error('demo_boot: 2d context unavailable');

  // Background — soft neutral.
  ctx.fillStyle = '#1c1c22';
  ctx.fillRect(0, 0, PORTRAIT_SIZE, PORTRAIT_SIZE);

  // Skin gradient.
  const cx = PORTRAIT_SIZE / 2;
  const cy = PORTRAIT_SIZE / 2 + 16;
  const grad = ctx.createRadialGradient(cx, cy - 40, 30, cx, cy, PORTRAIT_SIZE * 0.45);
  grad.addColorStop(0.0, '#f3d6b8');
  grad.addColorStop(0.6, '#d6a986');
  grad.addColorStop(1.0, '#1c1c22');
  ctx.fillStyle = grad;
  ctx.beginPath();
  ctx.ellipse(cx, cy, PORTRAIT_SIZE * 0.36, PORTRAIT_SIZE * 0.44, 0, 0, Math.PI * 2);
  ctx.fill();

  // Eyes.
  ctx.fillStyle = '#1a1a1f';
  ctx.beginPath(); ctx.ellipse(cx - 70, cy - 30, 14, 8, 0, 0, Math.PI * 2); ctx.fill();
  ctx.beginPath(); ctx.ellipse(cx + 70, cy - 30, 14, 8, 0, 0, Math.PI * 2); ctx.fill();
  ctx.fillStyle = '#ffffff';
  ctx.beginPath(); ctx.ellipse(cx - 66, cy - 32, 3, 3, 0, 0, Math.PI * 2); ctx.fill();
  ctx.beginPath(); ctx.ellipse(cx + 74, cy - 32, 3, 3, 0, 0, Math.PI * 2); ctx.fill();

  // Mouth.
  ctx.strokeStyle = '#8a4a3c';
  ctx.lineWidth = 5;
  ctx.beginPath();
  ctx.arc(cx, cy + 70, 38, 0.1 * Math.PI, 0.9 * Math.PI);
  ctx.stroke();

  if ('convertToBlob' in canvas) {
    return canvas.convertToBlob({ type: 'image/png' });
  }
  return new Promise<Blob>((resolve, reject) => {
    (canvas as HTMLCanvasElement).toBlob(
      (b) => (b ? resolve(b) : reject(new Error('demo_boot: toBlob returned null'))),
      'image/png',
    );
  });
}

export type DemoBootResult = BuiltAvatar;

export async function bootDemoAvatar(renderer: RendererHandle): Promise<DemoBootResult> {
  const portraitBlob = await syntheticPortrait();
  // Start at level 0.66 — the table's mid-stop, where the look reads as
  // "translucent but recognizable" (good demo default).
  return buildAvatarFromBlob(renderer, portraitBlob, 0.66);
}
