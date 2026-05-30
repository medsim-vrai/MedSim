import type { FaceIngestModule, NormalizedPortrait } from '@contracts/face_ingest';
import type { BootDeps } from '@contracts/shared';

/**
 * Square crop + RGB strip-alpha + hash. EXIF rotation is handled
 * automatically by `createImageBitmap({ imageOrientation: 'from-image' })`
 * — iOS Safari 16+ supports this; older browsers see correct pixels but
 * the orientation flag may be ignored (acceptable degradation).
 *
 * Real face-bbox detection lives in `mesh_builder` (it already loads
 * MediaPipe). At ingest time we report the full image as the bbox and
 * let the next stage refine.
 */
const TARGET_SIZE = 512;

async function loadBitmap(input: File | Blob): Promise<ImageBitmap> {
  return createImageBitmap(input, {
    imageOrientation: 'from-image',
    premultiplyAlpha: 'none',
    colorSpaceConversion: 'default',
  });
}

function squareCrop(bm: ImageBitmap): { sx: number; sy: number; size: number } {
  const size = Math.min(bm.width, bm.height);
  const sx = Math.floor((bm.width  - size) / 2);
  const sy = Math.floor((bm.height - size) / 2);
  return { sx, sy, size };
}

/**
 * Render to a 512×512 OffscreenCanvas, fill black first (strips alpha
 * cleanly), then draw the centered square crop scaled to fit. Returns
 * a PNG Blob.
 */
async function normalizeToPng(bm: ImageBitmap): Promise<Blob> {
  const { sx, sy, size } = squareCrop(bm);
  const canvas = typeof OffscreenCanvas !== 'undefined'
    ? new OffscreenCanvas(TARGET_SIZE, TARGET_SIZE)
    : (() => {
        const c = document.createElement('canvas');
        c.width = TARGET_SIZE; c.height = TARGET_SIZE;
        return c;
      })();

  const ctx = canvas.getContext('2d') as
    | CanvasRenderingContext2D
    | OffscreenCanvasRenderingContext2D
    | null;
  if (!ctx) throw new Error('face_ingest: 2d context unavailable');
  // Black background — strips alpha when source has it.
  ctx.fillStyle = '#000';
  ctx.fillRect(0, 0, TARGET_SIZE, TARGET_SIZE);
  ctx.drawImage(bm, sx, sy, size, size, 0, 0, TARGET_SIZE, TARGET_SIZE);

  if ('convertToBlob' in canvas) {
    return canvas.convertToBlob({ type: 'image/png' });
  }
  return new Promise<Blob>((resolve, reject) => {
    (canvas as HTMLCanvasElement).toBlob(
      (b) => (b ? resolve(b) : reject(new Error('face_ingest: toBlob returned null'))),
      'image/png',
    );
  });
}

/**
 * A stable hex hash of the normalized PNG, used ONLY as a cache key (mesh_builder
 * keys its built mesh on it) — never for security. Prefers SHA-256 via
 * SubtleCrypto, but falls back to a fast non-crypto hash when `crypto.subtle` is
 * unavailable.
 *
 * That fallback is essential on a tablet: the device loads the app over a plain
 * `http://<LAN-IP>` origin, which is NOT a secure context, so `window.crypto.subtle`
 * is `undefined`. Calling it threw, which took down the WHOLE avatar build (demo
 * AND bound) — the "demo avatar build failed" we saw on the device.
 */
async function portraitHashHex(blob: Blob): Promise<string> {
  const buf = await blob.arrayBuffer();
  const subtle = globalThis.crypto?.subtle;
  if (subtle) {
    try {
      const digest = await subtle.digest('SHA-256', buf);
      const bytes = new Uint8Array(digest);
      let out = '';
      for (let i = 0; i < bytes.length; i++) {
        out += bytes[i]!.toString(16).padStart(2, '0');
      }
      return out;
    } catch {
      // Secure-context check passed but digest failed — fall through.
    }
  }
  // Non-crypto 64-bit FNV-1a (two 32-bit lanes, forward + reverse for spread).
  // Collisions are astronomically unlikely for distinct portraits and would only
  // reuse a cached mesh — acceptable for this insecure-context fallback path.
  const view = new Uint8Array(buf);
  let a = 0x811c9dc5;
  let b = 0x811c9dc5;
  for (let i = 0; i < view.length; i++) {
    a = Math.imul(a ^ view[i]!, 0x01000193);
    b = Math.imul(b ^ view[view.length - 1 - i]!, 0x01000193);
  }
  const hex = (n: number): string => (n >>> 0).toString(16).padStart(8, '0');
  return `fnv1a-${hex(a)}${hex(b)}`;
}

export function createImpl(): FaceIngestModule {
  let _deps: BootDeps | null = null;

  return {
    async boot(deps) { _deps = deps; },

    dispose() { _deps = null; },

    async ingest(input: File | Blob): Promise<NormalizedPortrait> {
      void _deps;
      const bm = await loadBitmap(input);
      try {
        const png = await normalizeToPng(bm);
        const hash = await portraitHashHex(png);
        return {
          png,
          width: TARGET_SIZE,
          height: TARGET_SIZE,
          // bbox set to full image until mesh_builder refines it with MediaPipe.
          faceBbox: { x: 0, y: 0, w: TARGET_SIZE, h: TARGET_SIZE },
          hash,
        };
      } finally {
        bm.close();
      }
    },
  };
}
