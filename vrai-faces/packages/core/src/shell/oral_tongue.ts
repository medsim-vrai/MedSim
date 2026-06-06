// Procedural tongue (tongueOut, ARKit #52) — RB-003 Phase 1 / ADR-0036.
//
// ICT-FaceKit (RB-001) has no tongue, so the `tongueOut` morph currently moves nothing
// (QA shape 52). This adds a simple OPAQUE procedural tongue parented to the face: hidden
// until the tongueOut influence lifts off zero, then protruding FORWARD + DOWN by the
// coefficient. A CC0 (MakeHuman) / MIT (ICT) tongue sub-mesh is the Phase-2 fidelity
// upgrade per the findings; this is the $0, code-only, no-download Phase-1 cut.
//
// Reuses the proxy-in-the-mouth pattern, but tongueOut is MEANT to stick out, so being
// clearly in front of the lip plane is correct (not the narrow-band problem the inner-
// mouth cavity had). Opaque + depthWrite so it occludes the face where it protrudes, and
// it sits in the dark inner-mouth cavity when retracted. Driven via onBeforeRender; a
// child of the face mesh, so frameAvatar() + the morph runtime ignore it.

import * as THREE from 'three/webgpu';

// MediaPipe inner-lip ring — locate the mouth from the neutral geometry.
const INNER_LIP: ReadonlyArray<number> = [
  78, 95, 88, 178, 87, 14, 317, 402, 318, 324,
  308, 415, 310, 311, 312, 13, 82, 81, 80, 191,
];

// Tunable knobs (× mouth WIDTH). Iterated on-device.
const PROTRUDE = 0.45; // forward of the lip plane at tongueOut=1
const DROP = 0.12;     // downward travel at tongueOut=1 (rests toward the lower lip)
const TONGUE_COLOR = 0xc0504f; // fleshy red (lit by the scene) — a CC0/MIT tongue mesh is the Phase-2 upgrade

export interface OralTongueHandle { dispose(): void; }

/**
 * Attach a procedural tongue to a baked face mesh. Returns null (no-op) for non-baked
 * meshes (head proxy, synthetic) — no lip landmarks.
 */
export function mountOralTongue(faceMesh: THREE.Mesh): OralTongueHandle | null {
  const geo = faceMesh.geometry;
  const pos = geo.getAttribute('position') as THREE.BufferAttribute | undefined;
  const names = geo.userData['morphTargetNames'];
  if (!pos || !Array.isArray(names)) return null;
  const tIdx = names.indexOf('tongueOut');
  if (tIdx < 0) return null;

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

  // A flat, rounded tongue body: narrower than the mouth, thin, elongated forward.
  const tongueGeo = new THREE.SphereGeometry(mouthW * 0.5, 18, 12);
  tongueGeo.scale(0.62, 0.30, 0.95);
  const tongueMat = new THREE.MeshStandardMaterial({
    color: TONGUE_COLOR, roughness: 0.7, metalness: 0,
    transparent: false,  // opaque — occludes the face where it protrudes
    depthWrite: true,
  });
  const tongue = new THREE.Mesh(tongueGeo, tongueMat);

  const baseY = cy - mouthW * 0.05;
  tongue.position.set(cx, baseY, cz);
  tongue.scale.setScalar(1e-4); // start retracted (≈gone) — grows with tongueOut
  faceMesh.add(tongue); // child of the face → inherits its transform; not framed/animated

  const inf = faceMesh.morphTargetInfluences;
  tongue.onBeforeRender = (): void => {
    const t = inf?.[tIdx] ?? 0; // 0..1
    // Do NOT toggle `visible`: three skips an invisible object's onBeforeRender, so it could
    // never turn back on (the bug that kept the tongue hidden). Instead scale from ~0
    // (retracted/gone) to full as tongueOut rises, and protrude forward + down.
    tongue.scale.setScalar(Math.max(t, 1e-4));
    tongue.position.z = cz + t * PROTRUDE * mouthW;
    tongue.position.y = baseY - t * DROP * mouthW;
  };

  return {
    dispose(): void {
      faceMesh.remove(tongue);
      tongueGeo.dispose();
      tongueMat.dispose();
    },
  };
}
