# RB-001 — Findings (executed 2026-06-01, deep research)

Multi-angle deep research (5 parallel angle-researchers → synthesis; custom
text-output workflow after the bundled harness failed on schema-forcing). Decision
recorded as **ADR-0034**. This is the durable record (full raw report in the run's
temp output). Brief: `research/RB-001_blendshape-rig.{html,pdf}`.

## Verdict: CONDITIONAL GO — build the basis from MIT + Apache-2.0 sources

Build `face_mesh_morphbasis.json` by **deformation-transferring USC ICT-FaceKit's
MIT-licensed 53 ARKit-named expression shapes onto MediaPipe's Apache-2.0
canonical 468-vertex mesh**, then author **one supplemental `eyesClosed` (AU43)**
morph for clinical credibility. No off-the-shelf ARKit-52→MediaPipe-468 basis
exists; the bake is a solved, one-time offline job. The "condition" is the
transfer + per-shape QA effort and the small clinical supplement — **licensing is
clean and procurement is $0**.

## Ranked options (MUST-PASS = clinical + commercial + REDISTRIBUTABLE in a bundled on-device app)

| Source | License (MUST-PASS) | ARKit-52 fit | →468 mapping | Verdict |
|---|---|---|---|---|
| **ICT-FaceKit Light (USC-ICT)** | **PASS — MIT** (attribution only) | Strong (53 ARKit-named `_L/_R`) | Moderate (9,409-vtx → 468; MIT DT impl exists) | **WINNER** |
| MediaPipe `canonical_face_model.obj` | PASS — Apache-2.0 | none (neutral mesh) | — (this *is* the 468 target) | **Required BASE mesh** |
| FLAME 2023 **Open** | PASS — CC-BY-4.0 | Poor (PCA, not ARKit) | Heavy (~5k-vtx) | License-clean but inferior |
| MediaPipe Blendshape V2 model | bundleable but **coefficients only** | n/a (predictor) | — | Irrelevant (the runtime-signal trap) |
| FLAME std / BFM / FaceWarehouse | **DISQUALIFIED** — non-commercial / no-redistribute | Poor/Fair (PCA/FACS) | Heavy | ✗ |
| MetaHuman / Ready Player Me / Avatar SDK / Reallusion CC | **DISQUALIFIED** — EULA forbids redistributing extracted deltas (runtime/engine-locked; RPM also NC + shut down 2026-01) | Strong/Good | Heavy | ✗ |
| hinzka VRoid 52 / "iPhone X" blog dumps | **DISQUALIFIED** — no/unclear license | Strong | Heavy | ✗ |

