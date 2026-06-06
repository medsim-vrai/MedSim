import * as THREE from 'three/webgpu';
// TSL node functions moved from 'three/webgpu' to the dedicated 'three/tsl' entry
// (three r171+; required by the r181 bump — ADR-0036 Phase 0). The renderer +
// node materials (THREE.*) still come from 'three/webgpu' above.
import {
  uniform, color, dot, pow, oneMinus, saturate, mul,
  positionViewDirection, transformedNormalView,
} from 'three/tsl';
import type {
  ShaderTranslucentModule,
  TranslucentMaterial,
  TranslucentMaterialSnapshot,
} from '@contracts/shader_translucent';
import type { BootDeps } from '@contracts/shared';
import {
  lookupGeometry,
  lookupTexture,
  registerMaterial,
  lookupMaterial,
} from '@utils/resource_registry';

/**
 * Translucency table (Memory_management.MD §4):
 *   level 1.00 → transmission 0.00, opacity 1.00, fresnel 0,   spec 1.0
 *   level 0.66 → transmission 0.35, opacity 1.00, fresnel 0.3, spec 0.66
 *   level 0.33 → transmission 0.75, opacity 0.85, fresnel 0.6, spec 0.33
 *   level 0.00 → transmission 1.00, opacity 0.55, fresnel 1.0, spec 0.0
 *
 * Implemented as a piecewise lerp between the four anchor rows so the
 * mid-stops match the table exactly (a straight linear curve would not).
 */
const ANCHORS: ReadonlyArray<{
  level: number;
  transmission: number;
  opacity: number;
  fresnelStrength: number;
  specularIntensity: number;
}> = [
  { level: 0.00, transmission: 1.00, opacity: 0.55, fresnelStrength: 1.0, specularIntensity: 0.0 },
  { level: 0.33, transmission: 0.75, opacity: 0.85, fresnelStrength: 0.6, specularIntensity: 0.33 },
  { level: 0.66, transmission: 0.35, opacity: 1.00, fresnelStrength: 0.3, specularIntensity: 0.66 },
  { level: 1.00, transmission: 0.00, opacity: 1.00, fresnelStrength: 0.0, specularIntensity: 1.0 },
];

export function mapOpacity(level: number): Omit<TranslucentMaterialSnapshot, 'opacityLevel'> {
  const x = level < 0 ? 0 : level > 1 ? 1 : level;

  // Find the bracket [i, i+1] such that ANCHORS[i].level ≤ x ≤ ANCHORS[i+1].level.
  let i = 0;
  for (let k = 0; k < ANCHORS.length - 1; k++) {
    const next = ANCHORS[k + 1]!;
    if (x <= next.level) { i = k; break; }
    i = k;
  }
  const a = ANCHORS[i]!;
  const b = ANCHORS[i + 1] ?? a;
  const span = b.level - a.level;
  const t = span === 0 ? 0 : (x - a.level) / span;

  return {
    transmission:      a.transmission      + (b.transmission      - a.transmission)      * t,
    opacity:           a.opacity           + (b.opacity           - a.opacity)           * t,
    fresnelStrength:   a.fresnelStrength   + (b.fresnelStrength   - a.fresnelStrength)   * t,
    specularIntensity: a.specularIntensity + (b.specularIntensity - a.specularIntensity) * t,
  };
}

/** A uniform node whose `.value` we mutate at runtime — no shader recompile. */
interface MutableUniform { value: number; }

/**
 * Internal record kept per material so `setOpacity` can mutate uniforms
 * (no shader recompile) and `snapshot` can read back.
 */
interface MatRecord {
  material: THREE.MeshPhysicalNodeMaterial;
  level: number;
  /** Drives the Fresnel rim brightness; updated in place by setOpacity. */
  strengthU: MutableUniform;
}

const records = new Map<string, MatRecord>();

