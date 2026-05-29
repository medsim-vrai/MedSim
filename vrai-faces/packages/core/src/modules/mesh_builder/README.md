# mesh_builder

## Purpose
Turns a normalized portrait into a Three.BufferGeometry plus a diffuse
texture plus baseline ARKit-52 weights. This is the expensive step —
MediaPipe Face Landmarker runs here.

## Public contract
See `src/types/mesh_builder.ts`. The barrel exports `meshBuilder`.

## Dependencies
- `@contracts/*`
- `@mediapipe/tasks-vision`
- `three`

## Implementation — two paths
`build()` tries the REAL path and degrades to the FALLBACK if anything is
missing, so the pipeline always returns a usable `BuiltMesh`.

- **Real path** (`impl/face_landmarker.ts` + `impl/face_topology.ts`):
  `detectFaceLandmarks(png)` runs MediaPipe FaceLandmarker (dynamic import →
  own code-split chunk, **browser only**) → 478 per-identity landmarks + an
  ARKit-52 blendshape baseline. `buildFaceGeometry(landmarks, topology)` then
  deforms the canonical face topology into this identity's head (recenter +
  Y-flip), derives UVs from the landmarks, computes normals, and fills the 52
  morph attributes from the procedural basis. Pure & jsdom-testable.
- **Fallback path** (`buildBaseGeometry`): the elongated head-proxy sphere with
  52 zero morph attributes. Used in jsdom, on no-GPU, or when assets are absent.

### Bundled data assets (real path is LIVE in the browser)
Served from the app origin (local-first, ADR-0001 — never a CDN):
1. `public/assets/mediapipe/face_landmarker.task` — the FaceLandmarker model
   (3.75 MB, Google MediaPipe storage).
2. `public/assets/mediapipe/wasm/*` — the MediaPipe WASM (copied from
   `@mediapipe/tasks-vision`).
3. `public/assets/face/face_mesh_topology.json` — the canonical 468-vertex
   triangulation ONLY (898 triangles). Per-vertex UVs are NOT stored — they're
   derived from the landmarks at build time (the portrait is the detected image).
   Validated by `parseTopology` (fail-soft → fallback).

Regenerate the topology JSON from the vendored canonical model with
`node scripts/gen-face-topology.mjs` (parses `canonical_face_model.obj`, Apache-2.0).

## Gotchas
- Allocate position/normal/uv attributes ONCE; mutate in place. See
  Claude Code Guide §3.2.
- ARKit-52 morph target names must match exactly — `avatar_exporter`
  lints against this list. The canonical list lives in `impl/face_topology.ts`.
- Cache by `NormalizedPortrait.hash`. A re-build for the same hash should
  be a no-op (return the cached `BuiltMesh`).
- MediaPipe is imported DYNAMICALLY and only in `detectFaceLandmarks` — keep it
  out of the main bundle and the test graph. Detection never runs in jsdom.
- Morph deltas are PROCEDURAL (`impl/morph_basis.ts`) — an APPROXIMATION, not an
  ARKit rig. Only geometrically-defensible shapes are filled (jawOpen, mouthSmile
  L/R, browInnerUp); the rest stay zero pending a real rig. MediaPipe's blendshape
  *coefficients* feed the neutral `baselineMood`, not the deltas.

## Tests
`__tests__/mesh_builder.test.ts` — barrel shape + the pure core:
`buildFaceGeometry` (landmark→position mapping, landmark-derived UVs,
index/normal/52-morph wiring, too-few-landmarks guard), `parseTopology`
(well-formed accept, fail-soft `null` on malformed input), and `computeMorphBasis`
(per-region delta signs — jawOpen/brow/smile — and unsupported shapes stay zero).
Detection + the full real build path are browser-gated (`test/e2e/fixture.spec.ts`).