Key reasoning: ICT-FaceKit is the *only* source that clears the license bar **and**
already speaks ARKit naming. MediaPipe ships only the neutral mesh + a coefficient
*predictor* (the real basis is on Google's unreleased GHUM mesh). ICT's "full model
→ separate USC license" caveat gates only the unreleased hi-res identity/albedo PCA —
**the in-repo Light neutral + 53 expression OBJs we use are MIT.**

## Integration path → `face_mesh_morphbasis.json` (one-time offline bake)

1. **Inputs:** ICT `generic_neutral_mesh.obj` + 53 expression OBJs; MediaPipe
   `canonical_face_model.obj` (468 v) as the target + delivery topology.
2. **Correspondence:** landmark-guided dense map ICT→468 (the 468 verts *are*
   landmarks → seed markers from canonical indices). Recommended toolchain:
   **open-source NRICP + Sumner-Popović deformation transfer (NumPy/SciPy)**,
   starting from the **MIT `vasiliskatr/deformation_transfer_ARkit_blendshapes`**
   repo (swap target→468, source→ICT). R3DS Wrap = optional higher-fidelity paid
   alt (touches only the bake machine, not the output license). Blender Surface
   Deform = sanity fallback.
3. **Transfer + name-normalize:** factor once, backsubstitute all 53 → 468-vtx
   deltas. Merge ICT split halves to canonical ARKit (`*_L+_R → *`), drop non-ARKit
   extras, **visually QA every shape vs ARKit reference (ICT has documented FACS
   mislabels — don't trust names blindly)**. Resolve possible `tongueOut` gap.
4. **Supplement:** author `eyesClosed_L/_R` (AU43) through the identical bake.
5. **Format:** 52 (+supplement) ARKit-named entries, each a sparse
   `{vertexIndex, dx, dy, dz}` list (moved verts only), deltas as **float16/int16**.
   Pin solver settings + commit the asset hash (determinism).
6. **Size:** ~0.4–1.2 MB raw, ~0.3–0.8 MB gzipped. Negligible. (Can also emit glTF
   morph targets — exporter already bakes by ARKit name, so it's a drop-in.)

**Determinism/PHI:** entirely generation-time. No runtime camera/GHUM/predictor; the
shipped artifact is static geometry; nothing leaves the device. Both MUST-PASS hold.

## Clinical affects — ARKit-52 + ONE addition

- **Pain (PSPI = AU4 + AU6/7 + AU9/10 + AU43):** 4/5 map natively (AU4→`browDown`,
  AU6→`cheekSquint`, AU7→`eyeSquint`, AU9→`noseSneer`, AU10→`mouthUpperUp`). The gap
  is **AU43 sustained eye-closure** — ARKit only has transient `eyeBlink` (AU45).
- **Drowsiness (PERCLOS):** the heart is **slow/partial sustained lid closure = the
  same AU43**. Yawn = held `jawOpen` (free, a runtime pose).
- **Author:** `eyesClosed_L/_R` (REQUIRED) via the same DT bake. Runtime drivers:
  Pain = w·(AU4+AU6/7+AU9/10+AU43); Drowsy = slow-ramp AU43 + periodic jaw-drop —
  FACS-traceable, deterministic.

## Licensing & procurement
- **ICT-FaceKit — MIT:** use/modify/distribute/sell, no field-of-use limit; retain
  the notice in app credits. Use only the in-repo Light assets.
- **MediaPipe canonical mesh — Apache-2.0:** commercial + redistribution OK; retain
  notices. (The hosted-API ToS doesn't apply — we use the static file.)
- **Toolchain:** the DT repos are MIT (code); GPL Blender addons touch only the bake
  tool, not the data. **Net mandatory procurement: $0** (optional R3DS Wrap seat).
- **App credits to ship:** "USC ICT — ICT-FaceKit (MIT)" + "Google MediaPipe
  canonical_face_model (Apache-2.0)".

## Effort + risks
- **~3–5 days** total: open NRICP+DT bake (~2–4d) + per-shape QA + `eyesClosed`
  supplement (~0.25–0.5d). Re-bake after a tweak = minutes. (R3DS Wrap path ~0.5–1.5d.)
- **Risks:** ICT FACS mislabels → QA each shape (top quality risk); eyelid/lip-contact
  transfer error → prefer NRICP+DT, landmark-seed; MediaPipe OBJ revision/468-vs-478 →
  pin + hash the topology; `tongueOut` maybe absent → author or document; solver drift →
  pin settings + commit hash.

## Key sources
- ICT-FaceKit (MIT): https://github.com/USC-ICT/ICT-FaceKit (+ /blob/master/LICENSE, /tree/master/FaceXModel)
- MediaPipe canonical mesh (Apache-2.0): https://github.com/google-ai-edge/mediapipe `mediapipe/modules/face_geometry/data/canonical_face_model.obj`
- DT→ARKit MIT impl (bake-of-choice): https://github.com/vasiliskatr/deformation_transfer_ARkit_blendshapes
- Deformation transfer (Sumner & Popović): https://people.csail.mit.edu/sumner/research/deftransfer/
- ARKit↔FACS crosswalk (+ mislabel warnings): https://melindaozel.com/arkit-to-facs-cheat-sheet/
- Pain PSPI core AUs: https://pmc.ncbi.nlm.nih.gov/articles/PMC8552410/
- FLAME license (NC + CC-BY-4.0 Open): https://flame.is.tue.mpg.de/modellicense.html

→ Decision + consequences: **ADR-0034** (`Memory_management.MD §7`).
→ Implementation: bake `face_mesh_morphbasis.json` → swap `mesh_builder/impl/morph_basis.ts`
  to load it (fallback to the procedural basis if absent) → regenerate + verify.

## QA acceptance (2026-06-05) — RIG ACCEPTED

Per-shape visual QA on the live avatar (Mac, Chrome/WebGPU, `?debug` morph panel, fit ~0.6):
**46/52 shapes correct, ZERO mislabels** — every ARKit shape performs the right facial
action, validating both the bake and the ICT→ARKit name-map. The flagged items are all
**texture/topology** artifacts of morphing a single static photo, NOT rig errors:

- **Inner mouth** (jawOpen, mouthClose, mouthFunnel): the 468 mesh has no teeth/tongue/
  cavity, so opening stretches lip texture into the gap (the "blurry tongue").
- **`tongueOut`**: omitted (ICT has none) → nothing protrudes.
- **Mouth corners** (smile, mouthUpperUp, noseSneer): texture tears at the commissure when
  the corners pull — the photo can't cover the stretch.
- **Lower eyelid** (eyeBlink, eyeLookDown): lid texture smears as the lid closes.

These are the fidelity ceiling of photo-texture morphing — worst at weight 1.0 (the QA
stress-test), milder at the partial/blended weights real speech+emotion use. Captured as
**known limitations** and scoped to **RB-003 (avatar visual fidelity)**: inner-mouth
geometry, per-region eye/lip handling, synthesized `tongueOut`.

Also fixed during QA: an invisible-rig bug (deltas double-divided by canonicalHeight, ~17x
too small) and the camera framing (frame the CORE face, not the outlier-bloated bbox; a
tunable fit, default 0.6, slider for per-device screens).

**`eyesClosed` (AU43) wired** (ADR-0034 follow-through): a dedicated sustained-closure morph
target (`MORPH_TARGETS` = ARKit-52 + eyesClosed), driven by emotion_driver's **pain (PSPI)**
and **drowsy (PERCLOS)** moods.

**Verdict: RB-001 rig ACCEPTED.** Remaining visual polish → RB-003.
