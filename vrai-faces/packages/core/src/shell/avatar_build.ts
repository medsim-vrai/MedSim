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
  if (jawIdx >= 0 && jawU) {
    mesh.onBeforeRender = (): void => { jawU.value = mesh.morphTargetInfluences?.[jawIdx] ?? 0; };
  }
  shaderTranslucent.setOpacity(material.id, clamp01(opacityLevel));

  return { meshId, materialId: material.id };
}
