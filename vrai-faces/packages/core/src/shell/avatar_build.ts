// Portrait Blob → translucent avatar mesh, attached to the renderer.
//
// Shared by both boot paths: the standalone demo (synthetic portrait) and the
// MedSim bind path (the portal-attached portrait, via portalBinding). Runs the
// face_ingest → mesh_builder → shader_translucent pipeline and registers the
// result with the renderer + animation runtime.
//
// Imports `three/webgpu` (not `three`) — see renderer.ts for why mixing the two
// module instances leaves the avatar unlit.

import * as THREE from 'three/webgpu';
import { faceIngest } from '@modules/face_ingest';
import { meshBuilder } from '@modules/mesh_builder';
import { shaderTranslucent } from '@modules/shader_translucent';
import {
  lookupGeometry, lookupTexture, lookupMaterial, registerMesh,
} from '@utils/resource_registry';
import { mountOralTongue } from './oral_tongue';
import { mountOralEyeMesh } from './oral_eye_mesh';
import type { RendererHandle } from './renderer';

export interface BuiltAvatar {
  meshId: string;
  materialId: string;
}

function clamp01(n: number): number { return n < 0 ? 0 : n > 1 ? 1 : n; }

/**
 * Ingest a portrait, build its geometry + material, attach the mesh to the
 * renderer, and set the initial opacity. Throws if mesh_builder /
 * shader_translucent fail to register their resources.
 */
