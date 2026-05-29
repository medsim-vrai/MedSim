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
 * indices) into a minimal valid glTF 2.0 binary, and bakes the translucency
 * into `KHR_materials_transmission.transmissionFactor` + `extras.vraiOpacity`
 * (the contract's explicit requirement), carrying the baseline mood in
 * `extras.vraiBaselineMood` so it round-trips. exportVRM adds a minimal
 * `VRMC_vrm` meta extension on top of the same GLB.
 *
 * Morph-target (blendshape) baking is deferred: it needs mesh_builder to emit
 * real per-blendshape position deltas first (current topology is a placeholder,
 * task #16). When that lands, add a `targets[]` block per primitive here.
 */

function clamp01(n: number): number { return n < 0 ? 0 : n > 1 ? 1 : n; }

interface MeshArrays {
  positions: Float32Array;
  normals: Float32Array | null;
  indices: Uint32Array | null;
  vertexCount: number;
}

// Used when no geometry is registered for the ref (e.g. a unit test, or export
// requested before mesh_builder ran). Keeps the GLB valid rather than throwing.
const PLACEHOLDER: MeshArrays = {
  positions: new Float32Array([0, 0, 0, 1, 0, 0, 0, 1, 0]),
  normals: new Float32Array([0, 0, 1, 0, 0, 1, 0, 0, 1]),
  indices: new Uint32Array([0, 1, 2]),
  vertexCount: 3,
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
    return { positions, normals, indices, vertexCount: posAttr.count };
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

function writeGlb(arrays: MeshArrays, mat: MaterialParams, vrm: boolean): Blob {
  const { positions, normals, indices, vertexCount } = arrays;

  // --- Binary buffer: positions, [normals], [indices], each 4-byte aligned. ---
  const posBytes = positions.byteLength;
  const normBytes = normals ? normals.byteLength : 0;
  const idxBytes = indices ? indices.byteLength : 0;
  const posOffset = 0;
  const normOffset = posOffset + posBytes;
  const idxOffset = normOffset + normBytes;
  const binLen = posBytes + normBytes + idxBytes;     // all operands multiples of 4

  const bin = new ArrayBuffer(binLen);
  new Float32Array(bin, posOffset, positions.length).set(positions);
  if (normals) new Float32Array(bin, normOffset, normals.length).set(normals);
  if (indices) new Uint32Array(bin, idxOffset, indices.length).set(indices);

  // POSITION accessor needs min/max bounds per the glTF spec.
  const min = [Infinity, Infinity, Infinity];
  const max = [-Infinity, -Infinity, -Infinity];
  for (let i = 0; i < positions.length; i += 3) {
    for (let c = 0; c < 3; c++) {
      const v = positions[i + c] ?? 0;
      if (v < (min[c] ?? Infinity)) min[c] = v;
      if (v > (max[c] ?? -Infinity)) max[c] = v;
    }
  }

  const bufferViews: Array<Record<string, number>> = [
    { buffer: 0, byteOffset: posOffset, byteLength: posBytes, target: 34962 },
  ];
  const accessors: Array<Record<string, unknown>> = [
    { bufferView: 0, componentType: 5126, count: vertexCount, type: 'VEC3', min, max },
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

  const extensionsUsed = ['KHR_materials_transmission'];
  const gltf: Record<string, unknown> = {
    asset: { version: '2.0', generator: 'vrai-faces avatar_exporter (hand-rolled GLB)' },
    scene: 0,
    scenes: [{ nodes: [0] }],
    nodes: [{ mesh: 0, name: mat.name }],
    meshes: [{ name: mat.name, primitives: [primitive] }],
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
