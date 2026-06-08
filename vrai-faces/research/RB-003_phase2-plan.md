# RB-003 Phase-2 — Plan: real interior + mouth-deformation re-bake + eye

Dated 2026-06-07. Scopes the COMPREHENSIVE fix for the morph-deformation artifact *class* the
2026-06-07 morph-QA sweep confirmed (`RB-003_findings.md` §8). Phase-1 (inner-mouth cavity dome +
mucosa-feather tint + `tongueOut` + lip ΔUV) is **shipped**; it patches per-shape and is whack-a-mole.
Phase-2 fixes the class at the source.

> **Item 4 (eyelid margin-feather) IMPLEMENTED 2026-06-07 — pending on-device TUNE (EYELID_SKIN colour,
> strength/pow in shader_translucent). NEXT: tune Item 4, then Item 2 re-enable (needs the load fix) /
> Item 3 (gated download).** Rig loads; mouth in good shape; Item 2 subdivision reverted + deferred.

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
1. **Mouth-deformation re-bake — ✅ DONE 2026-06-07 (no download · M).** Diagnosed via probes: the
   tear is **triangle INVERSION** at the lips — the 468 topology is only ~898 tris total, so
   high-travel mouth shapes push lip verts past each other and faces fold over. (k-NN delta
   resampling was tested and **REFUTED** — it does not reduce the fold; the opposing lip motion is
   real, not a sampling error.) Fix shipped: an `inversion_guard` in `bake_morphbasis.py` attenuates
   ONLY the verts of folding/collapsing triangles, iteratively, until none invert — then re-emits
   `face_mesh_morphbasis.json` (drop-in, no runtime change). Result: folds → **0 on every shape**
   (mouthClose 24→0, mouthRollUpper 24→0, mouthLeft 11→0, mouthShrugLower 14→0, eyeBlink 10/11→0 →
   so `eyesClosed` improves too); 27 fold-free shapes stayed **bit-identical**, 25 changed (only what
   folds). ⏳ Pending iPad morph-QA re-test.
   **NOTE:** `mouthFrown` had **0** inversions → its seam-white is **TEXTURE, not geometry** → addressed
   by Item 3 / a ΔUV extension, NOT this re-bake.
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

## Refinement pass (2026-06-07, after the first iPad re-test)
The inversion-guard re-bake cleared the mouth tears on-device. The re-test punch-list, addressed:
- **Lip-movement seam-white** (mouthRollUpper etc. — 0 inversions, so texture not geometry): the
  inner-mouth tint is now driven by **lip SEPARATION** (MediaPipe 13↔14 inner-lip gap) instead of
  jawOpen-only, so ANY parting morph (rollUpper/funnel/pucker) darkens the revealed seam.
  `avatar_build.ts`; no shader/contract change.
- **Tongue** — reshaped from a flat disc to an elongated, downward-drooping body (`oral_tongue.ts`);
  still procedural (the CC0/MIT tongue mesh is the fidelity upgrade).
- **Cavity** — widened + smoothed the dome to cover the mouth corners (`oral_cavity.ts`).
- **Bake** — defensive inversion-guard on the SUMMED shapes (eyesClosed/cheekPuff/browInnerUp); a no-op
  today (all sums fold-free) but guards future regressions.
- **Eyelid (eyesClosed)** — the summed guard CONFIRMED it is **not** triangle inversion (folds 0→0):
  it's the flat-photo eye limitation. → Item 4 is now scoped as a **margin-feather** first (NEXT).

## Known shading limits — the tint ceiling (2026-06-07, deferred to Item 2/3)
The procedural inner-mouth tint + cavity + tongue have TOPPED OUT after several on-device rounds;
documented so we don't loop on micro-tuning:
- **Lip-movement edge-white** (mouthRollUpper outer upper-lip edge; mouthFunnel/pucker seam): the
  trade is binary — widening the tint MASK to cover the edge spreads it into a dark BLOB across the
  lower face (3-ring tried + reverted); the 2-ring mask leaves a faint edge-white. Root cause: the
  coarse ~898-tri lip topology stretches the flat-photo texture at the edge. FIX = **Item 2
  subdivision** (geometry) and/or **Item 3** interior mesh. NOT more tint.
- **jawOpen "more black"**: DEEP (0x120808) + cavity (0x0c0707) are as dark as the tint can go without
  spreading onto the lip; a truly black DEEP interior is the real mesh (Item 3), not tint.
- **Tongue**: flatten + matte + dark-cavity-behind is the no-download ceiling; real texture/teeth =
  **Item 3** (gated download). True lip-PARTING for the tongue needs a `tongueOut` morph (ICT has none).
- **eyesClosed smear**: confirmed NOT geometry (the inversion-guard was a no-op) → **Item 4** eyelid
  feather / eye mesh.

