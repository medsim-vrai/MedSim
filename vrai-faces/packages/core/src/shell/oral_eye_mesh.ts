// Real ICT-FaceKit oral mesh (teeth + gums/tongue) — RB-003 Phase-2 Item 3.
//
// Augments the procedural oral_cavity dome with REAL geometry: an open mouth (jawOpen) reveals actual
// teeth + tongue. The sub-meshes are baked in the MediaPipe CANONICAL frame
// (tools/morphbasis-bake/extract_oral_eye.py, from the LOCAL ICT head — MIT, no download). Here we fit
// the canonical mouth → the LIVE mouth (the shared MediaPipe inner-lip ring; centroid + uniform
// XY-scale, no rotation), so the teeth land + size to the portrait's mouth, and parent the result to
// the face. OPAQUE so it shows through the translucent face's transmission where the mouth opens
// (findings §5), like the cavity dome.
//
// The EYEBALLS (sclera/iris) are deliberately OMITTED: the full anatomical eyeball is much larger than
// the eye opening and bulges/protrudes, and the generic ICT iris clashes with the portrait — the
// texture eyes + the eyelid feather read better. (The groups remain in the JSON if revisited.)
//
// v1.1: STATIC placement + flat colours + on-device tuning knobs. Follow-up: drop the lower teeth/jaw
// with jawOpen.

import * as THREE from 'three/webgpu';

interface Group { vertexCount: number; positions: number[]; indices: number[]; }
interface OralEyeData { canonicalHeight: number; canonical468: number[]; groups: Record<string, Group>; }

// OPT-004: the ~444 KB mesh JSON is FETCHED at runtime (served from public/assets/face/) instead of
// `import`ed into the JS bundle — it was ~half the cold-load `index` chunk and parses slower as a JS
// object literal than as fetched JSON. Mirrors loadFaceTopology(); memoized so re-pairs reuse the parse.
const ORAL_EYE_MESH_URL = '/assets/face/oral_eye_mesh.json';
let _dataPromise: Promise<OralEyeData | null> | null = null;
function loadOralEyeData(): Promise<OralEyeData | null> {
  if (_dataPromise) return _dataPromise;
  _dataPromise = (async (): Promise<OralEyeData | null> => {
    try {
      if (typeof fetch !== 'function') return null;
      const res = await fetch(ORAL_EYE_MESH_URL);
      if (!res.ok) return null;
      const raw = (await res.json()) as Partial<OralEyeData> | null;
      if (!raw || !raw.groups || !Array.isArray(raw.canonical468)) return null;
      return raw as OralEyeData;
    } catch {
      return null;
    }
  })();
  return _dataPromise;
}

// MediaPipe inner-lip ring — the mouth anchor for the canonical→live fit (matches oral_cavity).
const MOUTH_IDX: ReadonlyArray<number> = [
  78, 95, 88, 178, 87, 14, 317, 402, 318, 324, 308, 415, 310, 311, 312, 13, 82, 81, 80, 191,
];

// Teeth ONLY. The ICT gums/tongue is a STATIC closed-mouth-config mass that occluded the teeth in the
// open mouth (the gum/tongue front sits over them) and poked through the philtrum — a static mesh can't
// open with the jaw. So for now: white teeth against the dark cavity dome (re-added in avatar_build).
// Real gums + tongue need the jaw-follow (split upper/lower, drop the lower jaw by jawOpen) — a v2.
// EMISSIVE keeps the teeth visible inside the shadowed (recessed) mouth (without it they read dark).
const PARTS: ReadonlyArray<{ key: string; color: number; roughness: number; emissive: number }> = [
  { key: 'teeth', color: 0xe8e1d0, roughness: 0.35, emissive: 0x55514a }, // enamel (self-lit, shows in dark mouth)
];

// On-device LIVE tuning (no rebuild): append e.g. `&oz=0.03&os=1.1&oy=-0.02` to the URL and reload.
function tuneNum(key: string, dflt: number): number {
  if (typeof location === 'undefined') return dflt;
  const m = (location.search + location.hash).match(new RegExp('[?&#]' + key + '=(-?[0-9.]+)'));
  if (!m || !m[1]) return dflt;
  const n = parseFloat(m[1]);
  return Number.isFinite(n) ? n : dflt;
}
const ORAL_SCALE = tuneNum('os', 1.0);  // mouth-fit scale fudge (↑ bigger teeth)
const ORAL_Z = tuneNum('oz', 0.015);    // recess behind the lip plane (× faceH). KEEP SMALL: the ICT
                                        // teeth are already ~2.55u behind the lip in the canonical frame,
                                        // so a big recess pushes the crowns BEHIND the cavity dome (which
                                        // then occludes them — why they vanished at 0.04+). ↑ = deeper
