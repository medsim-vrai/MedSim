/**
 * CHARACTERIZATION test: how far the baked ARKit rig displaces the seven landmarks that the
 * Cranial Nerve Face Rig's measurement engine treats as BONE-ANCHORED.
 *
 * `cnrig/measure/pose.py` estimates head pose with `cv2.solvePnP` over
 * `RIGID_POSE_POINTS = (168, 6, 4, 33, 263, 133, 362)` — nasion, nose-bridge mid, pronasale, and
 * both lateral + medial canthi — on the assumption that no expression moves them. Pose then gates
 * and normalises every clinical range-of-motion measurement, and `metrics.midline_axis()` fits the
 * facial midline to the (168, 6, 4) subset. If a blendshape displaces those vertices, the pose solve
 * absorbs part of the expression and the corruption is INVISIBLE: the gate still reports a
 * near-frontal face, because the error lives inside the reference frame the gate is expressed in.
 *
 * This test does NOT assert the invariant holds — it does not. It FREEZES the measured violation so
 * that any re-bake, re-prune, or basis edit that changes rigid-landmark drift fails loudly and gets
 * re-audited rather than silently shifting a clinical measurement.
 *
 * Full finding, induced pose error, and the recommended fix:
 *   <Cranial Nerve Face Rig>/docs/AUDIT_vrai_faces_rigid_drift.md
 *
 * Units: the basis stores deltas as fractions of `canonicalHeight`; multiplying by a live mesh whose
 * height equals `canonicalHeight` recovers the bake's native delta in canonical model units. The
 * MediaPipe canonical face model is in CENTIMETRES (its inter-canthal distance is 3.713 units against
 * a documented ~37 mm), so 1 unit = 10 mm. Figures below are mm on the canonical model; on a real
 * adult face, which is ~15% smaller than this artist-authored average, scale by ~0.85.
 */
import { describe, it, expect, beforeAll } from 'vitest';
import { MORPH_TARGETS } from '../impl/face_topology';
import { computeMorphBasis, setMorphBasis, type MorphBasisDoc } from '../impl/morph_basis';
import morphBasisDoc from '../../../../public/assets/face/face_mesh_morphbasis.json';

beforeAll(() => { setMorphBasis(morphBasisDoc as unknown as MorphBasisDoc); });

/** The measurement engine's bone-anchored set (cnrig/measure/landmarks.py). */
const RIGID_POSE_POINTS = [168, 6, 4, 33, 263, 133, 362] as const;
const LANDMARK_NAME: Readonly<Record<number, string>> = {
  168: 'nasion', 6: 'noseBridge', 4: 'pronasale',
  33: 'latCanthusR', 263: 'latCanthusL', 133: 'medCanthusR', 362: 'medCanthusL',
};

/** Anything at or above this at full weight is clinically material (cnrig audit threshold). */
const FLAG_MM = 0.05;
const MM_PER_UNIT = 10;
const N = 468;

/**
 * Measured drift, mm on the canonical model, at blendshape weight 1.0.
 * 43 of 52 shipped shapes move at least one "rigid" landmark; all 96 pairs exceed FLAG_MM.
 * Every one of the seven landmarks is displaced >= 1.0 mm by some shape — so there is no
 * non-drifting subset to fall back on.
 */
