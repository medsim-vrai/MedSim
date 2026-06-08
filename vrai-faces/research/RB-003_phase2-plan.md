# RB-003 Phase-2 — Plan: real interior + mouth-deformation re-bake + eye

Dated 2026-06-07. Scopes the COMPREHENSIVE fix for the morph-deformation artifact *class* the
2026-06-07 morph-QA sweep confirmed (`RB-003_findings.md` §8). Phase-1 (inner-mouth cavity dome +
mucosa-feather tint + `tongueOut` + lip ΔUV) is **shipped**; it patches per-shape and is whack-a-mole.
Phase-2 fixes the class at the source.

## The problem (recap)
A flat single-photo rig (UV = neutral landmark x,y) has no mouth interior and no "deformed" pixels, so
high-travel mouth/eye morphs either **tear** the topology (`mouthClose`, corners) or reveal bright photo
texture / a void where the lips part (`mouthFrown/Pucker/Right/RollUpper`) or the lid drops
(`eyesClosed`). Per-shape tint/ΔUV reaches only `jawOpen` + the smile cluster.

## Feasibility (checked 2026-06-07)
- **Bake env is PRESENT + runnable** — `tools/morphbasis-bake/` has the ICT-FaceKit expression OBJs,
  `canonical_face_model.obj`, its `.venv` (numpy) and `bake_morphbasis.py`. So bake-dependent work runs
  offline **now, no download**.
- **The real interior + eye MESHES need the ICT oral/eye component OBJs fetched** (mouth socket, gums+
  tongue, teeth / eyeball — MIT, the same source as RB-001) → a ⚠️ **user-approved download** before
  those items.

## Work items (sequenced)
1. **Mouth-deformation re-bake — no download · M · START HERE.** Diagnose why `mouthClose` + the
   lip-fold/seam shapes tear or expose white when deformation-transferred onto MediaPipe (lip-seam
   overlap, coarse corner topology). Fix in the bake — clamp/relax high-travel deltas, weld the lip
   seam, and/or a fold guard — then re-emit `face_mesh_morphbasis.json` (drop-in; no runtime change).
   Re-test the flagged shapes (`mouthClose`, frown, pucker, right, rollUpper) in morph-QA.
2. **Corner / lip-seam subdivision — no download · M.** The commissure + inner-lip triangles are coarse,
   so high-travel deltas tear. Subdivide those regions (bake-time densification or a runtime tessellation
   of the lip ring) so deltas distribute. Pairs with #1.
3. **Real interior mesh — ⚠️ download · M–L.** Fetch ICT-FaceKit oral components (mouth socket,
   gums+tongue, 32 teeth) → decimate (`gltf-transform`) → Umeyama-align into the MediaPipe frame (reuse
   the bake) → emit a small GLB → a new `oral_mesh` module parents it to the head, `jawOpen`-driven —
   **REPLACES** the `oral_cavity` dome + the inner-mouth tint. Covers every mouth-opening shape uniformly.
4. **Eye — ⚠️ download for a mesh, OR no-download feather · S–M.** `eyesClosed` smear: either a real
   eyeball+lid (ICT eye components) or a **margin-feather** (tint the lid toward eyelid skin, no
   download, like the inner-mouth). Decide on-device.
5. **Cleanup.** Retire the Phase-1 tint/dome where the real interior supersedes it; re-evaluate
   `FrontSide` (§5) now that a real interior exists.

## Recommended start
**Item 1** — no download, bake env is ready, and it attacks the worst artifact (`mouthClose` tearing)
plus the whole seam-white class **at the source (the basis)** rather than per-shape patches.

## Constraints
Offline bake, deterministic (ADR-0034); nothing ships at runtime beyond the JSON/GLB (ADR-0001/0014).
ICT-FaceKit is MIT (redistributable, attribution) — but the oral/eye OBJ fetch is a **download → needs
explicit approval**. Re-bakes go through the morph-QA gate before commit.
