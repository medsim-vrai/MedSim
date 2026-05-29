import { describe, it, expect } from 'vitest';
import * as THREE from 'three/webgpu';
import { animationRuntime } from '../index';
import { createImpl, smoothstep, blendEmotion } from '../impl/create';
import { registerMesh } from '@utils/resource_registry';
import type { BlendshapeWeights, BootDeps, DiagHandle, ModuleStat } from '@contracts/shared';

describe('animation_runtime', () => {
  it('exposes Lifecycle + Resumable', () => {
    expect(typeof animationRuntime.boot).toBe('function');
    expect(typeof animationRuntime.pause).toBe('function');
    expect(typeof animationRuntime.resume).toBe('function');
    expect(typeof animationRuntime.snapshot).toBe('function');
    expect(typeof animationRuntime.restore).toBe('function');
  });

  it('snapshot/restore round-trips state', async () => {
    animationRuntime.attach('mesh-a');
    animationRuntime.setEmotion({ mouthSmileLeft: 0.4, mouthSmileRight: 0.4 });
    animationRuntime.pushVisemes([{ t: 100, weights: { jawOpen: 0.8 } }]);
    const snap = animationRuntime.snapshot();

    animationRuntime.detach('mesh-a');
    animationRuntime.setEmotion({});

    await animationRuntime.restore(snap);
    const after = animationRuntime.snapshot();

    expect(after.attached).toContain('mesh-a');
    expect(after.emotionWeights.mouthSmileLeft).toBeCloseTo(0.4);
    expect(after.pendingVisemes[0]?.weights.jawOpen).toBeCloseTo(0.8);
  });
});

describe('animation_runtime diag reporting', () => {
  function fakeDeps(): { deps: BootDeps; stats: Map<string, Partial<ModuleStat>> } {
    const stats = new Map<string, Partial<ModuleStat>>();
    const diag: DiagHandle = {
      push() { /* timeline events not under test */ },
      set(moduleId, stat) { stats.set(moduleId, { ...stats.get(moduleId), ...stat }); },
    };
    return { deps: { diag, scenarioId: 'scn', characterId: 'chr' }, stats };
  }

  it('surfaces fps + lastTickMs to diag once past REPORT_EVERY ticks', async () => {
    const { deps, stats } = fakeDeps();
    const r = createImpl();
    await r.boot(deps);
    r.start();

    // REPORT_EVERY is 30; tick past it so at least one report lands. nowMs is
    // sourced from performance.now() to match the clock domain start() seeds.
    for (let i = 0; i < 31; i++) r.tick(performance.now());

    const stat = stats.get('animation_runtime');
    expect(stat).toBeDefined();
    expect(stat?.state).toBe('running');
    expect(stat?.fps ?? 0).toBeGreaterThan(0);
    expect(stat?.lastTickMs ?? 0).toBeGreaterThan(0);

    r.dispose();
  });

  it('stays quiet before the first REPORT_EVERY boundary', async () => {
    const { deps, stats } = fakeDeps();
    const r = createImpl();
    await r.boot(deps);
    r.start();
    for (let i = 0; i < 5; i++) r.tick(performance.now());
    expect(stats.has('animation_runtime')).toBe(false);
    r.dispose();
  });
});

describe('emotion cross-fade helpers', () => {
  it('smoothstep clamps and pins the anchor points', () => {
    expect(smoothstep(-1)).toBe(0);
    expect(smoothstep(0)).toBe(0);
    expect(smoothstep(0.5)).toBeCloseTo(0.5);   // symmetric midpoint
    expect(smoothstep(1)).toBe(1);
    expect(smoothstep(2)).toBe(1);
    // Eased, not linear: a quarter of the way in is well below 0.25.
    expect(smoothstep(0.25)).toBeLessThan(0.25);
  });

  it('blendEmotion lerps toward the target and prunes zeros', () => {
    const from: BlendshapeWeights = { jawOpen: 0.8 };
    const to: BlendshapeWeights = { mouthSmileLeft: 0.4 };
    const current: BlendshapeWeights = {};

    blendEmotion(from, to, current, 0.5);
    // jawOpen is leaving (only in `from`): decays to half.
    expect(current.jawOpen).toBeCloseTo(0.4);
    // mouthSmileLeft is arriving (only in `to`): rises from 0.
    expect(current.mouthSmileLeft).toBeCloseTo(0.2);

    blendEmotion(from, to, current, 1);
    // Fully arrived: the departing key is pruned, the target is exact.
    expect('jawOpen' in current).toBe(false);
    expect(current.mouthSmileLeft).toBeCloseTo(0.4);
  });
});

describe('animation_runtime emotion cross-fade (integration)', () => {
  // A fake mesh whose only morph target is mouthSmileLeft at index 0. Idle
  // motion writes only eye* shapes, so index 0 carries the emotion fade alone.
  function fakeSmileMesh(id: string): THREE.Mesh {
    const geom = new THREE.BufferGeometry();
    geom.userData['morphTargetNames'] = ['mouthSmileLeft'];
    const mesh = new THREE.Mesh(geom);
    mesh.morphTargetInfluences = [0];
    registerMesh(mesh, id);
    return mesh;
  }

  it('eases mouthSmileLeft from 0 → target over the easeMs window', () => {
    const r = createImpl();
    const mesh = fakeSmileMesh('fade-mesh');
    r.attach('fade-mesh');
    r.start();

    const t0 = 10_000;
    r.setEmotion({ mouthSmileLeft: 0.4 }, 200);

    r.tick(t0);              // anchors the fade; raw = 0
    expect(mesh.morphTargetInfluences![0]).toBeCloseTo(0, 5);

    r.tick(t0 + 100);        // halfway: smoothstep(0.5) = 0.5 ⇒ 0.4 * 0.5
    expect(mesh.morphTargetInfluences![0]).toBeCloseTo(0.2, 5);

    r.tick(t0 + 200);        // complete: clamps to the target
    expect(mesh.morphTargetInfluences![0]).toBeCloseTo(0.4, 5);

    // Fade is finished — a later tick holds at the target.
    r.tick(t0 + 400);
    expect(mesh.morphTargetInfluences![0]).toBeCloseTo(0.4, 5);

    r.dispose();
  });

  it('setEmotion with no easeMs snaps immediately', () => {
    const r = createImpl();
    const mesh = fakeSmileMesh('snap-mesh');
    r.attach('snap-mesh');
    r.start();

    r.setEmotion({ mouthSmileLeft: 0.7 });   // no ease window
    r.tick(20_000);
    expect(mesh.morphTargetInfluences![0]).toBeCloseTo(0.7, 5);

    r.dispose();
  });
});