const DRIFT_MM: Readonly<Record<string, ReadonlyArray<readonly [number, number]>>> = {
  eyeLookDownLeft:   [[263, 4.7102], [362, 2.6013]],
  eyeLookDownRight:  [[33, 4.7102], [133, 2.6013]],
  browInnerUp:       [[168, 4.4721], [6, 2.1161], [4, 1.1052], [133, 0.8299], [362, 0.8299], [263, 0.1468], [33, 0.1468]],
  eyeBlinkLeft:      [[263, 3.1132], [362, 1.4856]],
  eyeBlinkRight:     [[33, 3.1132], [133, 1.4856]],
  eyesClosed:        [[263, 3.1132], [33, 3.1132], [133, 1.4856], [362, 1.4856]],
  cheekPuff:         [[4, 2.8094], [6, 0.1504]],
  mouthLeft:         [[4, 2.6545]],
  mouthRight:        [[4, 2.6545]],
  eyeLookOutLeft:    [[263, 2.3540], [362, 1.1934]],
  eyeLookOutRight:   [[33, 2.3540], [133, 1.1936]],
  eyeLookInLeft:     [[263, 2.3111], [362, 1.2886]],
  eyeLookInRight:    [[33, 2.3111], [133, 1.2886]],
  eyeLookUpLeft:     [[263, 1.9565], [362, 1.4915]],
  eyeLookUpRight:    [[33, 1.9565], [133, 1.4915]],
  eyeWideLeft:       [[263, 1.9554], [362, 1.2913]],
  eyeWideRight:      [[33, 1.9554], [133, 1.2913]],
  noseSneerLeft:     [[4, 1.8274], [168, 1.1380], [6, 0.3457], [362, 0.2240]],
  noseSneerRight:    [[4, 1.8274], [168, 1.1380], [6, 0.3457], [133, 0.2240]],
  mouthPucker:       [[4, 1.6789], [6, 0.1802]],
  browOuterUpLeft:   [[263, 1.3085], [362, 0.6698], [168, 0.5729], [6, 0.2021]],
  browOuterUpRight:  [[33, 1.3085], [133, 0.6698], [168, 0.5729], [6, 0.2021]],
  mouthFunnel:       [[4, 1.2941], [6, 0.1048]],
  browDownLeft:      [[263, 0.8634], [168, 0.7878], [362, 0.4034]],
  browDownRight:     [[33, 0.8634], [168, 0.7878], [133, 0.4034]],
  cheekSquintLeft:   [[263, 0.8354], [362, 0.5717], [168, 0.2894], [4, 0.2786], [6, 0.2736]],
  cheekSquintRight:  [[33, 0.8354], [133, 0.5717], [168, 0.2894], [4, 0.2786], [6, 0.2736]],
  mouthPressLeft:    [[4, 0.5938], [6, 0.2739]],
  mouthPressRight:   [[4, 0.5938], [6, 0.2739]],
  jawOpen:           [[4, 0.5076], [6, 0.2517]],
  eyeSquintLeft:     [[263, 0.4481], [362, 0.1146]],
  eyeSquintRight:    [[33, 0.4481], [133, 0.1146]],
  jawLeft:           [[4, 0.3909]],
  jawRight:          [[4, 0.3909]],
  mouthFrownLeft:    [[4, 0.2025]],
  mouthFrownRight:   [[4, 0.2025]],
  mouthRollUpper:    [[4, 0.1784]],
  mouthSmileLeft:    [[4, 0.1420]],
  mouthSmileRight:   [[4, 0.1420]],
  mouthUpperUpLeft:  [[4, 0.1267]],
  mouthUpperUpRight: [[4, 0.1267]],
  mouthStretchLeft:  [[4, 0.1132]],
  mouthStretchRight: [[4, 0.1130]],
};

/** The only shipped shapes that leave every rigid landmark below FLAG_MM. */
const CLEAN_SHAPES = [
  'jawForward', 'mouthClose', 'mouthDimpleLeft', 'mouthDimpleRight',
  'mouthLowerDownLeft', 'mouthLowerDownRight', 'mouthRollLower',
  'mouthShrugLower', 'mouthShrugUpper',
] as const;

const doc = morphBasisDoc as unknown as MorphBasisDoc;

/**
 * A 468-vertex mesh whose bounding-box height is exactly `canonicalHeight`, so `computeMorphBasis`'s
 * `scale = b.h` returns the bake's native canonical-unit deltas. This drives the REAL runtime rescale
 * path rather than reading the JSON directly, so a regression in that path is caught too.
 */
function canonicalHeightMesh(): Float32Array {
  const pos = new Float32Array(N * 3);
  for (let i = 0; i < N; i++) {
    pos[i * 3] = (i % 11) - 5;                       // some x spread; b.w must be > 0
    pos[i * 3 + 1] = (i / (N - 1)) * doc.canonicalHeight; // y ∈ [0, canonicalHeight] → b.h = canonicalHeight
    pos[i * 3 + 2] = 0;
  }
  return pos;
}

