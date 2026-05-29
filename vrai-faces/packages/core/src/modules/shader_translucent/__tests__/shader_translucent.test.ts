import { describe, it, expect } from 'vitest';
import * as THREE from 'three/webgpu';
import { shaderTranslucent } from '../index';
import { createImpl, mapOpacity } from '../impl/create';
import { lookupMaterial } from '@utils/resource_registry';
import type { GeometryRef, TextureRef } from '@contracts/mesh_builder';

describe('shader_translucent barrel', () => {
  it('exposes the expected surface', () => {
    expect(typeof shaderTranslucent.boot).toBe('function');
    expect(typeof shaderTranslucent.setOpacity).toBe('function');
  });
});

describe('mapOpacity anchor rows (Memory_management.MD §4)', () => {
  it('1.00 → opaque', () => {
    const m = mapOpacity(1);
    expect(m.transmission).toBeCloseTo(0);
    expect(m.opacity).toBeCloseTo(1);
    expect(m.fresnelStrength).toBeCloseTo(0);
  });
  it('0.00 → ghost', () => {
    const m = mapOpacity(0);
    expect(m.transmission).toBeCloseTo(1);
    expect(m.opacity).toBeCloseTo(0.55);
    expect(m.fresnelStrength).toBeCloseTo(1);
  });
  it('clamps out-of-range input', () => {
    expect(mapOpacity(-5).transmission).toBeCloseTo(1);
    expect(mapOpacity(5).transmission).toBeCloseTo(0);
  });
});

describe('shader_translucent material (TSL Fresnel rim)', () => {
  // Unregistered refs: build() tolerates them (the registry returns null, so
  // the texture/map is simply absent), letting us exercise the real node
  // material without a GPU, a renderer, or mesh_builder output.
  const geometry = { __brand: 'GeometryRef', id: 'unreg-geo' } as GeometryRef;
  const texture  = { __brand: 'TextureRef',  id: 'unreg-tex' } as TextureRef;

  it('build() registers a node material carrying a Fresnel emissiveNode', () => {
    const mod = createImpl();
    const h = mod.build({ geometry, texture });
    const mat = lookupMaterial(h.id);
    expect(mat).toBeInstanceOf(THREE.MeshPhysicalNodeMaterial);
    if (mat instanceof THREE.MeshPhysicalNodeMaterial) {
      expect(mat.emissiveNode).not.toBeNull();   // the rim graph is attached
      expect(mat.transmission).toBeCloseTo(0);   // default level 1.0 → opaque
      expect(mat.opacity).toBeCloseTo(1);
    }
    mod.dispose();
  });

  it('setOpacity is uniform-only across the steady-state slider range', () => {
    const mod = createImpl();
    const h = mod.build({ geometry, texture });
    const mat = lookupMaterial(h.id);
    if (!(mat instanceof THREE.MeshPhysicalNodeMaterial)) throw new Error('material missing');

    // Leaving fully-opaque enables the transmission shader path — a one-time
    // recompile we don't fight. Everything after is the steady-state range.
    mod.setOpacity(h.id, 0.66);
    const versionSteady = mat.version;
    const nodeBefore = mat.emissiveNode;

    mod.setOpacity(h.id, 0.33);   // transmission 0.35 → 0.75: no boundary cross

    expect(mat.transmission).toBeCloseTo(0.75);
    expect(mat.opacity).toBeCloseTo(0.85);
    // Same node object + unchanged version ⇒ we mutated the uniform in place,
    // never rebuilt the graph or flipped needsUpdate (the README gotcha).
    expect(mat.emissiveNode).toBe(nodeBefore);
    expect(mat.version).toBe(versionSteady);

    mod.dispose();
  });

  it('snapshot round-trips the slider value and its derivatives', () => {
    const mod = createImpl();
    const h = mod.build({ geometry, texture });
    mod.setOpacity(h.id, 0.33);
    const snap = mod.snapshot(h.id);
    expect(snap.opacityLevel).toBeCloseTo(0.33);
    expect(snap.transmission).toBeCloseTo(0.75);
    expect(snap.opacity).toBeCloseTo(0.85);
    expect(snap.specularIntensity).toBeCloseTo(0.33);
    mod.dispose();
  });
});
