import * as THREE from 'three/webgpu';
import { computeMorphBasis } from './morph_basis';

/**
 * The canonical ARKit-52 blendshape names, in a fixed order. `avatar_exporter`
 * lints against this exact list, and MediaPipe's `outputFaceBlendshapes`
 * categories use these same `categoryName`s.
 */
export const ARKIT_52: ReadonlyArray<string> = [
  'browDownLeft', 'browDownRight', 'browInnerUp',
  'browOuterUpLeft', 'browOuterUpRight',
  'cheekPuff', 'cheekSquintLeft', 'cheekSquintRight',
  'eyeBlinkLeft', 'eyeBlinkRight',
  'eyeLookDownLeft', 'eyeLookDownRight',
  'eyeLookInLeft', 'eyeLookInRight',
  'eyeLookOutLeft', 'eyeLookOutRight',
  'eyeLookUpLeft', 'eyeLookUpRight',
  'eyeSquintLeft', 'eyeSquintRight',
  'eyeWideLeft', 'eyeWideRight',
  'jawForward', 'jawLeft', 'jawOpen', 'jawRight',
  'mouthClose', 'mouthDimpleLeft', 'mouthDimpleRight',
  'mouthFrownLeft', 'mouthFrownRight', 'mouthFunnel',
  'mouthLeft', 'mouthLowerDownLeft', 'mouthLowerDownRight',
  'mouthPressLeft', 'mouthPressRight', 'mouthPucker',
  'mouthRight', 'mouthRollLower', 'mouthRollUpper',
  'mouthShrugLower', 'mouthShrugUpper',
  'mouthSmileLeft', 'mouthSmileRight',
  'mouthStretchLeft', 'mouthStretchRight',
  'mouthUpperUpLeft', 'mouthUpperUpRight',
  'noseSneerLeft', 'noseSneerRight',
  'tongueOut',
];

/**
 * The mesh's actual morph targets: the canonical ARKit-52 + the supplemental
 * `eyesClosed` (AU43, RB-001/ADR-0034) — sustained lid closure for clinical pain
 * and drowsiness (distinct from the transient `eyeBlinkLeft/Right`, which idle_motion
 * drives). The baked basis (`face_mesh_morphbasis.json`) provides its delta; the
 * emotion_driver's pain/drowsy moods reference it.
 */
export const MORPH_TARGETS: ReadonlyArray<string> = [...ARKIT_52, 'eyesClosed'];

/** A 3D point — the structural subset of MediaPipe's `NormalizedLandmark`. */
export interface Landmark3 {
  x: number;
  y: number;
  z: number;
}

/**
 * The STATIC face-mesh CONNECTIVITY: the canonical triangle index list. This is
 * the only per-topology data we need bundled — vertex POSITIONS come from the
 * live landmarks (per identity) and UVs are derived from those same landmarks
 * (the portrait IS the detected image, so a vertex's UV is its normalized
 * landmark x,y). `loadFaceTopology` returns `null` until the asset is bundled
 * (local-first, ADR-0001), which makes `mesh_builder` fall back to the head
 * proxy. `vertexCount` is 468 (no irises) or 478 (with iris landmarks).
 */
export interface FaceTopology {
  /** Flat triangle index list; `length === 3 * triangleCount`. */
  indices: Uint32Array;
  /** Vertices this topology expects (468 or 478). */
  vertexCount: number;
}

/**
 * Where the bundled topology asset is served from. Local path (NOT a CDN) to
 * honor local-first (ADR-0001). Absent today → `loadFaceTopology` returns null.
 */
export const FACE_TOPOLOGY_URL = '/assets/face/face_mesh_topology.json';

/**
 * MediaPipe FaceMesh INNER-LIP ring indices (the mouth-opening contour). They mark
 * the per-vertex `innerMouth` mask (RB-003/ADR-0036) so `shader_translucent` can
 * darken the open mouth into a dark interior. Stable across the 468/478 split (the
 * iris verts are 468..477, lips unchanged).
 */
const INNER_LIP_RING: ReadonlyArray<number> = [
  78, 95, 88, 178, 87, 14, 317, 402, 318, 324,   // lower inner
  308, 415, 310, 311, 312, 13, 82, 81, 80, 191,  // upper inner
];

