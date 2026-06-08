import { describe, it, expect } from 'vitest';
import { meshBuilder } from '../index';
import {
  ARKIT_52,
  MORPH_TARGETS,
  buildFaceGeometry,
  parseTopology,
  subdivideLipRegion,
  type FaceTopology,
  type Landmark3,
} from '../impl/face_topology';
import { computeMorphBasis, SUPPORTED_MORPHS } from '../impl/morph_basis';

describe('mesh_builder barrel', () => {
  it('exposes the expected surface', () => {
    expect(typeof meshBuilder.boot).toBe('function');
    expect(typeof meshBuilder.dispose).toBe('function');
    expect(typeof meshBuilder.build).toBe('function');
  });
});

describe('baked rig scaling (RB-001/ADR-0034 regression)', () => {
  it('scales baked deltas to the LIVE face height (no double-division by canonicalHeight)', () => {
    // A 468-vertex mesh spanning a height of ~9.9 units. The vertex POSITIONS only
    // set the bounding box; baked deltas are looked up by index and scaled by height.
    const n = 468;
    const pos = new Float32Array(n * 3);
    for (let i = 0; i < n; i++) {
      pos[i * 3] = (i % 11) - 5;
      pos[i * 3 + 1] = ((i * 7) % 100) / 10 - 5; // y ∈ [-5, 4.9] → height ≈ 9.9
      pos[i * 3 + 2] = 0;
    }
    const basis = computeMorphBasis(pos, n, ARKIT_52);
    const jaw = basis[ARKIT_52.indexOf('jawOpen')]!;
    let maxAbs = 0;
    for (let k = 0; k < jaw.length; k++) maxAbs = Math.max(maxAbs, Math.abs(jaw[k]!));
    // jawOpen's max fraction is ~0.2 of canonical height; on a ~9.9-tall face the
    // delta must be ~2 (visible). The old `b.h / canonicalHeight` bug yielded ~0.11
    // (÷ ~17.7) — influences correct but the rig invisible. Assert the visible range.
    expect(maxAbs).toBeGreaterThan(1);
    expect(maxAbs).toBeLessThan(10);
  });
});

// A minimal real topology: a unit quad as two triangles over 4 vertices. Enough
// to exercise the geometry builder without the (unbundled) 468-vert asset.
const QUAD: FaceTopology = {
  vertexCount: 4,
  indices: new Uint32Array([0, 1, 2, 0, 2, 3]),
};
const QUAD_LANDMARKS: Landmark3[] = [
  { x: 0.5, y: 0.5, z: 0.0 },   // → pos (0, 0, 0),     uv (0.5, 0.5)
  { x: 1.0, y: 0.5, z: 0.1 },   // → pos (0.5, 0, -0.1), uv (1.0, 0.5)
  { x: 1.0, y: 1.0, z: 0.0 },   // → pos (0.5, -0.5, 0), uv (1.0, 1.0)
  { x: 0.5, y: 1.0, z: 0.0 },   // → pos (0, -0.5, 0),   uv (0.5, 1.0)
];

