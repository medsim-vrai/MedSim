/**
 * Blendshape-delta basis for the 468-vertex face.
 *
 * REAL ARKit-52 rig (RB-001 / ADR-0034): `face_mesh_morphbasis.json` holds per-vertex
 * deltas baked offline by deformation-transferring USC ICT-FaceKit's MIT ARKit shapes onto
 * MediaPipe's Apache-2.0 canonical 468 topology (+ a derived `eyesClosed`/AU43). Deltas are
 * stored as FRACTIONS of the canonical face height, so they rescale to the live mesh.
 *
 * PROCEDURAL fallback: when the live mesh is NOT the baked topology (468/478) — synthetic
 * meshes, the head-proxy, unit tests — or for any name absent from the rig (`tongueOut`), we
 * fall back to geometry-driven region rules keyed off the bounding box (no landmark indices,
 * so it survives the 468/478 split). The highest-value shape is `jawOpen` (lip-sync).
 *
 * Pure + deterministic (ADR-0005). The baked asset is generation-time only (no runtime
 * model, nothing leaves the device — ADR-0001/0014). `avatar_exporter` bakes whatever deltas
 * exist by name, so the rig is a drop-in: no contract change.
 */
// OPT-004: the ~292 KB ARKit-52 basis is FETCHED at runtime (served from public/assets/face/) rather
// than `import`ed into the JS bundle — it was the other big slice of the cold-load `index` chunk and
// parses faster as JSON than as an inlined object literal. `BAKED` stays null until loadMorphBasis()
// resolves; computeMorphBasis falls back to the PROCEDURAL rig while null (graceful, matches the
// no-asset philosophy). The mesh build awaits the load before the real-path geometry build (create.ts),
// so the rig is present in practice. Mirrors loadFaceTopology().
export interface MorphBasisDoc {
  readonly version: number;
  readonly vertexCount: number;
  readonly canonicalHeight: number;
  readonly shapes: Readonly<Record<string, ReadonlyArray<ReadonlyArray<number>>>>;
}
const MORPH_BASIS_URL = '/assets/face/face_mesh_morphbasis.json';
let BAKED: MorphBasisDoc | null = null;
let _basisPromise: Promise<void> | null = null;

/** Inject the baked basis directly. The loader uses it; tests inject the JSON synchronously. */
export function setMorphBasis(doc: MorphBasisDoc | null): void {
  BAKED = doc;
}

/**
 * Rig-lab sandbox (DEFAULT OFF). `?rigBasis=<name>` (query OR hash) loads a candidate-repair basis
 * from `/assets/face/face_mesh_morphbasis.<name>.json`, so a fix to the rigid-landmark drift
 * (see the CN-rig audit) can be seen in the REAL Three.js runtime before it ever ships as the default.
 * `<name>` is restricted to `[a-z0-9]+`, so the flag cannot point the fetch anywhere but a sibling
 * asset (no path traversal, no cross-origin). Returns the URLs to try IN ORDER: the sandbox override
 * first, then the shipped basis — a missing or typo'd sandbox asset silently renders the real rig.
 * With no flag (production), this is exactly `[MORPH_BASIS_URL]` — the loader is byte-for-byte the old
 * single fetch.
 */
