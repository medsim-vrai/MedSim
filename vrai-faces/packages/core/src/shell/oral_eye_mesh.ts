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
import meshData from './oral_eye_mesh.json';

interface Group { vertexCount: number; positions: number[]; indices: number[]; }
interface OralEyeData { canonicalHeight: number; canonical468: number[]; groups: Record<string, Group>; }
const DATA = meshData as unknown as OralEyeData;

// MediaPipe inner-lip ring — the mouth anchor for the canonical→live fit (matches oral_cavity).
const MOUTH_IDX: ReadonlyArray<number> = [
  78, 95, 88, 178, 87, 14, 317, 402, 318, 324, 308, 415, 310, 311, 312, 13, 82, 81, 80, 191,
];

// Per-part look + placement (tunable on-device).
const PARTS: ReadonlyArray<{ key: string; color: number; roughness: number }> = [
  { key: 'gumsTongue', color: 0x8a3f3a, roughness: 0.6 },  // dark pink-red mucosa
  { key: 'teeth', color: 0xe8e1d0, roughness: 0.35 },      // off-white enamel
];
const ORAL_SCALE = 1.0;   // fudge on the mouth-fit scale (↑ bigger teeth)
const ORAL_Z = 0.05;      // recess back behind the lip plane (× live face height) so teeth/gums don't
                          // poke through the closed lips; 0.08 hid them entirely, 0 poked through. ↑ = back

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
    p[i * 3 + 1] = ((g.positions[i * 3 + 1] ?? 0) - fit.c[1]) * fit.s + fit.l[1];
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
export function mountOralEyeMesh(faceMesh: THREE.Mesh): OralEyeHandle | null {
  const pos = faceMesh.geometry.getAttribute('position') as THREE.BufferAttribute | undefined;
  if (!pos) return null;
  const fit = fitMouth(DATA.canonical468, pos);
  if (!fit) return null;

  const meshes: THREE.Mesh[] = [];
  const mats: THREE.Material[] = [];
  for (const part of PARTS) {
    const g = DATA.groups[part.key];
    if (!g) continue;
    const mat = new THREE.MeshStandardMaterial({
      color: part.color, roughness: part.roughness, metalness: 0,
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
