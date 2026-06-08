// Real ICT-FaceKit oral (teeth + gums/tongue) + eye (sclera + iris) meshes — RB-003 Phase-2 Item 3.
//
// Augments the procedural oral_cavity dome with REAL geometry: an open mouth (jawOpen) now reveals
// actual teeth + tongue instead of a dark dome. The sub-meshes are baked in the MediaPipe CANONICAL
// frame (tools/morphbasis-bake/extract_oral_eye.py, from the LOCAL ICT head — MIT, no download). Here
// we fit canonical → the live portrait mesh (shared 468 topology; a centroid + uniform-scale similarity,
// no rotation) and parent the result to the face so it tracks the portrait + inherits its on-screen
// transform. OPAQUE (transparent:false) so it shows through the translucent face's transmission exactly
// where the mouth opens (findings §5) — the same rule that makes the cavity dome work.
//
// v1: STATIC placement (no jaw-follow yet) + flat per-part colours, tunable below. Follow-ups: drive the
// lower teeth/jaw by jawOpen, eye-look, and texture/colour-match the iris to the portrait.

import * as THREE from 'three/webgpu';
import meshData from './oral_eye_mesh.json';

interface Group { vertexCount: number; positions: number[]; indices: number[]; }
interface OralEyeData { canonicalHeight: number; canonical468: number[]; groups: Record<string, Group>; }
const DATA = meshData as unknown as OralEyeData;

// Per-part look (tunable on-device).
const PARTS: ReadonlyArray<{ key: string; color: number; roughness: number }> = [
  { key: 'gumsTongue', color: 0x9a4a45, roughness: 0.6 },  // pink-red mucosa
  { key: 'teeth', color: 0xe6dfce, roughness: 0.35 },      // off-white enamel
  { key: 'sclera', color: 0xe8e3d8, roughness: 0.3 },      // eye white
  { key: 'iris', color: 0x5d6e7a, roughness: 0.2 },        // muted blue-grey (TODO match portrait)
];

export interface OralEyeHandle { dispose(): void; }

interface Fit { c: readonly [number, number, number]; l: readonly [number, number, number]; s: number; }

/**
 * Best-fit similarity (centroid translation + uniform scale, no rotation) mapping the bundled canonical
 * 468 positions onto the LIVE 468-vertex portrait mesh. Both share the MediaPipe topology, so this maps
 * the whole canonical frame — and thus the oral/eye sub-meshes baked in it — onto the live face.
 */
function fitCanonicalToLive(canon: number[], pos: THREE.BufferAttribute): Fit | null {
  const n = pos.count;
  if (n < 468 || canon.length < n * 3) return null;       // live mesh must be the 468 topology
  let cx = 0, cy = 0, cz = 0, lx = 0, ly = 0, lz = 0;
  for (let i = 0; i < n; i++) {
    cx += canon[i * 3] ?? 0; cy += canon[i * 3 + 1] ?? 0; cz += canon[i * 3 + 2] ?? 0;
    lx += pos.getX(i); ly += pos.getY(i); lz += pos.getZ(i);
  }
  cx /= n; cy /= n; cz /= n; lx /= n; ly /= n; lz /= n;
  let cs = 0, ls = 0;
  for (let i = 0; i < n; i++) {
    const dcx = (canon[i * 3] ?? 0) - cx, dcy = (canon[i * 3 + 1] ?? 0) - cy, dcz = (canon[i * 3 + 2] ?? 0) - cz;
    cs += dcx * dcx + dcy * dcy + dcz * dcz;
    const dlx = pos.getX(i) - lx, dly = pos.getY(i) - ly, dlz = pos.getZ(i) - lz;
    ls += dlx * dlx + dly * dly + dlz * dlz;
  }
  const s = cs > 0 ? Math.sqrt(ls / cs) : 1;
  return { c: [cx, cy, cz], l: [lx, ly, lz], s };
}

function buildGroupGeometry(g: Group, fit: Fit): THREE.BufferGeometry {
  const p = new Float32Array(g.vertexCount * 3);
  for (let i = 0; i < g.vertexCount; i++) {
    p[i * 3] = ((g.positions[i * 3] ?? 0) - fit.c[0]) * fit.s + fit.l[0];
    p[i * 3 + 1] = ((g.positions[i * 3 + 1] ?? 0) - fit.c[1]) * fit.s + fit.l[1];
    p[i * 3 + 2] = ((g.positions[i * 3 + 2] ?? 0) - fit.c[2]) * fit.s + fit.l[2];
  }
  const geo = new THREE.BufferGeometry();
  geo.setAttribute('position', new THREE.BufferAttribute(p, 3));
  geo.setIndex(g.indices);
  geo.computeVertexNormals();
  return geo;
}

/**
 * Attach the real oral + eye meshes to a baked face mesh. Returns null (no-op) for a non-baked mesh
 * (head proxy / synthetic — no 468 topology) or if the asset is malformed.
 */
export function mountOralEyeMesh(faceMesh: THREE.Mesh): OralEyeHandle | null {
  const pos = faceMesh.geometry.getAttribute('position') as THREE.BufferAttribute | undefined;
  if (!pos) return null;
  const fit = fitCanonicalToLive(DATA.canonical468, pos);
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
