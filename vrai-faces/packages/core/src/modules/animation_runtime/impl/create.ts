import type * as THREE from 'three/webgpu';
import type {
  AnimationRuntimeModule,
  AnimationSnapshot,
} from '@contracts/animation_runtime';
import type { BlendshapeWeights, BootDeps } from '@contracts/shared';
import { lookupMesh } from '@utils/resource_registry';
import { idleMotion } from '@modules/idle_motion';

// The mesh's morph-target count: ARKit-52 + the supplemental `eyesClosed` (AU43,
// RB-001/ADR-0035) = 53. It caps BOTH the accum buffer (size) and the per-mesh apply
// loop (`min(inf.length, SHAPE_COUNT)`), so it MUST be ≥ the mesh's morph count.
// BUG IT FIXES (ADR-0036 QA): this was 52, so the 53rd shape — `eyesClosed`, index 52 —
// fell outside the `idx < SHAPE_COUNT` guard and was silently dropped; the eyes never
// closed via the QA panel OR the clinical pain/drowsy moods that compose it. Adding any
// further supplemental morph means bumping this (see the eyesClosed regression test).
const SHAPE_COUNT = 53;

// How often tick() surfaces frame timing to diag. ~30 frames ≈ 0.5 s at 60 fps —
// frequent enough for a live readout, rare enough to keep the hot loop light.
const REPORT_EVERY = 30;

/**
 * Smoothstep easing on [0,1] — `3x² − 2x³` with clamped input. Zero slope at
 * both ends, so an emotion cross-fade eases in and out instead of starting and
 * stopping abruptly. Pure; exported for unit testing.
 */
export function smoothstep(t: number): number {
  const x = t <= 0 ? 0 : t >= 1 ? 1 : t;
  return x * x * (3 - 2 * x);
}

/**
 * Cross-fade emotion weights `from → to` by factor `k ∈ [0,1]`, writing the
 * blended result into `current` (mutated in place, allocation-free). Keys that
 * blend to exactly 0 are deleted so the applied set stays sparse. `current` is
 * always a subset of `from ∪ to` (the caller seeds `from` from the live applied
 * weights), so no separate stale-key sweep is needed. Pure; exported for tests.
 */
export function blendEmotion(
  from: BlendshapeWeights,
  to: BlendshapeWeights,
  current: BlendshapeWeights,
  k: number,
): void {
  for (const key in to) {
    const a = from[key] ?? 0;
    const v = a + ((to[key] ?? 0) - a) * k;
    if (v === 0) delete current[key]; else current[key] = v;
  }
  for (const key in from) {
    if (key in to) continue;
    const v = (from[key] ?? 0) * (1 - k);
    if (v === 0) delete current[key]; else current[key] = v;
  }
}

