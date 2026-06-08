// Procedural inner-mouth cavity ("mouth bag") — RB-003 Phase 1 / ADR-0036, findings §2(a).
//
// The 468-vertex face mesh has no interior, so an open mouth (jawOpen) exposes an empty
// void — today softened only by a shader darkening of the inner-lip texels. This adds a
// small OPAQUE concave dome behind the lip ring: invisible when the mouth is closed (scaled
// to ~0 and recessed behind the lip plane), growing into a dark recess as jawOpen rises.
//
// The single rule that makes this both cheap and correct (findings §5): the interior must be
// OPAQUE (`transparent:false`) — three.js `transmission` only refracts opaque geometry, so an
// opaque dome lands in the transmission backdrop and shows through the translucent face
// exactly where the mouth opens, automatically, whenever the slider raises transmission above
// 1.0. No renderOrder hack, no extra pass (the transmission pass is already paid). `BackSide`
// (concave, viewed from outside) is cheaper than DoubleSide and hides the near rim, so the
// dome can't poke forward through the closed-lip plane.
//
// A decimated ICT-FaceKit teeth/tongue/socket mesh is the Phase-2 fidelity upgrade (findings
// §2a); this is the $0, code-only, no-download Phase-1 cut. Reuses the oral_tongue.ts pattern.

import * as THREE from 'three/webgpu';

// MediaPipe inner-lip ring — locate the mouth from the neutral geometry (matches oral_tongue).
const INNER_LIP: ReadonlyArray<number> = [
  78, 95, 88, 178, 87, 14, 317, 402, 318, 324,
  308, 415, 310, 311, 312, 13, 82, 81, 80, 191,
];

// Tunable knobs (× mouth WIDTH). Iterated on-device per the findings.
const RECESS = 0.48;           // depth behind the lip plane (−Z) — keeps it hidden when closed
const DEPTH = 0.9;             // dome z-depth (how far back the bowl goes)
const CAVITY_COLOR = 0x140a0a; // near-black, faintly warm (a teeth/tongue mesh is the Phase-2 upgrade)

export interface OralCavityHandle { dispose(): void; }

/**
 * Attach a procedural inner-mouth cavity to a baked face mesh. Returns null (no-op) for
 * non-baked meshes (head proxy, synthetic) — no lip landmarks / no jawOpen morph.
 */
export function mountOralCavity(faceMesh: THREE.Mesh): OralCavityHandle | null {
  const geo = faceMesh.geometry;
  const pos = geo.getAttribute('position') as THREE.BufferAttribute | undefined;
  const names = geo.userData['morphTargetNames'];
  if (!pos || !Array.isArray(names)) return null;
  const jawIdx = names.indexOf('jawOpen');
  if (jawIdx < 0) return null;

  // Mouth center + width from the inner-lip ring (neutral positions).
  let cx = 0, cy = 0, cz = 0, count = 0;
  let minX = Infinity, maxX = -Infinity;
  const v = new THREE.Vector3();
  for (const i of INNER_LIP) {
    if (i >= pos.count) continue;
    v.fromBufferAttribute(pos, i);
    cx += v.x; cy += v.y; cz += v.z; count += 1;
    if (v.x < minX) minX = v.x;
    if (v.x > maxX) maxX = v.x;
  }
  if (count === 0) return null;
  cx /= count; cy /= count; cz /= count;
  const mouthW = Math.max(maxX - minX, 1e-3);

  // A concave dark bowl: a low-poly sphere seen from inside (BackSide) — only the far interior
  // draws, so it reads as a recessed cavity and the near half can't poke through the lips.
  const cavityGeo = new THREE.SphereGeometry(mouthW * 0.62, 24, 16); // wider + smoother (covers the corners)
  cavityGeo.scale(1.08, 0.78, DEPTH);                                // oval, deeper in Z
  const cavityMat = new THREE.MeshStandardMaterial({
    color: CAVITY_COLOR, roughness: 1, metalness: 0,
    transparent: false,      // OPAQUE — the rule that lets it show through transmission (findings §5)
    side: THREE.BackSide,    // concave interior, viewed from outside — cheaper than DoubleSide
    depthWrite: true,        // normal depth (do NOT copy the face's depthWrite:false)
  });
  const cavity = new THREE.Mesh(cavityGeo, cavityMat);
  cavity.position.set(cx, cy, cz - RECESS * mouthW);
  cavity.scale.setScalar(1e-4); // start hidden (≈gone) — grows with jawOpen
  faceMesh.add(cavity);         // child of the face → inherits its transform; not framed/animated

  const inf = faceMesh.morphTargetInfluences;
  cavity.onBeforeRender = (): void => {
    const t = inf?.[jawIdx] ?? 0; // 0..1
    // Do NOT toggle `visible`: three skips an invisible object's onBeforeRender, so it could
    // never turn back on. Scale from ~0 (closed) to full (open) so the dark recess grows into
    // the opening and is gone behind the closed lips at weight 0.
    cavity.scale.setScalar(Math.max(t, 1e-4));
  };

  return {
    dispose(): void {
      faceMesh.remove(cavity);
      cavityGeo.dispose();
      cavityMat.dispose();
    },
  };
}