export async function buildAvatarFromBlob(
  renderer: RendererHandle,
  portraitBlob: Blob,
  opacityLevel = 0.66,
): Promise<BuiltAvatar> {
  const portrait = await faceIngest.ingest(portraitBlob);
  const built = await meshBuilder.build(portrait);

  const geo = lookupGeometry(built.geometryRef);
  const tex = lookupTexture(built.textureRef);
  if (!geo || !tex) {
    throw new Error('avatar_build: mesh_builder did not register geometry/texture');
  }

  const material = shaderTranslucent.build({
    geometry: built.geometryRef,
    texture: built.textureRef,
  });
  const matObj = lookupMaterial(material.id);
  if (!matObj) {
    throw new Error('avatar_build: shader_translucent did not register material');
  }

  const mesh = new THREE.Mesh(geo, matObj);
  // Normalize placement: recenter on the geometry's TRUE bounding-box center and
  // scale to a consistent on-screen size. mesh_builder centers by `lm.x - 0.5`,
  // which only frames a face that fills the image dead-center; an imported photo
  // with the face off to one side (or not filling the frame) otherwise renders
  // offset and mis-sized. Done on the mesh transform (not the geometry) so morph
  // targets are untouched.
  geo.computeBoundingBox();
  const bb = geo.boundingBox;
  if (bb) {
    const cx = (bb.min.x + bb.max.x) / 2;
    const cy = (bb.min.y + bb.max.y) / 2;
    const cz = (bb.min.z + bb.max.z) / 2;
    const maxDim = Math.max(bb.max.x - bb.min.x, bb.max.y - bb.min.y) || 1;
    const s = 1.1 / maxDim; // ~fills the 35° camera view at z = 2
    mesh.scale.setScalar(s);
    mesh.position.set(-cx * s, -cy * s, -cz * s);
  } else {
    mesh.position.set(0, 0, 0);
  }
  const meshId = registerMesh(mesh, built.meshId);

  renderer.attachMesh(meshId, mesh);
  // RB-003 Phase 1 (ADR-0036): feed the live jawOpen influence into shader_translucent's
  // inner-mouth darkening each frame. The shader exposes its jaw uniform on the material's
  // userData (no contract change); the inner-mouth MASK is baked per-vertex (mesh_builder),
  // so this only supplies the open-amount. onBeforeRender keeps it self-contained.
  const morphNames = geo.userData['morphTargetNames'];
  const jawIdx = Array.isArray(morphNames) ? morphNames.indexOf('jawOpen') : -1;
  const jawU = (matObj.userData as Record<string, unknown>)['vraiJawU'] as { value: number } | undefined;
  // RB-003 Phase-2 Item 4: feed the eyelid feather (shader) the live lid-closure amount so the eye
  // tints to skin as the lid descends. MAX of eyesClosed + the transient blinks, so idle_motion blinks
  // also feather (not only sustained closure). eyelidU rides on the material userData (no contract change).
  const ecIdx = Array.isArray(morphNames) ? morphNames.indexOf('eyesClosed') : -1;
  const blLIdx = Array.isArray(morphNames) ? morphNames.indexOf('eyeBlinkLeft') : -1;
  const blRIdx = Array.isArray(morphNames) ? morphNames.indexOf('eyeBlinkRight') : -1;
  const eyelidU = (matObj.userData as Record<string, unknown>)['vraiEyelidU'] as { value: number } | undefined;
  // RB-003 Phase-2 (ADR-0036): drive the inner-mouth darkening by LIP SEPARATION (MediaPipe inner-lip
  // centers — 13 upper, 14 lower), not jawOpen ALONE. Any lip-parting morph (mouthRollUpper, funnel,
  // pucker…) widens the 13↔14 gap, so the seam darkens instead of showing bright photo texture / white
  // (the morph-QA "gaps on lip movements"). Normalized by the jawOpen-full gap so jawOpen≈1 → openness
  // 1 (the jawOpen look is unchanged); the cavity dome still tracks jawOpen on its own.
  const posAttr = geo.getAttribute('position') as THREE.BufferAttribute | undefined;
  const morphPos = geo.morphAttributes['position'] as THREE.BufferAttribute[] | undefined;
  const UP_LIP = 13, LO_LIP = 14;
  let openRef = 0;
  if (posAttr && morphPos && jawIdx >= 0 && morphPos[jawIdx]) {
    const jm = morphPos[jawIdx]!;
    openRef = Math.max(jm.getY(UP_LIP) - jm.getY(LO_LIP), 1e-4); // 13↔14 gap increase at jawOpen=1
  }
  const hasOpen = !!(morphPos && openRef > 0);
  // RB-003 §2c: per-frame ΔUV — re-accumulate the geometry's UV from the neutral baseUv plus each
  // ACTIVE pinned mouth shape's ΔUV (image-follow, built in mesh_builder), so the mouth-corner
  // texture follows the deformation (no tear). Idle frames skip the UV work entirely.
  const baseUv = geo.userData['vraiBaseUv'] as Float32Array | undefined;
  const deltaUv = geo.userData['vraiDeltaUv'] as Array<{ shape: number; delta: Float32Array }> | undefined;
  const uvAttr = geo.getAttribute('uv') as THREE.BufferAttribute | undefined;
  const hasUv = !!(baseUv && deltaUv && uvAttr);
  if ((jawIdx >= 0 && jawU) || hasUv || eyelidU) {
    let uvWasActive = false;
    mesh.onBeforeRender = (): void => {
      const inf = mesh.morphTargetInfluences;
      if (jawU) {
        if (hasOpen && inf && morphPos) {
          let sep = 0;
          for (let s = 0; s < morphPos.length; s++) {
            const w = inf[s] ?? 0;
            if (w <= 0.001) continue;
            const ma = morphPos[s]!;
            sep += w * (ma.getY(UP_LIP) - ma.getY(LO_LIP));
          }
          const o = sep / openRef;
          jawU.value = o < 0 ? 0 : o > 1 ? 1 : o;
        } else {
          jawU.value = inf?.[jawIdx] ?? 0;
        }
      }
      if (eyelidU) {
        const ec = ecIdx >= 0 ? (inf?.[ecIdx] ?? 0) : 0;
        const bl = blLIdx >= 0 ? (inf?.[blLIdx] ?? 0) : 0;
        const br = blRIdx >= 0 ? (inf?.[blRIdx] ?? 0) : 0;
        eyelidU.value = Math.max(ec, bl, br);
      }
      if (hasUv && inf && baseUv && deltaUv && uvAttr) {
        let active = false;
        for (const e of deltaUv) { if ((inf[e.shape] ?? 0) > 0.001) { active = true; break; } }
        if (active || uvWasActive) {
          const arr = uvAttr.array as Float32Array;
          arr.set(baseUv);
          if (active) {
            for (const e of deltaUv) {
              const w = inf[e.shape] ?? 0;
              if (w <= 0.001) continue;
              const d = e.delta;
              for (let k = 0; k < arr.length; k++) arr[k] = arr[k]! + w * d[k]!;
            }
          }
          uvAttr.needsUpdate = true;
          uvWasActive = active;
        }
      }
    };
  }
  // RB-003 Phase 1 (ADR-0036): opaque inner-mouth cavity behind the lips (findings §2a) +
  // procedural tongue for `tongueOut` (ICT-FaceKit has none). Both no-op on non-baked meshes;
  // children of the face, driven by the jawOpen / tongueOut influences.
  mountOralTongue(mesh);
  // RB-003 Item 3: real ICT teeth/gums/tongue replace the procedural cavity dome (which was occluding
  // the recessed teeth) — the real gums/tongue ARE the dark interior now. No-op off-topology.
  mountOralEyeMesh(mesh);
  shaderTranslucent.setOpacity(material.id, clamp01(opacityLevel));

  return { meshId, materialId: material.id };
}
