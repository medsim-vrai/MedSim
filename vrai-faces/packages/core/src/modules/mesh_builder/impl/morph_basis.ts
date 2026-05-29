/**
 * PROCEDURAL blendshape-delta basis — an APPROXIMATION, not an ARKit rig.
 *
 * There is no off-the-shelf ARKit-52 → MediaPipe-468 deformation basis, so we
 * synthesize per-vertex deltas from the live mesh geometry using region rules
 * keyed off the face's bounding box (no hard-coded landmark indices, so it's
 * robust to the 468/478 split). Deltas are the FULL displacement at weight 1.0,
 * in the same normalized space as the geometry's positions, so they scale with
 * the face automatically.
 *
 * Coverage is intentionally PARTIAL — only shapes with a defensible geometric
 * rule are filled; the rest stay at zero (a real rig is the follow-up). The
 * highest-value shape for this product is `jawOpen` (it dominates lip-sync /
 * viseme motion). Pure + deterministic (ADR-0005 spirit); unit-tested by region.
 */

interface Bounds {
  minX: number; maxX: number; minY: number; maxY: number;
  cx: number; cy: number; w: number; h: number;
}

function computeBounds(positions: Float32Array, n: number): Bounds {
  let minX = Infinity, maxX = -Infinity, minY = Infinity, maxY = -Infinity;
  for (let i = 0; i < n; i++) {
    const x = positions[i * 3]!;
    const y = positions[i * 3 + 1]!;
    if (x < minX) minX = x;
    if (x > maxX) maxX = x;
    if (y < minY) minY = y;
    if (y > maxY) maxY = y;
  }
  return {
    minX, maxX, minY, maxY,
    cx: (minX + maxX) / 2, cy: (minY + maxY) / 2,
    w: maxX - minX, h: maxY - minY,
  };
}

/**
 * Build the 52 morph-target delta arrays (parallel to `names`), each a
 * `Float32Array(n*3)`. Unsupported shapes are returned all-zero.
 */
export function computeMorphBasis(
  positions: Float32Array,
  n: number,
  names: ReadonlyArray<string>,
): Float32Array[] {
  const basis: Float32Array[] = names.map(() => new Float32Array(n * 3));
  const b = computeBounds(positions, n);
  if (!(b.h > 0) || !(b.w > 0)) return basis; // degenerate mesh → all zero

  const slot = (name: string): Float32Array | null => {
    const i = names.indexOf(name);
    return i >= 0 ? basis[i]! : null;
  };
  const jawOpen = slot('jawOpen');
  const smileL = slot('mouthSmileLeft');
  const smileR = slot('mouthSmileRight');
  const browInnerUp = slot('browInnerUp');

  const mouthTop = b.cy - 0.05 * b.h;
  const mouthBot = b.cy - 0.32 * b.h;

  for (let i = 0; i < n; i++) {
    const x = positions[i * 3]!;
    const y = positions[i * 3 + 1]!;

    // jawOpen: the lower face swings down (+ a touch forward), ramping from the
    // vertical midline (0) to the chin (1).
    if (jawOpen && y < b.cy) {
      const t = (b.cy - y) / (b.cy - b.minY || 1);
      jawOpen[i * 3 + 1] = -0.18 * b.h * t;
      jawOpen[i * 3 + 2] = -0.03 * b.h * t;
    }

    // mouthSmile L/R: vertices in the mouth band move up-and-outward, strongest
    // mid-band and toward the sides. Split by which half of the face they're on.
    if ((smileL || smileR) && y <= mouthTop && y >= mouthBot) {
      const v = (y - mouthBot) / (mouthTop - mouthBot || 1);      // 0..1 in band
      const corner = Math.min(1, Math.abs(x - b.cx) / (0.35 * b.w));
      const amt = corner * (1 - Math.abs(0.5 - v) * 1.2);
      if (amt > 0) {
        if (x < b.cx && smileL) {
          smileL[i * 3] = -0.05 * b.w * amt;
          smileL[i * 3 + 1] = 0.06 * b.h * amt;
        } else if (x >= b.cx && smileR) {
          smileR[i * 3] = 0.05 * b.w * amt;
          smileR[i * 3 + 1] = 0.06 * b.h * amt;
        }
      }
    }

    // browInnerUp: the upper-center forehead/brow lifts.
    if (browInnerUp && y > b.cy + 0.22 * b.h && Math.abs(x - b.cx) < 0.18 * b.w) {
      browInnerUp[i * 3 + 1] = 0.045 * b.h;
    }
  }

  return basis;
}

/** Shapes `computeMorphBasis` currently fills (for docs/tests). The rest are zero. */
export const SUPPORTED_MORPHS: ReadonlyArray<string> = [
  'jawOpen', 'mouthSmileLeft', 'mouthSmileRight', 'browInnerUp',
];
