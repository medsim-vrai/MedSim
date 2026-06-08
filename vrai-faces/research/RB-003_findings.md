# RB-003 Findings — Avatar Visual Fidelity

## 1. Summary

**Recommendation: GO, in three phases, all as offline bakes + drop-ins consistent with RB-001 — no rig-contract change.** Add a small **opaque** inner-mouth proxy (mouth bag → teeth/tongue) extracted from already-vetted MIT/CC0 sources, parented to `jawOpen`; fix the mouth-corner tear and eyelid smear by baking a **UV-displacement channel** into the existing morph basis; implement `tongueOut` as a deterministic transform of a CC0 tongue sub-mesh. The single hard rule that makes all of this both cheap and correct: **the oral cavity must be rendered opaque (`transparent:false`), never transmissive**, because three.js `transmission` only refracts opaque geometry. The one engine action item is bumping three.js from r170 to **≥ r181** to clear a live WebGPU transmission-on-animation bug ([#31768](https://github.com/mrdoob/three.js/issues/31768)).

## 2. Ranked recommendation per artifact

Ranked by clinical visibility (inner-mouth highest — it is the most visible void during speech/airway/assessment scenarios; eyelid smear lowest).

### (a) Inner-mouth cavity — HIGHEST clinical visibility

**Recommended approach:** A small **opaque** concave proxy ("mouth bag") parented behind the lip ring, driven by `jawOpen`. Ship a dark ~200-tri dome first (Phase 1), then optionally upgrade to a decimated teeth+tongue+socket mesh (Phase 2).

**Why:** This is the standard real-time-avatar solution and it is dictated by how the shader works, not by taste. three.js `transmission` is a two-pass screen-space refraction that samples a backdrop containing **only opaque objects** — confirmed by maintainer donmccurdy: *"transmission only shows opaque surfaces behind it. Transmissive and transparent surfaces are not visible behind a transmissive surface"* ([three.js forum](https://discourse.threejs.org/t/objects-with-transmission-not-showing-objects-behind/47113), [#23184](https://github.com/mrdoob/three.js/issues/23184)). The WebGPU/TSL path confirms the same mechanism: `viewportSharedTexture` *"should only contain the opaque rendering objects"* and is sampled via a depth-aware screen-UV node ([TSL docs](https://threejs.org/docs/pages/TSL.html), [MeshTransmissionNodeMaterial](https://www.threejs-blocks.com/docs/MeshTransmissionNodeMaterial)). FLAME/Gaussian avatar papers add exactly this because the base face has no interior — AGORA *"extends FLAME with a mouth cavity and two rows of frontal teeth"* ([arXiv 2512.06438](https://arxiv.org/pdf/2512.06438)); 3D Gaussian Blendshapes and ToonifyGB use a **separate mouth-interior set that ignores expression and only moves with the jaw joint** ([arXiv 2404.19398](https://arxiv.org/pdf/2404.19398), [arXiv 2505.10072](https://arxiv.org/pdf/2505.10072)) — which maps cleanly onto driving the proxy from the `jawOpen` influence you already animate.

**License-clean assets/tools:**
- **ICT-FaceKit oral components** — mouth socket (2,046 v / 2,082 f), gums+tongue (2,977 v / 2,972 f), 32 individual teeth, occlusion meshes — **MIT, redistributable, attribution-only** ([README](https://github.com/USC-ICT/ICT-FaceKit/blob/master/README.md), [LICENSE](https://github.com/USC-ICT/ICT-FaceKit/blob/master/LICENSE)). **This is the same source RB-001/ADR-0034 already uses — zero new license, zero new provenance.** Decimate offline to ≤800 tris → tens of KB GLB.
- **Phase-1 dome:** procedurally generated, **$0 / no asset / no license** at all.
- `gltf-transform` (MIT) + `meshoptimizer` (Apache-2.0) for offline decimate/weld/KTX2.

**Shader interaction:** Render `transparent:false`, `side: BackSide` (the bag is concave, viewed from outside — cheaper than `DoubleSide` and avoids extra fragment work), roughness ~1, near-black / desaturated-red, **normal `depthWrite:true`** (the face stays `depthWrite:false` as today — do *not* copy that onto the proxy). It then lands in the opaque transmission backdrop and shows through the face exactly where the geometry opens, automatically, whenever the slider raises transmission above 0 — **no `renderOrder` hack, no new pass** (you already pay the transmission pass the moment the slider leaves 1.0). Critically, it will **not** bleed through closed lips, because the lips' see-through-ness is *transmission, not alpha* — the real bleed risk is purely **geometric** (proxy poking outside the lip silhouette or sitting too close to the lip plane), so drive both open-amount and −Z recess from `jawOpen` so it is fully hidden behind the closed-lip plane at weight 0.

### (b) tongueOut — HIGH clinical visibility (airway/neuro assessment)

**Recommended approach:** Bundle a CC0 tongue sub-mesh and implement `tongueOut` as a **deterministic forward (+Z) / down (−Y) transform** of that piece, blend amount = the ARKit `tongueOut` coefficient directly (Option A from the assets research). ICT-FaceKit covers 51/52 ARKit shapes; `tongueOut` is the one gap that currently falls through to a weak procedural bulge.

**Why:** ARKit `tongueOut` is a single 0→1 protrusion ([ARKit doc](https://developer.apple.com/documentation/arkit/arfaceanchor/blendshapelocation/tongueout)). A real tongue body that translates reads correctly between the teeth; the face-mesh-delta fallback (Option B) only makes a bulge because the 468-vertex mesh has no interior surface. Mapping the morph *name* to a transform on a sub-mesh keeps the rig contract intact.

**License-clean assets/tools:**
- **MakeHuman tongue** — `helper-tongue` group (+`joint-tongue-1..4`), 224 faces / 226 verts, in `makehuman/data/3dobjs/base.obj`, **CC0 1.0** (assets relicensed CC0 Sept 2020; AGPL covers only source) ([LICENSE](https://github.com/makehumancommunity/makehuman/blob/master/LICENSE.md), [license explanation](http://www.makehumancommunity.org/content/license_explanation.html)). CC0 = strongest posture, no attribution.
- **Alternative:** ICT-FaceKit gums+tongue (MIT) — keeps everything in one source if you prefer not to introduce MakeHuman. Either is clean; pick one to avoid a second provenance.

**Shader interaction:** Same as (a) — opaque, part of the same oral-cavity GLB, in the transmission backdrop. No separate handling.

### (c) Mouth-corner tear — MEDIUM clinical visibility

**Recommended approach:** Bake a **UV-displacement (ΔUV) channel** into the existing morph basis for the high-travel mouth shapes (`mouthSmile*`, `mouthUpperUp*`, `noseSneer*`, `mouthStretch*`), applied at runtime as `uv += Σ wᵢ·ΔUVᵢ`. Add a triangle-fold guard at the commissure **only if** the §7 diagnostic shows real winding inversion.

**Why (mechanism is confirmed from your own code, not guessed):** UV = raw landmark x,y (`face_topology.ts` line 104-105), so UVs are continuous — **there is no UV atlas and no seam anywhere on the face**. three.js morph targets displace `position`/`normal` only, **never `uv`**, so a moved vertex keeps its neutral texel — *"when blendshapes stretch the mesh, the UVs don't stretch or offset with it, so the texture looks offset and warped"* ([Godot forum](https://godotforums.org/d/23667-material-uv-stretch-after-runtime-blendshape-update), [polycount](https://polycount.com/discussion/80590/blend-shape-animation-uv-problem)). The commissure is the max-displacement region, so its fixed-UV triangles stretch to many times their neutral texel area (and can briefly fold → the "tear"). The fix is to **stop the UV from being fixed exactly where it travels** — authoring ΔUV deltas is the production "rig the corrective from the primary blendshape's value" wisdom expressed as a UV correction. Shipping systems converge here: KeenTools FaceBuilder offers an explicit **Mouth/Nostril Mask** to keep baked-in interior pixels out ([KeenTools guide](https://medium.com/keentools/facebuilder-for-blender-guide-cbb10c717f7c)); academic single-image rigs note blendshapes *"pull the mouth corners further apart than they should"* ([ACM 3565622](https://dl.acm.org/doi/fullHtml/10.1145/3562939.3565622), [AvatarTex arXiv 2511.06721](https://arxiv.org/html/2511.06721v1)).

**License-clean assets/tools:** **$0, no new asset.** Pure extension of the RB-001 offline DT bake. Store as a sparse `{vertexIndex, du, dv}` list per shape, float16; basis grows a few KB. Deterministic (pinned solver + hash).

**Shader interaction:** Apply ΔUV in the TSL graph of `shader_translucent` as a small node addition riding on an attribute (no recompile), or as a CPU UV update on the bound geometry. A **margin feather** (Option C polish) — `mix()` the photo sample toward a procedural skin/mucosa tint over the last 1–2 mm at the inner-lip contour — mops up residual stretch and is cheap node math in the `MeshPhysicalNodeMaterial` you already maintain.

### (d) Eyelid smear — LOWEST clinical visibility

**Recommended approach:** Same ΔUV channel as (c), for `eyeBlink*`, `eyesClosed`, `eyeLookDown*`. Authored and baked together with the mouth corrections — one mechanism covers both artifacts.

**Why:** Identical fixed-UV mechanism — thin, high-travel lid-margin triangles sweep their fixed texels over the static eye-white into a smear (named in rigging practice, [polycount eyelid thread](https://polycount.com/discussion/189095/how-to-have-eyelid-animation-conform-to-eyeballs)). No new technique needed beyond (c). (Optional bonus: MakeHuman ships a CC0 low-poly eyeball, `data/eyes/low-poly/low-poly.obj`, if eye-region fidelity ever warrants real geometry — not required for the smear fix.)

**License-clean assets/tools:** **$0, no new asset** — rides the (c) bake.

**Shader interaction:** Same as (c).

## 3. Integration path

| Work | Module(s) to touch | Offline-bake + drop-in? | Bundle size | Runtime cost |
|---|---|---|---|---|
| Oral-cavity proxy (a)+(b) | **NEW** `oral_cavity` module (builds/loads the GLB, parents to head, drives by `jawOpen`/`tongueOut`); reuse `tools/morphbasis-bake` harness for extract+decimate+align | **Yes** — extract → Umeyama-align into MediaPipe frame → decimate ≤800 tris → bake jawOpen + 2-3 visemes under existing ARKit names → emit small GLB | ~tens of KB GLB (Phase 1 dome ≈ negligible) | **+1 opaque draw call**, a few hundred tris (face is ~900). Transmission pass already paid. Negligible. |
| ΔUV channel (c)+(d) | `mesh_builder/morph_basis.ts` (load + apply a parallel ΔUV channel); `shader_translucent/create.ts` (optional TSL node to apply on GPU); `tools/morphbasis-bake` (emit ΔUV deltas) | **Yes** — pure extension of the RB-001 DT bake; sparse float16 deltas | +few KB to the basis | One extra attribute read; **no measurable perf cost** |
| Margin feather (c polish) | `shader_translucent/create.ts` (TSL `mix()` over a baked margin weight) | Yes (margin weight baked) | ~0 | A handful of TSL nodes |
| Engine bump | dependency pin `three@^0.170` → `≥0.181` | n/a | n/a | Re-verify existing avatar after bump |

All three workstreams are **offline-bake + small drop-in**, matching the RB-001 pattern (one-time bake, nothing leaves device, deterministic, PHI-safe). Re-bake is minutes.

**Relevant files (absolute):**
- Material: `/Users/petermarotta/Documents/Claude/Projects/Scenario structure to support character engagement/medsim_v8/vrai-faces/packages/core/src/modules/shader_translucent/impl/create.ts` (note `depthWrite:false`, `side:DoubleSide`, `transmission`)
- Topology / lip-ring / UV: `/Users/petermarotta/Documents/Claude/Projects/Scenario structure to support character engagement/medsim_v8/vrai-faces/packages/core/src/modules/mesh_builder/impl/face_topology.ts` (UV = landmark x,y, line 104-105)
- Morph basis (ΔUV channel + `tongueOut` fallback at lines 51–103, 132–146): `/Users/petermarotta/Documents/Claude/Projects/Scenario structure to support character engagement/medsim_v8/vrai-faces/packages/core/src/modules/mesh_builder/impl/morph_basis.ts`
- Delta format reference: `/Users/petermarotta/Documents/Claude/Projects/Scenario structure to support character engagement/medsim_v8/vrai-faces/packages/core/src/modules/mesh_builder/impl/face_mesh_morphbasis.json`
- Scene/sort: `/Users/petermarotta/Documents/Claude/Projects/Scenario structure to support character engagement/medsim_v8/vrai-faces/packages/core/src/shell/renderer.ts` (solid-black background, default transparency sort)
- Bake harness to reuse: `/Users/petermarotta/Documents/Claude/Projects/Scenario structure to support character engagement/medsim_v8/vrai-faces/tools/morphbasis-bake/README.md`

## 4. License summary table

| Asset / tool | License | Redistributable? | Size | Notes |
|---|---|---|---|---|
| **ICT-FaceKit** (mouth socket, gums+tongue, 32 teeth, occlusion meshes) | **MIT** | ✅ Yes (attribution-only) | raw few-MB OBJ → **tens of KB** decimated GLB | **PRIMARY** — same source as RB-001/ADR-0034. Zero new license. |
| **MakeHuman base mesh** (teeth/tongue/eye vertex groups) | **CC0 1.0** | ✅ Yes (no attribution) | base.obj 1.75 MB; extract teeth+tongue ≈ 390 v / 320 f → tens of KB | Strongest posture. Use for tongue if not using ICT's. |
| Procedural dome (Phase 1) | n/a ($0) | ✅ Yes | negligible | No asset, fully deterministic. |
| ΔUV deltas + margin weights (bake output) | n/a ($0) | ✅ Yes | +few KB | Generated in-pipeline. |
| `gltf-transform` (decimate/weld/KTX2) | MIT | ✅ (dev-time tool) | dev-time only | Drop-in to existing bake. |
| `meshoptimizer` (simplifier under gltf-transform) | Apache-2.0 | ✅ (dev-time) | dev-time only | — |
| Basis/KTX2 + ASTC (toktx/basisu) | Apache-2.0 | ✅ (dev-time) | dev-time only | Only if teeth atlas wanted. |
| **⚠️ LaMa `big-lama` checkpoint** (texture inpainting) | code Apache-2.0 **BUT weights trained on Places2** | **❌ NO** | 208 MB ONNX | **LANDMINE** — weights inherit Places2 **non-commercial** restriction ([LaMa #96](https://github.com/advimman/lama/issues/96), [Places2 terms](http://places2.csail.mit.edu/challenge.html)). Many blogs wrongly call it "Apache". **Do not bundle or derive shipped textures from it.** Use classical OpenCV Telea/Navier–Stokes if inpainting is ever needed. |
| **⚠️ Z-Anatomy** teeth/tongue | **CC BY-SA 4.0** | **❌ Avoid** | — | Share-alike is viral — could force your bundle's assets under CC-BY-SA ([repo](https://github.com/Z-Anatomy/Models-of-human-anatomy)). |
| **⚠️ Sketchfab "free" mouth models** (Zelad, Frank Buster Law, etc.) | **unconfirmed / mostly CC-BY** | **❌ Do not assume** | — | "Free" ≠ redistributable; license is per-upload. Not needed given ICT/MakeHuman. |
| **⚠️ TurboSquid / CGTrader / 3DPolyForge / RenderHub mouths** | paid / royalty-free **but EULA forbids bundling** | **❌ No** | — | Same redistribution trap RB-001 flagged for MetaHuman/RPM. Disqualified. |
| Pixel Codec Avatars (neural per-frame texture) | research weights | ❌ No | huge / per-frame GPU | Off-device-class. Reject. |
| Drei `MeshTransmissionMaterial` | MIT | ✅ but **not applicable** | — | React-Three-Fiber; solves a problem we avoid by keeping the interior opaque. Don't add. |

## 5. On-device feasibility verdict

**Feasible at ~60 fps on iPad-class WebGPU.** The cost is dominated by a transmission pass **you already render** the moment the translucency slider leaves 1.0 — the addition is **+1 opaque draw call and a few hundred triangles** (face is ~900 tris; total scene stays under ~2K). An iPad-class WebGPU app has hundreds of draw calls of headroom; **draw calls are not the constraint — overdraw and transmission-pass resolution are**. Concrete budget:

- **Geometry:** oral cavity ≤800 tris, opaque, static buffers. Negligible.
- **The decisive rule:** the interior **must be opaque** (`transparent:false`, no transmission). A second *translucent* `DoubleSide` layer behind a `DoubleSide` translucent face = up to **4× fragment cost** in the mouth footprint on Apple TBDR — this is the reason to keep it opaque, and opaque is also the only way it shows through the transmission lobe. (Meta moved avatars off translucent to masked rendering for this exact class of artifact, ~80% less GPU/frame — [Meta](https://developers.meta.com/horizon/blog/translucent-vs-masked-rendering-in-real-time-applications/).)
- **Texture:** none required for v1 (flat enamel/tongue shading reads fine at ghost translucency). If QA wants teeth detail, **one ≤1024² KTX2/ASTC atlas, ≤1 MB GPU / ≤0.3 MB disk** — avoid multiple 2K maps and a second face material.
- **Passes:** none added — reuse the existing transmission backbuffer at its default (sub-canvas) resolution.

**Engine caveat (the one gating item):** r170 is the *first* release with solid double-sided WebGPU transmission ([r170 release](https://github.com/mrdoob/three.js/releases/tag/r170)), but there is a **live bug — transmission renders incorrectly once animation starts / on resize under WebGPURenderer** ([#31768](https://github.com/mrdoob/three.js/issues/31768), fixes in PRs #32043/#32110 targeting r181). The avatar animates every frame, so **bump to ≥ r181 before committing**. Also re-evaluate dropping the face to `FrontSide` once a real interior exists — it would sidestep the `DoubleSide`+transmission self-transmission artifact ([#29592](https://github.com/mrdoob/three.js/issues/29592), closed "not planned").

## 6. GO / NO-GO per artifact

| Artifact | Verdict | Effort | Rationale |
|---|---|---|---|
| (a) Inner-mouth cavity | **GO** | **Phase 1 dome: S** · Phase 2 ICT teeth/tongue: **M** | Mechanism maintainer-confirmed; license trivial; +1 draw call. |
| (b) tongueOut | **GO** | **S** | Deterministic transform of a CC0/MIT sub-mesh; rides the cavity GLB. |
| (c) Mouth-corner tear | **GO** | **M** | ΔUV bake; magnitude is empirical tuning (~0.5–1 day). |
| (d) Eyelid smear | **GO** | **S** (rides c) | Same ΔUV mechanism, same bake. |
| Triangle-fold guard (F) | **CONDITIONAL** | S | Ship only if §7 diagnostic shows real winding inversion. |
| Engine bump r170→≥r181 | **GO (prerequisite)** | S | Clears WebGPU transmission-on-animation bug. |

**Suggested phasing:**
1. **Phase 0 (prereq, S):** Bump three.js ≥ r181; re-run RB-001 per-shape QA to confirm the existing avatar is unaffected. Run the §7 fold-vs-stretch diagnostic.
2. **Phase 1 (S):** Ship the **opaque dark mouth-bag dome** + the **ΔUV channel for mouth corner and eyelid**. This kills the most clinically visible voids/tears with $0 assets and validates the opaque-through-transmission composite on-device. `tongueOut` transform lands here if a CC0/MIT tongue is dropped in.
3. **Phase 2 (M, if QA wants it):** Upgrade the dome to decimated ICT-FaceKit teeth + tongue + socket; add margin feather and (conditionally) the fold guard; add a KTX2 teeth atlas only if detail is requested.

## 7. Open risks / what's still unknown

1. **Ghost-end composite look (on-device only).** The face is *also* `transparent:true` with `opacity` 0.55–1.0 riding alongside transmission. The opaque interior is captured by the transmission lobe, but the alpha-blend layer composites over it; whether it reads as "interior through translucent skin" vs. "interior floating over a ghost" at the 0.55-opacity extreme **cannot be predicted from docs** — QA watch-item. There's also a reported edge case where `transmission>0` with `opacity≈0.5` washes a surface fully transparent ([forum](https://discourse.threejs.org/t/why-is-transmission-property-not-working/58668)); the §4 table keeps opacity ≥0.55, so it's a watch-item, not a known blocker. **Fallback if it looks wrong at the ghost end:** clamp/anchor cavity visibility to the slider (full cavity when opaque, fade interior as the face goes ghost) — physically sensible and artifact-free.
2. **Fold vs. pure stretch at the commissure (unconfirmed until diagnosed).** ~15-min diagnostic on the live avatar at `mouthSmileLeft`/`noseSneer` = 1.0: wireframe + `FrontSide` and watch for triangles flickering/disappearing (winding flip ⇒ real inversion ⇒ enable fold guard); or compute signed triangle area in UV vs. deformed position (sign change ⇒ inversion). Does not change the primary fix, only whether F ships.
3. **ΔUV magnitudes are empirical.** No closed-form value; budget ~0.5–1 day of bake + eyeball iteration against the QA panel.
4. **Coordinate alignment for borrowed geometry.** MakeHuman/ICT meshes are in their own frames; need the same Umeyama-style alignment into the MediaPipe frame the bake harness already does for ICT — a bake-time fit, not a runtime guess.
5. **GLB byte size unverified.** "Tens of KB" is estimated from vertex/face counts (no textures); confirm with a 5-min export.
6. **r170 self-transmission + animation bugs** ([#29592](https://github.com/mrdoob/three.js/issues/29592), [#31768](https://github.com/mrdoob/three.js/issues/31768)) — addressed by the Phase-0 bump to ≥ r181, but re-verify the existing avatar after bumping (it's a non-trivial version jump).
7. **Pin discipline:** pin three.js exactly and re-test on any future bump — the transmission path has moved meaningfully across r156→r170→r181.

---

## 8. Phase-1 implementation (2026-06-07) — shipped + Phase-2 follow-ups

**Shipped (Phase-1, $0 / code-only, validated on iPad with Mr. Hayes):**
- **Opaque cavity dome** — `shell/oral_cavity.ts`: a near-black `BackSide` + `depthWrite` concave
  dome behind the lip ring, jawOpen-driven (scales from ~0), a child of the face mesh; lands in
  the transmission backdrop and shows through the open mouth.
- **Procedural `tongueOut`** — `shell/oral_tongue.ts` (already present): opaque tongue, protrusion
  driven by the `tongueOut` influence.
- **Inner-mouth "mucosa feather"** (chosen over the §2c ΔUV-only plan for the lit-texture problem):
  a **2-ring `innerMouth` mask dilation** (`mesh_builder/impl/face_topology.ts`, weights 1 / 0.7 /
  0.45) + a **facing-gated tint** in `shader_translucent/impl/create.ts` — FRONT-facing lip edge →
  `INNER_MOUTH_LIP` (reads as a lip, covers the bright photo texture → no white), BACK-facing inner
  surfaces + the membrane → `INNER_MOUTH_DEEP` (dark interior). `INNER_MOUTH_POW`/`STRENGTH` set the
  coverage. This resolved the empty-void / white-under-the-upper-lip / light-interior issues.

**Phase-2 follow-ups (DEFER — deeper review + cleanup, do not lose):**
1. **Commissure thin line.** A small white line still flickers at the stretched mouth CORNERS at
   full open. This is the **mouth-corner fold** (§2c / §7.2 — winding flip / triangle overlap), a
   GEOMETRY issue, *not* tint coverage — the fix is the **ΔUV + triangle-fold guard**, not more
   tint (widening coverage further just colours too much lip).
2. **Tint-colour refinement.** `INNER_MOUTH_LIP`/`INNER_MOUTH_DEEP` are first-pass values picked
   without a live preview; tune them on-device, and consider a depth term so rim vs deep interior
   read distinctly without leaning only on the facing heuristic.
3. **Real interior mesh (§2a Phase-2).** Replace the tinted-face stand-in with the decimated
   **ICT-FaceKit teeth/tongue/socket** GLB — the proper fidelity path.
4. **Re-evaluate `FrontSide`** (§5) once a real interior exists — sidesteps DoubleSide back-faces
   filling the view.

**Morph-QA sweep (2026-06-07, iPad / Hayes) — confirms the Phase-2 cluster, NOT new per-shape tuning.**
A full slider sweep flagged a *class* of mouth-deformation morphs that tear or reveal bright (white)
photo texture wherever the lips part/fold and Phase-1 coverage doesn't reach (the inner-mouth tint is
driven by `jawOpen` ONLY; ΔUV pins only the smile/stretch/upperUp/sneer cluster):
- **`mouthClose`** — significant geometry TEARING (lips fold/overlap → jagged gaps + white). → the
  `mouthClose` RE-BAKE (already a Phase-2 item) — geometry, not coverage.
- **`mouthRollUpper`** + (panel #30/31/38/39 ≈ `mouthFrownL/R`, `mouthPucker`, `mouthRight` — confirm
  exact names) — small white at the lip seam where those shapes part the lips.
- **`jawOpen`** (#25) — open-mouth smoothing already covered by Phase-1 inner-mouth + morph-normals
  (baseline, acceptable).
- **`eyesClosed`** — eyelid smear (moderate), as expected (no good flat-photo ΔUV; needs feather/eye mesh).

PATTERN: per-shape Phase-1 (jawOpen tint + smile-cluster ΔUV) is whack-a-mole — every *other* mouth
morph re-exposes the same flat-photo gap. Comprehensive fixes (the Phase-2 items above): (a) the **real
ICT interior mesh** covers ALL mouth-opening shapes uniformly; (b) **mesh subdivision / re-bake** fixes
the `mouthClose` + corner tears (geometry). Cheap Phase-1.5 stopgap for the *lip-parting* (not folding)
morphs only: drive the inner-mouth tint from a general "mouth-openness" signal instead of `jawOpen` alone.

**Phase-2 Item 1 — inversion-guard re-bake (2026-06-07, shipped, pending iPad re-test).** Probed the
bake numerically (scratch scripts, not committed): the `mouthClose`/fold tear is **triangle INVERSION**
— at full influence the morph folds lip triangles (the face normal flips) on the coarse 468 topology
(~898 tris total). k-NN delta resampling was tested and **refuted** (folds 24→~24; the opposing
upper/lower-lip motion is *real*, not a sampling artifact, so smoothing the sample does nothing). The
shipped fix is `inversion_guard()` in `bake_morphbasis.py`: it attenuates ONLY the deltas of vertices
belonging to a folding/collapsing triangle, iteratively, until the morph at full influence inverts
nothing; then re-emits the basis (drop-in, no runtime change). Re-bake result — folds → **0 on every
shape**: mouthClose 24→0, mouthRollUpper 24→0, mouthLeft 11→0, mouthShrugLower 14→0, mouthRollLower
10→0, eyeBlink 10/11→0 (→ `eyesClosed` too), mouthRight 12→0, jawOpen 4→0. Motion retained ≥89% for
all but the heavy folders (mouthClose 43%, mouthRollUpper 63% — a subtler press/roll instead of a tear,
the right trade). 27 fold-free shapes stayed **bit-identical**; 25 changed (only what folds).
**`mouthFrown` had 0 inversions** → its seam-white is **texture, not geometry** → Item 3 / a ΔUV
extension, NOT this re-bake. The full-fidelity alternative (keep 100% motion) is lip-region
subdivision (Item 2); the clamp is the no-topology-change fix that removes the visible tear now.

---

### Sources
- [Transmission shows only opaque surfaces (donmccurdy) — three.js forum](https://discourse.threejs.org/t/objects-with-transmission-not-showing-objects-behind/47113) · [transmission pass toggling #23184](https://github.com/mrdoob/three.js/issues/23184)
- [TSL docs — opaque-only viewport texture, depth-compare screen UV](https://threejs.org/docs/pages/TSL.html) · [MeshTransmissionNodeMaterial](https://www.threejs-blocks.com/docs/MeshTransmissionNodeMaterial) · [Drei MeshTransmissionMaterial](https://drei.docs.pmnd.rs/shaders/mesh-transmission-material)
- [DoubleSide + transmission self-transmission #29592](https://github.com/mrdoob/three.js/issues/29592) · [WebGPU transmission animation bug #31768](https://github.com/mrdoob/three.js/issues/31768) · [r170 release (double-side transmission)](https://github.com/mrdoob/three.js/releases/tag/r170) · [r156 WebGPU transmission gap](https://discourse.threejs.org/t/meshphysicalmaterials-transmission-property-is-broken-on-webgpu-api/56126) · [WebGPU migration guide](https://www.utsubo.com/blog/webgpu-threejs-migration-guide) · [transmission+opacity edge case](https://discourse.threejs.org/t/why-is-transmission-property-not-working/58668)
- [Material.depthWrite — three.js](https://threejs.org/docs/#api/en/materials/Material.depthWrite) · [Meta — Translucent vs Masked Rendering](https://developers.meta.com/horizon/blog/translucent-vs-masked-rendering-in-real-time-applications/) · [transparency sort limits](https://discourse.threejs.org/t/how-to-solve-the-rendering-order-for-random-meshes-to-get-proper-transparence/64164)
- [ICT-FaceKit README (mouth socket, gums+tongue, 32 teeth, occlusion meshes)](https://github.com/USC-ICT/ICT-FaceKit/blob/master/README.md) · [ICT-FaceKit MIT LICENSE](https://github.com/USC-ICT/ICT-FaceKit/blob/master/LICENSE)
- [MakeHuman LICENSE (assets CC0 since Sept 2020)](https://github.com/makehumancommunity/makehuman/blob/master/LICENSE.md) · [License explanation](http://www.makehumancommunity.org/content/license_explanation.html) · [makehumancommunity/makehuman](https://github.com/makehumancommunity/makehuman)
- [Z-Anatomy (CC BY-SA, flagged viral)](https://github.com/Z-Anatomy/Models-of-human-anatomy) · [Poly Pizza / Quaternius CC0](https://poly.pizza/u/Quaternius) · [Khronos glTF-Sample-Assets](https://github.com/KhronosGroup/glTF-Sample-Assets) · [Sketchfab mouth (license unconfirmed)](https://sketchfab.com/3d-models/mouth-teeth-for-game-character-low-poly-f5e88a5ad39044e5800dedf3295ed423)
- [LaMa code Apache-2.0](https://github.com/advimman/lama) · [LaMa-ONNX 208 MB (Carve)](https://huggingface.co/Carve/LaMa-ONNX) · [big-lama trained on Places2 (#96)](https://github.com/advimman/lama/issues/96) · [Places2 non-commercial terms](http://places2.csail.mit.edu/challenge.html) · [client-side ONNX inpainting feasibility](https://medium.com/@geronimo7/client-side-image-inpainting-with-onnx-and-next-js-3d9508dfd059)
- [Blendshapes don't move UVs (Godot forum)](https://godotforums.org/d/23667-material-uv-stretch-after-runtime-blendshape-update) · [polycount blendshape UV](https://polycount.com/discussion/80590/blend-shape-animation-uv-problem) · [polycount eyelid rigging](https://polycount.com/discussion/189095/how-to-have-eyelid-animation-conform-to-eyeballs)
- [MetaHuman from a photo — teeth/inner-mouth added by MTM (yelzkizi)](https://yelzkizi.org/metahuman-from-a-photo/) · [MetaHuman custom mouth/teeth textures (Joe Raasch)](https://www.joeraasch.com/projects/metahuman-custom-texture) · [itSeez3D Avatar SDK](https://itseez3d.com/blog/avatar-sdk-beta/) · [offline SDK docs](https://docs.avatarsdk.com/local-compute-sdk/1.0.0/md_offline_avatar_sdk.html) · [KeenTools FaceBuilder — Mouth/Eyelid masks](https://medium.com/keentools/facebuilder-for-blender-guide-cbb10c717f7c)
- [VolTeMorph — two-plane mouth interior, arXiv 2208.00949](https://arxiv.org/pdf/2208.00949) · [Pixel Codec Avatars, arXiv 2104.04638](https://arxiv.org/pdf/2104.04638) · [Automated Blendshape Personalization, ACM 3565622](https://dl.acm.org/doi/fullHtml/10.1145/3562939.3565622) · [AvatarTex, arXiv 2511.06721](https://arxiv.org/html/2511.06721v1) · [AGORA — FLAME + mouth cavity & teeth, arXiv 2512.06438](https://arxiv.org/pdf/2512.06438) · [3D Gaussian Blendshapes, arXiv 2404.19398](https://arxiv.org/pdf/2404.19398) · [ToonifyGB, arXiv 2505.10072](https://arxiv.org/pdf/2505.10072)
- [ARKit tongueOut blendshape](https://developer.apple.com/documentation/arkit/arfaceanchor/blendshapelocation/tongueout) · [ARKit blendshape reference](https://arkit-face-blendshapes.com/)
