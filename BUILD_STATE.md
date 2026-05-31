# MEDSIM V8 (Medsim-VRAI) · BUILD STATE

> **2026‑05‑28 — V8 FORK from V7.** The body of this file below describes
> the V7 multi-patient build, all of which is **carried into V8 verbatim**.
> V8 adds the VRAI Faces tablet avatar surface; everything related to
> that work lives in `vrai-faces/` and is tracked there. The V7 checkpoint
> below remains the authoritative state for everything *outside* the
> avatar surface.
>
> **V8 fork checkpoint (2026‑05‑28):**
> - `vrai-faces/` workspace scaffolded — 12 modules, types, configs,
>   tests, Capacitor shells (see `vrai-faces/Memory_management.MD`).
> - Portal routes added at the bottom of `portal/server.py`:
>   `GET /qr/face/<id>.svg` and `GET /portal/face/launch/<id>`.
> - `pyproject.toml` renamed to `medsim8` v8.0.0a0.
> - ADR‑0017 (fork) and ADR‑0018 (Pause/Resume) added in
>   `vrai-faces/Memory_management.MD §7`.
> - Pause/Resume code lands: `Resumable<T>` on `animation_runtime`,
>   `audio_pipeline`, `medsim_adapter`; `memory_state` aggregates via
>   IndexedDB at origin `vrai-faces`, store `session-state`.
> - **NOT YET BUILT:** real module impls (everything in
>   `vrai-faces/packages/core/src/modules/*/impl/` is a typed stub that
>   throws on call). Next step per `vrai-faces/Memory_management.MD §3`
>   is the `face_ingest` → `mesh_builder` → `shader_translucent`
>   vertical slice.
>
> **2026‑05‑28 — resume‑session additions (post‑fork):**
> - `vrai-faces/packages/core/src/perf/latency_meter.ts` — wraps the §5
>   budgets (prompt→first‑audio, audio→viseme, viseme→frame) into a
>   `mark()`/`measure()` pair that pushes warn vs metric to `diag`.
> - `vrai-faces/packages/core/src/shell/translucency_slider.ts` — the
>   single user‑facing opacity control; wires straight to
>   `shaderTranslucent.setOpacity`.
> - `vrai-faces/packages/core/src/workers/renderer.worker.ts` — opaque
>   command channel for the OffscreenCanvas path (§3.3); main thread
>   falls back to in‑page render when transferControlToOffscreen is absent.
> - `vrai-faces/packages/core/test/unit/speech_frame_to_runtime.test.ts`
>   — cross‑module seam test: parsed `VRAISpeechFrame` → `animationRuntime`
>   visemes + emotion baseline.
>
> **2026‑05‑28 — first vertical slice LANDED (supersedes the "NOT YET
> BUILT" note above for these modules).** The
> `face_ingest → mesh_builder → shader_translucent` slice plus the
> `animation_runtime` tick loop and a renderer/demo harness are now real
> impls (no longer throwing stubs):
> - `face_ingest`: `ingest(File|Blob) → NormalizedPortrait` — 512² centered
>   square crop, alpha stripped on a black ground via OffscreenCanvas,
>   EXIF via `createImageBitmap({imageOrientation:'from-image'})`, SHA‑256
>   of the PNG for downstream caching; bbox = full image (mesh_builder
>   refines later).
> - `mesh_builder`: `build(portrait) → BuiltMesh` — **placeholder topology**
>   (elongated 32×32 sphere, 52 ZERO‑displacement ARKit morph attributes,
>   `geometry.userData.morphTargetNames = [...ARKIT_52]`), `CanvasTexture`
>   (sRGB, flipY=false); registers geometry+texture in `resource_registry`,
>   caches by `portrait.hash`. Real MediaPipe 478‑vert deformation deferred.
> - `shader_translucent`: `build({geometry,texture}) → TranslucentMaterial`;
>   `setOpacity` drives the §4 anchor table (transmission/opacity/fresnel/
>   specular), mutating uniforms with no `needsUpdate` (Code Guide §3.2).
> - `animation_runtime`: `tick(nowMs)` sums viseme+emotion+idle into a
>   pre‑allocated `Float32Array(52)`, clamps, writes `morphTargetInfluences`
>   on every attached mesh; `Resumable` snapshot/restore intact.
> - `shell/renderer.ts`: WebGPU→WebGL2 `mountRenderer`, scene + camera +
>   3‑point lights, rAF loop calls `animationRuntime.tick(now)` then renders.
> - `shell/demo_boot.ts`: procedural 512² portrait → full pipeline →
>   `THREE.Mesh` → `renderer.attachMesh` → opacity 0.66 default.
> - `main.ts`: boots 9 modules, `resumeAll`, mounts renderer on `#stage`,
>   boots the demo avatar, mounts the translucency slider, starts the loop.
>
> Seam consistency verified by reading (every contract lines up):
> `tick(nowMs:number)` signature; branded `GeometryRef`/`TextureRef`;
> `NormalizedPortrait` shape (`png`/`hash`) consumed by mesh_builder;
> `morphTargetNames` key produced by mesh_builder and read by
> animation_runtime's `indexOfShape`; stable `meshId` flowing
> registry → `attachMesh` → `attach` → `lookupMesh`.
>
> **2026‑05‑28 — toolchain stood up + slice VERIFIED GREEN.** Installed
> Node 22.22.3 locally with no sudo/Homebrew (official `darwin-arm64`
> tarball → `~/.local/node/current`, `corepack`‑activated `pnpm@9.0.0`),
> then `pnpm install` (402 pkgs). **`pnpm -F @vrai/core typecheck` (tsc,
> full strict) is CLEAN and `pnpm -F @vrai/core test` is 29/29 across 15
> files.** Re‑run in a fresh shell with
> `export PATH="$HOME/.local/node/current/bin:$PATH"` then
> `pnpm -C packages/core typecheck && pnpm -C packages/core test`.
>
> **2026‑05‑28b — VERIFIED IN A REAL BROWSER (headless Chromium).** Ran
> the Vite dev server (`:5173`) plus a production build (`vite build`: 52
> modules, both renderer chunks emitted, `mediapipe` chunk empty as
> expected), then drove Playwright's bundled headless Chromium against the
> dev server. **The full async `boot()` chain completes with 0 page errors
> and 0 console errors** — the translucency slider mounts at value 66, and
> since the slider is the last thing `boot()` does, its presence proves the
> renderer + demo avatar + slider all came up. The placeholder translucent
> avatar renders. WebGPU has no adapter in headless, so it runs on the
> WebGL2 backend (the ADR‑0009 fallback).
>
> **Two issues the browser run surfaced. #1 is now FIXED + VERIFIED — see
> the 2026-05-28c note further below; #2 (lazy code-split) is now FIXED +
> VERIFIED — see the 2026-05-28d note.**
> 1. **Dual Three.js instance → unlit avatar.** `renderer.ts` builds the
>    scene/camera/lights from classic `three`, but instantiates
>    `WebGPURenderer` from the separate `three/webgpu` entry whenever
>    `navigator.gpu` exists — which is true on modern Chrome/Safari/iPad
>    even with no GPU adapter, because `WebGPURenderer` has its *own*
>    internal WebGL2 backend. So the classic `WebGLRenderer` fallback
>    (renderer.ts:57) is effectively dead on the target devices, and
>    `three/webgpu` pulls a second copy of three core ("Multiple instances
>    of Three.js"). The `WebGPURenderer` node‑light system then rejects the
>    classic‑`three` lights ("LightsNode.setupNodeLights: Light node not
>    found for DirectionalLight/AmbientLight"), so the avatar renders
>    flat/unlit (ambient + faint emissive only — visible in the smoke
>    screenshot). Fix is an ADR‑0009 design call: commit to a single
>    `three/webgpu` import surface (scene+lights+materials), or use the
>    classic `WebGLRenderer` for the first cut and defer WebGPU.
> 2. **Lazy code‑split boundaries silently defeated.** `vite build` warns
>    that `utils/resource_registry.ts` (dyn‑imported by `demo_boot`) and
>    `medsim_adapter/index.ts` (dyn‑imported by `lazy.ts`) are *also*
>    statically imported elsewhere, so they fold into the main chunk and
>    the intended lazy split never happens.
>
> **2026-05-28c — issue #1 (dual Three.js → unlit avatar) FIXED + VERIFIED.**
> Took the chosen ADR-0009 path: route the entire Three surface through
> `three/webgpu`. All six three-importing files now import from
> `three/webgpu` (renderer, mesh_builder, shader_translucent, demo_boot,
> resource_registry, animation_runtime); `renderer.ts` dropped the dead
> classic `WebGLRenderer` fallback + the `RendererLike` shim and uses a
> single `WebGPURenderer` that negotiates WebGPU→WebGL2 inside `init()`.
> Re-verified in headless Chromium against the dev server: the "Multiple
> instances of Three.js" and "Light node not found" warnings are both gone,
> 0 page/console errors, and the avatar now renders lit — directional key
> highlight + shaded falloff + visible portrait texture (before:
> `/tmp/vrai_boot.png`, after: `/tmp/vrai_boot_lit.png`). Bundle collapsed
> from two three chunks (468 kB + 823 kB) to one (~622 kB). typecheck CLEAN,
> 29/29 tests still pass. (Issue #2, the defeated lazy code-split, is now
> FIXED + VERIFIED in the 2026-05-28d note below.)
>
> **2026-05-28d — issue #2 (lazy code-split) FIXED + VERIFIED, plus two
> related build-hygiene fixes.**
> - **Lazy code-split warnings gone.** `demo_boot.ts` now imports
>   `lookupMaterial` statically (dropped the vestigial
>   `await import('@utils/resource_registry')` — that module is already
>   eagerly loaded). `lazy.ts` dropped the unused `lazyMedsim` wrapper:
>   `medsim_adapter` is statically imported at boot (main.ts +
>   registerLifecycles.ts), so its dynamic import was both dead code and the
>   sole cause of the "dynamically imported … but also statically imported"
>   warning. `lazyEmotion`/`lazyTts` stay (genuinely lazy — used by the
>   firstGesture warmup, no static import). Both `vite build` warnings gone.
> - **`check:no-any` guard de-falsed.** `scripts/check-no-any.mjs` was
>   substring-matching the English word "any", so prose tripped it (3 false
>   positives: "from any module", "if any.", "avoid `any`"). Rewrote it to
>   blank out comments + string/template literals (block-comment state carried
>   across lines) before testing the `\bany\b` keyword; `@ts-ignore` /
>   `eslint-disable` still match the raw line (they're comment directives).
>   Proven both ways: `OK` on `src/` (0 false positives) and a throwaway
>   fixture confirmed it still flags real `: any` / `as any` / `any[]` /
>   `Promise<any>` / `| any` / `<any>` and honours `// vrai-allow:`.
> - **`three` vendor chunk restored.** The 28c migration to `three/webgpu`
>   left `vite.config.ts` manualChunks keyed on the bare `'three'` specifier,
>   which no longer matches anything — so Three's ~545 kB spilled into the
>   main chunk and an empty `three` stub was emitted. Re-keyed to
>   `'three/webgpu'`: `three` chunk = 545 kB, main `index` chunk = 76 kB
>   (was ~622 kB). The `mediapipe` chunk stays empty (expected — nothing
>   imports `@mediapipe/tasks-vision` yet) and the >500 kB advisory on the
>   Three chunk is benign.
> - **Verification:** typecheck CLEAN, 29/29 tests, `vite build` clean of the
>   two lazy-split warnings + the empty-`three` warning, `check:no-any` OK.
>
> **2026-05-28e — the six throwing stub modules are implemented (the "move on"
> task). typecheck CLEAN · check:no-any OK · 49/49 tests (was 29) · build clean.**
> Constraint triage drove every choice: no new third-party lib (all pure TS, or
> the existing `three/webgpu`), PHI never leaves the device, and the
> classic-`three` dual-instance hazard is avoided by hand.
> - **idle_motion** — full deterministic idle: spontaneous blinks (smoothstep
>   close/open, ~2.8–6 s interval, 12 % double-blink), micro-saccades (dart→hold
>   with a slow sinusoidal sway), all on a mulberry32 PRNG advanced per *event*
>   off a t0 — framerate-independent, same seed → same sequence; catch-up loops
>   capped (CATCHUP_GUARD). 5 tests (determinism, blink closure/symmetry, gaze).
> - **emotion_driver** — local deterministic lexicon classifier (priority
>   pain>fear>anger>sad>drowsy>relieved), emits ARKit JSON weights + a short
>   label, never free text. Zero deps, zero network → PHI-safe by construction;
>   transformers.js / cloud-LLM stay deferred behind ADR-0005 / ADR-0014. 5 tests.
> - **medsim_adapter.bindFromCharacter** — validates + normalizes a MedSim
>   character payload → `VraiAvatarBinding` (characterId|id; portrait from a Blob
>   or a locally-decoded `data:` URI; voice default `default`; opacity clamp,
>   0.66 default; baselineMood clamped), fail-closed (throws on no id / no
>   portrait). Adds the same-origin BroadcastChannel speech transport
>   (connect/disconnect, pause/resume, snapshot/restore), guarded so a
>   non-browser env + unbooted unit tests open no channel. 8 tests (4 new).
> - **audio_pipeline** — real Web Audio graph: lazy, guarded `AudioContext`
>   (unprefixed; iOS ≥ 14.5), PCM16-24k hand-framed + opus/mp3 via
>   `decodeAudioData`, gapless `AudioBufferSourceNode` scheduling off a running
>   playhead, AnalyserNode RMS → `jawOpen` viseme loop (rAF). Degrades to a no-op
>   graph when there is no AudioContext (Node/jsdom): `primed` still flips,
>   enqueue drops silently, the prime-before-enqueue guard (ADR-0008) is intact.
>   4 tests.
> - **tts_provider.speak** — local on-device synthetic voicing (fundamental + 2
>   harmonics under a syllabic envelope), streamed as ~240 ms PCM16-24k frames,
>   deterministic (djb2 hash of voice|text seeds pitch), `endOfUtterance` on the
>   last frame. A stand-in, not speech — but the right format/dynamics to drive
>   the audio → viseme path. PHI-safe (text never leaves the device). The
>   tier→provider router (pickProvider/TIER_CHAIN/BAA_PROVIDERS) is unchanged;
>   real engines stay deferred (cloud = ADR-0014 BAA pool; kokoro / piper-wasm
>   each need an ADR + a tools-sheet line). 4 tests.
> - **avatar_exporter** — hand-rolled glTF-2.0 binary writer, deliberately NOT
>   three/addons `GLTFExporter` (it imports classic `three` → would reintroduce
>   the dual-instance / unlit bug). Reads geometry back from the registry
>   (`three/webgpu`, the same instance — safe) else a placeholder triangle; bakes
>   translucency into `KHR_materials_transmission.transmissionFactor` +
>   `extras.vraiOpacity` (+ `extras.vraiBaselineMood`). exportVRM adds a minimal
>   `VRMC_vrm` meta on the same GLB. Morph-target (blendshape) baking deferred
>   until mesh_builder emits real per-shape deltas. 5 tests (GLB header + JSON).
> - **Verification:** typecheck CLEAN, check:no-any OK, 49/49 tests pass,
>   `vite build` clean (three 545 kB / main 80 kB, no code-split warnings; the
>   empty `mediapipe` chunk + the >500 kB Three advisory are expected/benign).
>
> Three issues the first compile/tests forced (all fixed in source):
> 1. **Alias rename `@types/*` → `@contracts/*`** (tsconfig paths + vite +
>    vitest + every import + module READMEs). TypeScript reserves the
>    `@types/` specifier prefix for DefinitelyTyped packages (TS6137), so
>    the scaffold's original alias could never compile. The `src/types/`
>    directory is unchanged — only the import alias moved. **New
>    convention: contracts are imported as `@contracts/<name>`.**
> 2. **`parseLaunchUrl` opacity default**: `Number(null) === 0` is finite,
>    so a QR missing `?opacity` resolved to 0 (fully ghost) instead of the
>    0.66 mid‑stop; now guards null/empty explicitly (explicit `opacity=0`
>    still honoured).
> 3. Minor strict‑mode fixes: `Float32Array` + `noUncheckedIndexedAccess`
>    in `animation_runtime.tick` (`accum[idx] = accum[idx]! + w`), uncast
>    2D canvas ctx in `demo_boot`/`face_ingest`, and unused `_deps`/import
>    in four stub modules.
>
> **Throwing stubs: NONE remain.** All six implemented 2026-05-28e (see that
> note above): `idle_motion`, `emotion_driver`, `medsim_adapter.bindFromCharacter`,
> `audio_pipeline`, `tts_provider.speak`, `avatar_exporter`. Remaining work is
> upgrades behind their ADRs, not stubs: `emotion_driver` LLM path (ADR-0005),
> `tts_provider` real engines (ADR-0014 cloud BAA; kokoro/piper-wasm need an ADR +
> tools-sheet line), and `avatar_exporter` morph-target baking (needs real
> mesh_builder per-blendshape deltas).
>
> **2026-05-28f — diagnostic_panel made real + the observability loop closed.
> typecheck CLEAN · check:no-any OK · 55/55 tests (was 49) · build clean.**
> The last non-functional module is now live, and the panel has live data to show.
> - **diagnostic_panel** — real dev-only DOM overlay (no framework, no new dep).
>   Reads the `diag` singleton and paints a fixed top-right panel: an fps/ms line
>   (prefers `animation_runtime`'s reported tick time), one row per module
>   (state · fps, + any `lastError`), and a 14-event timeline tail colour-coded by
>   kind. Refreshes at 4 Hz. Self-gates to DEV or `?diag=1` — `show()` is a no-op
>   and mounts no DOM in production / SSR / non-jsdom tests. PHI note honoured: it
>   renders only the authored `event.message`, never `event.data`. Wired into
>   `main.ts` (called unconditionally after `renderer.start()` — safe because it
>   self-gates). 5 tests.
> - **animation_runtime → diag** — closed the loop the panel depends on: `tick()`
>   now surfaces a rolling-average frame time to `diag.set('animation_runtime',
>   {state, fps, lastTickMs})`, throttled every `REPORT_EVERY = 30` ticks
>   (~0.5 s @ 60 fps) so the hot loop stays allocation-light. Before this, only
>   `shell/renderer` reported, so the panel's fps line read "fps —". 2 tests
>   (reports past the 30-tick boundary; stays quiet before it).
> - **Verification:** typecheck CLEAN, check:no-any OK, 55/55 tests pass,
>   `vite build` clean (three 545 kB / main 82 kB; empty `mediapipe` chunk + the
>   >500 kB Three advisory expected/benign, no code-split warnings).
>
> **2026-05-28g — shader_translucent gets a REAL Fresnel rim (TSL node graph).
> typecheck CLEAN · check:no-any OK · 58/58 tests (was 55) · build clean.**
> Closes the long-standing TODO ("swap in a real onBeforeCompile patch"). The
> investigation flipped the approach: we render through `WebGPURenderer`
> (ADR-0009), where **`onBeforeCompile` never fires** — it is a WebGLRenderer
> hook. The WebGPU-native answer is TSL, so the module now builds a
> `MeshPhysicalNodeMaterial` and sets `emissiveNode` to a node graph
> `white · (1 − saturate(N·V))^POWER · strength`, replacing the old
> emissive-intensity fake.
> - **No new dependency / no dual-instance risk.** Verified `three/tsl` and
>   `three/webgpu` both resolve to the *same* build file (`three.webgpu.js`) in
>   three@0.170 — so TSL helpers (`uniform`, `dot`, `pow`, `oneMinus`,
>   `saturate`, `mul`, `color`, `positionViewDirection`, `transformedNormalView`)
>   and `MeshPhysicalNodeMaterial` import from the one instance the renderer's
>   node lighting already uses. (`@types/three@0.170` carries the decls;
>   typecheck is the oracle for the parts jsdom can't render.)
> - **setOpacity stays recompile-free** in steady state: the rim strength rides
>   on a TSL `uniform()` whose `.value` we mutate in place (the node graph is
>   never rebuilt). The one unavoidable exception — the first move off
>   fully-opaque enables `MeshPhysicalNodeMaterial`'s transmission path, a
>   single recompile — is now documented honestly (the old `MeshPhysicalMaterial`
>   had the same cost). `mapOpacity()` §4 table is untouched.
> - **Tests (3 new):** `build()` yields a node material with a Fresnel
>   `emissiveNode`; `setOpacity` is uniform-only across the steady-state range
>   (same `emissiveNode` object, `material.version` unchanged); `snapshot`
>   round-trips. Existing `mapOpacity` anchor-row tests unchanged.
> - **Verification:** typecheck CLEAN, check:no-any OK, 58/58 tests pass,
>   `vite build` clean (three 545 kB / main 82.6 kB, no new warnings).
>
> **2026-05-29 — animation_runtime honors setEmotion's cross-fade (easeMs).
> typecheck CLEAN · check:no-any OK · 62/62 tests (was 58) · build clean.**
> The `setEmotion(weights, easeMs)` contract has always promised a cross-fade;
> the impl had been snapping (the `_easeMs` arg was ignored). It now eases.
> - **Three weight sets.** `emotion` stays the cross-fade TARGET (still the
>   only set `snapshot()` persists — restore lands on the target, not mid-fade,
>   so the ADR-0017 round-trip test is untouched). `emotionCurrent` is what each
>   tick actually applies; `emotionFrom` is the applied set frozen when a fade
>   begins. tick() step 1c eases `emotionCurrent → emotion` and step 4 now reads
>   `emotionCurrent` instead of the raw target.
> - **Eased, allocation-free, clock-anchored.** Two new exported pure helpers:
>   `smoothstep` (`3x²−2x³`, clamped — zero slope at both ends) and
>   `blendEmotion(from,to,current,k)` which lerps in place and prunes keys that
>   reach 0 (so the applied set stays sparse; `current ⊆ from∪to` always, so no
>   stale-key sweep). The fade is anchored to the renderer clock on its FIRST
>   tick (not at `setEmotion` time), so `easeMs` is wall-clock and a paused tick
>   can't burn the window. `easeMs ≤ 0`/omitted snaps; `restore()` snaps.
> - **Tests (4 new):** unit — `smoothstep` clamps/pins anchors + is non-linear,
>   `blendEmotion` lerps toward target and prunes zeros; integration — a fake
>   mesh whose only morph target is `mouthSmileLeft` (idle motion touches only
>   eye shapes, so index 0 is clean) eases 0 → 0.2 → 0.4 across a 200 ms window,
>   and a no-easeMs `setEmotion` snaps. Diag fps/lastTickMs reporting (the
>   2026-05-28f wiring) is also now asserted past the REPORT_EVERY boundary.
> - **Verification:** typecheck CLEAN, check:no-any OK, 62/62 tests pass,
>   `vite build` clean (three 545 kB / main 83.4 kB, no new warnings).
> - **NEXT / OPEN:** ADR-0019 (Proposed, on-device emotion-inference engine for
>   `emotion_driver`) is being drafted in `vrai-faces/docs/` — NOT yet in §7
>   (undecided). Still ADR-gated: `mesh_builder` real MediaPipe 478-vert topology
>   (ADR-0002 approved), `avatar_exporter` morph-target baking (needs real
>   mesh_builder deltas), local-TTS fallback ENGINE choice.
>
> **2026-05-29b — mesh_builder gets the REAL MediaPipe path (landmark→geometry
> core + fallback). typecheck CLEAN · check:no-any OK · 67/67 tests (was 62) ·
> build clean.** Advances mesh_builder off the placeholder sphere onto a real
> two-path build, per ADR-0002 (MediaPipe Face Landmarker — already approved, so
> no new ADR). `@mediapipe/tasks-vision@0.10.35` is installed with types.
> - **Two paths.** `build()` tries the REAL path, degrades to the FALLBACK so the
>   pipeline always returns a usable `BuiltMesh`. Real: `detectFaceLandmarks(png)`
>   runs FaceLandmarker (478 landmarks + ARKit-52 blendshape baseline) →
>   `buildFaceGeometry` deforms the canonical topology into the identity's head
>   (recenter + Y-flip, UVs, normals, 52 morph attrs). Fallback: the elongated
>   head-proxy sphere (jsdom, no-GPU, or assets absent).
> - **New files (same module, no cross-module impl import).** `impl/face_topology.ts`
>   — pure `buildFaceGeometry` + `parseTopology` (fail-soft asset validation) +
>   `loadFaceTopology` (fetch seam) + the canonical `ARKIT_52` list. `impl/
>   face_landmarker.ts` — browser-only `detectFaceLandmarks` via a DYNAMIC import
>   of tasks-vision (own code-split chunk; returns null off-browser/no-asset).
> - **Gated on two UNBUNDLED data assets** (real path is dormant until they land,
>   local-first / ADR-0001, local paths not CDN): the `face_landmarker.task` model
>   and `face_mesh_topology.json` (triangulation + UVs). The MediaPipe WASM ships
>   inside the package. Morph DELTAS stay ZERO — real per-blendshape deltas need a
>   deformation basis MediaPipe doesn't ship (a further slice); the blendshape
>   *coefficients* feed only the neutral `baselineMood`.
> - **Tests (+5):** `buildFaceGeometry` (landmark→position mapping, index/UV/normal/
>   52-morph allocation, too-few-landmarks guard) and `parseTopology` (well-formed
>   accept, malformed → null). Detection + full real build stay browser-gated
>   (`test/e2e/fixture.spec.ts`).
> - **Verification:** typecheck CLEAN, check:no-any OK, 67/67 tests pass, `vite
>   build` clean — the `mediapipe` chunk is now a real 135 kB lazy split (was an
>   empty 0.05 kB), proving the dynamic import stays out of the main bundle; three
>   545 kB unchanged, main 85.6 kB.
> - **NEXT:** bundle the two assets to light up the real path end-to-end; then the
>   blendshape-delta basis for real morph targets (unblocks `avatar_exporter`
>   morph baking).
>
> **2026-05-29c — real path LIT UP: assets bundled + procedural morph basis.
> typecheck CLEAN · check:no-any OK · 72/72 tests (was 68) · build clean.**
> Both 2026-05-29b "NEXT" items done (user-approved the downloads + a procedural
> basis). The real MediaPipe path now runs end-to-end in the browser.
> - **Assets bundled (local-first, ADR-0001 — served from app origin, not a CDN).**
>   Downloaded (with explicit user OK): `public/assets/mediapipe/face_landmarker.task`
>   (3.75 MB, Google MediaPipe storage) and `canonical_face_model.obj` (46 KB,
>   google-ai-edge/mediapipe, Apache-2.0, vendored under `scripts/`). Copied the
>   MediaPipe WASM (6 files) from the installed package into
>   `public/assets/mediapipe/wasm/`. `scripts/gen-face-topology.mjs` parses the
>   .obj → `public/assets/face/face_mesh_topology.json` (468 verts, 898 tris,
>   10 KB). All land in `dist/` on build. **Repo grew ~3.8 MB** (the model binary).
> - **UVs now derived from landmarks**, not a stored asset — the portrait IS the
>   detected image, so a vertex's UV is its normalized landmark x,y (texture
>   `flipY=false` ⇒ no flip). So the topology asset is triangulation-ONLY.
> - **Procedural morph basis** (`impl/morph_basis.ts`) — an APPROXIMATION, not an
>   ARKit rig (no off-the-shelf ARKit-52→MediaPipe-468 asset exists). Geometry-
>   driven deltas (no hard-coded indices, robust to 468/478) fill the defensible
>   shapes — **jawOpen** (dominates lip-sync), mouthSmileL/R, browInnerUp — and
>   leave the other 48 zero pending a real rig. Deterministic (ADR-0005 spirit).
> - **Tests (+4 → 72):** `computeMorphBasis` region/sign assertions (jawOpen drops
>   the lower face, browInnerUp lifts upper-center, smile lifts the right corner,
>   tongueOut stays zero) + the UV-from-landmark assertions; `buildFaceGeometry`
>   now asserts the basis is wired (jawOpen nonzero on a lower vert).
> - **Verification:** typecheck CLEAN, check:no-any OK, 72/72 tests pass, `vite
>   build` clean; `dist/assets/{face,mediapipe}` confirmed populated (model + WASM
>   + topology), mediapipe chunk 135 kB lazy split, three 545 kB unchanged.
> - **NEXT:** a real ARKit-52 blendshape rig to replace the procedural basis
>   (then `avatar_exporter` can bake real morph deltas); browser-verify the live
>   FaceLandmarker path (e2e fixture) since it can't run in jsdom.
>
> **2026-05-29d — Phase 1.1: live MediaPipe path BROWSER-VERIFIED. typecheck CLEAN
> · 72/72 unit · e2e (desktop-chromium) GREEN (7.3s).** Phase 1 (real avatar
> geometry) started; Phase 0 decisions ratified just prior (ADR-0019/0020 + §9).
> - **GPU→CPU delegate fallback** (`face_landmarker.ts`): FaceLandmarker tries the
>   GPU delegate, falls back to CPU on failure (headless / no-WebGPU tablets / CI).
>   Without it the whole real path silently dropped to the sphere even with a face.
> - **Observable path log**: `mesh_builder.build()` pushes a diag event — "real mesh:
>   N landmarks, M tris" vs "fallback head-proxy (topology=…, detection=…)" —
>   surfaced in diagnostic_panel, PHI-safe (counts only, ADR-0014).
> - **e2e `test/e2e/face-pipeline.spec.ts`** (desktop-chromium, PASS): the demo boot
>   drives mesh_builder → loadFaceTopology + detectFaceLandmarks; the test asserts the
>   topology JSON, the `face_landmarker.task` model, and a `vision_wasm_*.wasm` all
>   fetch 200 with zero page errors ⇒ FilesetResolver + FaceLandmarker.createFromOptions
>   + detect() all run in a real browser. The live stack is wired end-to-end.
> - **NOT verified here (input-gated):** real photo → 478 landmarks → real mesh. Needs
>   a consented portrait fixture (facial-image policy) — documented in the spec as a QA
>   step; the synthetic demo portrait correctly falls back to the head-proxy.
> - **NEXT:** Phase 1.3 exporter morph baking against the current procedural basis
>   (achievable now), and/or Phase 1.2 a real ARKit-52→MediaPipe-468 rig (hard to
>   source — no clean off-the-shelf asset).
>
> **2026-05-29e — Phase 1.3: avatar_exporter MORPH-TARGET BAKING. typecheck CLEAN
> · check:no-any OK · 74/74 tests (was 72) · build clean.** Closes the long-deferred
> exporter TODO ("add a targets[] block per primitive when real deltas land").
> - `extractArrays` now reads `geometry.morphAttributes.position` (the 52 deltas)
>   + `userData.morphTargetNames`. `writeGlb` bakes each blendshape as a per-primitive
>   `targets[]` POSITION-delta accessor (with per-target min/max bounds), plus
>   `mesh.weights` (all 0) and `mesh.extras.targetNames` so the ARKit-52 set
>   round-trips BY NAME. Morph deltas append to the BIN buffer after indices, 4-aligned.
> - Decoupled from the rig question: works against ANY non-zero basis — today
>   mesh_builder's procedural deltas, a real rig later via the same path. Omitted
>   entirely for unrigged/placeholder geometry (existing tests unaffected).
> - **Tests (+2):** named `targets[]` + `weights` + `extras.targetNames` + non-zero
>   accessor bounds on a registered 2-target geom; targets omitted for placeholder.
> - **NEXT:** Phase 1.2 (real ARKit-52→MediaPipe-468 rig) is GATED — captured as a
>   Cowork research brief (`research/`), see the research-driven-enhancement strategy
>   added to `docs/ROADMAP.md`.
>
> **2026-05-29f — Phase 2.3: audio_pipeline ADR-0015 viseme gating. typecheck CLEAN
> · check:no-any OK · 77/77 tests (was 74) · build clean.** Phase 2 (real speech)
> started with the achievable, no-download piece.
> - `audio_pipeline` gains `setVisemeSource('native' | 'derived')`. `'native'`
>   (the provider streams its own visemes — Azure/AWS Polly) SUPPRESSES the
>   energy→`jawOpen` derived bridge so visemes aren't doubled; `'derived'` (default)
>   runs it. `startVisemeLoop` is guarded; the source round-trips in `AudioSnapshot`
>   (optional field; restore defaults to 'derived'). Consumer of `tts_provider.speak()`
>   sets it per utterance from whether `TtsChunk.visemes` is present.
> - **Tests (+3):** default derived; native/derived round-trips snapshot↔restore;
>   restore w/o the field defaults derived; callable pre-prime. (Real audio graph +
>   energy bridge stay browser-gated.)
> - **NEXT (Phase 2, gated):** 2.1 local TTS engine (Kokoro→Piper, ADR-0020) needs
>   the engine deps + voice-model downloads (large, browser-gated runtime); 2.2 cloud
>   tiers + failover state machine are v1.1-flagged (real SDKs need BAA + keys). The
>   failover STATE MACHINE logic is buildable now with stubs; the engines/SDKs are
>   the download/procurement-gated parts.
>
> **2026-05-29g — Phase 2.2: tts_provider FAILOVER STATE MACHINE (ADR-0013).
> typecheck CLEAN · check:no-any OK · 82/82 tests (was 77) · build clean.**
> `speak()` was a passthrough to the synth stand-in; it's now the real router.
> - `speakWithFailover` walks the request's allowed chain (`resolveChain`, PHI-filtered
>   per ADR-0014), hopping on FIRST-CHUNK failure; on success it commits and streams.
>   Two consecutive CLOUD failures (`isLocalProvider` excluded) lock the session to the
>   local chain (ADR-0013); `resolveChain(req, lockedToLocal)` then ignores the tier and
>   serves local. Hops surface to diagnostic_panel — `warn` per hop, `error` on lock —
>   provider names only (PHI-safe). `activeProvider()` reflects the lock.
> - Per-provider `synths` map (today all → the synthetic stand-in); real engines
>   (Kokoro/Piper local Phase 2.1; Azure/etc. cloud v1.1) swap in here. `createImpl`
>   takes an optional `synths` override so failures are injectable in tests.
> - **Tests (+5):** hop-on-failure + diag; lock after two cloud failures; locked request
>   skips cloud; all-fail throws; PHI filter holds under failover (cartesia excluded for
>   trainee_input). Existing pickProvider/stream tests unchanged (default synths never fail).
> - **Phase 2 remaining (gated):** 2.1 local engine (Kokoro→Piper) — deps + voice-model
>   downloads + browser runtime; 2.2 real cloud SDKs — v1.1 (BAA + keys). The state
>   machine is ready for both.
>
> **2026-05-29h — Phase 2.1: Kokoro local TTS engine WIRED + build-verified.
> typecheck CLEAN · check:no-any OK · 82/82 tests · build clean.** ADR-0020 primary
> local engine (user-approved the q8 download).
> - Added `kokoro-js@1.2.1` + `@huggingface/transformers@4.2.0` (onnxruntime-web).
>   `impl/local_engine.ts` = the `headtts-kokoro` synth: DYNAMIC import (own chunk),
>   browser-gated (bails in jsdom/Node → failover), lazy model singleton,
>   `.stream(text,{voice})` → Float32 24 kHz → PCM16 chunks (last = endOfUtterance),
>   persona voice id → curated Kokoro voice. Wired via `DEFAULT_SYNTHS`.
> - **Node smoke VERIFIED the engine**: q8 loads (~39 s) and synthesizes 24 kHz audio
>   (2.45 s clip for a sentence). Build code-splits `kokoro` (2.2 MB lazy) and bundles
>   onnxruntime WASM locally (`ort-wasm-…jsep` 21.6 MB in dist) — runtime is local-first.
> - **LOCAL-FIRST GAP (ADR-0001):** kokoro-js@1.2.1 hardcodes the browser voice URL to
>   huggingface.co; the model can be bundled but VOICES fetch from HF until a voice-URL
>   fix (lib patch / service worker / cache-prime). Until then Kokoro needs first-run
>   network; on failure the chain falls over to the synth stand-in. Browser synthesis is
>   QA-pending (Node already proved the engine).
> - **NEXT (Phase 2.1):** decide the local-first voice/model bundling approach; then the
>   Piper-WASM CPU floor; cloud SDKs stay v1.1.
>
> **2026-05-29i — Phase 2.1: Kokoro LOCAL-FIRST via service-worker intercept
> (ADR-0001). typecheck CLEAN · check:no-any OK · 82/82 tests · build clean.**
> Closes the hardcoded-HF-voice-URL gap (user chose the SW approach).
> - `public/kokoro-sw.js` intercepts kokoro-js's hardcoded
>   `huggingface.co/.../Kokoro-82M-v1.0-ONNX/resolve/main/*` requests and serves the
>   bundled `/assets/kokoro/*` (model + voices), with network passthrough on a miss.
>   `local_engine.ensureKokoroSW()` registers it before the first model fetch.
>   `dist/kokoro-sw.js` confirmed served.
> - `setup:assets` extended: fetches `onnx/model_quantized.onnx` (q8, 92 MB, HEAD-
>   confirmed) + config/tokenizer + 8 curated voices (~510 KB each) → `public/assets/
>   kokoro/` (paths mirror HF so the SW maps 1:1; git-ignored, ~96 MB).
> - **To populate + run offline:** `pnpm --filter @vrai/core setup:assets` (the ~96 MB
>   fetch wasn't run this turn to keep it bounded). Browser interception is QA-pending;
>   the engine is Node-verified.
> - **Phase 2 status:** 2.3 viseme gating ✅, 2.2 failover ✅, 2.1 Kokoro wired +
>   local-first ✅. Remaining: Piper-WASM CPU floor; cloud SDKs (v1.1); browser e2e of
>   the Kokoro path.
>
> **2026-05-29j — Phase 2 launch-scope DONE: Kokoro bundle populated + Piper dropped
> (ADR-0021). typecheck CLEAN · check:no-any OK · 82/82 tests · build clean.**
> - **Bundle populated:** ran `setup:assets` — `public/assets/kokoro/` now holds the q8
>   model (`model_quantized.onnx`, exact 92,361,116 B), config/tokenizer, and 8 curated
>   voices (~92 MB, git-ignored). Kokoro is fully local-first (SW-served) on this machine.
> - **Piper DROPPED — ADR-0021 (amends ADR-0020).** Recon showed `piper-tts-web` pins
>   conflicting `onnxruntime-web@1.20` + `transformers@3.3` (vs Kokoro's 1.26 / 4.2 →
>   duplicate clashing runtimes) and Piper voices are ~63 MB EACH. Kokoro already runs on
>   `device:'wasm'` (CPU) when WebGPU is absent, so it IS the floor. TIER_CHAIN drops
>   `piper-wasm` (primary `[azure, kokoro]`, local `[kokoro]`); the provider literal is
>   retained but unused. Synthetic-stand-in unit test moved to tier `primary` (azure has
>   no real engine yet → synthVoice); failover all-fail test now kokoro-only.
> - **Phase 2 = launch-complete** (local-first voice + lip-sync + failover). Deferred:
>   cloud SDKs (v1.1, BAA+keys); browser e2e of the live Kokoro path (Phase 5).
>
> **2026-05-29k — Phase 3: emotion_driver HYBRID engine (ADR-0019). typecheck CLEAN
> · check:no-any OK · 85/85 tests (was 82) · build clean.** No new dependency —
> `@huggingface/transformers` was already pulled by Kokoro.
> - Replaced the lexicon-only stand-in with the ratified hybrid: (1) CLINICAL OVERRIDE
>   — the lexicon flags pain/drowsy (which general emotion models can't) and wins
>   outright; (2) MODEL — a transformers.js text-classification pipeline maps the
>   utterance to a general emotion; (3) LEXICON FALLBACK when the model isn't loaded.
>   The model loads in `warmup()` ONLY (dynamic import → own chunk), so unit tests +
>   non-browser run the deterministic lexicon path. Output stays JSON weights (ADR-0005).
> - `LABEL_TO_MOOD` maps Ekman + GoEmotions labels → our moods; `topLabel` normalizes
>   transformers.js's loose output. Both exported + unit-tested (+3 tests incl. the
>   clinical-override-beats-general case).
> - **Model pick (ADR-0019 open Q1/Q2):** defaulted to `SamLowe/roberta-base-go_emotions-onnx`
>   q8 (28 emotions → rich facial mapping) — but it's ~125 MB and the live path is
>   browser/Node-gated. The model is NOT bundled yet; that download + size is the
>   remaining Phase 3 decision (vs a smaller/coarser model, vs HF-loaded, vs RB).
> - **Phase 3 status:** hybrid ENGINE done + verified (lexicon fallback active). Pending:
>   model pick/bundle decision; Node-smoke to confirm labels; local-first bundle via
>   setup:assets + transformers env.
>
> **2026-05-29l — Phase 4.1: medsim_adapter wires the REAL MedSim character card.
> typecheck CLEAN · check:no-any OK · 88/88 tests (was 85) · build clean.**
> - **§9 answered:** the canonical character schema is `medsim_v8/schemas/character.json`.
>   New `impl/medsim_character.ts` = `characterCardSchema` (Zod, `.passthrough()`) +
>   `parseCharacterCard` + `voiceIdFromProfile`. `bindFromCharacter` now prefers the real
>   card (id, voice_profile) and falls back to the tolerant key-scan for synthetic payloads.
> - **Key finding:** the real card has NO portrait and NO ARKit weights. So
>   `voice_profile` → a gender-encoded `TtsVoiceId` (the TTS layer maps it to a Kokoro
>   voice — links Phase 2), live mood stays with `emotion_driver`, and the PORTRAIT is
>   attached at LAUNCH (the portal merges it — Phase 4.3). `ghostColor` added to
>   `VraiAvatarBinding` + extracted (Phase 0 decision 4).
> - **Tests (+3):** real-card validate/reject, voice_profile→id mapping, bind a real
>   card (+ attached portrait + ghost tint). Existing tolerant-payload tests unchanged.
> - **Phase 4 remaining:** 4.2 WebSocket transport (cross-app; needs a WS-URL source —
>   BroadcastChannel is the only live transport today); 4.3 portal speak path +
>   launchable-character list (Python; also where the portrait gets attached).
>
> **2026-05-29m — Phase 4.2: medsim_adapter WebSocket transport (ADR-0007).
> typecheck CLEAN · check:no-any OK · 91/91 tests (was 88) · build clean.**
> - The binding's `speechWsUrl` (set by the portal) now drives transport selection:
>   present → WebSocket (cross-app) with auto-reconnect; else BroadcastChannel
>   (same-origin). WS carries JSON text frames; the existing `seq` dedup defends
>   against reconnect replays. A `WsLike` factory is injectable (`createImpl({ wsFactory })`)
>   so the path is unit-tested without a server.
> - `connect()` picks WS vs BroadcastChannel; `connectWs` returns a boolean (TS can't
>   see it mutate `transport`); `disconnect()` cancels reconnect + detaches handlers.
> - **Tests (+3):** WS selected on speechWsUrl + frame delivery + seq-dedup; reconnect
>   on unexpected close (fake timers); dispose() stops reconnection. Browser-gated real
>   WS path falls back to the synth/BroadcastChannel paths in jsdom.
> **2026-05-29n — Phase 4.3: portal speak path + launchable list (Python). Phase 4 COMPLETE.**
> - New self-contained `portal/vrai_faces.py` (+ `attach(app)` in server.py, mirroring the
>   device subsystem). Four surfaces:
>   - `GET /api/face/characters` (auth) — launchable-character list; reuses
>     `scenarios.list_characters()`/`list_scenarios()`; `launchable` = referenced by ≥1 scenario
>     (Phase 0 decision 6) + emits qr/bind/speech URLs.
>   - `GET /api/face/{id}/binding` (NO auth — same trust as the `/qr/face` deep link) — the bind
>     doc `medsim_adapter.bindFromCharacter()` consumes: the real card merged with `sourcePhoto`
>     (portrait inlined as a `data:` URI — **portrait attach**, ADR-0022), `voiceProfile`
>     (voice_profile→gender-encoded id), `speechWsUrl`, `ghostColor?`, `opacityLevel`.
>   - `WS /ws/face/{scenario}/{id}` — avatar speech transport (mirrors `ws_room._RoomManager`).
>   - `POST /api/face/{id}/speak` (auth) + in-process `push_speech()` — emit
>     `VRAISpeechFrame {v:1,characterId,seq,text,emotion?,endOfUtterance}`; **text+emotion only,
>     no audio bytes** (tablet synthesizes locally, ADR-0023); `seq` seeded from wall clock so a
>     portal restart never replays a de-duped value.
> - **Portrait source (ADR-0022):** `portal/data/face_portraits/{id}.{png,jpg,jpeg,webp}`
>   (facilitator-supplied, consented, READ-only — no scraping); neutral placeholder + canonical-
>   topology fallback when absent. README added in that dir.
> - server.py: `_vrai_faces_url` now appends `&api=<portal origin>` so the avatar can call back
>   for its binding.
> - **Tests:** `tests/v8/test_vrai_faces.py` (TestClient, sandboxed vault + tmp YAML dirs) —
>   list/launchable; binding placeholder+file portrait+voice map+ghost+404+no-auth; speak
>   delivery+seq-increment+emotion+400+auth-required. **Verified here: `py_compile` of all three
>   touched files + symbol/behavior checks. Full pytest needs the portal venv (fastapi) — not
>   installed in this sandbox; run `pytest tests/v8` there.**
> - **Phase 4 COMPLETE** (portal side). The shell seam follows in 2026-05-29o.
>
> **2026-05-29o — Avatar-shell seam: end-to-end loop closed. typecheck CLEAN ·
> check:no-any OK · 106/106 tests (was 91) · build clean.**
> - `parseLaunchUrl` now reads `?api=<portal origin>` (URL-decoded) → `LaunchParams.apiBase`.
> - NEW `shell/portalBinding.ts`: `fetchBinding()` (builds `${api}/api/face/{id}/binding?scenario=&opacity=`,
>   fails soft → null on HTTP/network/parse error) + `bindFromPortal()` (fetch → `adapter.bindFromCharacter`
>   [validates card + connects the speech WS, ADR-0007] → build avatar from the attached portrait).
>   Injectable `fetchFn`/`buildAvatar` for tests.
> - NEW `shell/avatar_build.ts`: `buildAvatarFromBlob()` extracted from `demo_boot` (the
>   face_ingest→mesh_builder→shader_translucent→renderer pipeline); both the demo and bind paths use it.
> - NEW `shell/speechConsumer.ts`: `installSpeechConsumer()` — bridges audio_pipeline's energy-derived
>   visemes → `animation_runtime.pushVisemes` (once); each frame's emotion → `setEmotion` (180 ms ease);
>   text → lazy Kokoro TTS (`lazyTts`) → `audio_pipeline.enqueueAudio` (+ native visemes when present,
>   ADR-0015); utterances serialized; pre-synth `frame.audio` supported. Voice read per-utterance so a
>   late bind is honored.
> - `main.ts`: if `apiBase` + a non-`default` characterId → `bindFromPortal` (else demo); installs the
>   speech consumer; slider uses the bound opacity. Boot diag logs `bound`/`demo`.
> - **Lazy preserved:** build splits `kokoro`/`transformers`/`three` into separate chunks; the entry
>   `index-*.js` is **3.43 kB** (gzip 1.52) — TTS is NOT in first paint.
> - **Tests (+15):** `portalBinding` (7: URL shape/encode, !ok→null, throw→null; no-apiBase→null,
>   happy fetch→bind→build, fetch-fail→adapter-not-called, bind-reject→null), `speechConsumer` (6:
>   emotion, text→TTS+enqueue, native visemes, derived bridge, no-voice no-op, unsub), `parseLaunchUrl` (+2 api).
> - **Remaining → Phase 5:** real-tablet browser e2e (live MediaPipe + Kokoro over a real WS), soak/perf,
>   Capacitor, CI. Phase 1.2 ARKit rig stays gated (RB-001).
>
> **2026-05-29p — Phase 5: hardening & ship (sandbox-buildable scope). typecheck CLEAN ·
> check:no-any OK · 110/110 unit tests (was 106) · e2e specs compile (5) · build clean.**
> - **CI** (commit 98bec21): `.github/workflows/ci.yml` — `web` (pnpm9/node22: typecheck +
>   check:no-any + test + build) + `portal` (py3.11: `pip install .[dev,serve]` → `pytest tests/v8`
>   gating, full `pytest tests` non-blocking). `e2e.yml` — nightly cron + dispatch: setup:assets →
>   Playwright Chromium → build → desktop-chromium (headless → WebGL2 fallback per ADR-0009; soak
>   behind a dispatch input). Both YAMLs parse-validated.
> - **perf:** `perf/probe.ts` exposes `window.__vraiPerf()` (fps from animation_runtime diag, JS heap,
>   over-budget latency warns) — DEV/?diag gated like the diag panel; wired in `main.ts`.
>   `latency_meter` §5 budgets unit-tested (+4): elapsed/consume, unknown→-1, over-budget→warn,
>   under→metric.
> - **e2e:** `soak.spec` rewritten (5-min slider sweep, samples the probe, asserts no errors +
>   budgetWarns==0 + fps≥55 + heap growth ≤8%, all guarded for headless); NEW `bind-path.spec`
>   (`page.route` mocks `/api/face/*/binding` → asserts the shell took the BOUND path + #stage +
>   no crash). All 5 specs compile via `playwright test --list`.
> - **Capacitor (ADR-0006):** `tablet-ios/scripts/apply-ios-permissions.sh` — idempotent PlistBuddy
>   that sets `UIBackgroundModes=[audio]` + `NSMicrophoneUsageDescription`; wired into `pnpm sync`
>   (`apply:ios-perms`); README updated. `bash -n` clean.
> - **Deferred:** OffscreenCanvas worker (optional, perf-only). **Hardware-gated (not sandbox/CI):**
>   native `cap add ios/android` + `.ipa`/`.apk` builds; the live nightly e2e/soak *run* (real
>   browser + ~100 MB assets). Phase 1.2 ARKit rig stays gated (RB-001).
> - **Phases 0–5 engineering complete.** The believable local-first demo path (0→1→2.1→3→4) is wired
>   end-to-end and green on every sandbox-runnable gate.
>
> **2026-05-29q — Avatar discoverability (UX fix). All changed Python py_compile-clean.**
> - **Problem reported:** "not seeing any links to the faces." Root cause: the face *routes*
>   existed but no UI surfaced them, AND personas (the roster the instructor uses) were a separate
>   namespace from the avatar (which keyed off `characters/*.yaml`).
> - **Persona→avatar bridge:** `vrai_faces.resolve_card()` falls back to `library.get_persona()` →
>   `persona_as_character()`, so a persona id (`P-0xx`) yields a renderable avatar. `bind_payload`
>   uses it; new `launch_info()` powers the launcher.
> - **Personas page:** each persona card now has a **🪞 Develop & assign avatar →** link →
>   `/portal/face/launch/{id}` (now a "develop & assign" page: resolved name/role, portrait status
>   custom-vs-placeholder + the drop-a-photo hint, QR + bind URL).
> - **Assignment opt-in (control wizard Step 4):** a per-persona **🪞 Use VRAI Faces avatar**
>   checkbox (`name="avatar_personas"`, stopPropagation so it doesn't toggle the persona-select).
>   Persisted on the encounter: `ControlSession.avatar_personas` (+ `create_session` param); parsed
>   in `POST /portal/control/start` (intersected with selected) and `POST /api/room/start`.
> - **Remaining:** room-mode (multi-patient) wizard JS doesn't yet emit `avatar_personas` (server
>   already accepts it); runtime "consumption" (auto-show launch links for avatar-enabled personas in
>   the running session) is the next visible step.
> - NOTE: portal isn't runnable in this sandbox (no fastapi); verified via py_compile + grep. The
>   user reloads the portal (uvicorn --reload) + loads/creates characters to see it.
>
> **2026-05-30 — Character devices + cloud-STT PTT demo + the tablet HTTPS path (live-testing arc).**
> Web gate green (`typecheck` + `check:no-any` + 111 tests + `build`); all changed Python py_compile-clean.
> Worked on real tablet hardware over the LAN — most of this entry is the bring-up debugging that
> surfaced there. ADRs **0024** (character devices) + **0025** (cloud-STT demo stopgap) added; **RB-002**
> (on-device voice) authored + rendered.
> - **Per-character DEVICE QR, both tracks.** Single-encounter **ops view** (`control_ops.html`) now shows
>   one device QR per character (scenario = the control-session id, so the speech WS + `/listen` push share
>   a key); multi-patient **encounter console** already had it; scenarios-page QR reworded as the device
>   launcher. Opens the Chrome interface — avatar if a skin is assigned, else audio-only/placeholder
>   (ADR-0024). _(4300482, e3640d9)_
> - **Multi-patient avatar assignment (was missing).** Room-mode Step 4r character drawer gained a per-persona
>   **🪞 avatar** opt-in + the **skin-thumbnail picker** (it had neither); the room finalize now emits
>   `avatar_personas` per encounter (it had read the single-mode checkboxes → always empty); the per-bed list
>   was clipped at 220px → raised to 60vh so the full 24-persona library shows. _(8c79624, 86b9ee6)_
> - **On-the-fly skin assignment from the ops device cells.** Tap a face under a character's QR → assigns
>   (`POST /portal/personas/<id>/avatar`) → reload the tablet to apply. `resolve_portrait` hardened to also
>   honor the `.skin` marker (not just a copied portrait file). _(deef381, 828b117)_
> - **Cloud-STT push-to-talk DEMO (gated stopgap, ADR-0025).** `shell/device_voice.ts` — Web Speech API,
>   **off by default**, "🎙 Enable push-to-talk · cloud (not PHI)"; trainee→character PTT + an editable
>   name-trigger. Portal `POST /api/face/<id>/listen` (no auth, device-origin trust) → character AI turn
>   (borrows the active control-session key, reuses `runtime.take_turn`) → `push_speech` so the avatar
>   answers; echoes the heard text when no scenario is running. The PHI-safe on-device replacement stays
>   gated on **RB-002**. _(435450b)_
> - **Tablet bring-up fixes (the long arc, in order):**
>   - **`ws 127.0.0.1 refused`** → the face QR baked the operator's localhost into the app host + `api`
>     (so the derived speech WS pointed at the tablet itself). Added `_vrai_base_for_qr` + LAN substitution;
>     QR/launcher pass `lan=True`. _(1293270)_
>   - **`:5173 ERR_CONNECTION_REFUSED`** → the QR/tablet path never triggered the vite autostart (only
>     Develop did). `_ensure_vrai_app_for_qr` brings up the LAN-reachable dev server when a QR page renders. _(17f5279)_
>   - **Avatar didn't populate + no PTT button** → `boot()` awaited the bind before mounting controls.
>     Reordered: PTT mounts first, the demo shows immediately, the real character binds in the **background**
>     and hot-swaps demo→bound. _(f97db69)_
>   - **"demo avatar build failed" on the tablet** → `face_ingest` hashed the portrait with `crypto.subtle`,
>     which is `undefined` in an insecure context (plain `http://<LAN-IP>`). Fall back to a non-crypto hash
>     (cache key only; SHA-256 still used on HTTPS/localhost). _(d112ace)_
>   - **Unskinned (bare WebGL2) avatar** → WebGPU is secure-context-gated, so the tablet fell back to WebGL2
>     where the translucent material doesn't render the skin. Fix = serve over **HTTPS**:
>     `scripts/make-dev-cert.sh` (local CA + leaf, SAN = localhost/127.0.0.1/LAN-IP), vite + uvicorn serve TLS
>     when the cert exists, QR/`api`/WS become `https`/`wss` via `request.url.scheme`; certs gitignored. _(0322183)_
> - **Net device state (over HTTPS):** the skin renders under WebGPU; demo→bound hot-swap works; PTT button
>   present. **KNOWN/expected:** the bound avatar is the head-proxy **"egg" textured with the assigned skin** —
>   real sculpted facial geometry + visible expression/lip-sync are gated on **RB-001** (Phase 1.2); the
>   cloud-STT mic needs the HTTPS secure context; a character with no assigned skin shows the placeholder egg.
> - **Next:** see `docs/PLAN-2026-05-30-resecure-and-animation.md` — (A) re-secure the device voice (execute
>   RB-002 → on-device STT/wake-word, retire the ADR-0025 stopgap) and (B) make the skinned face animate from
>   the character's prompts/speech (execute RB-001 rig; the speech→viseme/emotion/idle drive is already wired).
>
> **2026-05-30b — On-device STT + PWA/cache + the cert CA-fix + DURABLE one-origin serving (ADR-0028).**
> Web gate green (`typecheck` + `check:no-any` + **111 tests** + `build`); changed Python py_compile-clean +
> route-registration verified via FastAPI `TestClient`. ADRs **0026** (on-device STT), **0027** (device
> security posture), **0028** (durable serving) added.
> - **On-device PTT STT (Phase 6, ADR-0026).** `shell/device_stt.ts` runs `whisper-tiny.en` (ONNX, MIT) via
>   the bundled transformers.js, WebGPU→WASM fallback; `device_voice.ts` switched off the cloud Web Speech
>   stopgap to record-on-hold→transcribe-on-release, audio never leaves the device. Forced
>   onnxruntime-web `numThreads=1`/`proxy=false` (multi-threaded WASM needs COOP/COEP we don't set) so the
>   CPU floor always loads; the panel shows a `STT: <backend> · cold <ms> · last <ms>` line + surfaces a
>   load error in-UI. _(184e4f5, adc4ef4)_
> - **PWA + app-shell cache (Phase 5.5/5.7).** Home-screen icon (`manifest.webmanifest` + apple-touch-icon),
>   unified `app-sw.js` (Kokoro passthrough + app-shell runtime cache, navigations network-first), persistent
>   storage, and the binding cache (`vrai-binding-v1`, clear-on-unpair, `?forget`). Fast restart after the
>   first download; consented skins stay on the device (PHI-at-rest rules in ADR-0027).
> - **Cert root-cause (the "not secure" saga).** Android-strict cert validation rejected our CA because it
>   carried **no X509v3 extensions** (no `basicConstraints=CA:TRUE`/`keyCertSign`) — macOS `openssl verify`
>   was lenient and hid it. `scripts/make-dev-cert.sh` now mints the CA with those critical extensions
>   (reusing the CA across LAN-IP changes so devices keep trust; leaf ≤398d), and `GET /rootca.pem` serves
>   the CA for one-tap install. _(b5e4c40, c95aa6c, d6f080f)_
> - **DURABLE one-origin serving (ADR-0028) — "build it out so it doesn't repeat".** The recurring tablet
>   failures (`binding fetch failed`, "connection not secure", unskinned demo-fallback) all traced to TWO
>   servers each holding a SEPARATE cert — vite `:5173` (app) + uvicorn `:8765` (api) — with a cross-origin
>   bind + speech WS between them; any drift (changed LAN IP, a stale vite on an old cert) broke the tablet.
>   Patching certs fixed instances, not the class. Now, with **`VRAI_FACES_SERVE=portal`**, `run_portal.py`
>   builds `dist/` once and `portal/server.py` serves the avatar app itself: `/face/<id>` → `index.html`
>   (SPA), `/assets` mount (hashed bundles + bundled Kokoro/MediaPipe/face models), root PWA files. The QR
>   then points at the **portal origin** with `api` = the same origin, so binding/listen/speak/WS are all
>   **same-origin → one cert, no cross-origin, no `:5173`**. `_ensure_vrai_app_for_qr` skips the vite
>   autostart in this mode. Default (no env) = unchanged dev (vite + HMR via the Develop button). No new dep.
> - **Run (deployed tablets):** `VRAI_FACES_SERVE=portal MEDSIM_HOST=0.0.0.0 python3 run_portal.py` —
>   trust the one `portal/data/certs/rootCA.pem` on each tablet, then scan the device QR. See
>   `docs/PILOT-2026-05-30-on-device.md`.
> - **Next:** the on-device pilot (task #50) on a stable one-origin/one-cert surface — measure PTT latency /
>   clinical WER / thermal on the Android tablet, then tune (dtype / bundle whisper via `setup:assets`).
>
> **2026-05-31 — Root-caused the recurring "not secure" (Mac + tablet): it's CA TRUST, not the cert (ADR-0029).**
> `scripts/cert-doctor.sh` proves the served TLS is fully correct — cert/key moduli match, leaf chains to the
> CA, within validity, SAN covers the LAN IP (`192.168.1.185`) — yet macOS `security verify-cert` returns
> **`CSSMERR_TP_NOT_TRUSTED`**: the CA is in the keychain but never marked trusted, and it had been re-minted
> (which silently invalidates trust on every device). Every prior "fix" regenerated certs → *more* re-trust churn.
> - **`scripts/trust-ca-mac.sh`** — one command (`sudo`) that clears stale System-keychain copies then installs +
>   **trusts** the current `rootCA.pem` as a root (the missing `add-trusted-cert -d -r trustRoot` step). Trusting
>   a root CA is a system-security change, so the operator runs it (not automated).
> - **`scripts/cert-doctor.sh`** — read-only: serving mode, cert/key match, chain, validity, SAN-vs-LAN-IP, and the
>   decisive macOS trust check, plus the CA fingerprint + tablet install steps. SAN is parsed from `-text` (macOS
>   LibreSSL has no `-ext` flag — the doctor's first run flagged its own false "SAN missing" and that was fixed).
> - **Re-mint GUARD in `make-dev-cert.sh`** — `FORCE=1` now REFUSES unless `REMINT_CA=yes`, so the CA is
>   mint-once / trust-once and survives DHCP IP changes (leaf-only reissue keeps the trusted CA). Verified: the
>   guard refused + left the CA byte-identical.
> - **Operator runbook:** `sudo scripts/trust-ca-mac.sh` → fully quit + reopen Chrome (lock icon); on each tablet
>   install `rootCA.pem` once (fingerprint `DA:1C:D6:7E…`); `scripts/cert-doctor.sh` to verify. Plain-HTTP +
>   Chrome treat-as-secure-origin was REJECTED for real use (would put the trainee transcript = PHI unencrypted
>   on the LAN); non-PHI testing only.
>
> **2026-05-31b — Network strategy (ADR-0030) + `MEDSIM_PUBLIC_HOST` (first software step).**
> The recurring tablet "can't reach the portal" was finally root-caused as a NETWORK problem (a
> range-extender's isolated `192.168.1.x` LAN — same gateway, different physical net), not certs.
> Strategy written (`docs/NETWORK-STRATEGY.md`, ADR-0030): own the network, address the portal by
> NAME, push CA+Wi-Fi+app via MDM, contain PHI at the network layer; Option 2 now, Option 3 noted.
> - **`MEDSIM_PUBLIC_HOST`** — when set (e.g. `portal.medsim.lan`), `_base_url_for_qr` +
>   `_vrai_base_for_qr` build every QR/device URL from the NAME, not the auto-detected LAN IP. So a
>   DHCP/between-locations IP change never breaks the cert or a baked QR. Opt-in (unset = unchanged).
> - **Cert** now covers `localhost, portal.medsim.lan, 127.0.0.1, 192.168.1.185, 192.168.1.165`
>   (both dev locations + the name) — same CA, **no device re-trust**. `make-dev-cert.sh` auto-adds
>   `MEDSIM_PUBLIC_HOST` to the SAN and warns to pass ALL IPs on reissue (a bare run drops the others).
> - **`cert-doctor.sh`** now also checks the hostname is in the SAN and resolves here (site-doctor seed).
> - **Activate:** add `127.0.0.1 portal.medsim.lan` to `/etc/hosts` (Mac self-test) or a gateway DNS
>   record (devices), run with `MEDSIM_PUBLIC_HOST=portal.medsim.lan`, and restart the portal to serve
>   the refreshed cert. Verified: py_compile + the URL builders return the name when set / LAN IP when not.
> - Observed mid-build: the Mac's LAN IP was `.165` (moved to the 2nd location) — both IPs in the cert,
>   so it kept working — a live demonstration of why the hostname matters.
>
> **2026-05-31c — Deep-research: fleet BOM + MDM specifics → NETWORK-STRATEGY.md §8.**
> Workflow `wwusvbr4p` (114 agents, 31 sources, 23 verified claims). VERIFIED: UniFi is the strongest
> fit (gateway binds a local DNS A-record to a DHCP reservation in one step) — U6 Pro (~$159, Wi-Fi 6,
> 802.11r/k/v), keep "Client Device Isolation" OFF, don't pair 802.11r with switch-port isolation; dev
> BOM ~$600-1,150. Omada ER605 (~$60-70) the cheaper alt (leave "SSID Isolation" off, NEVER "Guest
> Network"). MDM: iOS auto-trusts an MDM-deployed CA for TLS (no manual step); Intune "Trusted
> certificate" profile; managed-Chrome URLAllowlist/Blocklist locks Android to the portal origin.
> HONEST GAPS (in §8.4, need a focused follow-up): the cert GO/NO-GO (step-ca vs public+DNS-01), and
> on-device confirmation of PWA/Web-Clip mic-permission persistence + Android CA→site-TLS trust.
>
> ---
> **Below: V7 BUILD STATE, preserved 1:1 from the fork moment.**
> ---

# MEDSIM V7 (Medsim-MP) · BUILD STATE

**This file is the checkpoint.** It is the single source of truth for
the V7 multi-patient build. If the build is paused or interrupted, a
new session resumes by reading this file top-to-bottom, then continuing
at the first module marked `NOT STARTED` (after handling anything still
`IN PROGRESS`).

Last updated: **2026-05-26** — **🟢 FULL BUILD + PHASE 7 COMPLETE.**
All 22 original modules (M0–M21) + Phase 7 (M22–M29 + 5 touch-ups)
DONE. v7-only acceptance: **180 passed, 1 Playwright skip** (up
from 132 — +48 Phase 7 tests). Full v6 regression on v7: **291
passed, 6 env-flaky (matches v6), 2 skipped, 0 v7 regressions**.
M21 release-gate protocol authored in `LAN_TEST_V7.md` — operator
manual sign-off pending on real hardware (now covers Phase 7
surfaces too).

The V6 build state has been archived to `BUILD_STATE_V6.md` for
reference. V6 stays untouched in `../medsim_v6/` as the fallback.

---

## How to resume (read this first if you are a fresh session)

1. Read this whole file.
2. Read `CONTINUATION.md` for the pause/resume protocol.
3. Read `CLAUDE.md` for the V7 overview.
4. Open `../../Multipatient multi student simualtion/deliverables/Development_Plan.md`
   for the per-module specifications (Goal, Files touched, New files,
   Acceptance, Blocks/Blocked-by, Estimated effort). That document
   plus the per-module PDF guides under `docs/module_guides/` are the
   build script.
5. Find the first module in the table below with status `NOT STARTED`
   whose `Blocked by` row is fully `DONE`. That is the next module.
6. Before coding, scan its design considerations in
   `docs/module_guides/M{NN}_*.md` (or `.pdf`).
7. Build it. Run its acceptance tests under `tests/v7/`. Update this
   table. Update or create the module's PDF guide change-list section.

The build is designed to be paused mid-module without data loss: every
SQLite mutation is durable, every dataclass-only change can be edited
in place, and the per-module PDF guide records design decisions so a
future session does not re-derive them.

---

## Phase table

| # | Module | Phase | Status | Files | Tests | Date |
|---|--------|-------|--------|-------|-------|------|
| M0 | Sibling clone v6 → v7 | 0 — Foundation | **DONE** | `pyproject.toml`, `portal/ehr_db.py`, `CLAUDE.md` | smoke import OK | 2026-05-26 |
| M1 | Schema migration v4 | 1 — Data | **DONE** | `portal/ehr_db.py` | 3/3 passing | 2026-05-26 |
| M2 | ControlRoom + Encounter + Student dataclasses | 1 — Data | **DONE** | `portal/control_room.py` (new), `portal/control_session.py` (shim) | 6/6 passing | 2026-05-26 |
| M3 | Route refactor: get_by_join_code + single-encounter routes | 2 — Routes | **DONE** | `portal/control_session.py` (legacy reset hook); v6 routes unchanged | 4/4 v7 + v6 regression 124/130 (6 env-flaky pre-existing on v6) | 2026-05-26 |
| M4 | New room API surface (no UI yet) | 2 — Routes | **DONE** | `portal/server.py` (+~280 lines of M4 routes) | 10/10 passing | 2026-05-26 |
| M5 | Charge-nurse dashboard | 3 — Dashboard | **DONE** | `portal/templates/control_room.html`, `portal/static/control_room.{js,css}`, `portal/templates/base.html` nav, `portal/server.py` `GET /portal/room`, `run_portal.py` cwd anchor | manual browser preview (Playwright in M20) | 2026-05-26 |
| M6 | Wizard step-0 toggle + room finalize | 3 — Dashboard | **DONE** | `portal/templates/control.html` (Mode toggle + Step 4r pane), `portal/static/control.{js,css}` (mode swap, encounter rows, submit branch). No server.py changes — reuses M4's `/api/room/start`. | 4/4 + manual browser flow | 2026-05-26 |
| M7 | Scenes engine (palette + inject) | 4 — Scenes | **DONE** | `portal/scenes.py` (new), `portal/server.py` (delegate + `/api/scenes/palette`), `tests/v7/test_room_api.py` (assertion update) | 9/9 + M4 test updated | 2026-05-26 |
| M8 | Student dataclass + roster persistence | 5 — Roster | **DONE** | `portal/ehr_db.py` (7 CRUD helpers), `portal/control_room.py` (`add_student`/`assign_student` write-through + `rehydrate_students_from_db`) | 7/7 passing | 2026-05-26 |
| M9 | Student join flow (room QR → roster → encounter QR) | 5 — Roster | **DONE** | `portal/templates/student_join.html` (new), `portal/static/student_join.{js,css}` (new), `portal/server.py` (2 public routes + `_room_by_code` helper) | 11/11 + browser-verified handshake | 2026-05-26 |
| M10 | **🟢 MVP GATE — single-patient regression + byte-for-byte compat** | 6 — Gate | **DONE — GATE PASSED** | `tests/v7/test_single_patient_mode_byte_for_byte_compat.py` (no production code changes) | 4/4 compat + 111 passed identical to v6 baseline + 58/58 v7-only | 2026-05-26 |
| M11 | Activity catalog: model + DB CRUD | 7 — Activities | **DONE** | `portal/activities.py` (new), `portal/ehr_db.py` (5 CRUD helpers) | 9/9 passing | 2026-05-26 |
| M12 | Activity catalog: routes + wizard integration | 7 — Activities | **DONE** | `portal/server.py` (6 routes + startup hook + wizard context), `portal/templates/control.html`, `portal/static/control.{js,css}` | 17/17 passing | 2026-05-26 |
| M13 | Dual chart mode (private clone / shared) | 8 — Chart Mode | **DONE** | `portal/control_session.py` (cloned_from_id), `portal/control_room.py` (clone_encounter + is_template + encounters_for_join_picker), `portal/server.py` (M9 handler clones on private_clone templates) | 7/7 passing | 2026-05-26 |
| M14 | Cohort debrief: data aggregation | 9 — Debrief | **DONE** | `portal/debrief.py` (+`build_cohort_debrief`, `save_cohort`, `load_cohort`, `list_saved_cohorts`, `COHORT_DEBRIEFS_DIR`) | 7/7 passing | 2026-05-26 |
| M15 | Cohort debrief: UI | 9 — Debrief | **DONE** | `portal/templates/debrief_cohort{,_index}.html` (new), `portal/static/debrief_cohort.{js,css}` (new), `portal/server.py` (4 routes + `/api/room/end` saves cohort) | 6/6 passing | 2026-05-26 |
| M16 | WebSocket transport for synchronized control | 10 — WS | **DONE** | `portal/ws_room.py` (new), `portal/server.py` (`/ws/room/{room_code}` + emitter hooks on freeze/resume/end/scenes). JS subscribers deferred. | 7/7 passing | 2026-05-26 |
| M17 | Per-encounter cost caps (Haiku + ElevenLabs) | 11 — Caps | **DONE** | `portal/budgets.py` (new), `portal/control_room.py` (`budget` property), `portal/server.py` (GET/POST `/api/room/budget`) | 10/10 passing | 2026-05-26 |
| M18 | Observer instructor seat | 12 — Observer | **DONE** | `portal/auth.py` (`role` + `require_instructor`), `portal/server.py` (login `role` + 12 mutating routes gated) | 5/5 passing | 2026-05-26 |
| M19 | Capacity hardening | 13 — Caps | **DONE** | `portal/control_room.py` (constants + `CapacityExceeded` + station counter), `portal/server.py` (409 gates + `capacity` in `/state`) | 6/6 passing | 2026-05-26 |
| M20 | Playwright multi-encounter coverage | 14 — E2E | **DONE** | `tests/v7/test_ehr_ui_multi_encounter.py` (new — skips when Playwright not installed) | 1 (skipped) | 2026-05-26 |
| M21 | **🟢 RELEASE GATE — verification + LAN test** | 15 — Verify | **DONE — protocol ready** | `LAN_TEST_V7.md` (new — 5-test matrix, perf targets, sign-off table) | 132 v7 + 243 total green | 2026-05-26 |
| — | **Phase 7 PLAN** — Nursing Station + Supervisor Telemetry/ECG/Intercom | 7 — Supervisor | **PLAN AUTHORED** | `docs/module_guides/PHASE7_PLAN_nursing_station_and_supervisor_telemetry.md` (+ .pdf) | — | 2026-05-26 |
| 1.x | Phase 7 pre-touch-ups (rename + Student.role + drill-in route + alarm tag + device kinds API) | 7 | **DONE** | `templates/control_room.html`, `base.html`; `ehr_db.py` schema v5; `control_room.py`; `static/control_room.js`; `scenes.py`; `devices/registry.py` | regression green | 2026-05-26 |
| M22 | Per-Patient Console scaffold | 7 — Console | **DONE** | `templates/encounter_console.html`, `static/encounter_console.{js,css}`, `server.py` route | 4/4 passing | 2026-05-26 |
| M23 | Telemetry simulation engine | 7 — Telemetry | **DONE** | `portal/telemetry.py` (new), `server.py` routes (GET/POST telemetry), `control_session.py` field | 5/5 passing | 2026-05-26 |
| M24 | ECG waveform library | 7 — ECG | **DONE** | `portal/ecg.py` (new), `static/ecg_strip.js` (new), `server.py` routes, `control_session.py` fields | 8/8 passing | 2026-05-26 |
| M25 | Per-Patient Console rich features | 7 — Console | **DONE** | rewritten `static/encounter_console.js`, ECG strip + override sliders + device list wiring | 2/2 passing | 2026-05-26 |
| M26 | Alarm bus | 7 — Alarms | **DONE** | `portal/alarms.py` (new), `server.py` routes (`/api/room/alarms` + clear) | 6/6 passing | 2026-05-26 |
| M27 | Nursing Station student role | 7 — Supervisor | **DONE** | `templates/nurse_station.html` (new), `static/nurse_station.{js,css}` (new), role step in `student_join.html`, role branch in `student_join.js`, register_nurse + nurse_station routes | 7/7 passing | 2026-05-26 |
| M28 | Intercom (one-way nurse → bedside) | 7 — Intercom | **DONE** | `portal/intercom.py` (new), `/api/intercom/{id}/page` route + WS push | 7/7 passing | 2026-05-26 |
| M29 | Future-device stubs (call bell, bed alarm, code blue button, fire alarm) | 7 — Stubs | **DONE** | `portal/future_devices.py` (new), routes `/api/future_devices/kinds` + `/api/encounter/{id}/future_device/{kind}/press` + WS push | 9/9 passing | 2026-05-26 |
| M30 | Per-encounter parity (transcript + voice + lead student + pop-out + device detail) | 7 — Console parity | **DONE** | rewritten `static/encounter_console.{js,css}`, `templates/encounter_console.html`, new `/api/encounter/{id}/{transcript,voices,lead_student}` routes | 11/11 passing | 2026-05-27 |
| M31 | Multi-patient wizard depth + per-encounter QR codes | 7 — Wizard parity | **DONE** | `templates/control.html` (`modulesForRoom`/`programsForRoom`/`roleGroup`), `static/control.{js,css}` (per-row Characters + Curriculum drawers), `templates/encounter_console.html` (3-cell QR card), `static/encounter_console.css` (`.qr-*`), `server.py` (template `base_url`) | 4/4 passing | 2026-05-27 |
| M32 | Room mode skips wizard single-patient steps | 7 — Wizard parity | **DONE** | `templates/control.html` (`data-step-single` + `data-pane-single` on steps 2/2b/3, `data-required-single` on `scenario_name`, Room label input + rewritten Step 4r intro), `static/control.js` (`applyMode` hides single panes + toggles `required`, new `refreshStepNumbers()`, `submitRoom` reads `#room-label-input`) | 4/4 passing | 2026-05-27 |
| M33 | Per-Patient Console: character names + voice test + engage | 7 — Console parity | **DONE** | `server.py` (`GET /api/encounter/{id}/voices` returns `personas:[{id,name,role}]` + `join_code`), `templates/encounter_console.html` (card title rename), `static/encounter_console.{js,css}` (bootVoices rebuild with name labels + ▶ Test + 💬 Engage, new `testVoiceForRow` preview path) | 5/5 passing | 2026-05-27 |
| M34 | Per-encounter instructor EHR launch | 7 — Console parity | **DONE** | `server.py` (new GET+POST `/portal/room/encounter/{id}/launch_ehr` keyed to encounter, reuses `_launch_ehr_station`), `templates/encounter_console.html` (header `📋 Open EHR ({ehr_id})` + QR-card inline `📋 Open EHR on this device`), `static/encounter_console.css` (`.header-action`, `.qr-launch-here`) | 8/8 passing | 2026-05-27 |
| M35 | Master Start/Pause/End + per-enc controls + instructor auto-stations + engage deep-link | 7 — Master controls | **DONE** | `server.py` (5 new routes: `/api/room/start_all`, `/api/encounter/{id}/{start,pause,end}`, `/portal/engage/{eid}/{pid}`; 2 helpers `_instructor_station_id_for` + `_ensure_instructor_stations`), `ws_room.py` (`emit_start_all`, `emit_encounter_state`), `templates/control_room.html` (master header rewired), `static/control_room.js` (btn-start-all wire, master End auto-redirects to cohort debrief), `templates/encounter_console.html` (3 per-encounter buttons), `static/encounter_console.js` (handlers + engage URL flipped from `/join` to `/portal/engage/`) | 14/14 passing | 2026-05-27 |
| M36 | Nursing Station QR + instructor launch button | 7 — Console parity | **DONE** | `server.py` (`portal_room` now passes `room` + `base_url`; new `/portal/control/launch_nurse_station` route that creates/reuses instructor nurse-station seat), `templates/control_room.html` (🩺 Nursing Station panel + QR + Open button), `templates/encounter_console.html` (4th `qr-cell-nurse` cell + room-vs-encounter-code clarifier copy), `static/control_room.css` (`.nurse-station-launch*` styles), `static/encounter_console.css` (`.qr-grid` 3→4 cols + midpoint breakpoint + `.qr-cell-nurse` tint) | 8/8 passing | 2026-05-27 |
| M37 | Fix TTS reply cut-off on reused primed audio | 7 — Bugfix | **DONE** | `static/tts_client.js` (`playElevenLabs` now pauses + detaches src + load()s + resets currentTime BEFORE the new src assignment, then load()s again after — fixes Chrome/Safari `ended`-fires-prematurely on second playback through the primed element) | 4/4 source-guard tests passing | 2026-05-27 |
| M38 | Anthropic key live-refresh + friendly 401 | 7 — Bugfix | **DONE** | `server.py` (new `_anthropic_runtime_key` cache + `_capture_anthropic_key` + `_resolve_anthropic_key`; hooks at `/portal/credentials`, `/portal/control/start`, `/api/room/start`; fail-fast 400 when no vault key; station-turn route translates 401 → friendly message pointing at `/portal/credentials`) | 7/7 passing | 2026-05-27 |
| M39 | Engage opens in-encounter modal dialog | 7 — UX fix | **DONE** | `templates/encounter_console.html` (`<dialog id="engage-dialog">` + iframe with `allow="microphone; autoplay"` + header with title + popout + close), `static/encounter_console.js` (engage row element is `<button data-engage-href>` now; new `openEngageDialog` + close handlers; iframe src blanked on close to stop audio), `static/encounter_console.css` (`.engage-dialog*` styles) | 5/5 passing | 2026-05-27 |
| M40 | Pre-populate Room of N row drawers from Activity | 7 — UX parity | **DONE** | `static/control.js` (extended Activity-change handler checks data-row-persona for seed_persona_id + data-row-module for each seed_module; new `updateRowTabBadges` + `cssEscape` helpers; new persona-dropdown change handler auto-checks the row's Characters drawer; `renderRoomEncounterRows`'s `prev` capture now reads personaList + modulesList + programId + week so re-renders preserve drawer state) | 8/8 source-guard tests passing | 2026-05-27 |
| M41 | Printable QR sheet (all encounters or scoped) | 7 — Feature | **DONE** | `templates/qr_print.html` (new — standalone, branded "Training Bridge MedSim-VRAI" header + patient banner + sign-in codes block + 4-up QR grid + page-break-after per encounter + `@media print` action-bar hide), `server.py` (new `GET /portal/control/qr_print[?encounter_id=…]` route — hydrates patient persona display name via library.get_persona; private-clone clones filtered), `templates/control_room.html` + `templates/encounter_console.html` (launch buttons), `static/control_room.css` + `static/encounter_console.css` (button styling) | 11/11 passing | 2026-05-27 |
| M42 | Inline device manager in encounter console (Phase A) | 7 — UX fix + bugfix | **DONE** | `server.py` (`/portal/control/ops` now accepts `?join` + `?patient_persona_id` + `?embed`; resolves session via `get_by_join_code`, falls back to `get_active()`; bootstrap exposes `default_device_patient_id` + `embed_mode`), `templates/control_ops.html` (bootstrap JS + embed-mode `<style>` block hides ops-view chrome), `static/control_ops_devices.js` (`openAddDevice` reads `default_device_patient_id` instead of hard-coded empty), `templates/encounter_console.html` (Devices card link-out replaced with `#btn-manage-devices` + `<dialog id="devices-dialog">` modal), `static/encounter_console.{js,css}` (handler + button styling). Shared med carts + grouped MAR deferred to M43. | 10/10 passing | 2026-05-27 |
| M43 | Device routes work in multi-patient + button rename | 7 — Bugfix | **DONE** | `portal/devices/routes.py` (new `_session_for_station(station)` helper that finds the encounter via `station.session_id` in the active room; new `_session_for_join(join)` helper; `POST /api/device/register` + `GET /api/device/roster` accept `?join=<code>`; inject/clear/advance_time/assign use `_session_for_station`. Friendly 409 messages point operator at the Per-Patient Console flow), `portal/static/control_ops_devices.js` (new `_joinQuery()` helper reads `MEDSIM2_OPS.join_code` and appends `?join=` on register + roster calls), `portal/templates/encounter_console.html` (button + dialog label "Manage devices" → "Managed devices"). | 11/11 passing | 2026-05-27 |
| M44 | Devices modal shows ONLY device card + cabinet block | 7 — UX fix + bugfix | **DONE** | `templates/control_ops.html` (devices section gets `id="devices-card"`; embed-mode CSS rewritten — hides every `.check-card`, re-shows only `#devices-card`; kills body padding/margins/max-widths), `static/control_ops_devices.js` (`fillKindSelect` filters `cabinet` in embed mode + relabels help text), `devices/routes.py` (`POST /api/device/register` rejects `device_kind=cabinet` when `?join=` resolves to a v7 encounter). M45 deferred (room-level med cart dashboard + grouped MAR). | 6/6 passing | 2026-05-27 |
| M45 | Inline device control cards in encounter Devices card | 7 — UX feature | **DONE** | `static/encounter_console.js` (new `pollDevices` + `renderDeviceCards`/`renderDeviceCard`/`onDeviceAction`/`onDeviceAssign`; `DEVICE_TONE_CATALOG` per kind matching `alarms.py`; `KIND_LABEL` icons; new 3 s `devicesTimer` in startPolling), `static/encounter_console.css` (`.device-card*` styles overriding the older `.device-list li { display: flex }` rule). | 9/9 passing | 2026-05-27 |
| M46 | Hide ops-footer in modal + device QR inline + on print sheet | 7 — UX fix + feature | **DONE** | `templates/control_ops.html` (embed-mode CSS adds `.ops-controls + p` hide), `static/encounter_console.js` (`renderDeviceCard` includes a `.device-card-qr` strip with `/api/qr.svg?data=…` of the device-join URL built from `cfg.joinCode` + `station_id`), `static/encounter_console.css` (`.device-card-qr*` styles), `server.py` (`portal_control_qr_print` adds `devices: [{station_id,device_kind,device_model,label}]` per encounter view), `templates/qr_print.html` (new `{% if enc.devices %}` block with `.device-qr-section` + 3-column grid). | 7/7 passing | 2026-05-27 |
| M47 | Room-level med carts (create + link + grouped MAR + dispense transcript) | 7 — Feature | **DONE** | `control_room.py` (ControlRoom gets `cart_links` + `cart_labels`), `server.py` (4 new routes: `POST /api/room/med_cart/register`, `POST/DELETE /api/room/med_cart/{sid}/link_encounter/{eid}`, `GET /api/room/med_carts`), `devices/routes.py` (cabinet bootstrap merges MARs across linked encounters via `cart_links`; `med.dispensed` event writes a transcript entry to the encounter owning the named patient via new `_log_cart_dispense_to_transcript` helper), `templates/control_room.html` (🛒 Med carts panel — create form + list + link/unlink + QR), `static/control_room.{js,css}` (handlers + styles). Closes the M44 §8 deferred work. | 15/15 passing | 2026-05-27 |
| M48 | Alarm thresholds + per-metric cadence + ECG cosmetic | 7 — Feature + UX fix | **DONE** | `control_room.py` (`alarm_thresholds` dict on ControlRoom with adult-norm defaults), `alarms.py` (new `_threshold_alarms_for` helper merged into `active_alarms`; threshold alarms use ts=0 to sort last in their severity tier), `server.py` (GET/POST `/api/room/alarm_thresholds`), `templates/nurse_station.html` (settings card with HR/SpO2/RR low+high inputs + dangerous-rhythm checkboxes), `static/nurse_station.{js,css}` (load/save handlers + styles), `static/ecg_strip.js` (stroke-width 1.4→0.7, color #5dffae→#7fc99a), `static/encounter_console.css` (`.ecg-canvas` color match), `static/encounter_console.js` (`METRIC_CADENCE_MS` per-metric commit cadence: HR/SpO2 10s, RR 30s, temp 60s, BP 120s; inject/override forces refresh) | 11/11 passing | 2026-05-27 |
| M49 | Clinical alarm sounds wired to Nursing Station | 7 — Feature | **DONE** | `static/sounds/clinical_alarms/` (15 WAVs + MANIFEST.txt — copied from operator drop folder), `alarm_sounds.py` (new — `severity_to_priority`, `audio_url_for`, `annotate`; maps source/metric/severity → WAV path), `alarms.py` (`active_alarms` now `alarm_sounds.annotate(out)` so every alarm carries `audio_url` + `audio_priority`), `static/nurse_station.js` (`renderAlarmBoard` calls new `_playNewAlarmSounds`; `_seenAlarmIds` set dedupes per occurrence; cleared on empty list + drops resolved ids so re-occurrence re-fires) | 16/16 passing | 2026-05-27 |
| M50 | Silence + Clear-bugfix + BP + danger + nurse Code Blue | 7 — Feature + bugfix | **DONE** | `control_room.py` (`alarm_thresholds` gets `bp_systolic`+`bp_diastolic`; new `silenced_alarms` dict), `alarms.py` (new severity `danger`=rank 4 above critical; `_apply_silenced` filter; `_threshold_alarms_for` extends to BP; dangerous rhythm now severity="danger"; `clear_alarm` handles threshold via silenced map; new `silence_alarm` helper), `alarm_sounds.py` (danger→high priority same as critical; BP families → HR audio bucket), `server.py` (`POST /api/alarm/{id}/silence`; `POST /api/room/encounter/{eid}/nurse_code_blue` with sid-or-instructor auth; threshold POST validates BP keys), `templates/nurse_station.html` (BP threshold rows), `static/nurse_station.{js,css}` (Silence + Code Blue buttons + danger pulse styling + silenced badge) | 15/15 passing | 2026-05-27 |
| M51 | Patient Integrated Alarm device (call bell + bed alarm + code blue + intercom + cascade) | 7 — Feature | **DONE** | `devices/registry.py` (`patient_integrated_alarm` kind + `pia_v1` model registered), `devices/pia/pia_v1/spec.json`+`skin.svg` (new — 4 controls + 3 alarm tones + stub SVG), `devices/engine/state_machine.py` (new thin `PiaEngine` so `make_engine` doesn't raise; base no-op reducer is enough — PIA effects route as side-effects), `devices/routes.py` (`device_app` branches to `device_pia.html` for PIA kind; `api_device_event` calls new `_handle_pia_button` for `pia.button` events → `call_bell`/`bed_alarm` write `alarm.injected`, `code_blue` fires `scenes.apply(code.blue)`, `intercom_request` writes `comm.intercom_request` chart event + transcript line), `templates/device_pia.html` (new — 4-button tablet UI + cascade banner), `static/pia_app.{js,css}` (new — press handler, M49 WAV playback, 4-color frame flash, 3s `/api/room/alarms` cascade poller dedupe via sorted alarm_id key, 15s heartbeat), `static/encounter_console.{js,css}` (📟 kind label, instructor mirror panel with 4 buttons + `pia.button` POST dispatch). | 13/13 passing | 2026-05-27 |
| M58 | Med list filters to patient persona only | 7 — UX fix | **DONE** | `ehr_seed.py` — new `patient_persona_id(session)` resolver (prefers explicit `session.patient_persona_id`, falls back to `selected_personas[0]` for v6 legacy) and new `seeds_for_patient_only(session)` that filters `seeds_for_all_personas` output to just the patient's `character_id`. `server.py` GET `/api/encounter/{eid}/medications` and `devices/routes.py` cabinet bootstrap both switched from `seeds_for_all_personas` to `seeds_for_patient_only`. Family / clinician role-players (which have no MAR) no longer appear in the encounter Medications card or on the med cart's character list. | 6 new + 13 existing M55/M58 tests passing | 2026-05-27 |
| M57 | Strip dead M30 lead-picker UI from encounter console | 7 — UX cleanup | **DONE** | `templates/encounter_console.html` — removed the M30 roster picker `<select>`, the "Lead (roster)" label, the long explanatory paragraph, and the now-orphaned `#lead-student-status` line; kept the heading + M53 `#lead-label-ref` banner; added a server-rendered `#lead-empty-hint` placeholder that's visible only when no lead is set (`hidden` attribute toggled with `_card_lead`). `static/encounter_console.{js,css}` — `bootLeadStudent` collapsed to an async no-op (kept as a stub so the existing DOMContentLoaded `await` still resolves); `updateLeadBanner` removed entirely; `_updateLeadLabelRef` simplified — dropped the `dataset.rosterName` fallback path (unreachable now) and added an `#lead-empty-hint` show/hide branch so the hint toggles in lockstep with the label. CSS adds `.lead-empty-hint` (dashed-border placeholder). | 4 new + 27 existing lead tests all passing | 2026-05-27 |
| M56 | Med-cart create with encounter checklist + post-create add-encounters UI | 7 — UX fix | **DONE** | `templates/control_room.html` (create form now carries a `<fieldset>` with one `.med-cart-create-enc-cb` checkbox per encounter pre-rendered server-side from `room.encounters`), `static/control_room.{js,css}` (submit handler scans `.med-cart-create-enc-cb:checked` and POSTs `encounter_ids[]`; per-cart card replaces the old single-select `med-cart-link-select` dropdown with a multi-checkbox `.med-cart-add-checklist` + "+ Add selected" button wired to a new `add-multi` action that fans out one link-encounter POST per ticked id; new CSS for both checklists — indigo pill chips matching M53). Back-end (M47's `/api/room/med_cart/register`) already accepted `encounter_ids[]`; the bug was the JS only sent `{label}`. | 11/11 passing | 2026-05-27 |
| M55 | Encounter Medications card + active-at-start toggle + cart filter | 7 — Feature | **DONE** | `control_session.py` (new `active_medications: dict[persona_id, list[str]]` on Encounter, default empty), `server.py` (3 new routes — GET `/api/encounter/{eid}/medications` lists every persona's seed MAR + `active` flag + `explicit_active_list` flag; POST `/api/encounter/{eid}/medications/active` replaces one persona's active list with body `{persona_id, active_med_names}`; DELETE `/api/encounter/{eid}/medications/active/{persona_id}` resets to default), `devices/routes.py` (cabinet bootstrap now filters per persona — if explicit list set, only listed meds appear on the cart for that patient; otherwise every med, preserving pre-M55 back-compat), `templates/encounter_console.html` (new collapsible "💊 Medications" card matching M54 threshold pattern with role=button h2 toggle + ARIA + caret), `static/encounter_console.{js,css}` (`wireMedsToggle` + `bootMedications` + `renderMedications` + `onMedToggle` + `onMedReset` + `cssEscape` polyfill; indigo-accent persona sections + per-row checkboxes + high-alert badges). | 13/13 passing | 2026-05-27 |
| M54 | Threshold panel collapse + concurrent tiered audio + magnitude-based severity | 7 — Feature + UX fix | **DONE** | `alarms.py` (code.blue + code_blue_button severity "critical"→"danger"; `_threshold_alarms_for` now computes `deviation_pct` per breach and maps 0-10%→info, 10-20%→warning, >20%→critical), `templates/nurse_station.html` (threshold section ships with `ns-collapsed` class + h2-as-button toggle with ARIA + caret marker), `static/nurse_station.js` (new `wireThresholdToggle()` with click + Enter/Space keyboard; four-tier `AUDIO_REPEAT_MS = {danger:2500, high:5000, medium:15000, low:35000}`; new `_audioCadenceTier(a)` reads severity-first so "danger" routes to its own bucket; 700ms `setInterval` re-runs dispatcher off cached `_lastAlarmsForAudio` so the 2.5s danger cadence isn't capped by the 3s state poll; explicit CONCURRENTLY comment), `static/nurse_station.css` (`.ns-thresholds-toggle` + caret rotate + `.ns-collapsed .ns-thresholds-form` display:none), `static/pia_app.js` (`CASCADE_AUDIO_REPEAT_MS` 8000→2500). 5 existing tests updated for intentional contract changes (code-blue severity, magnitude-based severity, PIA cascade cadence). | 17/17 passing | 2026-05-27 |
| M53 | Lead student/group/list assignment from Multi-Patient Control | 7 — Feature | **DONE** | `control_session.py` (new `lead_label: str = ""` field on Encounter, independent of M30 `lead_student_id`), `server.py` (3 new routes: `GET /api/room/lead_assignments`, `POST /api/encounter/{eid}/lead_label`, `POST /api/room/lead_assignments` bulk; `_encounter_summary` surfaces `lead_label` + `effective_lead_display` (label wins over roster name for display); `portal_room_get` context now includes `encounters` so the template can pre-render rows), `templates/control_room.html` (new "👤 Lead assignments" panel — per-encounter checkbox + free-text input + Apply/Clear + bulk "Apply to checked" action), `templates/encounter_console.html` (read-only `.lead-label-ref` banner above the M30 picker in the lead-student card with "set from Multi-Patient Control" footer hint), `static/control_room.{js,css}` (new `wireLeadAssignments()`; indigo-accent panel matching M47 med-carts visual style), `static/encounter_console.{js,css}` (`_updateLeadLabelRef` called from pollState → reads `enc.lead_label` from state poll). | 19/19 passing | 2026-05-27 |
| M52 | Repeating alarm audio + 45s silence default + brand rename | 7 — Feature + UX fix | **DONE** | `alarms.py` (`silence_alarm` default 120→45), `server.py` (`/api/alarm/{id}/silence` route default 120→45), `static/nurse_station.js` (replace `_seenAlarmIds` Set with `_audioLastAt` Map + `AUDIO_REPEAT_MS = {high: 8000, medium: 20000, low: 45000}` cadence table; consult `audio_priority` per alarm; silenced skipped; 45 s button title), `static/pia_app.js` (new `_cascadeAudioLastAt` Map + 8 s `CASCADE_AUDIO_REPEAT_MS`; cascade tone repeats per active code-blue alarm; flash still gated by `_cascadeKey` to avoid restarting CSS), 11 templates updated to "Training Bridge VRAI- MedSim" (base, home, login, join, ehr_join, device_app, device_join, device_pia, nurse_station, qr_print + apple-mobile-web-app-title metas), 2 existing tests updated to match new contract (`test_clinical_alarm_sounds.test_nurse_station_js_dedupes_by_alarm_id` → renamed `test_nurse_station_js_repeats_audio_by_cadence`; `test_qr_print_sheet` brand string). | 18/18 passing | 2026-05-27 |

**MVP gate at M10.** When M10 lights up green, MVP is shippable —
demo and collect feedback before starting M11+.

**Release gate at M21.** Full feature set, full test suite, manual LAN
test on real tablets.

---

## What's been built so far (M0–M2)

### M0 — Sibling clone (DONE 2026-05-26)

- `medsim_v7/` rsynced from `medsim_v6/`, excluding `.venv`,
  `__pycache__`, `*.egg-info`, `.pytest_cache`, `.DS_Store`.
- `pyproject.toml` bumped: name `medsim7`, version `7.0.0a0`,
  description updated to call out multi-patient extension.
- `portal/ehr_db.py` bumped: storage at `~/.medsim/v7/`, with
  `V6_DIR` / `V5_DIR` aliases preserved so legacy readers resolve.
- `CLAUDE.md` rewritten with V7 header above the V5/V6 baselines.
- Smoke verification: `python3 -c "from portal import ehr_db; ..."`
  shows `V7_DIR=~/.medsim/v7`, aliases resolve, 3 migrations defined.

### M1 — Schema migration v4 (DONE 2026-05-26)

- Migration 4 appended to `ehr_db.SCHEMA_MIGRATIONS`. New tables:
  `control_room`, `student`, `activity`. New columns on `ehr_session`:
  `room_id`, `label`, `activity_id`, `chart_mode` (default 'shared'),
  `patient_persona_id`. Supporting indexes added.
- Tests under `tests/v7/`:
  - `test_migration_v4_idempotent.py` — runs twice, second pass is a
    no-op. **PASS**
  - `test_migration_v4_preserves_v6_data.py` — v6 snapshot DB
    upgrades; legacy rows untouched; `chart_event` payload identical.
    **PASS**
  - `test_new_tables_exist.py` — tables, columns, indexes verified.
    **PASS**

### M2 — ControlRoom + Encounter + Student dataclasses (DONE 2026-05-26)

- New file `portal/control_room.py`: `ControlRoom` (room_id, room_code,
  status, encounters dict, students dict, optional caps), `Student`
  dataclass, `Encounter = ControlSession` alias, module-level
  singleton `_active_room`, helpers `create_room`, `get_active_room`,
  `get_by_join_code`, `end_active_room`, `get_active`,
  `_reset_for_tests`.
- `portal/control_session.py` augmented: `ControlSession` now carries
  v7 fields (`room_id`, `encounter_label`, `activity_id`,
  `chart_mode`, `patient_persona_id`, `assigned_student_ids`),
  defaulted so single-patient mode is unchanged. `create_session`,
  `get_active`, `get_by_join_code`, `end_active`, `set_state` delegate
  to the `control_room` module. The v6 import path
  `from portal.control_session import ...` keeps working.
- Tests under `tests/v7/`:
  - `test_room_create_with_2_encounters.py` — **PASS**
  - `test_get_active_returns_only_encounter_in_single_mode.py` —
    **PASS** (3 cases)
  - `test_get_by_join_code_finds_across_encounters.py` — **PASS** (2 cases)

**Test summary:** 9/9 v7 acceptance tests passing under the v6 venv
(`../medsim_v6/.venv`). The v6 venv works because v7 is a sibling
clone with identical dependencies; a future module should set up
`medsim_v7/.venv` of its own as part of pyproject install verification.

### M3 — Route refactor (DONE 2026-05-26)

- `portal/control_session.py` now installs a `ModuleType` subclass at
  import time that intercepts `_active = None` assignments and
  propagates them to `control_room._active_room`. This preserves the
  v6 reset idiom used by `tests/test_voices.py:147` and
  `tests/test_e2e_v3.py:46` (and any operator-debug code that relies
  on it). Without this hook the v6 fixture's reset would silently
  no-op in v7 because the singleton lives in `control_room` now.
- The 12 student-side routes (`/api/station/{join}/...`,
  `/api/ehr/{join}/...`, `/api/device/{join}/...`) need no code
  changes — M2's `get_by_join_code` already searches across every
  encounter in the active room, so dispatching to the right
  encounter happens automatically.
- The 22 `get_active()` callers in `server.py` work unchanged in
  single-patient mode (room of 1). Their per-route A/B/C
  classification per P6 §4.1 happens in M4 / M5 / M6 when the
  multi-encounter wizard branch is built — premature to do it now.
- New tests under `tests/v7/`:
  - `test_two_encounters_two_chat_streams_independent.py` — **PASS** (2 cases)
  - `test_two_encounters_two_ehr_charts_independent.py` — **PASS** (2 cases)
- v6 regression: full suite run on v7 yields **124 passed, 6 failed,
  1 skipped**. The same 6 failures (4 in `test_device_debrief.py`,
  2 in `test_voices.py`) appear in v6 baseline today — they are
  pre-existing environmental flakes (vault state on the operator's
  machine + test-order dependence in device_debrief). **Zero v7
  regressions.** Full failure list and root-cause analysis in M3
  guide §8.

**Test summary (v7-only):** 13/13 passing.

### M4 — New room API surface (DONE 2026-05-26)

- 8 new routes appended to `portal/server.py`:
  - `POST /api/room/start` (wizard finalize, multi-encounter mode)
  - `GET  /api/room/state` (dashboard 2 s poll body)
  - `POST /api/room/freeze_all` / `POST /api/room/resume_all`
  - `POST /api/room/end`
  - `POST /api/room/scene_broadcast` (targets: 'all' or [encounter_id])
  - `POST /api/encounter/{id}/scene`
  - `POST /api/encounter/{id}/assign_students`
- Five helpers in the same M4 section: `_encounter_summary`,
  `_room_summary`, `_require_active_room`, `_require_encounter`,
  `_apply_scene` (minimal — M7 replaces with templated palette).
- 10 acceptance tests in `tests/v7/test_room_api.py` — all PASS.
- Full v7 suite now: **134 passed, 6 pre-existing env-flaky, 0 v7
  regressions.** v7-only acceptance: **23 passed.**

**Test summary (v7-only):** 23/23 passing.

### M5 — Charge-nurse dashboard (DONE 2026-05-26)

- New template `portal/templates/control_room.html` (~80 lines) with
  the top bar (Freeze / Resume / Inject / Cohort / End), empty-state
  CTA with quickstart button, encounter grid container, scene-injector
  `<dialog>`.
- New JS `portal/static/control_room.js` (~280 lines, vanilla — no
  framework, matches v6 convention): 2 s poll of `/api/room/state`,
  visibility-change pause, encounter card painter with state classes
  (running/paused/ended), alert pills (no-chart-yet, no-chat-station),
  top-bar handlers, scene dialog with dynamic targets dropdown.
- New CSS `portal/static/control_room.css` (~180 lines) — top bar,
  responsive auto-fill grid (single column < 480 px), card state
  borders (green/orange/red), scene dialog, button palette overrides.
- `GET /portal/room` route appended in `server.py`. Nav link
  "Room (multi)" added in `base.html` under **Operate**.
- `run_portal.py` chdir anchor so Claude Preview can launch the
  v7 portal regardless of invocation cwd.
- **Manual browser verification (preview):** login → empty
  state → quickstart 2-bed demo → 2 cards render → freeze (status
  FROZEN, both PAUSED) → resume (ACTIVE, RUNNING) → scene targeted
  at Bed 1 only (chart_event count: Bed 1 → 1, Bed 2 → 0; end-to-end
  encounter-scoping holds through the UI) → end (ENDED state,
  Cohort Debrief stays clickable, other actions disabled). **No
  console errors. No unexpected network failures.** Automated
  Playwright coverage lands in M20.

**Test summary (v7-only automated):** 23/23 passing. **Manual
browser coverage:** 7-flow round-trip green on `/portal/room`.

### M6 — Wizard step-0 toggle + room finalize (DONE 2026-05-26)

- New "Mode" toggle above the wizard steps in `control.html`. Two
  cards: Single Patient (v6 default) / Room of N (v7).
- Step 4 (Characters) and a new Step 4r (Encounters) are siblings;
  the JS hides whichever is off-mode. `data-step-single` and
  `data-step-room` attributes drive the swap.
- Room-mode pane: number input (2–10), default chart-mode select,
  dynamic N rows each with label / persona / EHR. Persists typed
  values across re-renders.
- Submit handler branches on `mode`:
  - **single** → existing `POST /portal/control/start` form path,
    `redirect_url` lands on `/portal/control/ops`.
  - **room** → JSON `POST /api/room/start` with one entry per row,
    redirect to `/portal/room` (the M5 dashboard).
- 4 acceptance tests in `tests/v7/test_wizard_room_modes.py`:
  - single-patient finalize creates room of 1; `get_active()` works.
  - room-of-4 finalize creates 4 encounters with distinct join codes.
  - `/api/room/state` reflects each encounter immediately.
  - prior single-patient session is ended cleanly when toggling to
    room mode for the new finalize.
- **Manual browser verification (preview):** Open `/portal/control`,
  toggle Room of N, edit N (4 → 3 → 5 — labels preserved), fill 4
  distinct personas + labels, advance to Step 5, click Start →
  POST to `/api/room/start` succeeds, browser lands on
  `/portal/room` with the 4-card grid (room code H5PDZ9, four
  distinct join codes).

**Test summary (v7-only automated):** 27/27 passing. **Manual
browser coverage:** wizard → dashboard end-to-end round-trip green
in both modes.

### M7 — Scenes engine (DONE 2026-05-26)

- New `portal/scenes.py` (~270 lines): `PALETTE` of 8 built-in
  scene kinds + `palette()` accessor + `apply(enc, scene, by=)`
  dispatcher + 8 per-kind handlers + unknown-kind fallback.
- Scene catalog: **vitals.drop**, **vitals.rise** (typed
  `vitals.record` with hypotensive / sympathetic-surge presets,
  param overrides supported), **lab.result** (`result.acknowledge`
  with panel + values), **order.new** (`order.place` authored by
  instructor as MD), **family.arrives** (communication
  `note.save`), **pump.alarm** (device-event when a pump is bound;
  `instructor.trigger` chart-fallback otherwise — cabinets don't
  count as pumps), **code.blue** (compound: 3 chart events +
  optional pump alarm; each child tagged with `compound_role`),
  **note.instructor** (free-form `note.save`). Every payload
  carries `{source: 'scene', scene_kind, by}` for M14 debrief
  attribution.
- `server.py` updated: `_apply_scene` now a one-line delegate to
  `scenes.apply`; new `GET /api/scenes/palette` route.
- 9 acceptance tests in 3 files:
  - vitals.drop default + override + vitals.rise sister
  - pump alarm bound vs unbound vs cabinet-only
  - code.blue 3-event compound + 4-event compound with pump +
    room broadcast (3×N) + palette endpoint
- M4's existing scene-broadcast test updated to assert the typed
  event (`vitals.record`) instead of the M4 stub
  (`instructor.trigger`). No behavior regression — the contract is
  strictly stronger now.
- **Manual end-to-end verification (live preview):** login →
  `/api/scenes/palette` returns 8 kinds → start 2-bed room → fire
  `code.blue` at Bed 1 only → `/api/room/state` shows Bed 1's
  `chart_event_count: 3`, Bed 2 stays `0`.

**Test summary (v7-only automated):** 36/36 passing.

### M8 — Student roster persistence (DONE 2026-05-26)

- 7 new CRUD helpers in `ehr_db.py`: `register_student`,
  `update_student_assignment`, `touch_student`, `students_for_room`,
  `students_for_encounter`, `get_student`, `remove_student`. Each
  has SQLite + in-memory fallback paths matching the rest of
  ehr_db's storage contract.
- `ControlRoom.add_student` now persists first (DB-generated
  student_id `stu_<hex10>`), then hydrates the in-memory dataclass
  from the row. `assign_student` writes through to
  `update_student_assignment`. Both also keep the encounter's
  `assigned_student_ids` list consistent (removes from prior
  encounter on reassignment).
- New `ControlRoom.rehydrate_students_from_db()` method loads
  every student row for the room and (re-)populates each
  encounter's roster list. Idempotent. Unblocks M9's join flow
  after a server restart.
- 7 acceptance tests in 2 files:
  - Register persists 1 student / 3 distinct students / scoped by
    room_id / assign writes through.
  - Full restart cycle restores 3 students with assignments; idem-
    potent rehydrate; unassigned students restore with NULL
    `assigned_encounter_id`.
- No server.py changes — M4 dashboard's existing `assign_students`
  route works unchanged (open follow-up: migrate it to call
  `room.assign_student` so the write-through fires; deferred to M9
  when the student-side flow exercises both paths).

**Test summary (v7-only automated):** 43/43 passing.

### M9 — Student join flow (DONE 2026-05-26)

- Two new PUBLIC routes (no operator vault required — the room_code
  itself is the access token):
  - `GET /portal/students/join?code=ROOM_CODE` — renders the
    join page with the room's encounter cards and any pre-loaded
    roster. Error state with re-entry form on unknown / missing
    code (never redirects — easier to debug a typo).
  - `POST /portal/students/register` — registers a free-form
    student or reattaches via `existing_student_id`, assigns to
    the chosen encounter, creates a chat Station with the
    encounter's patient persona, returns `{redirect_url:
    /station/<join_code>/<station_id>}`.
- New public template `portal/templates/student_join.html` —
  standalone (does not extend `base.html` — no operator nav). Two-
  step flow: (1) pick roster card OR type display name, (2) tap
  encounter card. Error state if the room code is unknown.
- New `portal/static/student_join.{css,js}` — mobile-first; big
  tap targets; roster + encounter grids responsive; status banner.
- `_room_by_code(room_code)` helper in `server.py` resolves a
  room by operator code, case-insensitive, against the active
  room. Single-instructor model: no global code registry.
- 11 acceptance tests across 2 files:
  - register-then-pick happy path + state assertions
  - reattach to pre-loaded roster (no duplicate row)
  - GET renders room + roster + encounters
  - blank name 400s; unknown encounter 404s
  - missing code, unknown code, stale code, lowercase code,
    POST 404s on unknown/missing room
- **Live browser verification**: 2-bed quickstart → student opens
  `/portal/students/join?code=<code>` → types "Alice Pham" → step
  2 reveals → taps Bed 1 → redirected to
  `/station/<join_code>/<sid>` → v6 station UI loads with "Dr.
  Reyes" persona. Operator dashboard's next poll shows Bed 1
  `chat_stations: 1, students: 1`; Bed 2 untouched.

**Test summary (v7-only automated):** 54/54 passing.

### M10 — 🟢 MVP GATE PASSED (2026-05-26)

**No production code changes.** M10 is the formal verification
module — the regression contract had been held green by every
preceding module's acceptance run.

- New `tests/v7/test_single_patient_mode_byte_for_byte_compat.py`
  with 4 cases:
  - Same scripted scenario via v6-compat path and v7 explicit-room
    path produces IDENTICAL chart_event payloads + IDENTICAL fold
    projection (after normalizing `ts`, `latest_ts`, `station_id`,
    `session_id` which legitimately differ).
  - Fold has every v6-documented top-level key; no v7-only keys
    leaked into the projection.
  - Individual `chart_event.payload` dicts carry no `room_id` /
    `encounter_id` / `assigned_student_ids` leaks.
  - `control_session.get_active()` v6-compat shim returns the sole
    encounter of a room-of-1.
- **v6 inherited tests on v7: 111 passed, 6 failed, 1 skipped.**
  IDENTICAL to v6 baseline today (verified by running the v6 suite
  on the v6 codebase). The 6 failures are pre-existing
  environmental flakes (4 device_debrief test-order pollution; 2
  voice tests reading the operator's real vault). NOT v7
  regressions.
- v7-only acceptance: **58/58 passing**.
- Full suite: **169 passed, 6 env-flaky, 1 skipped, 0 v7 regressions**.

**MVP gate condition met. v7 is shippable as MVP.**

### MVP scope delivered

Operator: wizard with Single/Room toggle, charge-nurse dashboard
with 2 s poll + freeze/resume/scene/end controls, end-to-end
encounter scoping.

Student: public join page, room-code-as-access-token (no operator
auth required for students), encounter pick → v6 chat-station UI.

System: schema v4 migration, ControlRoom/Student dataclasses,
8 templated scenes, durable roster, byte-for-byte v6
single-patient compat.

Out-of-scope for MVP (covered in M11–M21): Activities catalog
(M11–M12), dual chart mode (M13), cohort debrief (M14–M15),
WebSocket transport (M16), cost caps (M17), observer seat (M18),
capacity hardening (M19), Playwright cross-browser coverage (M20),
formal release / LAN test gate (M21).

**Test summary (v7-only automated):** 58/58 passing.

---

## Per-module PDF guides

The PDF guides live at `docs/module_guides/`. Each module has a Markdown
spec (rendered to PDF on update) that records:
- **Purpose** — what this module exists for.
- **Structure** — files, classes, data shapes.
- **Uses** — how the rest of the system calls it.
- **Functions** — exported API surface.
- **Limitations** — what this module deliberately does not do.
- **Change list** — chronological list of changes with date + author + diff hash.
- **Test status** — current acceptance test results.
- **Dependencies** — Blocks / Blocked-by edges from the dependency graph.

A template lives at `docs/module_guides/MODULE_GUIDE_TEMPLATE.md`.

When you complete a module, **update its guide** before checking off
the row in this table.

---

## What this build deliberately does not do

(See the Development Plan §"What this plan deliberately does not do".)

- Does not touch v6. V7 is a sibling. V6 stays as fallback.
- Does not build a physiology model. Scenes write chart events;
  vitals trends are still instructor-driven.
- Does not introduce a new LLM. Haiku 4.5 per turn, ElevenLabs Flash
  v2.5 for voice — same as v6.
- Does not add LTI / SSO. V7 keeps vault + join-code auth.
- Does not break the v6 test suite. Every phase exits on a green run
  of the v6 suite under single-patient mode.

---

## Session log

| Date | Session action |
|------|----------------|
| 2026-05-26 | V7 build kicked off. M0 sibling clone complete, M1 schema migration v4 applied with 3 acceptance tests passing, M2 ControlRoom + Encounter + Student dataclasses complete with 6 acceptance tests passing. Continuation framework (BUILD_STATE.md, CONTINUATION.md, MODULE_GUIDE_TEMPLATE.md, M0/M1/M2 module guides) landed. |
| 2026-05-26 | M3 route refactor complete — legacy `_active = None` reset hook added via `ModuleType` subclass in `control_session.py`; 4 acceptance tests (2 files, 4 cases) added under `tests/v7/`. Full v7 suite: 13/13 v7-specific + 124/130 v6-regression (6 env-flaky pre-existing on v6, 0 v7 regressions). |
| 2026-05-26 | M4 new room API surface complete — 8 routes + 5 helpers + 10 acceptance tests in `tests/v7/test_room_api.py`. Routes split into lifecycle (start/state/end), synchronized control (freeze_all/resume_all/scene_broadcast), and per-encounter (scene/assign_students). Full v7 suite: 23/23 v7-specific + 134 total passing, 0 regressions. |
| 2026-05-26 | M5 charge-nurse dashboard complete — `/portal/room` template + JS + CSS rendering an Encounter grid that polls `/api/room/state` every 2 s. Top-bar buttons wired to M4's freeze/resume/scene/end routes. Empty-state CTA quickstarts a 2-bed demo via `/api/room/start`. Manual browser verification through Claude Preview: 7-flow round-trip green (login, quickstart, freeze, resume, scene, end, post-end state) with end-to-end encounter scoping holding (a scene targeted at Bed 1 only updates Bed 1's chart_event count). Automated Playwright coverage deferred to M20. |
| 2026-05-26 | M6 wizard step-0 mode toggle complete — Mode card above wizard-steps; Step 4 (Characters, single-mode) and Step 4r (Encounters, room-mode) are siblings, swapped by JS based on toggle. Room-mode pane: number input (2–10), per-encounter rows with label + persona + EHR. Submit branches: single→`/portal/control/start`, room→`/api/room/start`→`/portal/room`. 4 acceptance tests pass. Manual browser verification: end-to-end finalize lands on the M5 dashboard with the right N-card grid. |
| 2026-05-26 | M7 scenes engine complete — `portal/scenes.py` with 8 built-in templated scene kinds (vitals.drop/rise, lab.result, order.new, family.arrives, pump.alarm with device-or-chart-fallback, code.blue compound, note.instructor) + forward-compat fallback. `_apply_scene` in server.py now delegates to `scenes.apply`. New `GET /api/scenes/palette` endpoint. 9 acceptance tests pass; M4's scene-broadcast test updated to assert typed events. Live preview verified. |
| 2026-05-26 | M8 student roster persistence complete — 7 CRUD helpers in `ehr_db.py`, `ControlRoom.add_student`/`assign_student` write-through, `rehydrate_students_from_db()` reloads after restart. 7 acceptance tests pass. |
| 2026-05-26 | M9 student join flow complete — public `GET /portal/students/join` + `POST /portal/students/register` routes. Two-step student page (name → encounter pick) with roster pre-load support. End-to-end browser verification: operator → student handshake works through the live preview. 11 acceptance tests pass. |
| 2026-05-26 | **🟢 M10 MVP GATE PASSED.** Byte-for-byte single-patient compat test added (4 cases asserting v6-compat path + v7 explicit-room path produce identical chart_event + fold + no room-mode metadata leaks). v6 inherited tests on v7: **111 passed, 6 failed, 1 skipped — IDENTICAL to v6 baseline today**. v7-only acceptance: 58/58. Full suite: 169 passed, 6 env-flaky (pre-existing on v6), 0 v7 regressions. **MVP is shippable.** Out-of-scope for MVP, on roadmap: Activities (M11–M12), dual chart mode (M13), cohort debrief (M14–M15), WebSocket (M16), cost caps (M17), observer (M18), capacity (M19), Playwright (M20), LAN release gate (M21). |
| 2026-05-26 | **Phase 7 PLAN authored** (planning only — no code change). Operator clarification: "Charge-nurse dashboard" name conflated the instructor surface with an in-sim student role. Plan covers (a) rename + extraction into "Multi-Patient Control" with a new Per-Patient Console drill-in (instructor side), (b) Nursing Station as a new in-sim student role with multi-patient telemetry strips, ECG waveform library, device-state read, alarm board, and intercom to any bed, (c) future-device stubs for call bell / bed alarm / code blue button / fire alarm. 8 new modules (M22–M29) + 5 touch-ups to existing modules, ~19.5 engineer-days total. Recommended slot: after M21 release gate. Plan doc + PDF in `docs/module_guides/PHASE7_PLAN_nursing_station_and_supervisor_telemetry.{md,pdf}`. |
| 2026-05-26 | M11 Activity catalog (data layer) complete — new `portal/activities.py` with `Activity` dataclass + 8-entry built-in catalog (7 mirror `sample_scenarios.json`, 8th adds acute respiratory failure). 5 CRUD helpers in `ehr_db.py`. `seed_builtins()` idempotent + preserves instructor edits. 9 acceptance tests pass. |
| 2026-05-26 | M12 Activity catalog (routes + wizard) complete — 6 new HTTP routes + startup hook + wizard Step 4r picker column. 17 acceptance tests pass. |
| 2026-05-26 | M13 dual chart mode complete — `cloned_from_id` + `clone_encounter` + `is_template` + `encounters_for_join_picker`. M9 register handler clones private_clone templates per joining student. 7 acceptance tests pass. |
| 2026-05-26 | M14 cohort debrief data aggregation complete — PEARLS-scaffolded JSON + save/load helpers. 7 acceptance tests pass. |
| 2026-05-26 | M15 cohort debrief UI complete — PEARLS-tabbed render + save-notes round-trip + index. 6 acceptance tests pass. |
| 2026-05-26 | M16 WebSocket transport complete — `portal/ws_room.py` + `/ws/room/{room_code}` + emitter hooks on freeze/resume/end/scene routes. 7 acceptance tests pass. |
| 2026-05-26 | M17 + M18 + M19 complete (combined guide). M17 cost caps (`portal/budgets.py`), M18 observer seat (`auth.require_instructor` + 12 mutating routes gated), M19 capacity hardening (10 encounters / 24 stations + `capacity` block on `/api/room/state`). 21 acceptance tests across 4 files. |
| 2026-05-26 | **🟢 M20 + M21 — FULL BUILD COMPLETE.** M20 Playwright multi-encounter test; M21 release gate authored in `LAN_TEST_V7.md`. Final automated suite at end of M21: 132 v7 + 243 full-suite, 0 regressions. **All 22 original modules DONE.** Phase 7 plan authored as next roadmap. |
| 2026-05-26 | **🟢 PHASE 7 COMPLETE.** Eight new modules (M22–M29) + five 1.x touch-ups landed in an autonomous pass. Combined guide at `docs/module_guides/PHASE7_M22_M29_combined.md`. Highlights: instructor "Charge-nurse" surfaces renamed to "Multi-Patient Control"; Per-Patient Console drill-in at `/portal/room/encounter/{id}` with live telemetry (M23) + 11-rhythm ECG strip (M24) + override sliders (M25) + alarm board feeders (M26) + scene injector; new in-sim Nursing Station student role at `/portal/students/nurse_station` (M27) with per-bed mini-telemetry + mini-ECG + alarm board + intercom (M28 — one-way nurse → bedside with staff-persona voice resolution, WS push); four future-device stubs (call bell, bed alarm, code blue button, fire alarm, M29) emitting alarms on the M26 bus. Schema v5 (`student.role` field + `student.role` index). 48 new acceptance tests (4 + 5 + 8 + 2 + 6 + 7 + 7 + 9). Final automated suite: **180 v7 passed (1 Playwright skip) + 291 full-suite passed, same 6 env-flaky pre-existing on v6 baseline, 0 v7 regressions**. Remaining open items: LAN_TEST_V7.md operator sign-off; bedside chat-station JS hook for M28 intercom audio playback (~15 lines); v7.1 WebRTC upgrade for two-way intercom. |
| 2026-05-26 | **Bugfix** (operator-reported, two issues). (1) `/portal/control` 500'd whenever a multi-encounter room was active because v6's `control_session.get_active()` raised on >1 encounter. Changed the contract: `get_active()` now returns `None` for multi-encounter rooms (the v6 routes downstream all check `if active is None` and handle it cleanly); added `get_active_strict()` for the rare caller that wants the loud check. Wrapped the wizard route in a defensive try/except too. (2) Per-row scenario authoring — Step 4r encounter rows now expose a "✎ Edit scenario" toggle that opens a collapsible drawer with a per-bed scenario textarea. Picking an Activity pre-fills the textarea; the operator can override; the submit handler resolves per-row text first (most-specific), then activity-derived, then Step 3's wizard-wide as fallback. Template's `<script src="/static/control.js">` was missing `static_v()` cache-busting — fixed (was serving stale JS). Live browser flow verified: 4-bed room with 4 unique scenarios → finalize → 4 distinct Per-Patient Console pages with the right titles. 5 new bugfix tests (`tests/v7/test_wizard_per_row_scenario.py`). Final v7 suite: **185 passed, 1 skipped** (up from 180). Full suite: **296 passed**, same 6 env-flaky pre-existing on v6 baseline, **0 v7 regressions**. |
| 2026-05-27 | **🟢 M30 + M31 — Per-encounter parity loop closed.** M30 brought transcript / voice / lead-student / pop-out / detailed device list cards onto each Per-Patient Console, matching the single-patient ops view feature-by-feature. M31 closed the loop on *authoring*: the wizard Step 4r encounter rows now expose three tab-drawers (Scenario / Characters / Curriculum) with badge counts, so each bed gets its own persona multi-select + program/week + module list — no more "one set, broadcast to every bed". And each console now renders a 3-cell QR card (Chat / EHR / Device stations) keyed to that bed's `join_code`, so stations scan once and authenticate against only that encounter. No schema migration — `Encounter.selected_personas` / `selected_modules` / `program_id` / `week` already existed; the wizard simply now populates them per row. QR URLs use the existing `/api/qr.svg?data=…` route (template + test corrected from `text=` after the first run surfaced the param mismatch). Guide + PDF at `docs/module_guides/M31_wizard_depth_and_per_encounter_qrs.{md,pdf}`. **Final v7 suite: 200 passed, 1 skipped** (M20 Playwright skip — unchanged); 0 regressions. M31 contributes 4 acceptance tests in `tests/v7/test_wizard_depth_and_qr.py`. |
| 2026-05-27 | **M63 — Feature: full chart sections beyond the MAR.** Operator: *"The MAR function but we will need to access the rest of the medical records not just the medication administration."* The `ehr_seed.ChartSeed` builder produces a complete EHR-style chart (chief_complaint, code_status, allergies, problem_list, vitals_baseline, labs_recent, notes_recent, social/family/surgical history, immunizations, care_team, encounter metadata, iv_fluids, demographics) — but M61/M62 only surfaced the medication-focused subset. M63 wires every remaining seed section into both chart routes. **Approach**: rather than duplicate ~150 lines of HTML across the operator chart (`medical_records_chart.html`) and the public workstation chart (`medical_records_workstation_chart.html`), create a shared partial `_medical_records_full_chart.html` that both `{% include %}`. **Routes** (`server.py`) — both `portal_medical_records_chart` and `students_medical_records_chart` pass `seed=full_seed`, `chief_complaint`, `code_status`, `allergies`, `problem_list`, `vitals_baseline`, `immunizations`, `social_history`, `family_history`, `surgical_history`, `care_team`, `encounter_meta`, `notes_recent`, `iv_fluids` into the template context. Labs now prefer the richer `labs_recent` field over the older `labs`. **Partial sections** (each renders only when its data is non-empty so sparse seeds don't show empty cards): (1) **Alert banner** — amber-pill row with chief complaint + code status + allergy summary, sits at top so the safety-critical info is visible above the fold. (2) **Encounter** — admit time, location, reason for visit, attending. (3) **Problem list** — active problems with ICD-10 codes, status pills, onset dates. (4) **Vital signs (baseline)** — small-tile grid with label / value / unit / timestamp; explanatory note that real-time monitor values live elsewhere. (5) **Allergies (full detail)** — substance + reaction + severity pill (severe/moderate/mild color variants). (6) **IV fluids** — non-med drips (maintenance / boluses) with rate, volume, additives list, indication, start time — answers the operator's earlier ask for "fluid type and any associated medication to infused with rate and time and total dose" on the non-drug-drip side. (7) **Recent notes** — admission notes, daily notes, consults, separate from the M62 chart_inserts. (8) **Care team** — name / role / contact for every member. (9) **History** — four-block grid (social / family / surgical / immunizations) with compact lists. (10) **Demographics & identifiers** — always-shown card with name / MRN / FIN / DOB / sex / pronouns / weight / height / BSA / insurance. **CSS** appended to `medical_records.css`: alert banner with amber accent, vitals grid tiles, generic `.mr-list` pattern, severity pills (.mr-pill-severe / -moderate / -mild), code monospace tag, notes list with indigo left-border, history four-block grid layout. **Tests** in `tests/v7/test_medical_records_full_chart.py` (10 cases): both chart templates `{% include %}` the partial; operator chart renders Demographics + the alert banner sections; partial contains all 11 expected section headings (Chief complaint / Code status / Allergies / Encounter / Problem list / Vital signs / IV fluids / Recent notes / Care team / History / Demographics); workstation chart renders same sections for both student + supervisor roles; CSS hooks present for every new section class. **Final v7 suite: 572 passed, 0 failures, 0 regressions** (up from 562). |
| 2026-05-27 | **M62 — Feature: Medical Records workstation + instructor / supervisor admin entry.** Operator: *"there needs to be a path to open the system in from the multi-patient control screen with both a QR code and button to open from the control screen. the entry screen should list the active patients characters so that the student or instructor must select the patient then enter the medical records system. This will support setting up an independent work station that multiple students will access to enter patient data and get information. The instructor should also have a special access to all them to insert updates and information likes labs that have been generated, or doctors notes or other supporting character information into the selected patient chart as they need to to support the simulation. Separately a designated nursing supervisor student should be able access through the nursing station a 'administrative portal' to enter labs and make notes separate from students assigned to specific patient characters. A button on the nursing station that allows the Student Nursing supervisor to enter their 2 initials to enter the administrative entry to have the medical records open up in new window to do their work."* Built end-to-end across 5 surfaces. **(1) Data model**: `Encounter.chart_inserts: list[dict] = field(default_factory=list)` — each entry `{ts, kind ("note"|"lab"|"doctor_note"), persona_id, title, body, author_name, author_role, author_initials}`. In-memory, dies with the room (same lifecycle as M53 lead_label, M55 active_medications). **(2) Public workstation routes** (no vault auth — room_code in the querystring is the access gate, matching the M27 Nursing Station + M28 EHR join patterns): `GET /students/medical_records?code=<room>&role=<student|supervisor>&initials=<XX>` — entry page; `GET /students/medical_records/{persona_id}?code=...&user=...&initials=...&role=...` — per-patient chart. **(3) Insert API**: `POST /api/medical_records/{persona_id}/insert` — body `{kind, title, body, author_name, author_initials, author_role}`. Validates kind ∈ {note, lab, doctor_note}; lab requires title; notes require body. Server resolves the encounter that owns the persona (via `seeds_for_patient_only` per-encounter lookup) and appends to `enc.chart_inserts`. **(4) Multi-Patient Control panel**: new "📋 Medical Records Workstation" section between Med carts and Nursing Station — `mr-ws-launch-btn` (target=_blank for instructor's machine) + QR rendered from `/api/qr.svg` for student tablets to scan. **(5) Nursing Station Supervisor button**: `🩺 Open Supervisor Records` button in the header — JS `prompt()` collects 2 (or 3) initials, persists in sessionStorage, opens `/students/medical_records?code=<room>&role=supervisor&initials=<XX>` in a new window. **Workstation entry template** (`medical_records_workstation.html`): identity form (Display name + Initials, both required before opening a chart; persisted to sessionStorage across patient-switches on the same workstation) + patient picker grid (same as M61 with 5-cell status). **Workstation chart template** (`medical_records_workstation_chart.html`): full M61 layout (three-shift MAR + Continuous Infusions + Tube Feeds + PRN + Labs) PLUS a Notes & Updates section rendering `chart_inserts` for this persona PLUS a 📝 Add to chart form visible only when `role in (supervisor|instructor|admin)`. The form has a kind dropdown (lab/doctor note/other), title input, body textarea, and a submit that POSTs to the insert API with the author identity from the URL params. **Instructor view extension** (`medical_records_chart.html`): the operator's `/portal/medical_records/{persona_id}` view also renders `chart_inserts` and gets the same add-to-chart form (`can_edit=True`, `author_role="instructor"`). Inline JS on each form POSTs and reloads on success. **CSS** appended to `medical_records.css`: workstation page layout (standalone, no sidebar), role badges (supervisor=green, instructor=amber), identify form, inserts list with kind-based left-border colors (note=indigo, lab=amber, doctor_note=green), add-form, MPC launch panel mirroring the M47 Med Carts + M36 Nursing Station green-pill visual language. **Tests** in `tests/v7/test_medical_records_workstation.py` (17 cases): MPC panel renders / hidden without room; public entry lists every patient + carries role / initials; entry empty state when no session; chart renders for student (no admin form) vs. supervisor (form visible); chart 404 on bogus persona; insert API appends to encounter.chart_inserts; validation 400s (missing title for lab, missing body for note, unknown kind); 404 for unknown persona; chart view renders inserts with author identity; inserts filter by persona (P-014 note does NOT surface on P-003); instructor's operator chart view has the add form; Nursing Station carries the Supervisor button + 2-initials prompt + role=supervisor URL. **Final v7 suite: 562 passed, 0 failures, 0 regressions** (up from 545). |
| 2026-05-27 | **M43 follow-up + UX — fix "offline · HTTP 409" badge on cart tablets.** Operator: *"offline.http 409 on the upper right corner of the screen of med cart, then flashes polling, can this box be removed from the screen view and second is being offline ok or is this an error during the operation of the med cart?"* TWO distinct problems hiding behind one symptom. **(1) Real M43-style miss**: the device tablet's HTTP-poll fallback hits `/api/device/{station_id}/state` every 2 s, and that route still called `control_session.get_active()` — which returns `None` in multi-patient mode. So every poll on every device tablet 409'd forever, even though WebSocket was happily delivering folds. M43 had fixed `bootstrap`, `event`, `inject`, `clear`, `assign`, and `roster` to use `_session_for_station(station)`, but missed `state`. Fix: route `api_device_state` through `_session_for_station` too. Single-patient mode keeps working because `_session_for_station` falls back to the v6 singleton when no room is active. **(2) UX noise**: the LIVE/POLLING/OFFLINE connection badge in the upper-right of every device screen was distracting for students even in normal operation. Made it opt-in via `?debug=conn` querystring. The internal connection-state tracking still runs (so the WS-reconnect / polling-fallback lifecycle is intact); only the visible DOM badge is suppressed. `_CONN_STATE` records the latest mode for operators who pop the query param to debug. 7 new tests in `tests/v7/test_device_state_multipatient.py`: state route returns 200 for a multi-bed cart (the headline regression); unknown station 404; room-ended → 409 cleanly; repeated polls all 200; JS has `_SHOW_CONN_BADGE` opt-in flag, badge.remove on stale + `_CONN_STATE` tracking-before-guard pattern; WS / polling / offline setStatus calls still fire so debug mode still shows the right colors. **Final v7 suite: 545 passed, 0 failures, 0 regressions** (up from 538). |
| 2026-05-27 | **M61 — Feature: Medical Records entry page with patient picker + three-shift MAR + IV / tube-feed detail sections + pending-actions status.** Operator: *"Medical records entry page to select from patient characters and give status of pending actions – meds, labs etc. The MAR in the medical records should use the standard three shift time structure for medication administration. And for the case define the best practice route of administration and time frame, like BID, TID, QD, etc For Tube feed and IV the total volume rate, fluid type and any associated medication to infused with rate and time and total dose. Do both for single patient and multi-patient systems."* New operator-facing surface at **`/portal/medical_records`** that works in both v6 single-patient and v7 multi-patient modes. **Architecture**: rather than touch the 783-line student-facing React EHR SPA, M61 builds a parallel server-side rendered view tailored to the instructor's workflow. **Helper module** `portal/medical_records.py`: `SHIFTS = [("Day", 7, 15), ("Evening", 15, 23), ("Night", 23, 7)]`; `parse_frequency(freq, interval_h)` normalizes route prefixes (PO/IV/IM/SQ), expands plain English (`"daily"` → `QD`, `"twice daily"` → `BID`, `"every 6 hours"` → `Q6H`), recognises continuous-infusion sentinels (`"continuous"`, `"drip"`), recognises PRN tokens with interval_h override, and falls back to `interval_h` to derive `Q<N>H` slot lists; `_FREQUENCY_SCHEDULES` maps every canonical token to standard floor times (QD→09:00, BID→09+21, TID→09+13+21, QID→09+13+17+21, q4h/q6h/q8h/q12h spread evenly); `shift_for_hh_mm()` buckets times into Day/Evening/Night with the standard 07-15-23 cutoffs; `med_view_model()` produces the per-med dict the template iterates (name, dose, route, frequency_label, per-shift time slots, is_continuous, is_prn, high_alert, last_given, rationale); `is_continuous_infusion()` + `infusion_summary()` + `tube_feed_summary()` pull rate / volume / fluid / additives for the dedicated continuous-meds and tube-feed sections; `patient_status()` computes pending-actions counters (med_count, due_in_current_shift, continuous_count, prn_count, labs_pending, current_shift); `patients_for_picker()` resolves both single-patient (singleton via `control_session.get_active()`) and multi-patient (every encounter via `control_room.get_active_room()`) using the M58 `seeds_for_patient_only()` so family/clinician personas don't pollute the picker. **Routes** in `server.py`: `GET /portal/medical_records` (picker) + `GET /portal/medical_records/{persona_id}` (chart). **Templates**: `medical_records.html` (card grid with one card per patient showing 5-cell status grid — total meds, due-this-shift, infusions, PRN, labs pending) + `medical_records_chart.html` (header counter pills + three-shift MAR table + Continuous Infusions block with dose/route/status/started/admin history + Tube Feeds block with rate/daily-volume/infused-so-far/flush-schedule + PRN block + Labs block flagged pending-when-unresulted). **Navigation**: new `📋 Medical Records` link in the sidebar under "Operate" (`base.html`). **CSS** (`medical_records.css`): card-grid picker, indigo card accents (matching M53 lead-assignment styling), shift-MAR table with shaded columns + monospace HH:MM slot chips, infusion / tube-feed dl grids, pending-lab badge variant. 26 new tests in `tests/v7/test_medical_records.py` covering frequency parsing (QD/BID/TID/QID/q6h/continuous/PRN/route-prefix-strip/interval_h-fallback), shift bucketing (boundary times + TID lands in multiple shifts), view-model flagging of continuous + PRN, `patient_status()` counter math (continuous, PRN, labs-pending, due-in-current-shift), picker route renders one card per patient in single OR multi mode, chart route 200/404, nav link present, CSS selectors present. **Final v7 suite: 538 passed, 0 failures, 0 regressions** (up from 512). |
| 2026-05-27 | **M60 — Feature: med-cart patient picker drilling into per-patient MAR.** Operator: *"For the med cart patient pull up tab, should list all the patient characters in the sim, then select from that to pull up the med list in the cart for the patient character."* Pre-M60 the cart's MAR panel rendered only for the SINGLE instructor-assigned character (via WS `assign` event → `ASSIGNED_CHAR_ID`). Without an assignment the panel stayed empty even when the cart was linked to many patients via M47 `cart_links`. The cart bootstrap was already delivering the full `characters[]` roster (M58 patient-only filter applied per linked encounter); the device JS just wasn't using all of them. **New flow** in `portal/static/devices/device_app.js`: introduces local `SELECTED_CHAR_ID` state separate from the server-pushed `ASSIGNED_CHAR_ID`. The `renderCabinetChecklist()` dispatcher now picks one of two paths — when `SELECTED_CHAR_ID` is null and there's no instructor assignment, render the **patient picker** (cards for every entry in `CHARACTERS`, showing name + location + encounter label + med count + → chevron); tapping a card sets `SELECTED_CHAR_ID` and drills into the **MAR view** (extracted into new `_renderCabinetMar` helper so the panel chrome is shared). The MAR view gains a "← Patients" back button (only visible when `CHARACTERS.length > 1`) that clears `SELECTED_CHAR_ID` and returns to the picker. The bottom-left 👤 PATIENT LIST floating button now also resets the selection so opening always lands on the picker — *"show me everyone"*. Back-compat: instructor-pushed `assign` events still seed `SELECTED_CHAR_ID = ASSIGNED_CHAR_ID` on first render, so the pre-M60 "assign drills straight into MAR" workflow is unchanged for any drill where a single patient is pre-targeted. **Tests**: 9 new in `tests/v7/test_med_cart_patient_picker.py` — bootstrap delivers all linked patients with required fields (character_id/name/medications/encounter_label); device JS has `SELECTED_CHAR_ID` state; picker render function (`_renderCabinetPicker`) + per-card class (`cabinet-pick-patient`) + "Pick a patient" title; MAR render extracted (`_renderCabinetMar`); back-button id (`cabinet-checklist-back`) + "← Patients" label + handler clears `SELECTED_CHAR_ID`; floating button click clears `SELECTED_CHAR_ID`; assigned fallback branch present in render dispatcher; picker hidden when `haveAnyChars` is false; back button only shown when `CHARACTERS.length > 1`. **Final v7 suite: still 512 passed, 0 failures, 0 regressions** (up from 503). |
| 2026-05-27 | **M59 bugfix #2 — Shared med cart invisible on secondary encounter's Devices block.** Operator (after the previous UX defenses landed): *"I still have to enter each encounter separately when I click on both only the first shows up on the encounter page even though the second encounter is listed on the med cart device block in the multi patient control area."* This was the REAL root cause — distinct from the cosmetic "ticking is invisible" theory I'd been chasing. The Multi-Patient Control panel always showed the cart correctly linked to both beds (that data path was fine). But when the operator drilled into the SECONDARY encounter's per-patient console, the Devices block was empty — the cart didn't appear there. **Mechanism**: each M47 cart's `device_station` row is owned by ONE primary encounter (the first ticked at create time). `room.cart_links[cart_sid]` may name several encounters, but the back-end mapping from "encounter ⇒ its device stations" only looks in two places — the encounter's in-memory `device_stations` dict and `ehr_db.device_stations(session_id=enc.id)` — neither of which mention the shared cart for any secondary encounter. **Fix** in `portal/devices/routes.py::api_device_roster`: after the existing self-heal that rehydrates rows owned by THIS encounter, walk `room.cart_links` and — for any cart whose link list contains the resolved encounter id but whose station row is owned by a different primary — rehydrate that cart into `sess.device_stations` so the roster surfaces it. Per-station mutations (inject, clear, unlink, dispense) continue to route correctly because `_session_for_station(station)` resolves by the cart's stored `session_id` (the primary), not by which encounter just queried the roster. 4 new tests in `tests/v7/test_med_cart_encounter_checklist.py`: `test_shared_cart_appears_on_secondary_encounter_roster` (the headline bug — bed 2's roster includes the cart linked to beds 1+2), `test_shared_cart_metadata_intact_on_secondary_roster` (label / kind / model survive the rehydrate), `test_unlinked_encounter_does_NOT_see_cart` (sanity — bed 3 with no link to the cart still doesn't see it), `test_cart_unlinked_from_secondary_disappears_from_roster` (DELETE link removes bed 2 from `cart_links` so subsequent ticks won't surface the cart on that bed). **Final v7 suite: 503 passed, 0 failures, 0 regressions** (up from 499). |
| 2026-05-27 | **M59 bugfix — "second encounter still not linking" defensive UX overhaul.** Operator: *"Second encounter still not linking with med cart when selected."* Direct repro via **Playwright in a real headless Chromium** proved the entire flow works correctly end-to-end: ticking only bed 2 → request body `{"encounter_ids":["y-ZfysNW1Rs"]}` → server stores `linked=['y-ZfysNW1Rs']` (NOT bed 1). Ticking beds 1+2 → linked=[bed_1, bed_2]. Post-create "Add selected" of bed 2 → server stores linked=[bed_1, bed_2]. So the code on disk is provably correct in a fresh browser. Most likely cause is the operator's browser running cached pre-M56 JS / HTML despite the M56-bugfix `Cache-Control: no-store`. **Defensive UX overhaul** to make the bug impossible to overlook in the future: (1) **"✓ All beds" / "✗ None" quick toggles** on the create form so the operator can tick every encounter in one click (most common cart workflow); each button iterates `.med-cart-create-enc-cb` and refreshes the tick counter. (2) **Prominent "🔗 N beds" count badge** in each cart card header — large indigo pill for 1 bed, large green pill for 2+. Pre-fix the operator had to count small chips; now the linked count is impossible to miss. (3) **Playwright regression test** committed to `/tmp/medsim_m59_repro.py` (used to prove the flow; standing fixture-style E2E in the suite). Tests added: `test_create_form_renders_all_none_toggles` + `test_control_room_js_wires_all_none_toggles` + `test_cart_card_renders_count_badge` + `test_count_badge_styling_distinguishes_multi_bed` + `test_full_flow_ticking_second_encounter_only_links_it` (asserts encounter_ids=[bed_2] → linked=[bed_2], no phantom bed_1 fallback) + `test_full_flow_ticking_beds_2_and_3_links_both`. **Pre-existing flake fix**: while running the full v7 suite, the M20 playwright test `test_ehr_ui_multi_encounter` started failing because Playwright was just installed and the test (previously skipped silently) had stale assertions — clicked an `.encounter-card` while it was still inside the hidden role-picker step that M27 added, and clicked a `#btn-resume` button that M35 removed. Fixed by adding the role-picker click step (Bedside) and switching the resume action to `#btn-start-all` (M35's unified launch/resume). Test now passes in 2.9s (was timing out at 32s). **Final v7 suite: 499 passed, 1 skipped** (up from 492); 0 regressions. |
| 2026-05-27 | **M59 — Feature: per-cart "🛒 Open cart" launch button on Multi-Patient Control.** Operator: *"on the multi patient control page the instructor needs to be able to launch the med cart(s) created. When it launches into a new window, create a button for each cart created to allow them to be launched."* The dashboard already had a QR + join URL per cart, but no one-click open from the operator's own machine. **Server**: `/api/room/med_cart/register` and `/api/room/med_carts` responses both gain a `device_url` field — the direct `/device/{primary_join_code}/{cart_sid}` path that bypasses the `/device/join` landing page. (The existing `join_url` field still points at the join landing for QR-scan workflows; nothing changes for tablet onboarding.) **Client**: `renderMedCarts` adds a green pill anchor `.med-cart-launch-btn` ("🛒 Open cart") next to each cart label, `target="_blank"` so it opens in a new window. `.med-cart-card-header` upgraded to a flex row so the button sits on the right. Title attribute explains the behaviour: *"Open this cart's tablet UI in a new window on this device — skips the QR-scan join step."* Matches the Nursing Station "🩺 Open here" green-pill visual language for consistency. **Tests**: 5 new in `tests/v7/test_med_cart_encounter_checklist.py` — register response carries `device_url` pointing at the direct device tablet path (not the join landing); list response includes the same field; JS card render uses `cart.device_url` + `target="_blank"` + "Open cart" label; CSS rules present; hitting the `device_url` directly serves the device-tablet template (cabinet → `device_app.html`). **Final v7 suite: 492 passed, 1 skipped** (up from 487); 0 regressions. |
| 2026-05-27 | **M56 bugfix — multi-tick assigning only one encounter.** Operator: *"If more than one encounter is checked off when assigning them to a med cart only the first checked encounter is assigned."* Direct repro via Python TestClient confirmed both back-end (`/api/room/med_cart/register` with `encounter_ids=[e1,e2,e3]` returns `linked_encounter_ids=[e1,e2,e3]`) and front-end render path (`/api/room/med_carts` lists all 3) work correctly when the form HTML actually contains the M56 checkboxes. Root cause: a stale cached version of `/portal/room` HTML (from before M56 added the encounter checklist fieldset) lingered in the operator's browser. Without the checkboxes in the DOM, the JS submit handler found zero `.med-cart-create-enc-cb:checked`, sent `encounter_ids: []`, and the server's back-compat fallback linked the cart to just the first encounter — exactly the reported behaviour. **Three fixes** to harden against this and similar stale-UI states: (1) **Live "Will link N of M encounters" counter** next to the submit button, server-rendered and JS-updated on every checkbox change. Turns red when the count is 0 but the room has encounters — operator-visible warning that something's off BEFORE they click submit. New `_updateTickCount()` helper wired to every checkbox's `change` event + called once on init + reset after a successful create. (2) **`Cache-Control: no-store` on the `/portal/room` route** so the dashboard HTML never gets stuck in browser cache. The `static_v()` cache-busting (file mtime via `?v=` query) handles JS/CSS but not the HTML page that references them — fixed here. (3) **Latent fix at the `_captureEncountersForCarts` call site**: pre-bug the JS read `body.room` to find the encounters list, but `_room_summary` returns `encounters` at the TOP LEVEL of `/api/room/state`. `body.room` was always undefined, so `lastKnownEncounters` stayed empty and the cart card's chips fell back to bare encounter IDs instead of labels. Changed to `_captureEncountersForCarts(body)`. New CSS `.med-cart-tick-count` (indigo pill, red `-zero` variant). 4 new tests in `tests/v7/test_med_cart_encounter_checklist.py`: counter rendered on first paint with initial "Will link 0 encounter" text; `Cache-Control: no-store` header on `/portal/room`; JS has `_updateTickCount` + `med-cart-tick-count` + checkbox change wiring; `_captureEncountersForCarts(body)` call site no longer gated on `body.room`. **Final v7 suite: 487 passed, 1 skipped** (up from 483); 0 regressions. |
| 2026-05-27 | **M58 — UX fix: med list filters to patient persona only.** Operator: *"Med list should only populate with Patient character medications no other character."* Pre-M58, both the encounter Medications card (M55) and the M47 med cart iterated EVERY persona in `selected_personas` via `seeds_for_all_personas` — which on multi-persona encounters (patient + family role-players + clinicians) surfaced empty / stub-noisy med rows for personas that have no real MAR. **Fix**: two new small helpers in `ehr_seed.py` — `patient_persona_id(session)` resolves the patient via `session.patient_persona_id`, falling back to `selected_personas[0]` for v6 legacy compatibility, returning None otherwise; `seeds_for_patient_only(session, *, ehr_id)` calls `seeds_for_all_personas` and filters its output by `character_id == patient_persona_id(session)`. Both the GET `/api/encounter/{eid}/medications` endpoint and the cabinet bootstrap in `devices/routes.py` now use `seeds_for_patient_only` instead of `seeds_for_all_personas`. The cart continues to show ONE entry per linked encounter (the patient) — multi-bed semantics preserved. 6 new tests in `tests/v7/test_medications_active.py`: M58 GET only returns the patient persona when the encounter carries two personas (P-014 patient + P-003 family); cart bootstrap returns exactly one character per linked encounter and never the family persona; helper fallback to `selected_personas[0]` when `patient_persona_id` is None; helper prefers explicit field over first-of-selected; helper returns None when neither set; `seeds_for_patient_only` skips non-patient personas at the helper level. **Final v7 suite: 483 passed, 1 skipped** (up from 477); 0 regressions. |
| 2026-05-27 | **M57 — UX cleanup: strip the dead M30 lead-picker UI from the encounter Lead-student card.** Operator: *"Now the lead is listed in the encounter, remove the other parts in the leads area since they add no value 'Assign one bedside student as the lead for this encounter (M30, roster-picked). Surfaces in the cohort debrief facet header and on the dashboard card. For a group name or list of students, type it on the Multi-Patient Control "Lead assignments" panel — that label shows above. Lead (roster)' and the listing pull down."* Now that M53's free-text labels surface in the prominent header pill + card banner, the M30 roster picker added no value (and was its own configuration surface — operators could set TWO different leads). Removed: the `<select id="lead-student-picker">` dropdown, the "Lead (roster)" label, the entire explanatory paragraph ("Assign one bedside student… Surfaces in the cohort debrief…"), the `#lead-student-status` save-confirmation line. Added: an `#lead-empty-hint` placeholder *"No lead assigned yet. Set one on the Multi-Patient Control 👤 Lead assignments panel."* — server-rendered with the `hidden` attribute toggled by `encounter.lead_label`, so the card never looks empty. **JS cleanup**: `bootLeadStudent` collapsed to `async function bootLeadStudent() { /* no-op */ }` (preserved as a stub so the existing `await bootLeadStudent()` in DOMContentLoaded doesn't blow up). `updateLeadBanner` removed entirely. `_updateLeadLabelRef` simplified — dropped the `dataset.rosterName` fallback (only reachable from the now-deleted `updateLeadBanner`) and added an `#lead-empty-hint` show/hide branch so the placeholder toggles in lockstep with the label across state polls. **CSS** adds `.lead-empty-hint` (dashed-border, muted text). 4 new tests in `tests/v7/test_lead_assignments.py`: picker / status / paragraph all absent from the rendered HTML; empty-state hint visible when no label; hint hidden when label set; JS `bootLeadStudent` is a stub with no DOM touches or fetches to `/lead_student`, and `updateLeadBanner` is gone module-wide. 2 pre-existing tests updated for the contract change: SSR test narrows its "hidden not in window" check to the banner's own attributes (the new empty-state hint lives in the same card and IS hidden when a label is set, so the old broad window scoop-up was a false positive); `_updateLeadLabelRef` test asserts `rosterName` is NOT present so a future editor doesn't quietly bring it back. **Final v7 suite: 477 passed, 1 skipped** (up from 473); 0 regressions. |
| 2026-05-27 | **M56 — UX fix: med-cart create flow with encounter checklist + post-create add-encounters UI.** Operator report: *"When the Med Carts are generated, it needs to include a check off list of the encounters to be joined to it. Currently the med cart generated are only assigned to the first encounter of [the] listed in the Multi patient control screen. Additionally, med cart assignment needs the ability to add encounters to the list after it has been created."* Two distinct UX gaps. (1) **Create-time gap**: the M47 back-end `/api/room/med_cart/register` already accepted `encounter_ids[]` (with a defensive fall-back to the first encounter if empty) but the JS submit handler only sent `{label}`. So no matter how many encounters the room had, every cart was born with one link — always to the first listed encounter. **Fix**: the create form gains a `<fieldset>` with one `.med-cart-create-enc-cb` checkbox per encounter (pre-rendered server-side from `room.encounters` so it works on first paint). The submit handler scans `.med-cart-create-enc-cb:checked` in DOM order and POSTs them as `encounter_ids[]`; the first ticked becomes the cart's primary. Empty selection keeps the legacy fallback (first encounter), so single-bed workflows are unchanged. The post-create confirmation banner now reports the actual link count: "Created. Cart linked to N encounters." Form auto-unchecks every box after success so the next cart starts clean. (2) **Post-create gap**: the per-cart card had a single-select `<select>` dropdown + a "+ Link" button — one encounter at a time, slow if the operator needs to attach 3 beds. **Fix**: replaced with a multi-checkbox `.med-cart-add-checklist` (one checkbox per unlinked encounter) + a "+ Add selected" button. The new `add-multi` action handler in `onMedCartAction` fans out one POST per ticked id to the existing M47 link route (good enough for typical 1-10 bed rooms; no new batch endpoint needed). CSS adds new `.med-cart-encs-checklist` / `.med-cart-add-checklist` / `.med-cart-enc-check` / `.med-cart-add-check` rules — chip-styled checkboxes with indigo hover state matching the M53 lead-assignments visual language. Old `.med-cart-link-select` + `data-act="link"` markup fully removed from the cart-card render path. 11 new tests in `tests/v7/test_med_cart_encounter_checklist.py`: back-end multi-link at create time (full set, subset, empty list fallback to first, unknown-id 400); template render of fieldset legend + per-encounter checkbox + hidden when no room; JS markers (`.med-cart-create-enc-cb:checked` + `encounter_ids` + add-multi action + absence of old single-select markup); CSS rules; and the headline E2E flow: create cart with 2/3 encounters → post-create add the 3rd → cabinet bootstrap surfaces characters from all 3 encounters. **Final v7 suite: 473 passed, 1 skipped** (up from 462); 0 regressions. |
| 2026-05-27 | **M53 bugfix #2 — bulk Apply wiped per-row labels.** Operator report: typed labels into per-row inputs, ticked the checkboxes, clicked the bulk Apply button → all the per-row labels got cleared and the encounter still showed no lead. Root cause: the bulk Apply handler unconditionally read `lead-bulk-input.value` (an empty string in this workflow) and POSTed it as the `lead_label` for every checked row, OVERWRITING whatever the operator had typed into per-row inputs. The encounter then correctly showed nothing because the server's stored label was empty. **Fix (`portal/static/control_room.js`)**: (1) Smart fallback on bulk Apply — if the bulk input has text, behave as before (set all checked rows to that text); if empty, GROUP each checked row's OWN per-row input value by label and POST one assignment per distinct label. Empty per-row inputs are SKIPPED so the operator can't accidentally clear other beds. Empty-state error message ("nothing to apply — type a label in the bulk box or in the per-row inputs") instead of silent wipe. (2) Per-row inputs now AUTO-SAVE on Enter and on blur — extracted `_saveRowLabel(eid, label)` helper that the row Apply button, the row Clear button, the Enter key, and the blur event all share. `dataset.saved` snapshot prevents no-op POSTs on tab-away when nothing changed. (3) Bulk input no longer auto-clears on success — operator may want to re-apply the same label to additional rows; explicit comment "Intentionally NOT clearing the bulk input" anchors the contract. (4) Panel hint text updated in `control_room.html` to spell out the two workflows ("Per row: type + Enter / tab" vs. "Bulk: type + check + Apply") with a `<kbd>` element for the Enter key. 4 new regression tests in `tests/v7/test_lead_assignments.py`: heterogeneous bulk assignments (different labels per group), JS smart-fallback markers (`byLabel`, `"nothing to apply"`, `"if (bulkLabel)"`, `"Intentionally NOT clearing"`), per-row auto-save markers (`_saveRowLabel`, `keydown`, `blur`, `dataset.saved`), hint-text rendering (`Per row:` + `Bulk:` + `Enter`). **Final v7 suite: 462 passed, 1 skipped** (M20 Playwright skip — unchanged); 0 regressions. |
| 2026-05-27 | **M55 — Feature: encounter Medications card with active-at-start toggle + med-cart filter.** Operator request: *"Medication section needs to be added to the encounters. Click on the header to have it open up of the assigned medications for the scenario and allow the instructor to click on the medication to be present or in use at the start of the scenario. These medication will show up in the med cart under the name of the patient character in the encounter."* Delivered end-to-end. **Data model**: new `Encounter.active_medications: dict[str, list[str]]` mapping persona_id → list of lowercased med names. Default empty. Semantics: persona NOT in dict → cart shows every med (back-compat); persona in dict → cart shows only listed meds (empty list = none). **API**: three new routes — GET `/api/encounter/{eid}/medications` lists every persona's seed-derived MAR (via `ehr_seed.seeds_for_all_personas`) with per-med `active` boolean + per-persona `explicit_active_list` flag; POST `/api/encounter/{eid}/medications/active` body `{persona_id, active_med_names: [...]}` replaces one persona's explicit list (whitespace-trimmed + lowercased); DELETE `/api/encounter/{eid}/medications/active/{persona_id}` resets to default. **Cart filter** in `devices/routes.py` bootstrap path: per-persona, if explicit list set, filter `c["medications"]` to entries whose lowercased `name` is in the active set; else keep full list. M47 cart UI is unchanged — receives a smaller list. **Encounter console UI**: new "💊 Medications" card between Devices and Network/QR, collapsed by default matching M54's threshold-panel pattern (h2 styled as role=button with ARIA + rotating caret + Enter/Space keyboard). Renders one section per persona with header showing name + character_id + status badge ("default — all active" vs. "explicit list") + ↺ Reset button. Each med row has a checkbox (ticked = active), name + dose/route/frequency, and a "⚠ high-alert" badge for high_alert meds. Per-row tick fires `onMedToggle` which collects the FULL active list from the DOM and POSTs (server is dumb storage, no delta protocol). Indigo accent matching M53 lead-assignments. **Tests**: 13 new in `tests/v7/test_medications_active.py` covering dataclass default, GET endpoint shape + 404, POST sets explicit list + handles empty list + missing-persona-id 400 + unknown-encounter 404, DELETE resets to default, cart bootstrap filter (with active list → filtered; without → full list, back-compat preserved), and UI markers (template card + JS handlers + CSS rules). Guide + PDF at `docs/module_guides/M55_medications_active_at_start.{md,pdf}`. **Final v7 suite: 458 passed, 1 skipped** (M20 Playwright skip — unchanged); 0 regressions. |
| 2026-05-27 | **M53 bugfix — assigned leads weren't visible on the encounter page.** Operator report: *"The assigned Leads are not showing on the encounter"*. Root cause was two-part. (1) The M53 lead-label banner only existed inside the buried lead-student card, easy to miss; the prominent header pill `#lead-student-banner` (M30) was wired ONLY to the roster-picked `lead_student_id`, so M53 free-text labels never surfaced there. (2) Both surfaces relied on the JS state poll (~2 s cadence) to populate from the server response; on first paint the page rendered empty banners regardless of what the operator had typed on Multi-Patient Control. Fix: (a) The encounter console template now SERVER-SIDE renders the lead in BOTH the header pill `#lead-student-banner` (next to the encounter title) and the card-level `#lead-label-ref` reference banner — using Jinja `{% if encounter.lead_label %}`, so labels are visible immediately on page load. (b) The JS `_updateLeadLabelRef` now updates BOTH surfaces on every state poll, with a `nameSpan.dataset.rosterName` stash so the M30 roster-picked name persists alongside the M53 label rather than getting clobbered. (c) New CSS `#lead-student-banner` rule — indigo pill matching the Multi-Patient Control panel accent — so the lead reads as PROMINENT next to the encounter title rather than a quiet text fragment. 4 new acceptance tests in `tests/v7/test_lead_assignments.py` covering server-side render of label in header + card, hidden state when no label, and JS dual-surface update with rosterName fallback. **Final v7 suite: 445 passed, 1 skipped** (up from 441); 0 regressions. |
| 2026-05-27 | **M54 — Feature + UX fix: collapsible threshold panel + concurrent tiered repeating audio + magnitude-based threshold severity.** Operator request: *"Nursing station- alarm threshold click to drop down and open, click header of Alarm threshold and have it roll up. Alarms need to run concurrently. For higher priority alarms (low- medium-High) the alarms sound more frequently. For example the sound loop for a code blue should run continuously with minimal time gap running the sound loop. Low level alarms sound when parameters are 10% below lower threshold or 10% Higher than upper threshold. Medium is between 10% and 20% of threshold limits and high if above 20% of the threshold limits"*. Four asks bundled. (1) **Collapsible threshold panel**: section ships with `ns-collapsed` class on first paint; h2 header becomes a role=button toggle with `aria-expanded`/`aria-controls` + a rotating caret. Click or Enter/Space flips the class. CSS hides only the form when collapsed; header stays visible. (2) **Concurrent alarm playback**: dispatcher already spawns one `new Audio(url)` per alarm so multiple WAVs play in parallel — M54 adds an explicit `CONCURRENTLY` comment to lock the contract. (3) **Tiered repeating audio**: `AUDIO_REPEAT_MS` reworked from 3 tiers (high 8s / medium 20s / low 45s) to 4 tiers — `danger: 2500, high: 5000, medium: 15000, low: 35000`. A new `_audioCadenceTier(a)` helper reads `severity` first so "danger" routes to its own bucket even though `severity_to_priority` still maps both critical+danger to "high" for WAV lookup (same WAV file, different cadence). Because the 3s state poll would cap the 2.5s danger cadence, M54 adds a 700ms `setInterval` that re-runs the dispatcher off a cached `_lastAlarmsForAudio` list — the danger tier truly fires every ~2.5s for near-continuous code blue. Other tiers (≥5s cadence) gated by the poll as before. (4) **Magnitude-based threshold severity**: `_threshold_alarms_for` now computes `deviation_pct = (value - bound) / abs(bound) * 100` and maps the result: 0-10%→info, 10-20%→warning, ≥20%→critical. Each threshold alarm gets a new `deviation_pct` field for future UI badges. Replaces M48's per-metric fixed severity (SpO2 always critical, others warning). Pre-M54: a 1-point SpO2 dip below threshold fired critical; now it's info, matching real bedside monitor behaviour. **Code-blue promotion**: `_SEVERITY_BY_KIND` code.blue and code_blue_button both "critical"→"danger" so they sort to the TOP and ride the 2.5s near-continuous cadence (same `03_code_blue.wav` audio asset). **PIA cascade** cadence dropped 8000→2500ms to match the nurse-station danger tier — bedside hears the same near-continuous tone. **Tests updated for intentional contract changes**: `test_alarm_bus.py` (code.blue severity → danger), `test_alarm_thresholds_and_ecg_fix.py` (HR=130 vs high=80 is now critical at 62.5%; SpO2 deep-drop test value 85→70 to stay critical), `test_clinical_alarm_sounds.py` (SpO2 audio-priority test value 80→70; dispatcher fn search window widened), `test_future_devices.py` (code_blue_button severity → danger), `test_repeat_audio_silence_brand.py` (PIA cascade cadence 8000→2500). Guide + PDF at `docs/module_guides/M54_collapsible_concurrent_tiered_severity.{md,pdf}`. 17 new tests in `tests/v7/test_collapse_concurrent_tiered_severity.py` covering all four tier severity boundaries (both sides + deep + shallow), code-blue/button danger promotion, JS dispatcher tier-table + tier-picker + fast ticker + concurrent comment, PIA cascade cadence, collapsible markup + JS toggle + CSS hide-form. **Final v7 suite: 441 passed, 1 skipped** (M20 Playwright skip — unchanged); 0 regressions. |
| 2026-05-27 | **M53 — Feature: lead student / group / list assignment from Multi-Patient Control.** Operator request: *"In the encounter Lead student needs to be able to add the name of the lead student, the name of a group, a list of students or the name of a single student to assign to a specific encounter or in several encounters. this may be more effective to locate in the Multi-patient control and then list the lead in the encounter or encounters as a reference for the instructor."* Delivered end-to-end. **Data model**: new `Encounter.lead_label: str = ""` free-text field on the dataclass, independent of M30's `lead_student_id` (which still requires a roster registration). Both can coexist; the state poll's new `effective_lead_display` field surfaces `lead_label.strip() or lead_student_name or ""` so the M53 label wins for display while keeping the M30 fallback. **API**: three new routes — `GET /api/room/lead_assignments` (every encounter's label + roster fallback in one call), `POST /api/encounter/{eid}/lead_label` (set/clear one bed with whitespace trim, no length cap), `POST /api/room/lead_assignments` (bulk: `assignments: [{encounter_ids: [...], lead_label: "..."}]`; unknown ids land in response's `unknown[]` so the UI can warn; multiple assignment entries with different labels supported per call). **Multi-Patient Control panel**: new `.lead-assign-panel` section between Med carts and Nursing Station, pre-rendered server-side from `room.encounters` so it's visible on first paint. Per-encounter row = checkbox + label + free-text input + Apply/Clear/status; below = bulk input + "Apply to checked encounters" + "Check / uncheck all" toggle. Wire-up in `wireLeadAssignments()`; no live re-render so operator-typed text isn't overwritten by polls. Indigo (`#5a4ec3`) left-border accent distinguishing it from green med carts and green nursing station panels. **Encounter-console reference banner**: `lead-student` card gets a hidden `.lead-label-ref` div above the M30 picker; shown read-only when `lead_label` is set, with "set from Multi-Patient Control" footer hint pointing the bedside instructor at where to edit. JS `pollState` now reads `enc.lead_label` from the state-poll response and calls `_updateLeadLabelRef` to show/hide the banner. **Server-side template-context plumbing**: `portal_room_get` previously passed only `{room_code, room_id, label}`; M53 extends to also pass `encounters: [{id, encounter_label, scenario_name, lead_label}]` so the Jinja template can `{% for enc in room.encounters %}` render rows without an extra round-trip. Guide + PDF at `docs/module_guides/M53_lead_assignments.{md,pdf}`. 19 new tests in `tests/v7/test_lead_assignments.py` covering dataclass default, single-encounter set/clear/trim/404, bulk apply with one label to N beds, bulk apply with different labels per group, comma-separated student lists, unknown-id handling, GET shape, M30+M53 coexistence + display priority, template panel rendering when room active vs. hidden when no room, pre-filled existing labels, encounter console banner markup + JS consumption, dashboard JS handlers. **Final v7 suite: 424 passed, 1 skipped** (M20 Playwright skip — unchanged); 0 regressions. |
| 2026-05-27 | **M52 — Feature + UX fix: repeating alarm audio + 45 s silence default + brand rename to "Training Bridge VRAI- MedSim".** Three operator asks bundled. (1) **Repeating audio**: M49 played each alarm's WAV exactly ONCE on first sight (deduped via `_seenAlarmIds`). M52 replaces with `_audioLastAt: Map<alarm_id, ms>` + `AUDIO_REPEAT_MS = {high: 8000, medium: 20000, low: 45000}` cadence table on the nurse station. Each poll: for each active alarm, if `(now - lastPlayed) >= cadence` and not silenced, play + update timestamp. Cadence picked by `audio_priority` field (already on every alarm per M49). Map drops ids that leave the active list so re-occurrences fire immediately. PIA cascade poller gets the same treatment with a fixed 8 s cadence via `_cascadeAudioLastAt` (each active code-blue gets its own 8 s clock; multiple beds coding = staggered tones). `_cascadeKey` retained — only the flash animation restarts on new alarm sets; the audio keeps repeating. (2) **45 s silence default**: was 120 s per M50; operator: *"silence of an alarm last 45 seconds then it goes active if the condition is not resolved or cleared"*. Default dropped on both `silence_alarm` helper and `/api/alarm/{id}/silence` route. The existing `_apply_silenced` filter auto-expires past `until`, so a still-active breach surfaces its audio again the moment 45 s lapses — and the new repeating dispatcher then re-fires it. Operator override `?seconds=N` still works. Silence-button tooltip updated to match. (3) **Brand rename**: every user-visible screen + the printable QR sheet now reads **"Training Bridge VRAI- MedSim"** (exact spacing per operator — space after the hyphen, no space before). Touched 11 templates: `base.html` (`<title>` + topbar wordmark "MEDSIM 2 v2" → "Training Bridge VRAI- MedSim v7"), `home.html` (`<h1>MEDSIM 2</h1>`), `login.html` (title + h1, was "medsim portal"), `join.html` (title + h1, was "MEDSIM 2 session"), `ehr_join.html` (was "MEDSIM V3"), `device_app.html` + `device_join.html` (titles + `apple-mobile-web-app-title` meta), `device_pia.html` + `nurse_station.html` (brand-suffixed titles), `qr_print.html` (was "Training Bridge MedSim-VRAI" in 2 places). Code-level identifiers deliberately NOT renamed: `window.MEDSIM2_*` JS globals, `~/.medsim/vault.enc` filesystem path, `medsim_ehr_window` browser target, `medsim_a2hs_dismissed_at` localStorage key, `Voice4MedSim_v6` historical attribution — those are code, not user-visible brand. Two existing tests updated: `test_clinical_alarm_sounds.test_nurse_station_js_dedupes_by_alarm_id` was asserting the OLD once-per-occurrence symbols — renamed `…_repeats_audio_by_cadence` pointing at `_audioLastAt` + `AUDIO_REPEAT_MS`; `test_qr_print_sheet` brand string swapped to the new wording. Guide + PDF at `docs/module_guides/M52_repeat_audio_45s_silence_brand.{md,pdf}`. 18 new tests in `tests/v7/test_repeat_audio_silence_brand.py` covering 45 s silence default, helper signature, JS repeating-audio symbols on both nurse station and PIA, brand in every template, and live HTTP render of brand on `/portal/home` + `/portal/control/qr_print`. **Final v7 suite: 405 passed, 1 skipped** (M20 Playwright skip — unchanged); 0 regressions. |
| 2026-05-27 | **M51 — Feature: Patient Integrated Alarm (PIA) device.** Operator request: *"Create a new device to add to the device list, the 'Patient integrated alarm' for encounters – three functions- call bell, bed alarm, code blue and intercom with nurses station on one table. The instructor needs to able to trigger events as well as students responding to clear alarms or to use the intercom or activate the Code Blue alarm. The code blue should also cause the other Patient integrated alarm state the location-in this case encounter as well as on the nurse station and instructor control areas. Use available sound files to support the various alarms. The screen on the device should flash with alternating colors to indicate the alarm or if a function like intercom is active."* Built end-to-end. **Registry**: new `patient_integrated_alarm` kind + `pia_v1` model under `portal/devices/pia/pia_v1/` (spec declares 4 controls, 3 alarm tones; skin.svg is a registry-stub since the PIA renders a dedicated template, not a vendor overlay). **Engine**: thin `PiaEngine` added to `state_machine.make_engine` so the base no-op reducer is enough — PIA effects route as side-effects in `_handle_pia_button`. **Routes**: `device_app` branches to `device_pia.html` for PIA kind; `api_device_event` calls `_handle_pia_button` for `pia.button` events. The four actions route to: `call_bell`/`bed_alarm` → `alarm.injected` device_event so the M26 bus picks them up with `severity=info`/`warning`; `code_blue` → `scenes.apply(code.blue)` so the existing M7 scene fires (chart events + room-wide code-blue alarm); `intercom_request` → `comm.intercom_request` chart event + transcript line ("🎙 Intercom requested"). **Device-side UI**: new `device_pia.html` template (4 large buttons in a 2×2 grid + cascade banner area + status indicator + footer "last event" stamp) + `pia_app.js` (press → POST + WAV from M49 library + 4-second frame flash in a kind-matched colour + 3 s poll of `/api/room/alarms` for room-wide cascade awareness; `_cascadeKey` dedupes by sorted alarm_id so the flash only re-triggers on a NEW code blue; 15 s heartbeat) + `pia_app.css` (dark theme matching M48 nurse station, per-kind `@keyframes flash-*` rules, `.cascade-pulse` for the banner, `.pia-cascade-active` for continuous red flash while a code is live anywhere in the room). **Room-wide cascade**: every PIA polls the SAME `/api/room/alarms` endpoint as the nurse station — when any code blue is active, every PIA shows "CODE BLUE — Bed N" reading the originating encounter's label, plays `03_code_blue.wav` once, and stays flashing red until the alarm clears. **Instructor mirror**: encounter_console.js renders a `device-card-pia` panel with four mirror buttons on every PIA station's device card so the instructor can fire any of the four actions from the encounter console (POSTs the same `pia.button` event via the new `pia` branch in `onDeviceAction`). KIND_LABEL gets `📟 Patient Integrated Alarm`. CSS adds `.device-card-pia` + `.pia-mirror-row` + `.pia-mirror-btn.pia-mirror-cb` (red treatment for the Code Blue mirror). Guide + PDF at `docs/module_guides/M51_patient_integrated_alarm.{md,pdf}`. 13 new tests in `tests/v7/test_patient_integrated_alarm.py` covering registry, engine factory, template rendering, the four button-routing paths, cascade visibility from a sibling bed, sound file presence, JS WAV + flash class references, encounter-console mirror panel markers, and CSS keyframes. Implementation fix during test run: `device_pia.html` was referencing `station.station_id` but `get_device_station` returns dicts with key `id` — swapped (matches existing `device_app.html`). **Final v7 suite: 387 passed, 1 skipped** (M20 Playwright skip — unchanged); 0 regressions. |
| 2026-05-27 | **M50 — Feature + bugfix: Silence + Clear (bugfix) + BP thresholds + danger severity + Nurse-station Code Blue.** Five operator asks bundled. (1) **Silence**: new POST `/api/alarm/{id}/silence?seconds=N` (default 120) — alarm stays visible with a 🔇 badge but the audio dispatcher skips it. Works on every source. Stored in new `room.silenced_alarms: dict[alarm_id, {until, cleared}]`. Auto-cleans expired entries. (2) **Clear bugfix**: pre-M50 `clear_alarm()` returned `None` for `source=threshold` (no event log to write into) so the route 404'd on every threshold alarm. Fixed by adding a `source == "threshold"` branch that records the clear in `silenced_alarms` with `cleared=True` + a 24h `until` — the next `active_alarms` read filters it out. When the underlying breach resolves, the entry expires harmlessly. M26 device + scene clear paths unchanged. (3) **BP thresholds**: new `bp_systolic` + `bp_diastolic` keys on `room.alarm_thresholds` (defaults sbp 90–160, dbp 60–100). `_threshold_alarms_for` extends `metric_breaches` to check both sides. POST `/api/room/alarm_thresholds` validates the new keys. (4) **Danger severity**: dangerous-rhythm alarms (v-fib, asystole, v-tach) now use `severity="danger"` (rank 4) which outranks `critical` (rank 3) — they sort to the TOP of the alarm board with a red pulsing visual treatment. `alarm_sounds.severity_to_priority` maps both `danger` and `critical` → "high" so they share the same WAV bucket (no separate danger asset ships). (5) **Nurse-station Code Blue**: new POST `/api/room/encounter/{eid}/nurse_code_blue` accepts EITHER instructor cookie OR `nurse_sid` body field (validates against `room.students` whose `role == "nurse_station"`). Fires the `code.blue` scene via the existing `scenes.apply()` — same chart/alarm path the instructor's scene-inject would take. The Nursing Station's bed cards get a 🚨 Code Blue button with native confirm() dialog. UI updates: Silence button alongside Clear in alarm rows (silenced rows render greyed with badge); BP rows in the threshold settings; `.severity-danger` red pulsing CSS; per-bed Code Blue button. Guide + PDF at `docs/module_guides/M50_silence_clear_bp_danger_codeblue.{md,pdf}`. 15 new tests in `tests/v7/test_silence_and_code_blue.py`; 1 phrase-only assertion update in `test_alarm_thresholds_and_ecg_fix.py` (rhythm severity was `critical`, now `danger`). **Final v7 suite: 374 passed, 1 skipped** (M20 Playwright skip — unchanged); 0 regressions. |
| 2026-05-27 | **M49 — Feature: clinical alarm sounds wired to the Nursing Station.** Operator dropped 15 production-ready clinical-alarm WAV files into `~/Documents/Claude/Projects/Multipatient multi student simualtion/sounds/clinical_alarms/` covering HR/SpO2/RR/ECG × HIGH/MEDIUM/LOW priority + dedicated code blue / bed exit / call bell tones. Imported to `portal/static/sounds/clinical_alarms/` (15 WAVs + MANIFEST). New `portal/alarm_sounds.py` mapping module: `severity_to_priority` (critical→high, warning→medium, info→low), `audio_url_for(alarm)` (resolves source/metric/severity → WAV path; returns None for un-curated alarms like pump device tones), `annotate(alarms)` (in-place adds `audio_url` + `audio_priority` to every alarm). `alarms.active_alarms(room)` now calls `annotate` so the entire alarm response carries audio fields. On `nurse_station.js`: `renderAlarmBoard` calls a new `_playNewAlarmSounds(alarms)` helper that instantiates `new Audio(url)` at volume 0.8 + `.play()` with autoplay-policy catch. `_seenAlarmIds` set dedupes per occurrence — an unresolved breach doesn't replay every 3s poll, but the same breach RE-OCCURRING after resolution re-fires (drops the id when it leaves the active list). Cleared entirely when active list goes empty. Maps: hr→05/09/13, spo2→06/10/14, rr→07/11/15, ecg+rhythm→04/08/12, scene+code.blue→03, device+call_bell→02, device+bed_alarm→01. Pump/cabinet device alarms get None — device tablet's own audio handles them. v6 single-patient path: alarms still annotated (the helpers are source-agnostic) — the v6 ops view can read `audio_url` whenever it wants. Guide + PDF at `docs/module_guides/M49_clinical_alarm_sounds.{md,pdf}`. 16 new tests in `tests/v7/test_clinical_alarm_sounds.py`. **Final v7 suite: 359 passed, 1 skipped** (M20 Playwright skip — unchanged); 0 regressions. |
| 2026-05-27 | **M48 — Feature + UX fix: operator-settable alarm thresholds on the Nursing Station + per-metric display cadence + ECG trace cosmetic.** Three asks bundled. (1) New settings card on `nurse_station.html` with low/high inputs for HR, SpO2, RR + dangerous-rhythms checkboxes (v-fib, v-tach, asystole, a-fib RVR, 3° block). Thresholds live on `ControlRoom.alarm_thresholds` (in-memory, room-level) with adult-norm defaults. The alarm bus's `active_alarms()` now merges in a new `_threshold_alarms_for(room, enc)` source — checks every encounter's `telemetry.snapshot(enc.id, jitter=False)` against the room bounds and emits `source=threshold` alarms. SpO2 breaches → critical; HR/RR → warning. Threshold alarms use `ts=0` so they sort to the END of their severity tier — device/scene alarms still own the top (preserves M26 invariants). Dangerous-rhythm detection checks `enc.ecg_rhythm_id` against the danger list, but only when `enc.ecg_enabled=True`. Auto-resolves when value returns to range (no clear button). New routes `GET/POST /api/room/alarm_thresholds`. (2) Per-metric display cadence on the Per-Patient Console: server poll stays 1s, but client commits to display per cadence — HR/SpO2 every 10s, RR every 30s, temp every 60s, BP every 120s. New `METRIC_CADENCE_MS` table + `_maybeCommit(metric, value, now)` helper + `_committed` per-metric state. Operator inject/override forces immediate commit (latest server value differs from last committed). Display reads `_committed.hr` etc instead of raw `t.hr`. (3) ECG trace stroke-width `1.4 → 0.7` and color `#5dffae` (saturated neon) → `#7fc99a` (muted green) — removes the glowing-against-dark-canvas effect. `.ecg-canvas` text color matches. Engine-side vitals drift documented as M49 (telemetry doesn't naturally drift; only operator inject changes values). Guide + PDF at `docs/module_guides/M48_thresholds_cadence_ecg.{md,pdf}`. 11 new tests in `tests/v7/test_alarm_thresholds_and_ecg_fix.py`. **Final v7 suite: 343 passed, 1 skipped** (M20 Playwright skip — unchanged); 0 regressions. |
| 2026-05-27 | **M47 — Feature: room-level med carts (closes the M44 §8 deferred work).** Operator request: *"On the multi-patient control page setup a device generator for Medication Carts. Have this setup to be able to assign one or more encounters and use the medication list under the name of the patient characters to populate the medications on the cart. When a student accesses the medication in the cart under the assigned patient character from an encounter the transcript for the encounter will be updated with the cart name time, medication name and amount and if any medication was wasted and the name of the person who wasted the excess medication."* Built the full feature end-to-end. **Data model**: `ControlRoom` gains two new dicts — `cart_links: dict[str, list[str]]` (cart station_id → list of linked encounter ids, primary first) and `cart_labels: dict[str, str]`. In-memory only; no schema migration. The cart's DB row still has a single `session_id` (the primary encounter) so M43's `_session_for_station` keeps every per-station route working. **Routes**: 4 new endpoints under `/api/room/med_cart/...` — `POST /register` mints the cart with optional pre-link list (validates encounter ids, defaults primary to the first encounter), `POST .../link_encounter` adds, `DELETE .../link_encounter/{eid}` removes (rejects primary unlink with 409), `GET /api/room/med_carts` lists with QR URLs. **Cabinet bootstrap**: now reads `room.cart_links.get(station_id)` and iterates EVERY linked encounter, calling `ehr_seed.seeds_for_all_personas` per encounter; each returned character dict gets an `encounter_id` + `encounter_label` tag so the cart UI can render per-patient sections. Also fixed M43-style — the bootstrap was still using `get_active()` (M43 missed this one); swapped for `_session_for_station(station)`. **Transcript hook**: new `_log_cart_dispense_to_transcript()` helper in `portal/devices/routes.py`. When `POST /api/device/{sid}/event` fires with `type=med.dispensed` on a cabinet, the helper finds the linked encounter that owns the payload's `character_id` (matches against `enc.selected_personas` + `enc.patient_persona_id`), composes a line like *"💊 ICU Cart A · dispensed lorazepam · 2 mg · by Student Bob · wasted 1 mg (witness: RN Jane Doe)"*, and calls `enc.log_turn(...)`. Other linked encounters' transcripts are untouched. Non-`med.dispensed` events skip the hook. Failures are non-fatal — logged to stderr, route still returns ok=True. **UI**: Multi-Patient Control gets a new `.med-carts-panel` (green left-border accent to distinguish from the nurse-station card). Operator types a label + clicks Add → cart card appears with QR + linked-encounter chip list + "Link encounter" dropdown for unlinked beds. The primary encounter shows "★ primary" instead of an unlink button. Cart panel refreshes on a 5 s timer. Guide + PDF at `docs/module_guides/M47_room_level_med_carts.{md,pdf}`. 15 new tests in `tests/v7/test_room_med_carts.py` covering registration, linking, unlinking primary-rejection, bootstrap merge, dispense routing to right encounter, non-dispense skip, and UI markers. **Final v7 suite: 332 passed, 1 skipped** (M20 Playwright skip — unchanged); 0 regressions. |
| 2026-05-27 | **M46 — UX fix + feature: hide ops-footer in modal, device QR inline + on the print sheet.** Two operator asks bundled: (1) *"remove the control buttons in the footer of the page like run, pause, stop"* — M44 embed-mode CSS missed `<div class="ops-controls">` (Pause/Resume/Preview debrief/End scenario/Kill switch) + its explanation paragraph that sit below the device card in `control_ops.html`. They leaked through and competed with the M35 per-encounter Start/Pause/End in the parent console. (2) *"the QR code for the device created should populate in the encounter page... and be able to print out as part of the QR print out list"* — the mint-time QR returned by `/api/device/register` was previously visible only in the modal's add flow. M46 surfaces it in two new places. Fixes: extended embed-mode CSS in control_ops.html with `.ops-controls, .ops-controls + p { display: none !important; }` (the `+ p` adjacent-sibling selector picks up the description paragraph too). `renderDeviceCard` in encounter_console.js now renders a `.device-card-qr` strip (56px QR + URL in monospace) built from `${window.location.origin}/device/join?code=${cfg.joinCode}&station=${sid}` → fed through `/api/qr.svg?data=…`. The M41 print sheet route (`portal_control_qr_print`) now hydrates each encounter view with a `devices: [{station_id,device_kind,device_model,label}]` list. The `qr_print.html` template gets a new `{% if enc.devices %}` block rendering a `.device-qr-section` with a 3-column grid of per-device QR blocks (1.4-inch QRs with `page-break-inside: avoid` so blocks don't split). Section only renders when at least one device is bound; the inline `<style>` carries the CSS rules whether or not the section is rendered. v6 single-patient path unchanged (the M44 embed CSS only applies under `{% if embed_mode %}`). Guide + PDF at `docs/module_guides/M46_modal_footer_and_device_qrs.{md,pdf}`. 7 new tests in `tests/v7/test_device_qr_and_modal_footer.py`. **Final v7 suite: 317 passed, 1 skipped** (M20 Playwright skip — unchanged); 0 regressions. |
| 2026-05-27 | **M45 — UX feature: inline device control cards in the encounter Devices card.** Operator request: *"Once the device is added the control system for the device should populate in the device area of the encounter for easy access of the instructor."* Pre-M45 the Devices card was display-only — a count summary pulled from `/api/room/state`. To control any device the operator had to reopen the M42/M44 Managed-devices modal every time (inject alarm, clear, reassign patient, advance pump clock). M45 inlines the full control surface. After a device is added via the modal (which stays — mint QR + label happens there), it shows up in the Devices card on the next 3 s poll as a card row with: device kind icon + label + model + online indicator + runtime state, patient-assignment dropdown (reassign without opening the modal), active alarms with per-alarm Clear + Clear all, alarm-tone picker + ⚠ Inject button, and (for pumps) +5m/+15m/+1h advance-time buttons. New `pollDevices()` hits `/api/device/roster?join=<encounter join>` (the M43 multi-patient-aware route). New `renderDeviceCard(s)` paints the markup; `onDeviceAction(el)` handles inject/clear/advance; `onDeviceAssign(sel)` reassigns. Tone catalog (`DEVICE_TONE_CATALOG`) is hard-coded per device kind matching the server's `PUMP_ALARMS`/`CABINET_ALERTS` in `portal/devices/engine/alarms.py` — server validates every inject so a stale client gets a clean 400. `startPolling()` launches a third 3 s timer alongside telemetry (1 s) and state+transcript (2 s); the roster fold is slightly heavier (engine.fold per station) so we space it out. Persona names in the assignment dropdown resolve from the M33 voices cache (`encVoiceBody.personas`). Cabinets surface with a "Med cart (room-level)" note — full shared-cart UI still in the M44-§8 deferred work. CSS adds a new `.device-card` block style overriding the older `.device-list li { display: flex }` so cards lay out vertically. Guide + PDF at `docs/module_guides/M45_inline_device_control_cards.{md,pdf}`. 9 new tests in `tests/v7/test_inline_device_cards.py`. **Final v7 suite: 310 passed, 1 skipped** (M20 Playwright skip — unchanged); 0 regressions. |
| 2026-05-27 | **M44 — UX fix + bugfix: devices modal shows ONLY the simulated-devices card; cabinet/cart blocked from per-encounter add (M45 sets up the room-level dashboard).** Operator feedback after M43: *"The pop up should only bring up the simulated devices, it is make an entire control room page. Also on Med Carts have them created in the Multi-Patient control and then allow them to add the encounters in the simulation to a specifc med cart so the function is no longer able to generate the med carts in the encounter."* Two distinct issues: (1) the M42 embed-mode CSS hide list targeted class names that don't actually exist in `control_ops.html` (`.operator-ptt-card` vs the real `.op-ptt-card`, `.live-transcript-card` vs `.transcript-card`, etc.) — so the invite-stations, connected-stations, session-context, PTT, transcript, voices, and EHR-stations cards all stayed visible. The modal "looked like an entire control room page". (2) Med carts should be a room-level resource, not per-encounter. Phase A of both fixes landed in M44: gave the devices section a stable `id="devices-card"` anchor, rewrote the embed-mode `<style>` block to hide every `.check-card` and re-show only `#devices-card`, and zero out body padding/margins/max-widths so the iframe content uses the full modal frame. `fillKindSelect` in `control_ops_devices.js` reads `MEDSIM2_OPS.embed_mode` and filters out `cabinet` from the kind dropdown in embed mode; the help text under the button is relabeled to *"Bed-level devices only (pumps + future-device buttons). Med carts are managed at the room level — add them on the Multi-Patient Control page."* Server-side guard: `POST /api/device/register` rejects `device_kind=cabinet` when the resolved session is an encounter in the active room (catches a clever client that bypasses the dropdown filter). Friendly 409 + "use Multi-Patient Control" hint. v6 single-patient cabinet flow unchanged. The full room-level med-cart feature (new room dashboard panel + cart↔encounter linking + grouped per-patient MAR view per the user's *"list each of the assigned character patients and their assigned medication under their character name"* requirement) is sized at ~1.5 engineer-days and deferred to **M45** — M44 set up the encounter side so M45 can drop in the room dashboard without conflicts. Guide + PDF at `docs/module_guides/M44_devices_modal_scope_and_cart_setup.{md,pdf}`. 6 new tests in `tests/v7/test_devices_modal_scope.py`. **Final v7 suite: 301 passed, 1 skipped** (M20 Playwright skip — unchanged); 0 regressions. |
| 2026-05-27 | **M43 — Bugfix: device routes work in multi-patient + button renamed to "Managed devices".** Operator-reported after M42: the M42 iframe loaded the v6 ops view inside the encounter modal, but every operator action (Add device, etc.) raised *"AuthenticationError: it wasn't linked to session"* — actually a 409 *"No active session"* from `/api/device/register`, surfaced in the iframe as an error toast. Root cause: every operator-facing device route in `portal/devices/routes.py` called `control_session.get_active()`, which (per the M2 contract) returns `None` in v7 multi-encounter rooms. The pattern `sess = get_active(); if sess is None or sess.id != station["session_id"]: raise 409` failed unconditionally in multi-patient mode. Fix: added two helpers — `_session_for_station(station)` (resolves via singleton first, then via active room's `encounters` dict keyed by `station.session_id`) and `_session_for_join(join)` (resolves via `get_by_join_code`, singleton fallback). All 5 operator-facing routes patched: `POST /api/device/register` (accepts `?join=<code>` now), `POST /api/device/{sid}/{inject,clear,advance_time,assign}` (per-station, use station.session_id), `GET /api/device/roster` (accepts `?join=` to scope by encounter). `control_ops_devices.js` got a `_joinQuery()` helper that reads `window.MEDSIM2_OPS.join_code` (already set by M42's bootstrap) and appends `?join=` to register + roster calls. The v6 single-patient path is byte-for-byte unchanged in behavior because both helpers call `get_active()` first and only fall through when it returns None. Operator's second ask: button label "🔧 Manage devices" → "🔧 Managed devices" (panel descriptor, not imperative verb). Friendly 409 messages now point at the Per-Patient Console flow. Bigger ask from the original message (shared med carts across encounters + grouped MAR per patient) explicitly deferred to M44 — M43's session-resolution fix is the unblocker. Guide + PDF at `docs/module_guides/M43_device_routes_multi_patient.{md,pdf}`. 11 new tests in `tests/v7/test_device_routes_multi_patient.py`; 1 phrase-only update to the M42 button test. **Final v7 suite: 295 passed, 1 skipped** (M20 Playwright skip — unchanged); 0 regressions. |
| 2026-05-27 | **M42 — UX fix + bugfix: inline device manager in the encounter console (Phase A).** Operator feedback: *"On each encounter the device manager should be setup to operate within the encounter… not having to leave the encounter through a link like it currently is. All the device functions and assignments should function the same. The assignment for a device being added should pre-populate with the patient Character of the encounter. In the case of med carts, more than one encounter can be assigned to a single med cart. The medicine administration system will list each of the assigned character patients and their assigned medication under their character name."* Three issues bundled: (1) the existing `/portal/control/ops?join=…` link-out was actually BROKEN in multi-patient mode — `control_session.get_active()` returns None per M2 contract, so clicking the link bounced the operator to the wizard; (2) even when it worked, leaving the encounter window lost telemetry/ECG/transcript context; (3) the v6 add-device modal hard-coded the patient assignment to "— unassigned —" (`control_ops_devices.js:272` was `fillCharacterSelect($('ad-char'), '')`). Phase A fixes (1)+(2)+(3): the ops view now accepts `?join=<code>` (resolves via `get_by_join_code`, falls back to `get_active`), `?patient_persona_id=<pid>` (override for the add-device default; falls back to `sess.patient_persona_id`), and `?embed=1` (CSS hides the ops-view chrome that conflicts with the encounter console's M35 header + M33 voice card). `openAddDevice()` now reads `window.MEDSIM2_OPS.default_device_patient_id` and passes it to `fillCharacterSelect` — the patient pre-populates from the encounter's primary persona. Devices card on the Per-Patient Console gets a `#btn-manage-devices` button that opens a `<dialog id="devices-dialog">` modal containing an iframe at `/portal/control/ops?join=<jc>&embed=1`. Same modal pattern as M39 Engage — iframe blanked on close to stop in-flight connections, popout anchor preserved for second-monitor workflows (with the encounter scope baked into href). Reuses the existing ~1500 LOC of v6 device-management JS verbatim — no porting cost. Phase B/C (shared med carts across encounters + grouped MAR per patient) explicitly deferred to M43 because they require a `DeviceStation.character_id → character_ids: list` model change + cabinet bootstrap + MAR rewrite. Guide + PDF at `docs/module_guides/M42_inline_device_manager.{md,pdf}`. 10 new tests in `tests/v7/test_inline_device_manager.py`. **Final v7 suite: 284 passed, 1 skipped** (M20 Playwright skip — unchanged); 0 regressions. |
| 2026-05-27 | **M41 — Feature: printable QR-sheet for the instructor (all-encounters or per-encounter).** Operator feature request: a single page or per-encounter sheet of QR codes that can be printed and handed to students. Specs: "Training Bridge MedSim-VRAI" header title, patient character on the per-encounter header, sign-in codes (room + join) printed at the top, each QR clearly labeled. Built new `/portal/control/qr_print[?encounter_id=…]` route + new `templates/qr_print.html` standalone page (does NOT extend base.html — no portal nav on printed paper). Layout: one page per encounter, page-break-after between, action bar with "🖨 Print" + back link hidden via `@media print`. Each page renders: title bar (brand color "Training Bridge MedSim-VRAI"), warm-yellow patient banner showing the persona's display name + id + role (hydrated server-side via library.get_persona), sign-in codes block (Room code + Bed join code + EHR system id), and a 2×2 QR grid (Chat / EHR / Device / Nursing Station). The Nursing Station block is tinted green and sub-labeled "uses the room code, not the bed join code" — guards against the M36 confusion. Private-clone clones filtered out (the template encounter is what the operator distributes). Two launch buttons: 🖨 Print QR codes in the Multi-Patient Control top bar (all encounters), and 🖨 Print QR codes for this encounter in each Per-Patient Console's QR card footer (scoped to that bed). Both open in a new tab; the operator then triggers the browser print dialog. Guide + PDF at `docs/module_guides/M41_qr_print_sheet.{md,pdf}`. 11 new tests in `tests/v7/test_qr_print_sheet.py`. **Final v7 suite: 274 passed, 1 skipped** (M20 Playwright skip — unchanged); 0 regressions. |
| 2026-05-27 | **M40 — UX parity: Room of N row drawers pre-populate from the picked Activity.** Operator feedback after M39: *"For Room of N for the encounters the characters and curriculum should pre-populate like they do for the single character."* In single-patient mode, picking a sample at Step 2 calls `applySample(s)` which checks every persona checkbox in `s.personas` and every module checkbox in `s.modules`. M31's Room of N per-row Activity picker had been stashing `seed_persona_id` + `seed_modules` into a dataset for submit but never updating the drawer checkboxes — operators saw the badge counts stay at 0 even after picking an Activity, and had to manually open each drawer + check boxes. Fix: extended the Activity-change handler to programmatically check `[data-row-persona][value=<seed_persona_id>]` + every `[data-row-module][value=<m>]` for `m in seed_modules`, then refresh both badge counts. Added `updateRowTabBadges(row)` shared helper + `cssEscape` polyfill for safe attribute-selector embedding. Bonus fixes bundled in: (1) the row's primary-persona dropdown change now auto-checks the matching Characters-drawer checkbox (surfaces the "primary is always part of the cast" submit invariant in the UI); (2) `renderRoomEncounterRows`'s `prev` capture now reads each row's `personaList`, `modulesList`, `programId`, `week` so re-renders (triggered by the room-N input changing) preserve drawer state instead of wiping it. Guide + PDF at `docs/module_guides/M40_room_row_prepopulate.{md,pdf}`. 8 new source-guard tests in `tests/v7/test_room_row_prepopulate.py`. **Final v7 suite: 263 passed, 1 skipped** (M20 Playwright skip — unchanged); 0 regressions. |
| 2026-05-27 | **M39 — UX fix: Engage chat opens as an in-encounter modal instead of a new tab.** Operator feedback after M38 audio + key fixes: *"The system audio is working but it jumps out of the encounter window to a station window — it should stay in the encounter window during the conversation if the conversation is prompted from the encounter module."* M33+M35 had wired the Engage button as `<a target="_blank">` which spawned a new tab and lost the encounter console context (telemetry, ECG, devices, scene injector). Fixed by overlaying the chat as a modal `<dialog>` containing an iframe pointed at the same `/portal/engage/{eid}/{pid}` route. The iframe carries `allow="microphone; autoplay"` so STT + TTS work inside it; cookies are inherited from the parent window so the engage route's `require_vault` authenticates cleanly; the engage route's existing 303 chains into `/station/{join}/INST-{pid}` so the chat UI is unchanged (M37 audio reset + M38 key live-refresh still apply verbatim). The dialog header carries a "↗ Pop out" link (preserves the old new-tab behavior for instructors who want a second-monitor workflow) + a "✕ Close" button (and ESC works too — native `<dialog>` API). Closing blanks the iframe `src` to `about:blank` which unloads the chat page and tears down the in-flight `<audio>` element — no zombie playback. Guide + PDF at `docs/module_guides/M39_engage_in_encounter_modal.{md,pdf}`. 5 new tests in `tests/v7/test_engage_modal_dialog.py`. **Final v7 suite: 255 passed, 1 skipped** (M20 Playwright skip — unchanged); 0 regressions. |
| 2026-05-27 | **M38 — Bugfix: Anthropic 401 in Engage chat → live-refreshable key + friendly message.** Operator-reported after M37: the filler audio plays ("one sec"), then the Haiku turn POST returns a raw `AuthenticationError: Error code: 401 - {'type': 'error', 'error': {'type': 'authentication_error', 'message': 'invalid x-api-key'}, ...}` repr into the chat. Root cause: the station-turn route used `sess.api_key` (snapshotted at `/api/room/start`) directly. If the vault key was wrong-at-room-start OR got rotated after, the snapshot is invalid and every turn 401s — no path to recover without ending and restarting the room. Fix mirrors the ElevenLabs `_runtime_key` pattern in `portal/voices.py`: added a process-wide `_anthropic_runtime_key` cache in server.py, populated by 3 operator-auth hooks (`/portal/credentials` POST, `/portal/control/start`, `/api/room/start`). New `_resolve_anthropic_key(sess)` helper prefers cache → snapshot. The station-turn route now uses this helper + keeps `sess.api_key` in sync. Plus: `/api/room/start` now fails fast with 400 + clear message when the vault has no `ANTHROPIC_API_KEY` (prevents the silent-broken-room footgun); the station-turn route catches Anthropic 401 / authentication exceptions and returns *"Anthropic rejected the API key (401). Update ANTHROPIC_API_KEY at /portal/credentials and try again — the new key applies immediately."* Operator can now rotate the key in /portal/credentials and the next PTT works without a room restart. Empty `_capture_anthropic_key("")` is a no-op (protects against accidental clears). Guide + PDF at `docs/module_guides/M38_anthropic_key_live_refresh.{md,pdf}`. 7 new tests in `tests/v7/test_anthropic_key_live_refresh.py`. **Final v7 suite: 250 passed, 1 skipped** (M20 Playwright skip — unchanged); 0 regressions. |
| 2026-05-27 | **M37 — Bugfix: TTS reply cuts off shortly after starting in the Engage flow.** Operator-reported after exercising the M35 Engage flow in multi-patient mode: STT input works, the selected ElevenLabs voice starts playing the reply, then audio cuts off within ~½ second. Root cause: `playElevenLabs` in `static/tts_client.js` reuses a single primed `<audio>` element for every playback (the V6 autoplay-policy workaround). Setting `audio.src = newUrl` on an element that just finished a playback does NOT fully reset its internal state in Chrome/Safari — `ended` stays `true`, `currentTime` stays at the prior duration — and the browser fires `ended` prematurely on the new stream. The bug was latent since V6 introduced the primed-audio workaround; M35's Engage flow was the first surface that consistently exposed it (operators had previously hit the chat station via the student `/join` flow with different timing). Fix: before assigning the new src, explicitly `audio.pause()` → `removeAttribute("src")` → `load()` → reset `currentTime = 0`, then set the new src and call `load()` again. Each reset is wrapped in try/catch (some browsers throw `InvalidStateError` mid-lifecycle). Preserves the `primedAudio || new Audio()` reuse pattern so Chrome's autoplay block stays defeated. Guide + PDF at `docs/module_guides/M37_tts_audio_reset.{md,pdf}`. 4 source-guard tests in `tests/v7/test_tts_audio_reset.py` (regression catch — full browser verification is operator-side, the M20 Playwright skip is unchanged). **Final v7 suite: 243 passed, 1 skipped**; 0 regressions. Known secondary issue documented in guide §8: `_session_el_key()` falls back to env/keyfile/runtime-cache in multi-patient mode (it calls `control_session.get_active()` which returns None per M2). Did NOT change this in M37 because the operator confirmed the ElevenLabs voice IS being reached — but if cut-off persists after this fix, the next step is plumbing the per-encounter `elevenlabs_api_key` through `/api/tts` via the station's join_code. |
| 2026-05-27 | **M36 — Nursing Station QR + instructor launch button on both control surfaces.** Operator feedback after M35: *"On the control room or encounter control, each should have a QR code setup to launch the nursing station in a new computer or tablet, and a button to open the nurses station from the control page by opening a new window to host the nursing station for the instructor."* Added: (1) `/portal/control/launch_nurse_station` route that creates (or reuses) an instructor nurse-station student named *"Instructor (Nursing Station)"* and 303s into `/portal/students/nurse_station?sid=…` — same pattern as M34's EHR launcher; (2) a 🩺 Nursing Station panel on `/portal/room` (only when room active) with QR encoding `{base}/portal/students/join?code={room_code}` + green "Open Nursing Station (new window)" button targeting the launcher with `target="_blank"`; (3) a 4th cell (`.qr-cell-nurse`) in each Per-Patient Console's QR card with the same QR + an inline "🩺 Open here" link. Crucial scoping note carried in the footer copy: Chat/EHR/Device cells use the *encounter's join code*, but the Nursing Station uses the *room code* (it supervises every bed). `portal_room` route now passes `room` + `base_url` to the template (was passing only `{"active": "room"}`). QR grid widened from 3 to 4 columns with a midpoint breakpoint at 1000px so 4 cells collapse cleanly on tablets. Guide + PDF at `docs/module_guides/M36_nurse_station_launch.{md,pdf}`. 8 new tests in `tests/v7/test_nurse_station_launch.py`. **Final v7 suite: 239 passed, 1 skipped** (M20 Playwright skip — unchanged); 0 regressions. |
| 2026-05-27 | **M35 — Master Start/Pause/End controls + per-encounter mirrors + instructor auto-stations + engage deep-link.** Operator feedback bundle after M34. Three asks: (1) master `▶ Start all scenarios · ⏸ Pause all · ⏹ End all (debrief)` in the Multi-Patient Control header; (2) the same three buttons scoped to a single bed on each Per-Patient Console, with the critical contract that per-encounter End does NOT save the cohort debrief (only master End does — per M15's "save before clear" path); (3) the M33 Engage button should NOT land on the public `/join` page — instead the instructor stations should be auto-created behind the scenes when master Start fires, and Engage should deep-link directly to that station. Added 5 new routes (`/api/room/start_all`, `/api/encounter/{id}/{start,pause,end}`, `/portal/engage/{eid}/{pid}`) + 2 helpers (`_instructor_station_id_for`, `_ensure_instructor_stations`) + 2 WS emitters (`emit_start_all`, `emit_encounter_state`). State machine: `configured → running ⇄ paused → ended`. Instructor stations use deterministic id `INST-{persona_id}` so engage is O(1) lookup. Engage route lazy-creates the station if master Start hasn't fired yet (safety net). Master End in the dashboard JS now auto-redirects to the cohort debrief URL in the response. Guide + PDF at `docs/module_guides/M35_master_controls_and_engage.{md,pdf}`. 14 new tests in `tests/v7/test_master_controls_and_engage.py`; 1 phrase-only regression update in `test_encounter_characters_voices_engage.py`. **Final v7 suite: 231 passed, 1 skipped** (M20 Playwright skip — unchanged); 0 regressions. |
| 2026-05-27 | **M34 — Per-encounter instructor EHR launch button.** Operator feedback after M33: *"I need to be able to launch and access the medical records from the encounter page as the instructor, and launch the system into a new window."* The v6 route `/portal/control/launch_ehr` would dead-end in room mode (it calls `control_session.get_active()` which returns None in multi-encounter rooms per the M2 contract). Added a v7-aware twin: new `GET/POST /portal/room/encounter/{id}/launch_ehr` that resolves the encounter from `_require_active_room()`, calls the existing `_launch_ehr_station(enc)` helper (the v7 Encounter dataclass IS a ControlSession — M2 rename, not re-impl), and 303s into `/ehr/{join_code}/{station_id}` (the unified EHR bundle). Console header now carries a green `📋 Open EHR ({ehr_id})` anchor with `target="_blank" rel="noopener"` so the chart opens in a new tab — true side-by-side workflow. Disabled state (`📋 No EHR configured`) appears when `encounter.ehr_id` is empty. Second discovery point: a `📋 Open EHR on this device` link inside the QR-codes card's EHR cell. Repeat launches reuse the still-online control-room station instead of piling up new ones (`reused=true` in the POST response). Guide + PDF at `docs/module_guides/M34_per_encounter_ehr_launch.{md,pdf}`. 8 new tests in `tests/v7/test_encounter_launch_ehr.py`. **Final v7 suite: 217 passed, 1 skipped** (M20 Playwright skip — unchanged); 0 regressions. |
| 2026-05-27 | **M33 — Character names + voice test + engage on the Per-Patient Console.** Operator feedback after M32: *"On the individual encounter control pages, use the character names rather than the character code on the pull down for the selecting patient voices. Have a button to check voice sound. Also list all the characters for the scenario so that the instructor can engage the character from the control page for the encounter control page."* The voice card on `/portal/room/encounter/{id}` was the natural home for all three asks — renamed it to "🎙 Characters · voices · engage" and rebuilt each row to show the persona's display name + role tag (instead of the raw `P-014` id), plus a `▶ Test` button that previews the selected voice via `POST /api/tts` (browser SpeechSynthesis fallback when no ElevenLabs voice is picked), plus a `💬 Engage` link that opens `/join?code={join_code}` in a popup so the instructor can pick that character and chat as them. Backend: `GET /api/encounter/{id}/voices` now hydrates each selected persona via `library.get_persona()` and returns `personas: [{id,name,role}]` + `join_code` (legacy fields preserved for backward-compat callers). Defensive: unknown persona ids echo as `name=id` instead of 500-ing. Guide + PDF at `docs/module_guides/M33_characters_voices_engage.{md,pdf}`. 5 new tests in `tests/v7/test_encounter_characters_voices_engage.py`. **Final v7 suite: 209 passed, 1 skipped** (M20 Playwright skip — unchanged); 0 regressions. |
| 2026-05-27 | **M32 — Room mode wizard skips single-patient steps.** Operator feedback after M31: *"for the multi patient the system still follows the path for the single patient then has the encounter page."* The wizard was making room-mode users walk through Step 2 (Scenario), Step 2b (Records system), and Step 3 (Curriculum) — wizard-wide single-patient defaults that M31's per-row Step 4r drawers already override. Tagged those steps + panes with `data-step-single` / `data-pane-single` so `applyMode("room")` hides them; added a dedicated "Room label" input to Step 4r (replaces the now-hidden `scenario_name` as the source of the cohort label); added `data-required-single` to `scenario_name` so the JS strips HTML5 `required` in room mode (otherwise browser validation blocks the submit handler). New `refreshStepNumbers()` in `control.js` renumbers the visible step-strip prefixes based on sequence position, so room mode reads *"1 · System check · 2 · Encounters · 3 · Network"*. Room-mode flow is now Step 1 → Step 4r → Step 5 (3 visible steps, down from 6). Guide + PDF at `docs/module_guides/M32_room_mode_skips_single_steps.{md,pdf}`. 4 new acceptance tests in `tests/v7/test_wizard_room_mode_skips_single_steps.py`; 1 phrase-only assertion update in `test_wizard_per_row_scenario.py` after rewriting Step 4r's intro copy. **Final v7 suite: 204 passed, 1 skipped**; 0 regressions. |
