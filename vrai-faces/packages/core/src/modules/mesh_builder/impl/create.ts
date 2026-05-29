import * as THREE from 'three/webgpu';
import type { BuiltMesh, MeshBuilderModule } from '@contracts/mesh_builder';
import type { BootDeps, BlendshapeWeights } from '@contracts/shared';
import type { NormalizedPortrait } from '@contracts/face_ingest';
import { registerGeometry, registerTexture } from '@utils/resource_registry';
import { ARKIT_52, buildFaceGeometry, loadFaceTopology } from './face_topology';
import { detectFaceLandmarks } from './face_landmarker';

/**
 * Two-path mesh builder.
 *
 * REAL PATH (browser + bundled assets): MediaPipe FaceLandmarker reads the
 * portrait → 478 per-identity landmarks + an ARKit-52 blendshape baseline; the
 * landmarks deform the canonical face topology (`face_topology`) into this
 * person's head, UV-mapped from the portrait. See `face_landmarker.ts` /
 * `face_topology.ts`.
 *
 * FALLBACK PATH (jsdom, no GPU, or assets not yet bundled): a smooth elongated
 * sphere with the ARKit-52 morph attributes allocated at ZERO displacement, so:
 *   - `animation_runtime` can write `morphTargetInfluences[i]` without blowing
 *     up (the contract holds);
 *   - the user still sees a translucent head-proxy with their portrait UV-mapped
 *     onto it, so `shader_translucent` can be tuned end-to-end.
 *
 * The real path activates automatically once two data assets land (local-first,
 * ADR-0001): the `face_landmarker.task` model and the canonical
 * triangulation/UV table (`face_mesh_topology.json`). Until then every build
 * degrades to the fallback — honestly signaling the real topology isn't here yet.
 * Real per-blendshape morph DELTAS are a further slice (they need a deformation
 * basis MediaPipe doesn't ship); morph attributes stay zero for now.
 */

function buildBaseGeometry(): THREE.BufferGeometry {
  // 32×32 segment sphere, elongated slightly along Y to approximate a head.
  const geo = new THREE.SphereGeometry(0.5, 32, 32);
  geo.scale(1.0, 1.2, 1.0);
  geo.computeVertexNormals();

  const basePos = geo.getAttribute('position') as THREE.BufferAttribute;
  const vertCount = basePos.count;

  // Allocate 52 zero-displacement morph attributes so morphTargetInfluences
  // writes are valid. ~1.2 MB at this segment count — acceptable for a
  // fallback; the real path allocates these sized to the 468/478-vert topology.
  const morphs: THREE.BufferAttribute[] = [];
  for (let i = 0; i < ARKIT_52.length; i++) {
    morphs.push(new THREE.BufferAttribute(new Float32Array(vertCount * 3), 3));
  }
  geo.morphAttributes.position = morphs;

  geo.userData['morphTargetNames'] = [...ARKIT_52];
  return geo;
}

async function buildTextureFromPortrait(portrait: NormalizedPortrait): Promise<THREE.Texture> {
  const bm = await createImageBitmap(portrait.png);
  const tex = new THREE.CanvasTexture(bm);
  tex.colorSpace = THREE.SRGBColorSpace;
  tex.flipY = false;
  tex.needsUpdate = true;
  return tex;
}

/**
 * Project a (possibly partial) weight map onto the canonical ARKit-52 list:
 * keep only the 52 known shapes, default any missing to 0. The fallback passes
 * `{}` (neutral); the real path passes MediaPipe's blendshape scores.
 */
function baselineFrom(weights: BlendshapeWeights): BlendshapeWeights {
  const out: BlendshapeWeights = {};
  for (const name of ARKIT_52) out[name] = weights[name] ?? 0;
  return out;
}

let cache = new Map<string, BuiltMesh>();
let nextMeshId = 0;

export function createImpl(): MeshBuilderModule {
  let _deps: BootDeps | null = null;

  return {
    async boot(deps) { _deps = deps; },

    dispose() {
      // Geometry + texture lifetimes are owned by the registry; clearing
      // the cache just lets a re-ingest produce fresh refs.
      cache.clear();
      _deps = null;
    },

    async build(portrait: NormalizedPortrait): Promise<BuiltMesh> {
      void _deps;
      const cached = cache.get(portrait.hash);
      if (cached) return cached;

      const tex = await buildTextureFromPortrait(portrait);

      // Real path needs BOTH the canonical topology asset AND a successful
      // landmark detection. Skip detection entirely if the topology is absent.
      const topo = await loadFaceTopology();
      const detection = topo ? await detectFaceLandmarks(portrait.png) : null;

      let geo: THREE.BufferGeometry;
      let baselineMood: BlendshapeWeights;
      if (topo && detection) {
        geo = buildFaceGeometry(detection.landmarks, topo);
        baselineMood = baselineFrom(detection.blendshapes);
      } else {
        geo = buildBaseGeometry();
        baselineMood = baselineFrom({});
      }

      const geometryRef = registerGeometry(geo);
      const textureRef  = registerTexture(tex);
      nextMeshId++;
      const built: BuiltMesh = {
        meshId: `built-${nextMeshId.toString(36)}`,
        geometryRef,
        textureRef,
        baselineMood,
        vertexCount: (geo.getAttribute('position') as THREE.BufferAttribute).count,
      };
      cache.set(portrait.hash, built);
      return built;
    },
  };
}
