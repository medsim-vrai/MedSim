# face_ingest

## Purpose
Accepts a portrait image (`File | Blob`) from the user or from a MedSim
character record and emits a normalized PNG plus a face bounding box that
the mesh builder can consume. This module is NOT for face detection
quality scoring — that belongs upstream in capture UI.

## Public contract
See `src/types/face_ingest.ts`. The barrel exports a single `faceIngest`
object implementing `FaceIngestModule`.

## Dependencies
- `@contracts/*`
- MediaPipe Face Landmarker (for face bbox detection)

## Gotchas
- Output PNG MUST be square, RGB, no alpha. Downstream `mesh_builder`
  assumes this.
- The hash is SHA-256 of the normalized PNG. Use it as a cache key for
  the (expensive) `mesh_builder.build()` call.
- iOS Safari sometimes returns EXIF-rotated images. Normalize the
  orientation here, not in `mesh_builder`.

## Tests
`__tests__/face_ingest.test.ts` — boot/dispose lifecycle is asserted.
Real ingest path is exercised by `test/e2e/fixture.spec.ts` once the
synthetic portrait fixture is in place.
