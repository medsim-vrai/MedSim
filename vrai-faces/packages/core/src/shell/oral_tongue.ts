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
const PROTRUDE = 0.5;    // forward of the lip plane at tongueOut=1
const DROP = 0.06;       // downward travel at tongueOut=1 (the tip-tilt provides most of the droop)
const BASE_RECESS = 0.1; // start the body BEHIND the lip plane so its base stays hidden (blends in)
const TIP_TILT = -0.25;  // radians — droop the protruding tip DOWN so it doesn't read as a flat disc
const TONGUE_COLOR = 0x9a3f3d; // fleshy red (lit by the scene) — a CC0/MIT tongue mesh is the Phase-2 upgrade

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

  // An elongated tongue body: narrower than the mouth, LONGER than wide (not a flat disc), tipped
  // down so it droops out of the mouth. Sphere scaled long in Z; the mesh scale grows it uniformly.
  const tongueGeo = new THREE.SphereGeometry(mouthW * 0.42, 20, 14);
  tongueGeo.scale(0.52, 0.20, 1.5); // long + narrow + FLAT (flattened per on-device review)
  // Subtle vertex-colour FORM (no texture map without a download): darken toward the protruding tip
  // and the underside so the tongue reads as a fleshy body with depth, not a flat blob. A real tongue
  // TEXTURE needs an image map (gated download) or the CC0/MIT tongue mesh — the Phase-2 upgrade.
  const tp = tongueGeo.getAttribute('position') as THREE.BufferAttribute;
  const zHalf = mouthW * 0.42 * 1.5 || 1;
  const yHalf = mouthW * 0.42 * 0.20 || 1;
  const cols = new Float32Array(tp.count * 3);
  for (let i = 0; i < tp.count; i++) {
    const fwd = Math.max(0, tp.getZ(i) / zHalf);    // 0 at base → 1 at the tip
    const under = Math.max(0, -tp.getY(i) / yHalf); // 0 top to 1 underside
    const s = Math.max(0.3, 1 - 0.3 * fwd - 0.4 * under);
    cols[i * 3] = s; cols[i * 3 + 1] = s; cols[i * 3 + 2] = s;
  }
  tongueGeo.setAttribute('color', new THREE.BufferAttribute(cols, 3));
  const tongueMat = new THREE.MeshStandardMaterial({
    color: TONGUE_COLOR, roughness: 0.85, metalness: 0, // matte — kills the glossy white highlight
    vertexColors: true,  // the tip/underside form baked above
    transparent: false,  // opaque — occludes the face where it protrudes
    depthWrite: true,
  });
  const tongue = new THREE.Mesh(tongueGeo, tongueMat);

  const baseY = cy; // emerge from the mouth centre (not floating below the lower lip)
  tongue.position.set(cx, baseY, cz);
  tongue.rotation.x = TIP_TILT; // droop the protruding tip downward
  tongue.scale.setScalar(1e-4); // start retracted (≈gone) — grows with tongueOut
  faceMesh.add(tongue); // child of the face → inherits its transform; not framed/animated

  const inf = faceMesh.morphTargetInfluences;
  tongue.onBeforeRender = (): void => {
    const t = inf?.[tIdx] ?? 0; // 0..1
    // Do NOT toggle `visible`: three skips an invisible object's onBeforeRender, so it could
    // never turn back on (the bug that kept the tongue hidden). Instead scale from ~0
    // (retracted/gone) to full as tongueOut rises, and protrude forward + down.
    tongue.scale.setScalar(Math.max(t, 1e-4));
    tongue.position.z = cz - BASE_RECESS * mouthW + t * PROTRUDE * mouthW; // emerge from inside
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
