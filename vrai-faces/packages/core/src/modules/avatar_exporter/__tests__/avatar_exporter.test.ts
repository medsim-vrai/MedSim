import { describe, it, expect } from 'vitest';
import * as THREE from 'three/webgpu';
import { avatarExporter } from '../index';
import { registerGeometry } from '@utils/resource_registry';
import type { ExportInput } from '@contracts/avatar_exporter';
import type { BuiltMesh, GeometryRef, TextureRef } from '@contracts/mesh_builder';
import type { TranslucentMaterialSnapshot } from '@contracts/shader_translucent';

const GLB_MAGIC = 0x46546c67;   // 'glTF'
const CHUNK_JSON = 0x4e4f534a;  // 'JSON'

// Refs that resolve to nothing in the registry → exporter uses its placeholder
// geometry. That's the right path to exercise the container writer in Node.
const mesh: BuiltMesh = {
  meshId: 'patient-007-mesh',
  geometryRef: { __brand: 'GeometryRef', id: 'unregistered' } as GeometryRef,
  textureRef: { __brand: 'TextureRef', id: 'unregistered' } as TextureRef,
  baselineMood: { jawOpen: 0.1, mouthSmileLeft: 0.2 },
  vertexCount: 3,
};

const translucency: TranslucentMaterialSnapshot = {
  opacityLevel: 0.66,
  transmission: 0.4,
  opacity: 0.7,
  fresnelStrength: 0.5,
  specularIntensity: 0.3,
};

const input: ExportInput = { mesh, translucency, bakeOpacity: true };

interface GltfDoc {
  asset: { version: string };
  materials: Array<{
    extensions?: Record<string, { transmissionFactor?: number }>;
    extras?: Record<string, unknown>;
  }>;
  buffers: Array<{ byteLength: number }>;
  extensionsUsed: string[];
  extensions?: Record<string, unknown>;
  meshes?: Array<{
    weights?: number[];
    extras?: { targetNames?: string[] };
    primitives: Array<{ targets?: Array<Record<string, number>> }>;
  }>;
  accessors?: Array<{ count: number; type: string; min?: number[]; max?: number[] }>;
}

async function parseGlb(blob: Blob): Promise<{ magic: number; version: number; jsonType: number; doc: GltfDoc }> {
  const buf = await blob.arrayBuffer();
  const dv = new DataView(buf);
  const magic = dv.getUint32(0, true);
  const version = dv.getUint32(4, true);
  const jsonLen = dv.getUint32(12, true);
  const jsonType = dv.getUint32(16, true);
  const jsonBytes = new Uint8Array(buf, 20, jsonLen);
  const doc = JSON.parse(new TextDecoder().decode(jsonBytes)) as GltfDoc;
  return { magic, version, jsonType, doc };
}

describe('avatar_exporter barrel', () => {
  it('exposes the expected surface', () => {
    expect(typeof avatarExporter.boot).toBe('function');
    expect(typeof avatarExporter.exportGLB).toBe('function');
    expect(typeof avatarExporter.exportVRM).toBe('function');
  });
});

describe('avatar_exporter exportGLB', () => {
  it('writes a valid glTF 2.0 binary', async () => {
    const blob = await avatarExporter.exportGLB(input);
    expect(blob.type).toBe('model/gltf-binary');
    const { magic, version, jsonType, doc } = await parseGlb(blob);
    expect(magic).toBe(GLB_MAGIC);
    expect(version).toBe(2);
    expect(jsonType).toBe(CHUNK_JSON);
    expect(doc.asset.version).toBe('2.0');
    expect(doc.buffers[0]!.byteLength).toBeGreaterThan(0);
  });

  it('bakes opacity into KHR_materials_transmission + extras.vraiOpacity', async () => {
    const { doc } = await parseGlb(await avatarExporter.exportGLB(input));
    const mat = doc.materials[0]!;
    expect(doc.extensionsUsed).toContain('KHR_materials_transmission');
    expect(mat.extensions?.['KHR_materials_transmission']?.transmissionFactor).toBeCloseTo(0.4);
    expect(mat.extras?.['vraiOpacity']).toBeCloseTo(0.66);
    expect(mat.extras?.['vraiBaselineMood']).toEqual({ jawOpen: 0.1, mouthSmileLeft: 0.2 });
  });

  it('omits transmission when bakeOpacity is false', async () => {
    const { doc } = await parseGlb(await avatarExporter.exportGLB({ ...input, bakeOpacity: false }));
    expect(doc.materials[0]!.extensions?.['KHR_materials_transmission']?.transmissionFactor).toBe(0);
  });
});

describe('avatar_exporter exportVRM', () => {
  it('adds a minimal VRMC_vrm extension on top of the GLB', async () => {
    const { magic, doc } = await parseGlb(await avatarExporter.exportVRM(input));
    expect(magic).toBe(GLB_MAGIC);
    expect(doc.extensionsUsed).toContain('VRMC_vrm');
    expect(doc.extensions?.['VRMC_vrm']).toBeTruthy();
  });
});

describe('avatar_exporter morph-target baking', () => {
  it('bakes geometry morph targets into glTF targets[] + named weights', async () => {
    // A 3-vertex geom with two named morph targets (one non-zero, one all-zero).
    const geo = new THREE.BufferGeometry();
    geo.setAttribute('position', new THREE.BufferAttribute(new Float32Array([0, 0, 0, 1, 0, 0, 0, 1, 0]), 3));
    geo.setIndex(new THREE.BufferAttribute(new Uint32Array([0, 1, 2]), 1));
    const jaw = new THREE.BufferAttribute(new Float32Array([0, 0, 0, 0, -0.2, 0, 0, -0.1, 0]), 3);
    const smile = new THREE.BufferAttribute(new Float32Array(9), 3); // all zero
    geo.morphAttributes.position = [jaw, smile];
    geo.userData['morphTargetNames'] = ['jawOpen', 'mouthSmileLeft'];
    const ref = registerGeometry(geo);

    const rigged: BuiltMesh = { ...mesh, geometryRef: ref, vertexCount: 3 };
    const { doc } = await parseGlb(
      await avatarExporter.exportGLB({ mesh: rigged, translucency, bakeOpacity: true }),
    );

    const prim = doc.meshes?.[0]?.primitives[0];
    expect(prim?.targets).toHaveLength(2);                       // one per blendshape
    expect(doc.meshes?.[0]?.weights).toEqual([0, 0]);           // initial weights
    expect(doc.meshes?.[0]?.extras?.targetNames).toEqual(['jawOpen', 'mouthSmileLeft']);

    // The jawOpen target's POSITION accessor carries real (non-zero) bounds.
    const jawAccessorIdx = prim?.targets?.[0]?.['POSITION'];
    expect(typeof jawAccessorIdx).toBe('number');
    const acc = doc.accessors?.[jawAccessorIdx as number];
    expect(acc?.type).toBe('VEC3');
    expect(acc?.count).toBe(3);
    expect(acc?.min?.[1]).toBeCloseTo(-0.2);                    // min Y delta
  });

  it('omits the targets block for unrigged (placeholder) geometry', async () => {
    // The shared `input` uses an unregistered ref → placeholder geometry, no morphs.
    const { doc } = await parseGlb(await avatarExporter.exportGLB(input));
    expect(doc.meshes?.[0]?.primitives[0]?.targets).toBeUndefined();
    expect(doc.meshes?.[0]?.weights).toBeUndefined();
  });
});
