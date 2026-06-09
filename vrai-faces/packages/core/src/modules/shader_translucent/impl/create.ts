import * as THREE from 'three/webgpu';
// TSL node functions moved from 'three/webgpu' to the dedicated 'three/tsl' entry
// (three r171+; required by the r181 bump — ADR-0036 Phase 0). The renderer +
// node materials (THREE.*) still come from 'three/webgpu' above.
import {
  uniform, color, dot, pow, oneMinus, saturate, mul, attribute, texture,
  positionViewDirection, transformedNormalView, mix, smoothstep, frontFacing, float, max,
  uv, add, vec2, length,
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
const INNER_MOUTH_POW = 0.4;      // ↓: widen the tint COVERAGE to the very mask edge so the low-mask
                                  //   fade band is fully tinted — no bright photo texture (white) peeks
                                  //   at the inner-lip or the stretched corners. Lower = wider/harder edge.
const INNER_MOUTH_STRENGTH = 7.0; // how fast the inner-mouth tint saturates (higher = covers the
                                  // margin/corner texture fully so no white peeks at the edges)
// RB-003 "mucosa feather": where the open jaw reveals the inner mouth, blend the lit skin toward
// these tints instead of toward black — so the bright inner-lip photo texture is replaced by
// believable colour. The dilated COLLAR (lip body, mask≈0.7) lands on LIP, so the bottom of the
// upper lip SHOWS as a lip (not white, not a black void); the MEMBRANE (mask≈1) lands on DEEP,
// the dark opening. Both tunable.
const INNER_MOUTH_DEEP = 0x120808; // deep opening — dark (a hair darker than 0x180b0b for the jawOpen
                                   // interior, but the 2-ring mask keeps it from spreading onto the lip)
const INNER_MOUTH_LIP = 0x5a3737;  // inner-lip margin — muted flesh red (reverted: 0x4e2e2e read as a dark blob)

// RB-003: live URL tuning (append e.g. &win=0.96 and reload). Read at module load → baked into the
// node graph at material build (not a per-frame uniform).
function tuneNum(key: string, dflt: number): number {
  if (typeof location === 'undefined') return dflt;
  const m = (location.search + location.hash).match(new RegExp('[?&#]' + key + '=(-?[0-9.]+)'));
  if (!m || !m[1]) return dflt;
  const v = parseFloat(m[1]);
  return Number.isFinite(v) ? v : dflt;
}
// Open-mouth WINDOW strength: how transparent the membrane goes where the mouth opens, so the real
// teeth + cavity behind it show THROUGH it instead of being hidden under the opaque dark surface.
const WINDOW_OPEN = tuneNum('win', 0.92);
// Lower edge of the window's mask ramp. The membrane centre is mask≈1; the inner-lip MARGIN (the dilation
// rings) is ~0.45–0.7. Lowering this opens the window OUT over the margin too, so the side teeth (which sit
// behind the margin, not the centre) are revealed — not just the front teeth. Gated by jawU, so rest is unaffected.
const WINDOW_LO = tuneNum('winlo', 0.4);

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
  const maskAttr = attribute('innerMouth', 'float');
  const amt = saturate(mul(pow(maskAttr, INNER_MOUTH_POW), mul(jawU, INNER_MOUTH_STRENGTH)));
  // FRONT-facing lip edge (seen straight on) → LIP, so the bottom of the upper lip reads as a lip
  // and the bright photo texture is covered (no white). BACK-facing inner surfaces + the membrane
  // (mask≈1) → DEEP, so the mouth INTERIOR reads dark, not lit lip-flesh. (RB-003 mucosa feather.)
  const toDeep = max(oneMinus(float(frontFacing)), smoothstep(0.9, 1.0, maskAttr));
  const tint = mix(color(INNER_MOUTH_LIP), color(INNER_MOUTH_DEEP), toDeep);
  const innerResult = mix(diffuse, tint, amt);
  // RB-003 Phase-2 Item 4: eyelid margin-feather — tint the eye toward EYELID_SKIN as the lid closes,
  // so the eyesClosed/blink smear (stretched open-eye photo texture) reads as skin. Same machinery as
  // the inner-mouth feather; the eye + mouth masks don't overlap. eyelidU rides on userData
  // (avatar_build writes max(eyesClosed, blinkL, blinkR) per frame). TUNE on device.
  const EYELID_POW = 2.0;      // ↑ pow + ↓ strength = the feather FADES with the soft mask falloff at
  const EYELID_STRENGTH = 2.5; // the eyelid edge, blending into the surrounding skin (no hard cut-off)
  const EYELID_SKIN = 0x6f4d3e; // darker, warmer eyelid tone — sits in the shadowed eye socket (was
                                // 0x8a6a5e, too pale/grey against ruddy skin). v2: sample local skin.
  const EYELID_SRC_Y = 0.11;   // sample DOWN (under-eye -> cheek) far enough to CLEAR the iris for the
                               // whole eye region; a small/upward shift left the eye showing.
  const EYELID_FLAT_MIX = 0.4; // hold this much flat EYELID_SKIN tone so the lid sits dark in the socket
  const eyelidU = uniform(0);
  const eyelidMask = attribute('eyelid', 'float');
  const eAmt = saturate(mul(pow(eyelidMask, EYELID_POW), mul(eyelidU, EYELID_STRENGTH)));
  // Real skin TEXTURE on the closed lid: sample the portrait DOWN past the iris (under-eye -> cheek), so
  // the lid shows actual skin (pores/wrinkles) and never the eye colour, then blend in some flat tone so
  // it reads as a lid sitting in the shadowed socket rather than a slice of cheek.
  const eyelidSrc = map ? texture(map, add(uv(), vec2(0, EYELID_SRC_Y))) : color(EYELID_SKIN);
  const eyelidSkin = mix(eyelidSrc, color(EYELID_SKIN), EYELID_FLAT_MIX);
  // RB-003 eyelid Tier 2: a CREASE / lash line — darken the eye CONTOUR (mask≈1, the lid edge) toward a
  // dark brown so the closed lid shows the crease/lash seam instead of a flat patch. (The eyeball-BULGE
  // radial shading wants baked per-eye local coords — a follow-up.)
  const EYELID_CREASE = 0x241715;
  const eyelidLid = mix(eyelidSkin, color(EYELID_CREASE), mul(smoothstep(0.78, 1.0, eyelidMask), 0.7));
  // RB-003 eyelid Tier 2 BULGE: darken toward the eye rim (|eyelidLocal| → 1) so the lid reads as domed
  // over the eyeball; the membrane interpolates the ring coords to ~0 (bright) at the centre.
  const EYELID_BULGE = 0.45;
  const eyelidRim = mul(smoothstep(0.25, 1.05, length(attribute('eyelidLocal', 'vec2'))), EYELID_BULGE);
  const eyelidLidBulged = mul(eyelidLid, oneMinus(eyelidRim));
  material.colorNode = mix(innerResult, eyelidLidBulged, eAmt);
  // RB-003 open-mouth WINDOW (fix for "the mask covers the teeth"): where the membrane spans the opening
  // (mask≈1) and the jaw is open, drop the face's OPACITY so it becomes a transparent hole revealing the
  // opaque teeth + cavity drawn behind it — instead of an opaque dark surface OVER them. The lip MARGIN
  // (mask 0.45–0.7, below the 0.8 threshold) keeps full opacity + the LIP tint, feathering the opening.
  const windowAmt = mul(jawU, smoothstep(WINDOW_LO, 1.0, maskAttr));
  material.opacityNode = mul(float(s.opacity), oneMinus(mul(windowAmt, WINDOW_OPEN)));
  (material.userData as Record<string, unknown>)['vraiJawU'] = jawU;
  (material.userData as Record<string, unknown>)['vraiEyelidU'] = eyelidU;

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