/** Drift magnitude in mm at each rigid landmark, for every shape, through the runtime rescale. */
function measureDrift(): Map<string, Map<number, number>> {
  const basis = computeMorphBasis(canonicalHeightMesh(), N, MORPH_TARGETS);
  const out = new Map<string, Map<number, number>>();
  for (let s = 0; s < MORPH_TARGETS.length; s++) {
    const arr = basis[s]!;
    const per = new Map<number, number>();
    for (const vi of RIGID_POSE_POINTS) {
      const dx = arr[vi * 3]!, dy = arr[vi * 3 + 1]!, dz = arr[vi * 3 + 2]!;
      const mm = Math.hypot(dx, dy, dz) * MM_PER_UNIT;
      if (mm > 0) per.set(vi, mm);
    }
    out.set(MORPH_TARGETS[s]!, per);
  }
  return out;
}

describe('rigid pose-landmark drift (cnrig invariant — KNOWN VIOLATION, frozen)', () => {
  it('keeps the mm conversion valid: the basis is the 468 canonical topology in centimetres', () => {
    // If either changes, every mm figure in DRIFT_MM and in the audit doc is wrong.
    expect(doc.vertexCount).toBe(N);
    expect(doc.canonicalHeight).toBeCloseTo(17.665156, 6);
  });

  it('reproduces the audited drift table exactly (mm on the canonical model, weight 1.0)', () => {
    const measured = measureDrift();
    for (const [shape, pairs] of Object.entries(DRIFT_MM)) {
      const per = measured.get(shape);
      expect(per, `${shape} missing from the basis`).toBeDefined();
      for (const [vi, expectedMm] of pairs) {
        const got = per!.get(vi) ?? 0;
        expect(
          Math.abs(got - expectedMm),
          `${shape} @ ${LANDMARK_NAME[vi]}(${vi}): expected ${expectedMm} mm, got ${got.toFixed(4)} mm`,
        ).toBeLessThan(1e-3);
      }
    }
  });

  it('flags no NEW drifting (shape, landmark) pair beyond the audited 96', () => {
    const measured = measureDrift();
    const found: string[] = [];
    for (const [shape, per] of measured) {
      for (const [vi, mm] of per) {
        if (mm > FLAG_MM) found.push(`${shape}@${vi}`);
      }
    }
    const expected = Object.entries(DRIFT_MM)
      .flatMap(([shape, pairs]) => pairs.map(([vi]) => `${shape}@${vi}`));
    expect(found.slice().sort()).toEqual(expected.slice().sort());
    expect(found).toHaveLength(96);
  });

  it('holds the nine clean shapes below the 0.05 mm flag threshold', () => {
    const measured = measureDrift();
    for (const shape of CLEAN_SHAPES) {
      for (const [vi, mm] of measured.get(shape)!) {
        expect(mm, `${shape} @ ${LANDMARK_NAME[vi]}(${vi}) started drifting: ${mm.toFixed(4)} mm`)
          .toBeLessThanOrEqual(FLAG_MM);
      }
    }
  });

  it('documents that NO rigid landmark survives — excluding the drifters empties the pose set', () => {
    const measured = measureDrift();
    for (const vi of RIGID_POSE_POINTS) {
      let worst = 0;
      for (const per of measured.values()) worst = Math.max(worst, per.get(vi) ?? 0);
      // Every one of the seven is displaced by >= 1 mm by at least one shape. This is why the
      // audit rejects "exclude the drifting landmarks" as a fix.
      expect(worst, `${LANDMARK_NAME[vi]}(${vi}) max drift`).toBeGreaterThan(1.0);
    }
  });

  it('confirms setEmotion resting baselines are not pose-neutral (all 7 landmarks move at rest)', () => {
    // emotion_driver MOODS are a PERSISTENT additive baseline (animation_runtime.tick step 4), so a
    // non-neutral mood biases the pose solve on EVERY frame — including the "neutral reference" frame
    // an ROM measurement is differenced against. Only `neutral` ({}) is clean.
    const measured = measureDrift();
    const drowsy: Record<string, number> = {
      eyesClosed: 0.55, browInnerUp: 0.2, jawOpen: 0.08, mouthFrownLeft: 0.1, mouthFrownRight: 0.1,
    };
    for (const vi of RIGID_POSE_POINTS) {
      // Upper bound on the resting displacement: Σ wᵢ·|Δᵢ| (component signs may partially cancel).
      let bound = 0;
      for (const [shape, w] of Object.entries(drowsy)) bound += w * (measured.get(shape)!.get(vi) ?? 0);
      expect(bound, `drowsy leaves ${LANDMARK_NAME[vi]}(${vi}) at rest`).toBeGreaterThan(FLAG_MM);
    }
  });
});