describe('buildFaceGeometry (landmark → morph-ready geometry)', () => {
  it('maps normalized landmarks into recentered, Y-flipped positions', () => {
    const geo = buildFaceGeometry(QUAD_LANDMARKS, QUAD);
    const pos = geo.getAttribute('position');
    expect(pos.count).toBe(4);

    // vertex 0 (image center) lands at the origin
    expect(pos.getX(0)).toBeCloseTo(0);
    expect(pos.getY(0)).toBeCloseTo(0);
    expect(pos.getZ(0)).toBeCloseTo(0);

    // vertex 1: x 1.0 → +0.5, y 0.5 → 0, z 0.1 → -0.1 (depth toward camera)
    expect(pos.getX(1)).toBeCloseTo(0.5);
    expect(pos.getY(1)).toBeCloseTo(0);
    expect(pos.getZ(1)).toBeCloseTo(-0.1);

    // vertex 2: y 1.0 → -0.5 (Y flipped)
    expect(pos.getY(2)).toBeCloseTo(-0.5);
  });

  it('derives UVs from the landmark image positions', () => {
    const geo = buildFaceGeometry(QUAD_LANDMARKS, QUAD);
    const uv = geo.getAttribute('uv');
    expect(uv.count).toBe(4);
    // uv === raw landmark (x, y); texture flipY=false means no flip needed
    expect(uv.getX(1)).toBeCloseTo(1.0);
    expect(uv.getY(1)).toBeCloseTo(0.5);
    expect(uv.getX(0)).toBeCloseTo(0.5);
    expect(uv.getY(2)).toBeCloseTo(1.0);
  });

  it('carries the index buffer, normals, and a 53-slot procedural morph basis (ARKit-52 + eyesClosed)', () => {
    const geo = buildFaceGeometry(QUAD_LANDMARKS, QUAD);

    expect(geo.getIndex()?.count).toBe(6);            // 2 triangles
    expect(geo.getAttribute('normal')).toBeDefined(); // computeVertexNormals ran
    expect(geo.getAttribute('innerMouth')?.count).toBe(4); // per-vertex inner-mouth mask, sized to topo
    expect(geo.getAttribute('eyelid')?.count).toBe(4);     // RB-003 Item 4 eyelid feather mask, sized to topo

    const morphs = geo.morphAttributes.position;
    expect(morphs?.length).toBe(53);
    expect(morphs?.[0]?.count).toBe(4);               // sized to the topology

    // browDownLeft (index 0) is unsupported by the procedural basis → zero…
    expect(morphs?.[0]?.getY(2)).toBe(0);
    // …but jawOpen IS filled: the lower verts (e.g. 2) swing down.
    const jaw = morphs?.[ARKIT_52.indexOf('jawOpen')];
    expect(jaw?.getY(2)).toBeLessThan(0);

    const names = geo.userData['morphTargetNames'] as string[];
    expect(names).toHaveLength(53);
    expect(names).toEqual([...MORPH_TARGETS]);
  });

  it('ships morph NORMALS matching the position targets (deformed shading, RB-003)', () => {
    const geo = buildFaceGeometry(QUAD_LANDMARKS, QUAD);
    const posMorphs = geo.morphAttributes.position;
    const normMorphs = geo.morphAttributes.normal;
    // One normal target per position target — without this the renderer lights a deformed
    // mesh with its NEUTRAL-pose normals, mis-shading every expression (the dark/faceted/
    // jagged edges on eyelids, lips, jaw). Guard the wiring; visual correctness is on-device.
    expect(normMorphs?.length).toBe(posMorphs?.length);
    expect(normMorphs?.length).toBe(53);
    for (const m of normMorphs ?? []) {
      expect(m.itemSize).toBe(3);
      expect(m.count).toBe(4); // sized to the topology
    }
  });

  it('throws if there are fewer landmarks than the topology needs', () => {
    expect(() => buildFaceGeometry([{ x: 0, y: 0, z: 0 }], QUAD)).toThrow(/landmarks/);
  });
});

describe('parseTopology (asset validation, fail-soft)', () => {
  it('accepts a well-formed topology and returns a typed index array', () => {
    const t = parseTopology({ vertexCount: 4, indices: [0, 1, 2, 0, 2, 3] });
    expect(t).not.toBeNull();
    expect(t?.indices).toBeInstanceOf(Uint32Array);
    expect(t?.vertexCount).toBe(4);
    expect(Array.from(t?.indices ?? [])).toEqual([0, 1, 2, 0, 2, 3]);
  });

  it('rejects malformed inputs by returning null (never throws)', () => {
    expect(parseTopology(null)).toBeNull();
    expect(parseTopology(42)).toBeNull();
    // indices not a multiple of 3
    expect(parseTopology({ vertexCount: 4, indices: [0, 1] })).toBeNull();
    // index out of range
    expect(parseTopology({ vertexCount: 3, indices: [0, 1, 9] })).toBeNull();
    // missing indices
    expect(parseTopology({ vertexCount: 3 })).toBeNull();
  });
});

describe('subdivideLipRegion (RB-003 Phase-2 Item 2)', () => {
  // A quad as 2 triangles sharing edge 0-2; vertex 2 is in the lip region (mask=1), so BOTH
  // triangles subdivide and must SHARE the 0-2 edge midpoint (watertight, no crack).
  const POS = new Float32Array([0, 0, 0,  1, 0, 0,  1, 1, 0,  0, 1, 0]);
  const UV = new Float32Array([0, 0,  1, 0,  1, 1,  0, 1]);
  const MASK = new Float32Array([0, 0, 1, 0]);
  const INDEX = new Uint32Array([0, 1, 2, 0, 2, 3]);
  const morph = new Float32Array(4 * 3); morph[2 * 3] = 2; // only vert 2 displaced (x+2)

  it('subdivides lip triangles 1->4 and shares the common edge midpoint (watertight)', () => {
    const r = subdivideLipRegion(POS, UV, MASK, [morph], INDEX, 4);
    expect(r.n).toBe(9);             // 5 unique new midpoints (01,12,20,23,30), NOT 6 -> dedup
    expect(r.index.length).toBe(24); // 8 triangles
    expect(r.pos[0]!).toBe(0);       // original verts preserved
    expect(r.pos[3]!).toBe(1);
    expect(r.pos[4 * 3]!).toBeCloseTo(0.5); // vert 4 = mid(0,1) = (0.5,0,0)
    expect(Array.from(r.pos).every(Number.isFinite)).toBe(true);
    expect(Array.from(r.basis[0]!).every(Number.isFinite)).toBe(true);
  });

  it('interpolates morph deltas + mask at the midpoints (average of endpoints)', () => {
    const r = subdivideLipRegion(POS, UV, MASK, [morph], INDEX, 4);
    expect(r.basis[0]![5 * 3]!).toBeCloseTo(1);   // mid(1,2): (0+2)/2
    expect(r.basis[0]![4 * 3]!).toBeCloseTo(0);   // mid(0,1): (0+0)/2
    expect(r.mask[5]!).toBeCloseTo(0.5);          // mid(1,2): (0+1)/2
  });

  it('leaves a mesh with no lip verts untouched', () => {
    const r = subdivideLipRegion(POS, UV, new Float32Array([0, 0, 0, 0]), [morph], INDEX, 4);
    expect(r.n).toBe(4);
    expect(r.index.length).toBe(6);
  });
});

