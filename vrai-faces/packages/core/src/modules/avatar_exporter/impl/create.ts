import type { AvatarExporterModule, ExportInput } from '@contracts/avatar_exporter';
import type { BlendshapeWeights, BootDeps } from '@contracts/shared';
import type { GeometryRef } from '@contracts/mesh_builder';
import { lookupGeometry } from '@utils/resource_registry';

/**
 * Hand-rolled GLB / VRM writer.
 *
 * Deliberately NOT three/addons `GLTFExporter`: that addon imports the CLASSIC
 * `three` entry, which would load a second Three-core instance alongside the
 * app's `three/webgpu` build and reintroduce the "multiple instances of Three"
 * bug (unlit avatar). Reading geometry back from the shared registry is safe —
 * the registry already lives on `three/webgpu`, the same instance the app uses.
 *
 * The writer serializes the bound geometry (POSITION, optional NORMAL, optional
 * indices, and the ARKit-52 morph targets) into a minimal valid glTF 2.0 binary,
 * and bakes the translucency into `KHR_materials_transmission.transmissionFactor`
 * + `extras.vraiOpacity` (the contract's explicit requirement), carrying the
 * baseline mood in `extras.vraiBaselineMood` so it round-trips. exportVRM adds a
 * minimal `VRMC_vrm` meta extension on top of the same GLB.
 *
 * Morph-target baking: each blendshape becomes a per-primitive `targets[]` entry
 * (POSITION deltas) with `mesh.weights` (all 0) and `mesh.extras.targetNames`
 * carrying the ARKit-52 names, so the set round-trips by name. The deltas come
 * from `geometry.morphAttributes.position` — mesh_builder's procedural basis
 * today, a real rig later, via the same code path. When no morphs are present
 * (placeholder / unrigged geometry) the targets block is omitted.
 */

function clamp01(n: number): number { return n < 0 ? 0 : n > 1 ? 1 : n; }

interface MeshArrays {
  positions: Float32Array;
  normals: Float32Array | null;
  indices: Uint32Array | null;
  vertexCount: number;
  /** Per-blendshape POSITION deltas, in ARKit-52 order; null when unrigged. */
  morphTargets: Float32Array[] | null;
  /** ARKit-52 names parallel to morphTargets; null when unrigged. */
  morphNames: string[] | null;
}

// Used when no geometry is registered for the ref (e.g. a unit test, or export
// requested before mesh_builder ran). Keeps the GLB valid rather than throwing.
const PLACEHOLDER: MeshArrays = {
  positions: new Float32Array([0, 0, 0, 1, 0, 0, 0, 1, 0]),
  normals: new Float32Array([0, 0, 1, 0, 0, 1, 0, 0, 1]),
  indices: new Uint32Array([0, 1, 2]),
  vertexCount: 3,
  morphTargets: null,
  morphNames: null,
};

/** Pull plain typed arrays out of the registered BufferGeometry, or null. */
function extractArrays(ref: GeometryRef): MeshArrays | null {
  try {
    const geom = lookupGeometry(ref);
    if (!geom) return null;
    const posAttr = geom.getAttribute('position');
    if (!posAttr) return null;
    const positions = Float32Array.from(posAttr.array);
    const normAttr = geom.getAttribute('normal');
    const normals = normAttr ? Float32Array.from(normAttr.array) : null;
    const idx = geom.getIndex();
    const indices = idx ? Uint32Array.from(idx.array) : null;

    // Morph targets (per-blendshape POSITION deltas) + their ARKit-52 names.
    const morphAttrs = geom.morphAttributes.position;
    const morphTargets =
      morphAttrs && morphAttrs.length > 0 ? morphAttrs.map((a) => Float32Array.from(a.array)) : null;
    const namesRaw: unknown = geom.userData['morphTargetNames'];
    const morphNames = Array.isArray(namesRaw)
      ? namesRaw.filter((n): n is string => typeof n === 'string')
      : null;

    return { positions, normals, indices, vertexCount: posAttr.count, morphTargets, morphNames };
  } catch {
    return null;
  }
}

interface MaterialParams {
  name: string;
  opacity: number;            // baseColor alpha
  transmissionFactor: number;
  vraiOpacity: number;        // the raw slider value, for re-import
  vraiBaselineMood: BlendshapeWeights;
}