// Fresnel rim tuning. POWER sharpens the falloff toward the silhouette; GAIN
// sets how bright the rim gets at the ghost end (fresnelStrength → 1). These
// are look constants, not part of the §4 table — the table value rides in on
// `strengthU`, so `snapshot()` still reports the pure §4 fresnelStrength.
const FRESNEL_POWER = 3.0;
const RIM_GAIN = 0.85;

/**
 * Build a `MeshPhysicalNodeMaterial` per §4, with a real Fresnel rim expressed
 * in TSL — the WebGPU-native path (ADR-0009). `onBeforeCompile` is a
 * WebGLRenderer hook and never fires under WebGPURenderer, so the rim is a node
 * graph instead: `white · (1 − saturate(N·V))^POWER · strength`. `strength`
 * rides on a uniform so `setOpacity` is a uniform write, never a recompile.
 */
function buildMaterial(
  map: THREE.Texture | null, level: number,
): { material: THREE.MeshPhysicalNodeMaterial; strengthU: MutableUniform } {
  const s = mapOpacity(level);
  const material = new THREE.MeshPhysicalNodeMaterial({
    color: 0xffffff,
    map: map ?? null,
    transmission: s.transmission,
    thickness: 0.5,
    ior: 1.4,
    roughness: 0.35,
    metalness: 0.0,
    opacity: s.opacity,
    transparent: true,
    side: THREE.DoubleSide,
    specularIntensity: s.specularIntensity,
    depthWrite: false,
  });

  // facing ∈ [0,1]: 1 head-on, 0 at the silhouette. The rim is its complement
  // raised to POWER, tinted white and scaled by the per-material strength.
  const strengthU = uniform(s.fresnelStrength * RIM_GAIN);
  const facing = saturate(dot(transformedNormalView, positionViewDirection));
  const rim = pow(oneMinus(facing), FRESNEL_POWER);
  material.emissiveNode = mul(mul(color(0xffffff), rim), strengthU);

  return { material, strengthU };
}

function applyLevel(rec: MatRecord, level: number): void {
  const s = mapOpacity(level);
  rec.level = level;
  rec.material.transmission      = s.transmission;
  rec.material.opacity           = s.opacity;
  rec.material.specularIntensity = s.specularIntensity;
  rec.strengthU.value            = s.fresnelStrength * RIM_GAIN;
  // Uniform + scalar writes only; we never set `needsUpdate`. (The first move
  // off fully-opaque enables transmission inside MeshPhysicalNodeMaterial, a
  // one-time recompile we don't fight — steady-state slides stay uniform-only.)
}

export function createImpl(): ShaderTranslucentModule {
  let _deps: BootDeps | null = null;

  return {
    async boot(deps) { _deps = deps; },

    dispose() {
      for (const rec of records.values()) rec.material.dispose();
      records.clear();
      _deps = null;
    },

    build({ geometry, texture }): TranslucentMaterial {
      void _deps;
      void lookupGeometry(geometry);       // touch to validate registration
      const tex = lookupTexture(texture);
      const { material, strengthU } = buildMaterial(tex, 1.0);  // default opaque
      const handle = registerMaterial(material);
      records.set(handle.id, { material, level: 1.0, strengthU });
      return handle;
    },

    setOpacity(materialId: string, level: number) {
      const rec = records.get(materialId);
      if (!rec) {
        const stray = lookupMaterial(materialId);
        if (!stray) throw new Error(`shader_translucent.setOpacity: unknown materialId ${materialId}`);
        return;
      }
      const clamped = level < 0 ? 0 : level > 1 ? 1 : level;
      applyLevel(rec, clamped);
    },

    snapshot(materialId: string): TranslucentMaterialSnapshot {
      const rec = records.get(materialId);
      if (!rec) throw new Error(`shader_translucent.snapshot: unknown materialId ${materialId}`);
      const s = mapOpacity(rec.level);
      return { opacityLevel: rec.level, ...s };
    },
  };
}