/**
 * Turn a set of MediaPipe landmarks + the canonical connectivity into a
 * morph-ready `BufferGeometry`. Pure (no GPU, no I/O) so it is unit-testable in
 * jsdom.
 *
 * MediaPipe landmarks are in normalized image space: x,y ∈ [0,1] with y pointing
 * DOWN, z a relative depth. POSITIONS recenter to the origin and flip Y so the
 * mesh sits in world space. UVS are the raw landmark (x,y): the texture is the
 * portrait the landmarks were detected on, and `buildTextureFromPortrait` sets
 * `flipY=false`, so image-top maps to v=0 with no flip. The 52 ARKit morph
 * attributes come from the PROCEDURAL basis (`computeMorphBasis`) — an
 * approximation that fills the geometrically-defensible shapes (jawOpen, smile,
 * brow) and leaves the rest zero, pending a real rig.
 */
export function buildFaceGeometry(
  landmarks: ReadonlyArray<Landmark3>,
  topo: FaceTopology,
): THREE.BufferGeometry {
  const n = topo.vertexCount;
  if (landmarks.length < n) {
    throw new Error(
      `buildFaceGeometry: need ≥ ${n} landmarks for this topology, got ${landmarks.length}`,
    );
  }

  const pos = new Float32Array(n * 3);
  const uv = new Float32Array(n * 2);
  for (let i = 0; i < n; i++) {
    const lm = landmarks[i]!;
    pos[i * 3] = lm.x - 0.5;        // [0,1] → [-0.5, 0.5]
    pos[i * 3 + 1] = 0.5 - lm.y;    // flip Y (image y-down → world y-up)
    pos[i * 3 + 2] = -lm.z;         // depth toward camera
    uv[i * 2] = lm.x;               // portrait projection (texture flipY=false)
    uv[i * 2 + 1] = lm.y;
  }

  const geo = new THREE.BufferGeometry();
  geo.setAttribute('position', new THREE.BufferAttribute(pos, 3));
  geo.setAttribute('uv', new THREE.BufferAttribute(uv, 2));
  geo.setIndex(new THREE.BufferAttribute(topo.indices, 1));
  geo.computeVertexNormals();

  // RB-003 Phase 1 (ADR-0036): per-vertex inner-mouth mask — 1 on the inner-lip ring,
  // 0 elsewhere. The stretched membrane triangles that span the open mouth connect
  // inner-lip verts, so they interpolate to ~1; shader_translucent darkens those
  // fragments by jawOpen → a dark interior instead of stretched lip texture.
  const innerMouth = new Float32Array(n);
  for (const li of INNER_LIP_RING) if (li < n) innerMouth[li] = 1;
  // Dilate the mask outward over TWO triangle-rings (weights 0.7, 0.45) onto the lip BODY around
  // the whole opening, so the inner-lip AND the stretched CORNERS (commissures) are covered when
  // the jaw drops — shader_translucent tints this region, so no bright photo texture (white) peeks,
  // including at the corners. The membrane (mask=1) stays darkest; the weights fall off to the lit
  // lip. (RB-003 follow-up — clear the corner/edge white; tint colours are refined separately.)
  const idx = topo.indices;
  const RING_WEIGHTS = [0.7, 0.45];
  let frontier = new Set<number>();
  for (const li of INNER_LIP_RING) if (li < n) frontier.add(li);
  for (const w of RING_WEIGHTS) {
    const next = new Set<number>();
    for (let t = 0; t + 2 < idx.length; t += 3) {
      const a = idx[t]!, b = idx[t + 1]!, c = idx[t + 2]!;
      if (!(frontier.has(a) || frontier.has(b) || frontier.has(c))) continue;
      if (innerMouth[a]! === 0) { innerMouth[a] = w; next.add(a); }
      if (innerMouth[b]! === 0) { innerMouth[b] = w; next.add(b); }
      if (innerMouth[c]! === 0) { innerMouth[c] = w; next.add(c); }
    }
    frontier = next;
  }
  geo.setAttribute('innerMouth', new THREE.BufferAttribute(innerMouth, 1));

  // 52 morph attributes from the procedural basis (jawOpen/smile/brow filled,
  // the rest zero), each sized to the real vertex count.
  const basis = computeMorphBasis(pos, n, MORPH_TARGETS);
  geo.morphAttributes.position = basis.map((arr) => new THREE.BufferAttribute(arr, 3));
  // RB-003 (ADR-0036): matching morph NORMALS, so a deformed mesh lights correctly. Without
  // these the geometry shipped position targets only — every blendshape moved vertices while
  // the shading stayed pinned to the NEUTRAL-pose normals. The high-deformation regions
  // (eyelids, lips, mouth, jaw) then shaded as if undeformed and read as dark, faceted, jagged
  // edges on EVERY expression — the artifact a per-feature texture/UV patch could never fix.
  geo.morphAttributes.normal = computeMorphNormals(geo, basis);
  // CRITICAL: the basis arrays are DELTAS (displacement from base), and most are
  // zero (only jawOpen/smile/brow filled). Without this flag Three treats them
  // as ABSOLUTE target positions, so any influence — including idle_motion's
  // zero-filled eye shapes — pulls every vertex toward the origin and scales the
  // whole head each frame. Relative = add the delta (zero ⇒ no movement).
  geo.morphTargetsRelative = true;
  geo.userData['morphTargetNames'] = [...MORPH_TARGETS];

  return geo;
}