const GLB_MAGIC = 0x46546c67;   // 'glTF'
const CHUNK_JSON = 0x4e4f534a;  // 'JSON'
const CHUNK_BIN  = 0x004e4942;  // 'BIN\0'

/** Component-wise min/max over a flat VEC3 array (glTF accessor bounds). */
function vec3Bounds(a: Float32Array): { min: number[]; max: number[] } {
  const min = [Infinity, Infinity, Infinity];
  const max = [-Infinity, -Infinity, -Infinity];
  for (let i = 0; i < a.length; i += 3) {
    for (let c = 0; c < 3; c++) {
      const v = a[i + c] ?? 0;
      if (v < (min[c] ?? Infinity)) min[c] = v;
      if (v > (max[c] ?? -Infinity)) max[c] = v;
    }
  }
  // Guard the empty-array case so bounds stay finite/valid.
  if (!Number.isFinite(min[0] ?? Infinity)) return { min: [0, 0, 0], max: [0, 0, 0] };
  return { min, max };
}

function writeGlb(arrays: MeshArrays, mat: MaterialParams, vrm: boolean): Blob {
  const { positions, normals, indices, vertexCount } = arrays;
  const morphTargets = arrays.morphTargets ?? [];

  // --- Binary buffer: positions, [normals], [indices], [morph deltas], 4-aligned. ---
  const posBytes = positions.byteLength;
  const normBytes = normals ? normals.byteLength : 0;
  const idxBytes = indices ? indices.byteLength : 0;
  const morphBytes = morphTargets.reduce((s, t) => s + t.byteLength, 0);
  const posOffset = 0;
  const normOffset = posOffset + posBytes;
  const idxOffset = normOffset + normBytes;
  const morphBase = idxOffset + idxBytes;             // morph deltas follow indices
  const binLen = posBytes + normBytes + idxBytes + morphBytes;  // all operands ×4

  const bin = new ArrayBuffer(binLen);
  new Float32Array(bin, posOffset, positions.length).set(positions);
  if (normals) new Float32Array(bin, normOffset, normals.length).set(normals);
  if (indices) new Uint32Array(bin, idxOffset, indices.length).set(indices);
  const morphOffsets: number[] = [];
  {
    let off = morphBase;
    for (const t of morphTargets) {
      morphOffsets.push(off);
      new Float32Array(bin, off, t.length).set(t);
      off += t.byteLength;
    }
  }

  const posBounds = vec3Bounds(positions);
  const bufferViews: Array<Record<string, number>> = [
    { buffer: 0, byteOffset: posOffset, byteLength: posBytes, target: 34962 },
  ];
  const accessors: Array<Record<string, unknown>> = [
    { bufferView: 0, componentType: 5126, count: vertexCount, type: 'VEC3', min: posBounds.min, max: posBounds.max },
  ];
  const attributes: Record<string, number> = { POSITION: 0 };

  if (normals) {
    bufferViews.push({ buffer: 0, byteOffset: normOffset, byteLength: normBytes, target: 34962 });
    accessors.push({ bufferView: bufferViews.length - 1, componentType: 5126, count: vertexCount, type: 'VEC3' });
    attributes['NORMAL'] = accessors.length - 1;
  }

  const primitive: Record<string, unknown> = { attributes, material: 0, mode: 4 };
  if (indices) {
    bufferViews.push({ buffer: 0, byteOffset: idxOffset, byteLength: idxBytes, target: 34963 });
    accessors.push({ bufferView: bufferViews.length - 1, componentType: 5125, count: indices.length, type: 'SCALAR' });
    primitive['indices'] = accessors.length - 1;
  }

  // Morph targets: one POSITION-delta accessor per blendshape (ARKit-52 order).
  if (morphTargets.length > 0) {
    const targets: Array<Record<string, number>> = [];
    for (let m = 0; m < morphTargets.length; m++) {
      const t = morphTargets[m]!;
      const b = vec3Bounds(t);
      bufferViews.push({ buffer: 0, byteOffset: morphOffsets[m] ?? morphBase, byteLength: t.byteLength, target: 34962 });
      accessors.push({ bufferView: bufferViews.length - 1, componentType: 5126, count: vertexCount, type: 'VEC3', min: b.min, max: b.max });
      targets.push({ POSITION: accessors.length - 1 });
    }
    primitive['targets'] = targets;
  }

  const material: Record<string, unknown> = {
    name: mat.name,
    pbrMetallicRoughness: {
      baseColorFactor: [1, 1, 1, mat.opacity],
      metallicFactor: 0,
      roughnessFactor: 0.6,
    },
    alphaMode: mat.opacity < 1 || mat.transmissionFactor > 0 ? 'BLEND' : 'OPAQUE',
    extensions: { KHR_materials_transmission: { transmissionFactor: mat.transmissionFactor } },
    extras: { vraiOpacity: mat.vraiOpacity, vraiBaselineMood: mat.vraiBaselineMood },
  };

  const meshDef: Record<string, unknown> = { name: mat.name, primitives: [primitive] };
  if (morphTargets.length > 0) {
    meshDef['weights'] = morphTargets.map(() => 0);
    if (arrays.morphNames && arrays.morphNames.length === morphTargets.length) {
      meshDef['extras'] = { targetNames: arrays.morphNames };
    }
  }

  const extensionsUsed = ['KHR_materials_transmission'];
  const gltf: Record<string, unknown> = {
    asset: { version: '2.0', generator: 'vrai-faces avatar_exporter (hand-rolled GLB)' },
    scene: 0,
    scenes: [{ nodes: [0] }],
    nodes: [{ mesh: 0, name: mat.name }],
    meshes: [meshDef],
    materials: [material],
    accessors,
    bufferViews,
    buffers: [{ byteLength: binLen }],
    extensionsUsed,
  };
  if (vrm) {
    gltf['extensions'] = {
      VRMC_vrm: {
        specVersion: '1.0',
        meta: { name: mat.name, authors: ['vrai-faces'], licenseUrl: '' },
        humanoid: { humanBones: {} },     // minimal: face-only avatar has no body bones
      },
    };
    extensionsUsed.push('VRMC_vrm');
  }

  // --- Assemble the GLB container. ---
  const jsonBytes = new TextEncoder().encode(JSON.stringify(gltf));
  const jsonPad = (4 - (jsonBytes.length % 4)) % 4;       // pad JSON chunk with spaces
  const jsonChunkLen = jsonBytes.length + jsonPad;
  const total = 12 + 8 + jsonChunkLen + 8 + binLen;

  const out = new ArrayBuffer(total);
  const dv = new DataView(out);
  let p = 0;
  dv.setUint32(p, GLB_MAGIC, true); p += 4;
  dv.setUint32(p, 2, true);        p += 4;                // glTF version 2
  dv.setUint32(p, total, true);    p += 4;
  dv.setUint32(p, jsonChunkLen, true); p += 4;
  dv.setUint32(p, CHUNK_JSON, true);   p += 4;
  new Uint8Array(out, p, jsonBytes.length).set(jsonBytes); p += jsonBytes.length;
  for (let i = 0; i < jsonPad; i++) { dv.setUint8(p, 0x20); p += 1; }
  dv.setUint32(p, binLen, true);   p += 4;
  dv.setUint32(p, CHUNK_BIN, true); p += 4;
  new Uint8Array(out, p, binLen).set(new Uint8Array(bin));

  return new Blob([out], { type: 'model/gltf-binary' });
}

function materialFrom(input: ExportInput): MaterialParams {
  const t = input.translucency;
  return {
    name: input.mesh.meshId,
    opacity: input.bakeOpacity ? clamp01(t.opacity) : 1,
    transmissionFactor: input.bakeOpacity ? clamp01(t.transmission) : 0,
    vraiOpacity: clamp01(t.opacityLevel),
    vraiBaselineMood: input.mesh.baselineMood,
  };
}

export function createImpl(): AvatarExporterModule {
  let _deps: BootDeps | null = null;
  return {
    async boot(deps) { _deps = deps; },
    dispose() { _deps = null; },

    async exportGLB(input: ExportInput): Promise<Blob> {
      void _deps;
      return writeGlb(extractArrays(input.mesh.geometryRef) ?? PLACEHOLDER, materialFrom(input), false);
    },

    async exportVRM(input: ExportInput): Promise<Blob> {
      return writeGlb(extractArrays(input.mesh.geometryRef) ?? PLACEHOLDER, materialFrom(input), true);
    },
  };
}
