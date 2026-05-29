// Shared, in-process registry for Three.js objects.
//
// Why this exists: module barrels exchange branded-id references
// (`GeometryRef`, `TextureRef`, `TranslucentMaterial`) but the actual
// Three objects are heavy and must live in one place. Modules write
// here on `build()` and read here on `lookup*()`. The renderer reads
// every entry on each frame to assemble the scene.
//
// This is a utility, NOT a module — the §3 module list is closed.

import * as THREE from 'three/webgpu';
import type { GeometryRef, TextureRef } from '@contracts/mesh_builder';
import type { TranslucentMaterial } from '@contracts/shader_translucent';

const geometries = new Map<string, THREE.BufferGeometry>();
const textures   = new Map<string, THREE.Texture>();
const materials  = new Map<string, THREE.Material>();
const meshes     = new Map<string, THREE.Mesh>();

let nextId = 0;
function mkId(prefix: string): string {
  nextId++;
  return `${prefix}-${nextId.toString(36)}`;
}

// --- Geometry ---
export function registerGeometry(g: THREE.BufferGeometry): GeometryRef {
  const id = mkId('geo');
  geometries.set(id, g);
  return { __brand: 'GeometryRef', id } as GeometryRef;
}
export function lookupGeometry(ref: GeometryRef): THREE.BufferGeometry | null {
  return geometries.get(ref.id) ?? null;
}

// --- Texture ---
export function registerTexture(t: THREE.Texture): TextureRef {
  const id = mkId('tex');
  textures.set(id, t);
  return { __brand: 'TextureRef', id } as TextureRef;
}
export function lookupTexture(ref: TextureRef): THREE.Texture | null {
  return textures.get(ref.id) ?? null;
}

// --- Material ---
export function registerMaterial(m: THREE.Material): TranslucentMaterial {
  const id = mkId('mat');
  materials.set(id, m);
  return { id };
}
export function lookupMaterial(id: string): THREE.Material | null {
  return materials.get(id) ?? null;
}

// --- Mesh ---
export function registerMesh(m: THREE.Mesh, idHint?: string): string {
  const id = idHint ?? mkId('mesh');
  meshes.set(id, m);
  return id;
}
export function lookupMesh(id: string): THREE.Mesh | null {
  return meshes.get(id) ?? null;
}
export function listMeshes(): IterableIterator<[string, THREE.Mesh]> {
  return meshes.entries();
}

// --- Disposal ---
export function disposeAll(): void {
  for (const g of geometries.values()) g.dispose();
  for (const t of textures.values())   t.dispose();
  for (const m of materials.values())  m.dispose();
  geometries.clear();
  textures.clear();
  materials.clear();
  meshes.clear();
}
