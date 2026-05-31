import * as THREE from 'three/webgpu';
import type { BuiltMesh, MeshBuilderModule } from '@contracts/mesh_builder';
import type { BootDeps, BlendshapeWeights } from '@contracts/shared';
import type { NormalizedPortrait } from '@contracts/face_ingest';
import { registerGeometry, registerTexture } from '@utils/resource_registry';
import { ARKIT_52, buildFaceGeometry, loadFaceTopology } from './face_topology';
import { computeMorphBasis } from './morph_basis';
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
 * sphere carrying the SAME procedural morph basis as the real path (Phase 7 B0),
 * so the head-proxy actually animates — `animation_runtime` writes
 * `morphTargetInfluences[i]` and the jaw/smile/brow shapes move — with the
 * portrait UV-mapped onto it for `shader_translucent` to tune end-to-end.
 *
 * The real path activates automatically once two data assets land (local-first,
 * ADR-0001): the `face_landmarker.task` model and the canonical
 * triangulation/UV table (`face_mesh_topology.json`). Until then every build
 * degrades to the fallback — honestly signaling the real topology isn't here yet.
 * Both paths use the PROCEDURAL `morph_basis` (jawOpen / smiles / browInnerUp
 * filled, the rest zero); the full ARKit-52 deformation rig is RB-001 (Phase 7 B2+).
 */

function buildBaseGeometry(): THREE.BufferGeometry {
  // 32×32 segment sphere, elongated slightly along Y to approximate a head.
  const geo = new THREE.SphereGeometry(0.5, 32, 32);
  geo.scale(1.0, 1.2, 1.0);
  geo.computeVertexNormals();

  const basePos = geo.getAttribute('position') as THREE.BufferAttribute;
  const vertCount = basePos.count;

  // Phase 7 B0 — give the head-proxy the PROCEDURAL morph basis (jawOpen /
  // smiles / browInnerUp) so it actually animates from speech + emotion, instead
  // of zero-displacement morphs that move nothing. computeMorphBasis is purely
  // geometric (bbox region rules, no landmark indices), so the same basis the
  // real MediaPipe path uses applies to this sphere too. Eye/other shapes stay
  // zero — the full ARKit-52 rig is RB-001 (Phase 7 B2+).
  const basis = computeMorphBasis(basePos.array as Float32Array, vertCount, ARKIT_52);
  geo.morphAttributes.position = basis.map((arr) => new THREE.BufferAttribute(arr, 3));
  // Deltas, not absolute targets — see face_topology.ts. Without this the
  // morphs would be treated as absolute positions and scale/warp the head as
  // morphTargetInfluences change each frame.
  geo.morphTargetsRelative = true;

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

      // Surface which path ran — observable in diagnostic_panel + console. No PHI
      // (counts only), so it satisfies the ADR-0014 message-only rule.
      _deps?.diag.push({
        t: performance.now(),
        moduleId: 'mesh_builder',
        kind: topo && detection ? 'info' : 'warn',
        message:
          topo && detection
            ? `real mesh: ${detection.landmarks.length} landmarks, ${((geo.getIndex()?.count ?? 0) / 3) | 0} tris`
            : `fallback head-proxy (topology=${topo ? 'ok' : 'absent'}, detection=${detection ? 'ok' : 'none'})`,
      });

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