const ORAL_Y = tuneNum('oy', 0.0);      // vertical offset (× faceH); −down lowers the mesh off the philtrum

export interface OralEyeHandle { dispose(): void; }

interface Fit { c: readonly [number, number, number]; l: readonly [number, number, number]; s: number; faceH: number; }

/**
 * Similarity (centroid + uniform XY-scale, no rotation) mapping the canonical MOUTH onto the LIVE
 * mouth, over the shared inner-lip ring. XY-only scale because the landmark z is on a different scale
 * than x,y — z gets the same scale (the oral mesh is ~isotropic) plus the ORAL_Z recess at placement.
 */
function fitMouth(canon: number[], pos: THREE.BufferAttribute): Fit | null {
  const n = pos.count;
  if (n < 468 || canon.length < n * 3) return null;
  const idx = MOUTH_IDX.filter((i) => i < n);
  if (idx.length === 0) return null;
  let cx = 0, cy = 0, cz = 0, lx = 0, ly = 0, lz = 0;
  for (const i of idx) {
    cx += canon[i * 3] ?? 0; cy += canon[i * 3 + 1] ?? 0; cz += canon[i * 3 + 2] ?? 0;
    lx += pos.getX(i); ly += pos.getY(i); lz += pos.getZ(i);
  }
  const m = idx.length;
  cx /= m; cy /= m; cz /= m; lx /= m; ly /= m; lz /= m;
  let cs = 0, ls = 0;
  for (const i of idx) {
    const dcx = (canon[i * 3] ?? 0) - cx, dcy = (canon[i * 3 + 1] ?? 0) - cy;
    cs += dcx * dcx + dcy * dcy;                       // XY only
    const dlx = pos.getX(i) - lx, dly = pos.getY(i) - ly;
    ls += dlx * dlx + dly * dly;
  }
  const s = cs > 0 ? Math.sqrt(ls / cs) * ORAL_SCALE : 1;
  // live face height (for the z-recess unit) from the full mesh y-extent
  let yMin = Infinity, yMax = -Infinity;
  for (let i = 0; i < n; i++) { const y = pos.getY(i); if (y < yMin) yMin = y; if (y > yMax) yMax = y; }
  return { c: [cx, cy, cz], l: [lx, ly, lz], s, faceH: yMax - yMin };
}

function buildGroupGeometry(g: Group, fit: Fit): THREE.BufferGeometry {
  const zRecess = ORAL_Z * fit.faceH;
  const p = new Float32Array(g.vertexCount * 3);
  for (let i = 0; i < g.vertexCount; i++) {
    p[i * 3] = ((g.positions[i * 3] ?? 0) - fit.c[0]) * fit.s + fit.l[0];
    p[i * 3 + 1] = ((g.positions[i * 3 + 1] ?? 0) - fit.c[1]) * fit.s + fit.l[1] + ORAL_Y * fit.faceH;
    p[i * 3 + 2] = ((g.positions[i * 3 + 2] ?? 0) - fit.c[2]) * fit.s + fit.l[2] - zRecess;
  }
  const geo = new THREE.BufferGeometry();
  geo.setAttribute('position', new THREE.BufferAttribute(p, 3));
  geo.setIndex(g.indices);
  geo.computeVertexNormals();
  return geo;
}

/**
 * Attach the real oral mesh to a baked face mesh. Returns null (no-op) for a non-baked mesh
 * (head proxy / synthetic — no 468 topology) or a malformed asset.
 */
export async function mountOralEyeMesh(faceMesh: THREE.Mesh): Promise<OralEyeHandle | null> {
  const pos = faceMesh.geometry.getAttribute('position') as THREE.BufferAttribute | undefined;
  if (!pos) return null;
  const DATA = await loadOralEyeData();   // fetched + memoized (OPT-004); null on absence/error → no-op
  if (!DATA) return null;
  const fit = fitMouth(DATA.canonical468, pos);
  if (!fit) return null;

  const meshes: THREE.Mesh[] = [];
  const mats: THREE.Material[] = [];
  for (const part of PARTS) {
    const g = DATA.groups[part.key];
    if (!g) continue;
    const mat = new THREE.MeshStandardMaterial({
      color: part.color, roughness: part.roughness, metalness: 0,
      emissive: part.emissive,  // self-lit so the recessed mesh stays visible in the shadowed mouth
      transparent: false,  // OPAQUE — shows through the translucent face's transmission (findings §5)
      depthWrite: true,
    });
    const m = new THREE.Mesh(buildGroupGeometry(g, fit), mat);
    faceMesh.add(m);  // child of the face → inherits its transform; not framed/animated
    meshes.push(m);
    mats.push(mat);
  }

  return {
    dispose(): void {
      for (const m of meshes) { faceMesh.remove(m); m.geometry.dispose(); }
      for (const mt of mats) mt.dispose();
    },
  };
}
