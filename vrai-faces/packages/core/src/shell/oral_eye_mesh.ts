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
const TEETH_SPLIT = tuneNum('tsplit', -4.45); // classify a WHOLE tooth: upper if its centroid y ≥ this, else lower
const TEETH_RISE = tuneNum('trise', 0.0);    // manual nudge (canonical) on top of the auto bite→lip-centroid alignment
const TEETH_FOLLOW_UP = tuneNum('tfup', 1.0); // how much the UPPER teeth track the upper-lip morph displacement
const TEETH_FOLLOW_LO = tuneNum('tflo', 1.0); // how much the LOWER teeth track the lower-lip (jaw) morph displacement
const TEETH_LIT = tuneNum('tlit', 1.0);      // teeth self-illumination — scene lights don't reach inside the mouth,
                                             // so without this only the 2 frontmost crowns (catching leak-light) read

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

function buildGroupGeometry(g: Group, fit: Fit, yRiseCanon = 0): THREE.BufferGeometry {
  const zRecess = ORAL_Z * fit.faceH;
  const p = new Float32Array(g.vertexCount * 3);
  for (let i = 0; i < g.vertexCount; i++) {
    p[i * 3] = ((g.positions[i * 3] ?? 0) - fit.c[0]) * fit.s + fit.l[0];
    p[i * 3 + 1] = ((g.positions[i * 3 + 1] ?? 0) + yRiseCanon - fit.c[1]) * fit.s + fit.l[1] + ORAL_Y * fit.faceH;
    p[i * 3 + 2] = ((g.positions[i * 3 + 2] ?? 0) - fit.c[2]) * fit.s + fit.l[2] - zRecess;
  }
  const geo = new THREE.BufferGeometry();
  geo.setAttribute('position', new THREE.BufferAttribute(p, 3));
  geo.setIndex(g.indices);
  geo.computeVertexNormals();
  return geo;
}

/**
 * Group a teeth mesh's triangles into UPPER (maxilla) vs LOWER (mandible) WHOLE teeth. A flat Y-cut
 * slices through the middle of every crown — blocky slabs, severed biting edges, a lopsided split (the
 * failure we saw). Instead: find connected components (= individual teeth, the ICT arch is 32 separate
 * teeth) and assign each WHOLE tooth to a set by its centroid Y. Crowns + biting edges stay intact, so
 * the jaw can pull the lower row away cleanly. Runtime + no re-bake; the shipped crowns hold both arches.
 */