describe('computeMorphBasis (procedural deltas, by region)', () => {
  // Synthetic face: top-center, chin, center, lower-left, lower-right.
  const POS = new Float32Array([
    0, 0.5, 0,      // 0: top-center (forehead/brow)
    0, -0.5, 0,     // 1: chin
    0, 0, 0,        // 2: center
    -0.3, -0.15, 0, // 3: lower-left (mouth band, left half)
    0.3, -0.15, 0,  // 4: lower-right (mouth band, right half)
  ]);
  const N = 5;
  const dy = (a: Float32Array, v: number) => a[v * 3 + 1]!;

  it('returns 52 zero-initialized slots and lists its supported shapes', () => {
    const basis = computeMorphBasis(POS, N, ARKIT_52);
    expect(basis).toHaveLength(52);
    expect(basis.every((a) => a.length === N * 3)).toBe(true);
    expect(SUPPORTED_MORPHS).toContain('jawOpen');
  });

  it('jawOpen drops the lower face and leaves the upper face untouched', () => {
    const basis = computeMorphBasis(POS, N, ARKIT_52);
    const jaw = basis[ARKIT_52.indexOf('jawOpen')]!;
    expect(dy(jaw, 1)).toBeLessThan(0);   // chin swings down
    expect(dy(jaw, 0)).toBe(0);           // forehead unaffected
  });

  it('browInnerUp lifts the upper-center, mouthSmile lifts the mouth corners', () => {
    const basis = computeMorphBasis(POS, N, ARKIT_52);
    const brow = basis[ARKIT_52.indexOf('browInnerUp')]!;
    const smileL = basis[ARKIT_52.indexOf('mouthSmileLeft')]!;
    const smileR = basis[ARKIT_52.indexOf('mouthSmileRight')]!;

    expect(dy(brow, 0)).toBeGreaterThan(0);   // forehead lifts
    expect(dy(brow, 1)).toBe(0);              // chin unaffected
    expect(dy(smileL, 3)).toBeGreaterThan(0); // left corner lifts
    expect(dy(smileR, 4)).toBeGreaterThan(0); // right corner lifts
    expect(dy(smileL, 4)).toBe(0);            // left shape doesn't touch the right corner
  });

  it('leaves unsupported shapes (e.g. tongueOut) at zero', () => {
    const basis = computeMorphBasis(POS, N, ARKIT_52);
    const tongue = basis[ARKIT_52.indexOf('tongueOut')]!;
    expect(tongue.every((v) => v === 0)).toBe(true);
  });

  // RB-001/ADR-0034: the baked ARKit rig overlays the procedural basis on the real 468 topology.
  it('overlays the baked ARKit rig on the real 468-vertex topology', () => {
    const M = 468;
    const pos = new Float32Array(M * 3);
    for (let i = 0; i < M; i++) pos[i * 3 + 1] = i / (M - 1) - 0.5; // spread Y so face height > 0
    const basis = computeMorphBasis(pos, M, ARKIT_52);
    const sumAbs = (a: Float32Array): number => a.reduce((s, v) => s + Math.abs(v), 0);
    // browDownLeft is ZERO in the procedural basis, but the baked rig fills it:
    expect(sumAbs(basis[ARKIT_52.indexOf('browDownLeft')]!)).toBeGreaterThan(0);
    expect(sumAbs(basis[ARKIT_52.indexOf('jawOpen')]!)).toBeGreaterThan(0);
    // tongueOut is absent from the rig → stays at the procedural (zero) delta:
    expect(sumAbs(basis[ARKIT_52.indexOf('tongueOut')]!)).toBe(0);
  });
});