## Item 2: lip-seam subdivision — ATTEMPTED, REVERTED, DEFERRED (2026-06-07)
`subdivideLipRegion()` (1->4 split, interpolating position/uv/mask + all 53 morph deltas, deduped
shared-edge midpoints) was implemented + unit-tested (watertight on the synthetic fixture) and wired
into buildFaceGeometry. On-device it **BROKE avatar load** (the rig didn't render after the QR scan),
so it was reverted (commit 31d4b93); `subdivideLipRegion()` + its tests stay for a guarded re-enable.
- Offline repro on the REAL 468 topology (`/tmp/_repro_subdiv.py`): 468->685 verts, 898->1312 tris,
  indices in range, NaN-free — BUT **20 T-JUNCTIONS** at the lip-region boundary (a subdivided triangle
  splits an edge its non-subdivided neighbour keeps whole -> cracks). The structural mesh is valid, so
  the LOAD failure is most likely render-time (WebGPU morph upload); needs the on-device console.
- BEFORE re-enabling, solve BOTH: (a) the load failure — capture the console error; (b) the T-junctions
  — selective subdivision inherently leaves them. Options: subdivide UNIFORMLY (no T-junctions, ~4x the
  whole mesh, simplest + clean), add a transition ring, or stitch the boundary. Wrap in try/catch with a
  base-mesh fallback regardless, so it can never block load again.

## Item 4: eyelid margin-feather — IMPLEMENTED 2026-06-07 (pending on-device tune)
Shipped (commit follows). Topology-independent (a shader tint + one mask attribute), so it CANNOT
regress load. The spec below is the build record + the on-device TUNE reference: re-test `eyesClosed`
on the iPad (and watch idle blinks), then adjust `EYELID_SKIN` / `EYELID_STRENGTH` / `EYELID_POW` in
`shader_translucent/impl/create.ts` if the lid reads off (too pale/dark, over/under-covered).

GOAL: the `eyesClosed` smear (the open-eye photo texture stretched as the lid descends) is NOT geometry
(the inversion-guard was a no-op on it). Cover it the way the inner-mouth feather covers the open mouth:
tint the eye region toward EYELID-SKIN as the lid closes, so the closed eye reads as skin, not a smear.
Topology-independent (a shader tint + one per-vertex mask attribute) → it CANNOT regress avatar load.

THREE files, mirroring the inner-mouth feather machinery exactly:

1. `mesh_builder/impl/face_topology.ts` — add a per-vertex `eyelid` mask (copy the `innerMouth` block):
   - Eye-ring indices (MediaPipe canonical, BOTH eyes):
     `RIGHT = [33,246,161,160,159,158,157,173,133,155,154,153,145,144,163,7]`
     `LEFT  = [362,398,384,385,386,387,388,466,263,249,390,373,374,380,381,382]`
   - Set mask = 1 on those; dilate 1 ring inward (weight ~0.6) over `topo.indices` (same BFS as the
     innerMouth dilation) so the eye OPENING is covered. `geo.setAttribute('eyelid', new
     THREE.BufferAttribute(eyelid, 1))`. Build it on the base arrays (BEFORE any future subdivision).

2. `shader_translucent/impl/create.ts` — add the eyelid feather (parallel to the inner-mouth block):
   - Constants: `EYELID_POW = 0.5`, `EYELID_STRENGTH = 6.0`, `EYELID_SKIN = 0x8a6a5e` (mid-flesh; TUNE on
     device like the inner-mouth colours — eyelid skin is fairly consistent across portraits).
   - `const eyelidU = uniform(0);`  `const eyelidMask = attribute('eyelid', 'float');`
   - `const eAmt = saturate(mul(pow(eyelidMask, EYELID_POW), mul(eyelidU, EYELID_STRENGTH)));`
   - COMPOSE on top of the existing colorNode (currently `mix(diffuse, tint, amt)`; eye + mouth masks
     don't overlap, so no conflict):
       `const innerResult = mix(diffuse, tint, amt);`
       `material.colorNode = mix(innerResult, color(EYELID_SKIN), eAmt);`
   - Expose `(material.userData as Record<string, unknown>)['vraiEyelidU'] = eyelidU;` (like `vraiJawU`).

3. `shell/avatar_build.ts` — feed the eyelid drive per frame (in the existing `onBeforeRender`):
   - idx: `eyesClosed`, `eyeBlinkLeft`, `eyeBlinkRight` from `morphNames`.
   - `const eyelidU = (matObj.userData as Record<string, unknown>)['vraiEyelidU'] as { value: number } | undefined;`
   - drive by the MAX so idle_motion blinks feather too (not just sustained closure):
       `if (eyelidU) eyelidU.value = Math.max(inf?.[ecIdx] ?? 0, inf?.[blLIdx] ?? 0, inf?.[blRIdx] ?? 0);`

VERIFY: add a face_topology unit test (eyelid mask: ring verts = 1, dilated verts in (0,1], zero away
from the eyes); then `typecheck && check:no-any && test && build`; commit; iPad re-test `eyesClosed`
(and watch idle blinks). TUNE on device: `EYELID_SKIN` to match the portrait, `EYELID_STRENGTH/POW` for
coverage. v2 (later): sample brow-skin texture instead of a constant; a top-down directional sweep.

Still queued after Item 4: **Item 2** re-enable (uniform/transition-ring subdivision + the load fix +
a try/catch fallback); **Item 3** real interior + tongue/teeth mesh (⚠️ gated download).

## Constraints
Offline bake, deterministic (ADR-0034); nothing ships at runtime beyond the JSON/GLB (ADR-0001/0014).
ICT-FaceKit is MIT (redistributable, attribution) — but the oral/eye OBJ fetch is a **download → needs
explicit approval**. Re-bakes go through the morph-QA gate before commit.
