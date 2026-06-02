# morphbasis-bake — RB-001 / ADR-0034

One-time **offline** bake of the real ARKit-52 blendshape deformation basis for the avatar.
Deformation-transfers USC **ICT-FaceKit** (MIT) expression shapes onto MediaPipe's
**canonical 468-vertex** topology (Apache-2.0) and emits the deltas the runtime consumes.

- **Output (committed):** `packages/core/src/modules/mesh_builder/impl/face_mesh_morphbasis.json`
  — 52 ARKit-named shapes (51 of ARKit-52, minus `tongueOut`, + a derived `eyesClosed`/AU43),
  sparse per-vertex deltas stored as fractions of the canonical face height (~292 KB / ~73 KB gz).
- **Consumed by:** `morph_basis.ts` → overlays the rig on the live 468/478 mesh, scaled to its
  height; falls back to the procedural basis off-topology and for `tongueOut`.
- Bake-time only — **nothing here ships in the app** (no runtime model; ADR-0001/0014 hold).

## Reproduce
```bash
cd vrai-faces/tools/morphbasis-bake
python3 -m venv .venv && ./.venv/bin/pip install numpy        # bake-time only dep (ADR-0034)
# fetch sources into _assets/ (gitignored): MediaPipe canonical_face_model.obj (Apache-2.0)
#   https://raw.githubusercontent.com/google-ai-edge/mediapipe/master/mediapipe/modules/face_geometry/data/canonical_face_model.obj
# + ICT-FaceKit FaceXModel/<expr>.obj + generic_neutral_mesh.obj + vertex_indices.json (MIT)
#   https://github.com/USC-ICT/ICT-FaceKit  (FaceXModel/; expression list = vertex_indices.json["expressions"])
./.venv/bin/python bake_morphbasis.py            # full bake -> emits the JSON
./.venv/bin/python bake_morphbasis.py --poc      # alignment check + a few sample shapes only
```

## Method
1. Umeyama similarity-align ICT neutral → MediaPipe neutral via shared dlib-68 landmarks
   (ICT side = `vertex_indices.json:idx_to_landmark_verts`; MediaPipe side = canonical indices
   in `DLIB_TO_MP`). The bake prints a landmark-residual + surface-overlap trust check.
2. Nearest-vertex correspondence (ICT is dense, so ≈ nearest-surface-point).
3. Per shape: `delta = ict_expr - ict_neutral`, sampled at the 468 correspondences, rotated+scaled
   into the MediaPipe frame; name-mapped to ARKit-52; `eyesClosed = eyeBlink_L + eyeBlink_R`.

## ⚠️ Acceptance QA (human, required)
ICT-FaceKit has documented FACS **mislabels**, so the bake is structurally verified (symmetry,
region, magnitude all sane) but each shape must still be **visually QA'd** against an ARKit
reference on the live avatar before this rig is considered final. Re-bake after any fix is minutes.

## Attribution (ship in app credits)
USC Institute for Creative Technologies — **ICT-FaceKit (MIT)**; Google **MediaPipe
canonical_face_model (Apache-2.0)**.