export function resolveBasisUrls(searchAndHash: string): string[] {
  const m = searchAndHash.match(/[?&#]rigBasis=([a-z0-9]+)/i);
  const name = m ? m[1]!.toLowerCase() : null;
  return name && name !== 'shipped'
    ? [`/assets/face/face_mesh_morphbasis.${name}.json`, MORPH_BASIS_URL]
    : [MORPH_BASIS_URL];
}

/**
 * Fetch + parse the baked ARKit rig once (memoized). No-op → procedural fallback on absence/error.
 * `searchAndHash` defaults to the live URL; it exists so tests (and an explicit override) can drive
 * the sandbox flag without touching `location`.
 */
export function loadMorphBasis(searchAndHash?: string): Promise<void> {
  if (_basisPromise) return _basisPromise;
  const qs = searchAndHash ?? (typeof location !== 'undefined' ? `${location.search}${location.hash}` : '');
  _basisPromise = (async (): Promise<void> => {
    if (typeof fetch !== 'function') return;
    for (const url of resolveBasisUrls(qs)) {
      try {
        const res = await fetch(url);
        if (!res.ok) continue; // 404 on a sandbox asset → fall through to the shipped basis
        const raw = (await res.json()) as Partial<MorphBasisDoc> | null;
        if (raw && raw.shapes && typeof raw.canonicalHeight === 'number') {
          BAKED = raw as MorphBasisDoc;
          if (url !== MORPH_BASIS_URL && typeof console !== 'undefined') {
            console.info(`[rig-lab] morph basis override active: ${url}`);
          }
          return;
        }
      } catch {
        // try the next candidate; if all fail, leave BAKED null → procedural rig
      }
    }
  })();
  return _basisPromise;
}

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

/** Procedural approximation (the pre-RB-001 basis) — fallback for non-baked meshes + tongueOut. */
function computeProceduralBasis(
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

    if (jawOpen && y < b.cy) {
      const t = (b.cy - y) / (b.cy - b.minY || 1);
      jawOpen[i * 3 + 1] = -0.18 * b.h * t;
      jawOpen[i * 3 + 2] = -0.03 * b.h * t;
    }

    if ((smileL || smileR) && y <= mouthTop && y >= mouthBot) {
      const v = (y - mouthBot) / (mouthTop - mouthBot || 1);
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

    if (browInnerUp && y > b.cy + 0.22 * b.h && Math.abs(x - b.cx) < 0.18 * b.w) {
      browInnerUp[i * 3 + 1] = 0.045 * b.h;
    }
  }
  return basis;
}

/**
 * Build the 52 morph-target delta arrays (parallel to `names`), each `Float32Array(n*3)`.
 *
 * On the real MediaPipe topology (n === 468 or 478) the baked ARKit-52 rig defines each shape;
 * otherwise — and for any name not in the rig (`tongueOut`) — the procedural fallback applies.
 */
export function computeMorphBasis(
  positions: Float32Array,
  n: number,
  names: ReadonlyArray<string>,
): Float32Array[] {
  const basis = computeProceduralBasis(positions, n, names);

  // Overlay the baked rig only on the topology it was baked for (face verts 0..467; a 478-vertex
  // iris mesh keeps its iris verts procedural/zero). Scale the canonical-height fractions to the
  // live face so the rig adapts to any face size, exactly like the procedural basis does.
  const baked = BAKED;                       // OPT-004: null until loadMorphBasis() → procedural fallback
  if (!baked) return basis;
  const onBakedTopology = (n === baked.vertexCount || n === 478) && baked.canonicalHeight > 0;
  if (!onBakedTopology) return basis;

  const b = computeBounds(positions, n);
  if (!(b.h > 0)) return basis;
  // The JSON deltas are FRACTIONS of the canonical face height (delta / canonicalHeight),
  // so rescaling to the live face is a SINGLE multiply by the live height. (A prior
  // `b.h / canonicalHeight` divided by canonicalHeight a second time, shrinking every
  // delta ~17x — influences were correct but the rig was invisible.)
  const scale = b.h;

  for (let i = 0; i < names.length; i++) {
    const sparse = baked.shapes[names[i]!];
    if (!sparse) continue;          // not in the rig (e.g. tongueOut) → keep the procedural delta
    const arr = basis[i]!;
    arr.fill(0);                    // the baked rig fully defines this shape
    for (const e of sparse) {
      const vi = e[0]!;
      if (vi >= 0 && vi < n) {
        arr[vi * 3] = e[1]! * scale;
        arr[vi * 3 + 1] = e[2]! * scale;
        arr[vi * 3 + 2] = e[3]! * scale;
      }
    }
  }
  return basis;
}

/** Names the BAKED rig defines (every ARKit-52 shape except tongueOut, + the eyesClosed supplement).
 *  A function now (was a const) because the basis loads asynchronously (OPT-004) — empty until loaded. */
export function bakedMorphNames(): ReadonlyArray<string> {
  return BAKED ? Object.keys(BAKED.shapes) : [];
}

/** Shapes the PROCEDURAL fallback fills (used when the baked rig is unavailable). */
export const SUPPORTED_MORPHS: ReadonlyArray<string> = [
  'jawOpen', 'mouthSmileLeft', 'mouthSmileRight', 'browInnerUp',
];