/**
 * Per-shape morph NORMALS matching `morphAttributes.position` (RB-003 / ADR-0036).
 *
 * For each shape we recompute SMOOTH vertex normals on the deformed positions (base + delta —
 * the basis is in the same world units) over the shared index topology, then store the DELTA
 * (deformed − base) so it rides the existing `morphTargetsRelative` path:
 *   morphedNormal = baseNormal + Σ wᵢ·Δnᵢ   (re-normalized in-shader)
 * At full influence of one shape this collapses to exactly that shape's deformed normal; a
 * zero-displacement shape yields a zero normal delta (a true no-op). The temp geometry is
 * CPU-only (never uploaded), so this is a few ms at build time and frees on GC.
 *
 * Exported + geometry-based so BOTH builders (baked face + synthetic head-proxy) share it.
 */
export function computeMorphNormals(
  geo: THREE.BufferGeometry,
  basis: ReadonlyArray<Float32Array>,
): THREE.BufferAttribute[] {
  const posAttr = geo.getAttribute('position') as THREE.BufferAttribute | undefined;
  const normAttr = geo.getAttribute('normal') as THREE.BufferAttribute | undefined;
  if (!posAttr || !normAttr) {
    return basis.map((d) => new THREE.BufferAttribute(new Float32Array(d.length), 3));
  }
  const basePos = posAttr.array as Float32Array;
  const baseNormal = normAttr.array as Float32Array;
  const len = basePos.length;

  const tmp = new THREE.BufferGeometry();
  const deformed = new Float32Array(len);
  const tmpPos = new THREE.BufferAttribute(deformed, 3);
  tmp.setAttribute('position', tmpPos);
  const index = geo.getIndex();
  if (index) tmp.setIndex(index); // read-only share; computeVertexNormals never mutates the index

  return basis.map((delta) => {
    for (let k = 0; k < len; k++) deformed[k] = (basePos[k] ?? 0) + (delta[k] ?? 0);
    tmpPos.needsUpdate = true;
    tmp.computeVertexNormals();
    const dn = (tmp.getAttribute('normal') as THREE.BufferAttribute).array as Float32Array;
    const out = new Float32Array(len);
    for (let k = 0; k < len; k++) out[k] = (dn[k] ?? 0) - (baseNormal[k] ?? 0);
    return new THREE.BufferAttribute(out, 3);
  });
}

/**
 * Validate + convert a parsed JSON object into a `FaceTopology`. Returns null on
 * any shape mismatch (so a corrupt asset degrades to the fallback, never throws
 * into the build path). Pure; exported for unit testing.
 */
export function parseTopology(raw: unknown): FaceTopology | null {
  if (typeof raw !== 'object' || raw === null) return null;
  const obj = raw as Record<string, unknown>;

  const vertexCount = obj['vertexCount'];
  const indices = obj['indices'];
  if (typeof vertexCount !== 'number' || !Number.isInteger(vertexCount) || vertexCount <= 0) return null;
  if (!Array.isArray(indices)) return null;
  if (indices.length === 0 || indices.length % 3 !== 0) return null;

  const idx = new Uint32Array(indices.length);
  for (let i = 0; i < indices.length; i++) {
    const v: unknown = indices[i];
    if (typeof v !== 'number' || !Number.isInteger(v) || v < 0 || v >= vertexCount) return null;
    idx[i] = v;
  }

  return { indices: idx, vertexCount };
}

/**
 * Fetch + parse the bundled canonical connectivity. Returns null when the asset
 * is absent (today: always), when `fetch` is unavailable (jsdom), or on any
 * error — the caller falls back to the head proxy. Lives behind I/O so it stays
 * out of the pure-test path.
 */
export async function loadFaceTopology(): Promise<FaceTopology | null> {
  try {
    if (typeof fetch !== 'function') return null;
    const res = await fetch(FACE_TOPOLOGY_URL);
    if (!res.ok) return null;
    const raw: unknown = await res.json();
    return parseTopology(raw);
  } catch {
    return null;
  }
}
