// Main-thread renderer. WebGPU-preferred per ADR-0009, with a WebGL2
// fallback chosen once at boot — we never switch backends mid-session.
//
// We import the entire Three surface from `three/webgpu` — a superset
// build that bundles core Three + the node system + WebGPURenderer. This
// is load-bearing: WebGPURenderer's node-based lighting only recognizes
// lights/materials constructed from the *same* module instance. Mixing
// classic `three` with `three/webgpu` pulls two copies of Three and the
// renderer silently drops the scene lights ("LightsNode.setupNodeLights:
// Light node not found"), leaving the avatar unlit. Every module that
// builds scene objects (mesh_builder, shader_translucent, demo_boot,
// resource_registry, animation_runtime) therefore imports `three/webgpu`.
//
// WebGPURenderer negotiates a WebGPU backend when an adapter exists and
// otherwise initializes its own WebGL2 backend, so one instance covers
// both ADR-0009 paths (no separate WebGLRenderer needed).
//
// The OffscreenCanvas/worker variant lives at workers/renderer.worker.ts;
// the shell decides which to use based on `transferControlToOffscreen`
// support. For the first cut we always run main-thread.

import * as THREE from 'three/webgpu';
import { animationRuntime } from '@modules/animation_runtime';
import { lookupMaterial } from '@utils/resource_registry';
import { diag } from '@perf/diag';

export interface RendererHandle {
  scene: THREE.Scene;
  camera: THREE.PerspectiveCamera;
  /** Add a mesh and bind it to the animation runtime by id. */
  attachMesh(meshId: string, mesh: THREE.Mesh): void;
  /** Bind the same material to a different mesh later if needed. */
  swapMaterial(meshId: string, materialId: string): void;
  start(): void;
  stop(): void;
  dispose(): void;
}

async function makeRenderer(canvas: HTMLCanvasElement): Promise<{
  renderer: THREE.WebGPURenderer;
  kind: 'webgpu' | 'webgl2';
}> {
  // ADR-0009 — one WebGPURenderer. init() picks a WebGPU backend if an
  // adapter is available and otherwise stands up a WebGL2 backend; the
  // choice is made here, once, and never changes for the session.
  const renderer = new THREE.WebGPURenderer({ canvas, antialias: true });
  try {
    await renderer.init();
  } catch (e) {
    diag.push({
      t: performance.now(), moduleId: 'shell.renderer', kind: 'error',
      message: 'WebGPURenderer.init failed (no WebGPU and no WebGL2?)',
      data: e instanceof Error ? e.message : String(e),
    });
    throw e;
  }
  // `backend` is not in the public typings; read it defensively just to
  // label the diag line — it has no functional effect.
  const backend = (renderer as unknown as { backend?: { isWebGPUBackend?: boolean } }).backend;
  const kind: 'webgpu' | 'webgl2' = backend?.isWebGPUBackend ? 'webgpu' : 'webgl2';
  return { renderer, kind };
}

export async function mountRenderer(canvas: HTMLCanvasElement): Promise<RendererHandle> {
  const { renderer, kind } = await makeRenderer(canvas);
  diag.set('shell.renderer', { state: 'running' });
  diag.push({
    t: performance.now(), moduleId: 'shell.renderer', kind: 'info',
    message: `renderer initialized: ${kind}`,
  });

  const scene = new THREE.Scene();
  scene.background = new THREE.Color(0x000000);

  const camera = new THREE.PerspectiveCamera(35, 1, 0.1, 100);
  camera.position.set(0, 0, 2.0);
  camera.lookAt(0, 0, 0);

  // Lighting — three-point-ish setup tuned for transmission look.
  const key  = new THREE.DirectionalLight(0xffffff, 1.6);
  key.position.set(1.2, 1.0, 1.6);
  const fill = new THREE.DirectionalLight(0xa0c0ff, 0.6);
  fill.position.set(-1.4, 0.2, 0.6);
  const rim  = new THREE.DirectionalLight(0xffffff, 0.9);
  rim.position.set(0, -0.5, -1.6);
  const amb  = new THREE.AmbientLight(0x202028, 1.0);
  scene.add(key, fill, rim, amb);

  // Track managed meshes so dispose() can free them.
  const managed = new Map<string, THREE.Mesh>();

  function fitToWindow(): void {
    const dpr = Math.min(window.devicePixelRatio || 1, 2);
    const w = window.innerWidth;
    const h = window.innerHeight;
    renderer.setPixelRatio(dpr);
    renderer.setSize(w, h, false);
    camera.aspect = w / Math.max(h, 1);
    camera.updateProjectionMatrix();
  }
  fitToWindow();
  window.addEventListener('resize', fitToWindow);

  let rafId = 0;
  let running = false;
  const frame = (now: number): void => {
    if (!running) return;
    animationRuntime.tick(now);
    renderer.render(scene, camera);
    rafId = requestAnimationFrame(frame);
  };

  return {
    scene, camera,

    attachMesh(meshId, mesh) {
      managed.set(meshId, mesh);
      scene.add(mesh);
      animationRuntime.attach(meshId);
    },

    swapMaterial(meshId, materialId) {
      const mesh = managed.get(meshId);
      if (!mesh) return;
      const mat = lookupMaterial(materialId);
      if (!mat) return;
      const prev = mesh.material;
      mesh.material = mat;
      if (Array.isArray(prev)) {
        for (const m of prev) m.dispose();
      } else if (prev) {
        prev.dispose();
      }
    },

    start() {
      if (running) return;
      running = true;
      animationRuntime.start();
      rafId = requestAnimationFrame(frame);
    },

    stop() {
      running = false;
      animationRuntime.stop();
      if (rafId) cancelAnimationFrame(rafId);
      rafId = 0;
    },

    dispose() {
      running = false;
      animationRuntime.stop();
      if (rafId) cancelAnimationFrame(rafId);
      window.removeEventListener('resize', fitToWindow);
      for (const mesh of managed.values()) {
        scene.remove(mesh);
      }
      managed.clear();
      renderer.dispose();
    },
  };
}
