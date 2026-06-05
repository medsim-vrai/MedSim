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
  /** Remove a managed mesh (scene + animation runtime) and free its GPU
   *  resources. Used when the avatar is rebuilt from a new portrait. */
  detachMesh(meshId: string): void;
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

  // Fraction of the tighter viewport axis the avatar fills when framed. ~0.9 ⇒ a
  // large, nearly edge-to-edge face (good for QA + the bedside view). Tunable.
  const FRAME_FILL = 0.9;

  // Dolly the camera so the avatar fills ~FRAME_FILL of the viewport on the tighter
  // axis (accounting for aspect), so it never spills off a narrow/tall window.
  // Re-run on resize and whenever a mesh is attached/detached.
  function frameAvatar(): void {
    if (managed.size === 0) return;
    // Fit to the CORE face, NOT the raw bounding box. A handful of mis-detected /
    // out-of-frame landmarks (lm.y outside [0,1]) can stretch the bbox ~2-3x past
    // the visible face, leaving it small even at high FRAME_FILL. So take a central
    // percentile of the vertices per axis (trim outliers), then frame that extent.
    const xs: number[] = [];
    const ys: number[] = [];
    let minZ = Infinity;
    let maxZ = -Infinity;
    const v = new THREE.Vector3();
    for (const m of managed.values()) {
      m.updateMatrixWorld(true);
      const pos = m.geometry.getAttribute('position') as THREE.BufferAttribute | undefined;
      if (!pos) continue;
      for (let i = 0; i < pos.count; i += 1) {
        v.fromBufferAttribute(pos, i).applyMatrix4(m.matrixWorld);
        xs.push(v.x);
        ys.push(v.y);
        if (v.z < minZ) minZ = v.z;
        if (v.z > maxZ) maxZ = v.z;
      }
    }
    if (xs.length === 0) return;
    xs.sort((a, b) => a - b);
    ys.sort((a, b) => a - b);
    const at = (arr: number[], p: number): number =>
      arr[Math.min(arr.length - 1, Math.max(0, Math.round(p * (arr.length - 1))))]!;
    const TRIM = 0.05; // ignore the extreme 5% of vertices per axis (outliers)
    const minX = at(xs, TRIM);
    const maxX = at(xs, 1 - TRIM);
    const minY = at(ys, TRIM);
    const maxY = at(ys, 1 - TRIM);
    const sizeX = maxX - minX;
    const sizeY = maxY - minY;
    const sizeZ = Number.isFinite(maxZ - minZ) ? maxZ - minZ : 0;
    const cx = (minX + maxX) / 2;
    const cy = (minY + maxY) / 2;
    const cz = (minZ + maxZ) / 2;
    const fov = (camera.fov * Math.PI) / 180;
    const tan = Math.max(Math.tan(fov / 2), 1e-3);
    const aspect = camera.aspect || 1;
    // Distance so the CORE face projects to FRAME_FILL of the tighter axis; the z
    // term is only a floor keeping the camera in front of the mesh (no clipping).
    const distH = (sizeY / 2) / (tan * FRAME_FILL);
    const distW = (sizeX / 2) / (tan * aspect * FRAME_FILL);
    const dist = Math.max(distH, distW, sizeZ / 2 + 0.1);
    // Degenerate/NaN geometry must not poison the camera (→ blank screen).
    if (!Number.isFinite(dist) || !Number.isFinite(cx)
        || !Number.isFinite(cy) || !Number.isFinite(cz)) return;
    camera.position.set(cx, cy, cz + Math.max(dist, 0.2));
    camera.lookAt(cx, cy, cz);
    camera.updateProjectionMatrix();
  }

  let lastW = -1, lastH = -1, lastDpr = -1;
  function fitToWindow(): void {
    const dpr = Math.min(window.devicePixelRatio || 1, 2);
    const w = window.innerWidth;
    const h = window.innerHeight;
    if (typeof window !== 'undefined') {
      const d = window as unknown as { __fit?: { calls: number; w: number; h: number } };
      d.__fit = { calls: (d.__fit?.calls ?? 0) + 1, w, h };
    }
    // Skip redundant resizes — same dimensions ⇒ no work. Crucially this breaks
    // any resize feedback loop (e.g. setSize → reflow → resize → setSize …),
    // which would otherwise re-dolly the camera every event and make the avatar
    // pulse/scale rapidly while idle.
    if (w === lastW && h === lastH && dpr === lastDpr) return;
    lastW = w; lastH = h; lastDpr = dpr;
    renderer.setPixelRatio(dpr);
    // updateStyle=true: set the canvas CSS size to the logical w×h (buffer stays
    // w×dpr for crispness). With `false`, a retina canvas (dpr 2) displayed at
    // its buffer size — 2× the viewport — pushing the centred avatar into the
    // bottom-right corner (only "fixed" by zooming the window under 100%).
    renderer.setSize(w, h, true);
    camera.aspect = w / Math.max(h, 1);
    camera.updateProjectionMatrix();
    // Re-frame to fill the CURRENT window. The dedup early-return above means this
    // runs ONLY on a real size change (never a resize feedback loop), and
    // frameAvatar() only moves the camera — it never resizes the canvas, so it
    // can't re-trigger fitToWindow. So the face holds ~FRAME_FILL of whatever the
    // DEVICE window is: maximizing, moving to a bigger display, or a late layout
    // settle all re-fit, instead of staying sized for the window-at-load-time.
    frameAvatar();
  }
  fitToWindow();
  window.addEventListener('resize', fitToWindow);

  // Dev/diag-only inspection handle (window.__vrai) for debugging the scene.
  const dbg = (() => {
    try {
      const dev = Boolean((import.meta as { env?: { DEV?: boolean } }).env?.DEV);
      return dev || (typeof location !== 'undefined' && location.search.includes('diag=1'));
    } catch { return false; }
  })();
  if (dbg && typeof window !== 'undefined') {
    (window as unknown as { __vrai?: unknown }).__vrai = { camera, scene, managed, frameAvatar };
  }

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
      frameAvatar();
    },

    detachMesh(meshId) {
      const mesh = managed.get(meshId);
      if (!mesh) return;
      animationRuntime.detach(meshId);
      scene.remove(mesh);
      managed.delete(meshId);
      mesh.geometry.dispose();
      const mat = mesh.material;
      if (Array.isArray(mat)) { for (const m of mat) m.dispose(); }
      else if (mat) mat.dispose();
      frameAvatar();
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