export function createImpl(): AnimationRuntimeModule {
  let _deps: BootDeps | null = null;
  let running = false;
  const attached = new Set<string>();
  // `emotion` is the cross-fade TARGET (what snapshot persists). `emotionCurrent`
  // is what we actually apply each tick; it eases toward `emotion` over a fade.
  // `emotionFrom` is the applied set captured when a fade begins.
  const emotion: BlendshapeWeights = {};
  const emotionCurrent: BlendshapeWeights = {};
  const emotionFrom: BlendshapeWeights = {};
  let fadeDurMs = 0;        // 0 ⇒ no fade in flight (emotionCurrent === emotion)
  let fadeStartMs = -1;     // anchored to the renderer clock on the fade's 1st tick
  const pending: Array<{ t: number; weights: BlendshapeWeights }> = [];

  // Pre-allocated hot-loop buffers (Code Guide §3.1). Re-used every tick;
  // never reallocated.
  const accum = new Float32Array(SHAPE_COUNT);
  const idleBuf: BlendshapeWeights = {};

  let lastFrame = 16.7;     // rolling-average frame time, ms
  let lastNow = 0;
  let ticks = 0;            // frame counter; throttles the diag report

  /**
   * Resolve a shape NAME to an index in the mesh's morph attribute
   * array. The mesh stores its name list in `geometry.userData.morphTargetNames`
   * (placed there by `mesh_builder`). We cache the lookup per mesh.
   */
  const nameIdxCache = new WeakMap<THREE.Object3D, Map<string, number>>();
  function indexOfShape(mesh: THREE.Mesh, name: string): number {
    let cache = nameIdxCache.get(mesh);
    if (!cache) {
      cache = new Map();
      const names = mesh.geometry.userData['morphTargetNames'];
      if (Array.isArray(names)) {
        for (let i = 0; i < names.length; i++) {
          if (typeof names[i] === 'string') cache.set(names[i] as string, i);
        }
      }
      nameIdxCache.set(mesh, cache);
    }
    return cache.get(name) ?? -1;
  }

  function applyToMesh(mesh: THREE.Mesh): void {
    const inf = mesh.morphTargetInfluences;
    if (!inf) return;
    const lim = Math.min(inf.length, SHAPE_COUNT);
    for (let i = 0; i < lim; i++) {
      const v = accum[i]!;
      inf[i] = v > 1 ? 1 : v < 0 ? 0 : v;
    }
  }

  return {
    async boot(deps) { _deps = deps; },

    dispose() {
      running = false;
      attached.clear();
      pending.length = 0;
      for (const k of Object.keys(emotion)) delete emotion[k];
      for (const k of Object.keys(emotionCurrent)) delete emotionCurrent[k];
      for (const k of Object.keys(emotionFrom)) delete emotionFrom[k];
      fadeDurMs = 0;
      fadeStartMs = -1;
      _deps = null;
    },

    attach(meshId) { attached.add(meshId); },
    detach(meshId) { attached.delete(meshId); },

    pushVisemes(frames) {
      for (const f of frames) pending.push(f);
    },

    setEmotion(weights, easeMs) {
      // Record the new target.
      for (const k of Object.keys(emotion)) delete emotion[k];
      for (const [k, v] of Object.entries(weights)) emotion[k] = v;

      const ease = easeMs ?? 0;
      if (ease > 0) {
        // Begin a cross-fade: freeze the currently-applied weights as the
        // fade's start, then let tick() ease emotionCurrent → emotion. The
        // start time is anchored to the renderer clock on the next tick.
        for (const k of Object.keys(emotionFrom)) delete emotionFrom[k];
        for (const [k, v] of Object.entries(emotionCurrent)) emotionFrom[k] = v;
        fadeDurMs = ease;
        fadeStartMs = -1;
      } else {
        // No ease window: snap the applied weights straight to the target.
        for (const k of Object.keys(emotionCurrent)) delete emotionCurrent[k];
        for (const [k, v] of Object.entries(emotion)) emotionCurrent[k] = v;
        fadeDurMs = 0;
        fadeStartMs = -1;
      }
    },

    start() { running = true; lastNow = performance.now(); },
    stop()  { running = false; },

    tick(nowMs: number) {
      if (!running) return;

      // 1. Rolling frame-time average.
      const dt = nowMs - lastNow;
      lastNow = nowMs;
      lastFrame = lastFrame * 0.9 + dt * 0.1;

      // 1b. Surface frame timing to diag for the diagnostics overlay. Throttled
      //     so the hot loop stays allocation-light (Code Guide §3.1).
      if (++ticks % REPORT_EVERY === 0) {
        _deps?.diag.set('animation_runtime', {
          state: 'running',
          fps: lastFrame > 0 ? 1000 / lastFrame : 0,
          lastTickMs: lastFrame,
        });
      }

      // 1c. Advance an in-flight emotion cross-fade. Anchored to the renderer
      //     clock on the first tick of the fade so easeMs is wall-clock time.
      if (fadeDurMs > 0) {
        if (fadeStartMs < 0) fadeStartMs = nowMs;
        const raw = (nowMs - fadeStartMs) / fadeDurMs;
        if (raw >= 1) {
          blendEmotion(emotionFrom, emotion, emotionCurrent, 1);
          fadeDurMs = 0;
          fadeStartMs = -1;
        } else {
          blendEmotion(emotionFrom, emotion, emotionCurrent, smoothstep(raw));
        }
      }

      // 2. Zero the accumulator.
      accum.fill(0);

      // 3. Drain pending visemes whose time has passed. For each shape
      //    in the frame, add its weight to the accumulator at the right
      //    index. We need a representative mesh to resolve name → index;
      //    use the first attached mesh that exists.
      let probeMesh: THREE.Mesh | null = null;
      for (const id of attached) {
        const m = lookupMesh(id);
        if (m) { probeMesh = m; break; }
      }
      if (probeMesh) {
        // Drain visemes that are due. `pending` is FIFO; we splice as we go.
        for (let i = 0; i < pending.length; i++) {
          const f = pending[i]!;
          if (f.t > nowMs) break;             // not yet due
          for (const [name, w] of Object.entries(f.weights)) {
            const idx = indexOfShape(probeMesh, name);
            if (idx >= 0 && idx < SHAPE_COUNT) accum[idx] = accum[idx]! + w;
          }
          pending.splice(i, 1);
          i--;
        }
        // 4. Add emotion baseline (the cross-faded applied weights, not the
        //    raw target — `emotionCurrent` eases toward `emotion` in step 1c).
        for (const [name, w] of Object.entries(emotionCurrent)) {
          const idx = indexOfShape(probeMesh, name);
          if (idx >= 0 && idx < SHAPE_COUNT) accum[idx] = accum[idx]! + w;
        }
        // 5. Add idle motion. idleMotion.sample mutates `idleBuf` additively.
        for (const k of Object.keys(idleBuf)) delete idleBuf[k];
        idleMotion.sample(nowMs, idleBuf);
        for (const [name, w] of Object.entries(idleBuf)) {
          const idx = indexOfShape(probeMesh, name);
          if (idx >= 0 && idx < SHAPE_COUNT) accum[idx] = accum[idx]! + w;
        }
      }

      // 6. Write to every attached mesh.
      for (const id of attached) {
        const m = lookupMesh(id);
        if (m) applyToMesh(m);
      }
    },

    lastFrameMs() { return lastFrame; },

    // --- Resumable ---
    async pause()  { running = false; },
    async resume() { running = true; lastNow = performance.now(); },
    snapshot(): AnimationSnapshot {
      return {
        attached: Array.from(attached),
        emotionWeights: { ...emotion },
        pendingVisemes: pending.map((p) => ({ t: p.t, weights: { ...p.weights } })),
      };
    },
    async restore(s) {
      attached.clear();
      for (const id of s.attached) attached.add(id);
      for (const k of Object.keys(emotion)) delete emotion[k];
      for (const [k, v] of Object.entries(s.emotionWeights)) emotion[k] = v;
      // A restore lands on the target instantly — it is not a fade.
      for (const k of Object.keys(emotionCurrent)) delete emotionCurrent[k];
      for (const [k, v] of Object.entries(emotion)) emotionCurrent[k] = v;
      for (const k of Object.keys(emotionFrom)) delete emotionFrom[k];
      fadeDurMs = 0;
      fadeStartMs = -1;
      pending.length = 0;
      pending.push(...s.pendingVisemes);
    },
  };
}
