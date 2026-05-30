import type { BlendshapeWeights } from '@contracts/shared';
import type { Landmark3 } from './face_topology';

/**
 * Result of running MediaPipe FaceLandmarker on a portrait: the per-identity
 * landmark positions (468 or 478) plus the ARKit-52 blendshape baseline read
 * straight off the model (`categoryName → score`).
 */
export interface FaceDetection {
  landmarks: Landmark3[];
  blendshapes: BlendshapeWeights;
}

/**
 * Local-first asset locations (ADR-0001 — NOT a CDN). The WASM ships inside
 * `@mediapipe/tasks-vision` and the `.task` model must be bundled alongside it.
 * Until both are served from the app origin, detection fails fast and the caller
 * falls back to the head proxy.
 */
const MEDIAPIPE_WASM_BASE = '/assets/mediapipe/wasm';
const FACE_MODEL_URL = '/assets/mediapipe/face_landmarker.task';

/**
 * Run FaceLandmarker on a normalized portrait and return its landmarks +
 * blendshape baseline, or `null` if it can't run here.
 *
 * Browser+asset gated by design:
 *  - jsdom / Node / workers without `createImageBitmap` → `null` (so the unit
 *    suite and headless paths never touch MediaPipe);
 *  - `@mediapipe/tasks-vision` is loaded via a DYNAMIC import so it lands in its
 *    own code-split chunk and never enters the main bundle or the test graph;
 *  - any failure (missing WASM/model asset, no GPU, no face found) resolves to
 *    `null` — `mesh_builder` then builds the placeholder sphere instead.
 */
export async function detectFaceLandmarks(png: Blob): Promise<FaceDetection | null> {
  try {
    if (typeof createImageBitmap !== 'function') return null;

    const vision = await import('@mediapipe/tasks-vision');
    const fileset = await vision.FilesetResolver.forVisionTasks(MEDIAPIPE_WASM_BASE);
    // Prefer the GPU delegate, but fall back to CPU when GPU init fails (headless,
    // no-WebGPU/WebGL tablets, CI). Without this the whole real path silently drops
    // to the sphere even when a face is present.
    const make = (delegate: 'GPU' | 'CPU') =>
      vision.FaceLandmarker.createFromOptions(fileset, {
        baseOptions: { modelAssetPath: FACE_MODEL_URL, delegate },
        runningMode: 'IMAGE',
        numFaces: 1,
        outputFaceBlendshapes: true,
      });
    const landmarker = await make('GPU').catch(() => make('CPU'));

    try {
      const bitmap = await createImageBitmap(png);
      const result = landmarker.detect(bitmap);
      bitmap.close();

      const face = result.faceLandmarks[0];
      if (!face || face.length === 0) return null;

      const blendshapes: BlendshapeWeights = {};
      const cls = result.faceBlendshapes[0];
      if (cls) {
        for (const c of cls.categories) {
          if (c.categoryName) blendshapes[c.categoryName] = c.score;
        }
      }

      // `NormalizedLandmark` ({x,y,z,visibility}) is structurally a `Landmark3`.
      return { landmarks: face, blendshapes };
    } finally {
      landmarker.close();
    }
  } catch {
    return null;
  }
}
