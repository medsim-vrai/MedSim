import * as THREE from 'three/webgpu';
// TSL node functions moved from 'three/webgpu' to the dedicated 'three/tsl' entry
// (three r171+; required by the r181 bump — ADR-0036 Phase 0). The renderer +
// node materials (THREE.*) still come from 'three/webgpu' above.
import {
  uniform, color, dot, pow, oneMinus, saturate, mul, attribute, texture,
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

// RB-003 inner-mouth darkening (ADR-0036). The per-vertex `innerMouth` mask
// (mesh_builder) is ~1 across the stretched membrane spanning the open mouth and 0
// elsewhere; we tint those fragments toward black by the live `jawOpen` so an open
// jaw reads as a dark interior instead of stretched lip texture. POW concentrates the
// effect on the membrane (mask≈1) vs the inner-lip body; STRENGTH sets how black it goes.
const INNER_MOUTH_POW = 1.2;      // ↓ from 2.0: let the mask falloff darken too, so the void
                                  //   extends toward the lip edges (fuller, not just mask≈1)
const INNER_MOUTH_STRENGTH = 4.0; // ↑ from 2.5: deeper black across the opening

// Surface-reflection gate (look tweak): the specular reflection fades to ZERO as the
// translucency level rises 0.6 → 0.8 and stays 0 above 0.8 — so the more-opaque avatar reads
// MATTE (no shiny surface highlights), while the translucent end keeps its sheen. Gates the
// specular only; the Fresnel rim is a separate ghost-edge cue (and already ~0 by the opaque end).
function reflectionGate(level: number): number {
  if (level <= 0.6) return 1;
  if (level >= 0.8) return 0;
  return (0.8 - level) / (0.8 - 0.6);
}

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
    specularIntensity: s.specularIntensity * reflectionGate(level),
    depthWrite: false,
  });

  // facing ∈ [0,1]: 1 head-on, 0 at the silhouette. The rim is its complement
  // raised to POWER, tinted white and scaled by the per-material strength.
  const strengthU = uniform(s.fresnelStrength * RIM_GAIN);
  const facing = saturate(dot(transformedNormalView, positionViewDirection));
  const rim = pow(oneMinus(facing), FRESNEL_POWER);
  material.emissiveNode = mul(mul(color(0xffffff), rim), strengthU);

  // RB-003 (ADR-0036): darken the inner-mouth region by the live jawOpen. The diffuse
  // is rebuilt as `texture(map)` so we can multiply it down where the mask × jawOpen is
  // high (at darken=0 this equals the plain map, so the look is unchanged when closed).
  // jawU rides on userData; avatar_build writes it per frame (no contract change).
  const jawU = uniform(0);
  const diffuse = map ? texture(map) : color(0xffffff);
  const darken = saturate(mul(pow(attribute('innerMouth', 'float'), INNER_MOUTH_POW), mul(jawU, INNER_MOUTH_STRENGTH)));
  material.colorNode = mul(diffuse, oneMinus(darken));
  (material.userData as Record<string, unknown>)['vraiJawU'] = jawU;

  return { material, strengthU };
}

function applyLevel(rec: MatRecord, level: number): void {
  const s = mapOpacity(level);
  rec.level = level;
  rec.material.transmission      = s.transmission;
  rec.material.opacity           = s.opacity;
  rec.material.specularIntensity = s.specularIntensity * reflectionGate(level);
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