function splitTeethByComponent(g: Group, splitY: number): { upper: Group; lower: Group } {
  const vc = g.vertexCount;
  const parent = new Int32Array(vc);
  for (let i = 0; i < vc; i++) parent[i] = i;
  const find = (a: number): number => {
    let r = a;
    while (parent[r]! !== r) r = parent[r]!;
    while (parent[a]! !== r) { const nx = parent[a]!; parent[a] = r; a = nx; } // path-compress
    return r;
  };
  for (let t = 0; t + 2 < g.indices.length; t += 3) {
    const a = g.indices[t]!, b = g.indices[t + 1]!, c = g.indices[t + 2]!;
    parent[find(a)] = find(b);
    parent[find(a)] = find(c);
  }
  // Per-component centroid Y → classify each whole tooth as upper/lower once.
  const sumY = new Map<number, number>();
  const cnt = new Map<number, number>();
  for (let v = 0; v < vc; v++) {
    const r = find(v);
    sumY.set(r, (sumY.get(r) ?? 0) + (g.positions[v * 3 + 1] ?? 0));
    cnt.set(r, (cnt.get(r) ?? 0) + 1);
  }
  const rootIsUpper = new Map<number, boolean>();
  for (const [r, sy] of sumY) rootIsUpper.set(r, sy / (cnt.get(r) || 1) >= splitY);
  const build = (wantUpper: boolean): Group => {
    const remap = new Map<number, number>();
    const positions: number[] = [];
    const indices: number[] = [];
    for (let t = 0; t + 2 < g.indices.length; t += 3) {
      const tri = [g.indices[t]!, g.indices[t + 1]!, g.indices[t + 2]!];
      if ((rootIsUpper.get(find(tri[0]!)) ?? false) !== wantUpper) continue; // whole tooth → one set
      for (const vi of tri) {
        let nv = remap.get(vi);
        if (nv === undefined) {
          nv = positions.length / 3;
          remap.set(vi, nv);
          positions.push(g.positions[vi * 3] ?? 0, g.positions[vi * 3 + 1] ?? 0, g.positions[vi * 3 + 2] ?? 0);
        }
        indices.push(nv);
      }
    }
    return { vertexCount: positions.length / 3, positions, indices };
  };
  return { upper: build(true), lower: build(false) };
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
  const teeth = DATA.groups['teeth'];
  const enamel = PARTS[0];
  if (teeth && enamel) {
    const makeTeeth = (g: Group, rise: number): THREE.Mesh => {
      const mat = new THREE.MeshStandardMaterial({
        color: enamel.color, roughness: enamel.roughness, metalness: 0,
        // The 3 directional scene lights are occluded by the lips and the ambient is near-black, so the
        // mouth interior is unlit — only the 2 frontmost crowns catch leak-light. The teeth must light
        // THEMSELVES to read as a full arch through the dark cavity + translucent face. enamel.emissive
        // (~0x55) was far too dim; this self-illuminates the whole arch (tune live with &tlit=).
        emissive: 0xbeb4a0,
        emissiveIntensity: TEETH_LIT,
        transparent: false,  // OPAQUE — shows through the translucent face's transmission (findings §5)
        depthWrite: true,
      });
      const m = new THREE.Mesh(buildGroupGeometry(g, fit, rise), mat);
      faceMesh.add(m);  // child of the face → inherits its transform
      meshes.push(m);
      mats.push(mat);
      return m;
    };
    // RB-003 jaw-follow: split the ICT arch into the maxilla (upper, fixed) + mandible (lower, hinges
    // down with jawOpen) by WHOLE tooth, so the open mouth shows an upper row above a separating lower row.
    const { upper, lower } = splitTeethByComponent(teeth, TEETH_SPLIT);
    // Auto-align the closed bite (occlusion) to the lip centroid. The ICT occlusal plane lands ~0.35
    // BELOW the MediaPipe inner-lip centre, so uncorrected the upper crowns hang past the opening (buck
    // teeth) while the lower crowns sit behind the chin (never seen). The occlusion is where the upper
    // set's biting edges (its min-Y) meet the lower set's (its max-Y); raise both so that meets the lip.
    let uMinY = Infinity, lMaxY = -Infinity;
    for (let i = 0; i < upper.vertexCount; i++) { const y = upper.positions[i * 3 + 1] ?? 0; if (y < uMinY) uMinY = y; }
    for (let i = 0; i < lower.vertexCount; i++) { const y = lower.positions[i * 3 + 1] ?? 0; if (y > lMaxY) lMaxY = y; }
    const occlusionY = Number.isFinite(uMinY) && Number.isFinite(lMaxY) ? (uMinY + lMaxY) / 2 : fit.c[1];
    const riseCanon = (fit.c[1] - occlusionY) + TEETH_RISE;
    const upperMesh = makeTeeth(upper, riseCanon); // maxilla — rides the upper inner lip
    const lowerMesh = makeTeeth(lower, riseCanon); // mandible — rides the lower inner lip (drops with jaw)
    // RB-003: the teeth FOLLOW THE LIP MESH (the user's request) rather than a fixed drop — the upper arch
    // rides the upper inner lip, the lower arch rides the lower inner lip, so they move with the mouth +
    // jaw. Each frame we recompute the lip vert's MORPHED displacement on the CPU (Σ influence·delta — the
    // same sum the vertex shader runs; with relative morphs, displacement-from-neutral IS that sum) and
    // offset the arch by it (face-local). The lower lip drops with jawOpen → the lower teeth drop with it.
    const UPPER_INNER_LIP = 13, LOWER_INNER_LIP = 14; // MediaPipe inner-lip centre verts (upper / lower)
    const morphs = faceMesh.geometry.morphAttributes['position'] as THREE.BufferAttribute[] | undefined;
    const lipFollow = (mesh: THREE.Mesh, vi: number, gain: number): void => {
      mesh.onBeforeRender = (): void => {
        const infl = faceMesh.morphTargetInfluences;
        let dx = 0, dy = 0, dz = 0;
        if (morphs && infl) {
          for (let m = 0; m < morphs.length; m++) {
            const w = infl[m] ?? 0;
            if (w === 0) continue;
            const d = morphs[m]!;
            dx += w * d.getX(vi); dy += w * d.getY(vi); dz += w * d.getZ(vi);
          }
        }
        mesh.position.set(dx * gain, dy * gain, dz * gain);
      };
    };
    lipFollow(upperMesh, UPPER_INNER_LIP, TEETH_FOLLOW_UP);
    lipFollow(lowerMesh, LOWER_INNER_LIP, TEETH_FOLLOW_LO);
  }

  return {
    dispose(): void {
      for (const m of meshes) { faceMesh.remove(m); m.geometry.dispose(); }
      for (const mt of mats) mt.dispose();
    },
  };
}
