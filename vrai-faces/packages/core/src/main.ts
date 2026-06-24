// VRAI Faces app entry. Boots every module, mounts the renderer to
// #stage, and brings up a translucent demo avatar so the user has
// something to see and a slider to drive end-to-end.
//
// When MedSim binds a real character (via medsim_adapter), the demo
// avatar is replaced. For now, the demo IS the avatar.

import { animationRuntime } from './modules/animation_runtime';
import { audioPipeline } from './modules/audio_pipeline';
import { diagnosticPanel } from './modules/diagnostic_panel';
import { idleMotion } from './modules/idle_motion';
import { memoryState } from './modules/memory_state';
import { medsimAdapter } from './modules/medsim_adapter';
import { shaderTranslucent } from './modules/shader_translucent';
import { faceIngest } from './modules/face_ingest';
import { meshBuilder } from './modules/mesh_builder';
import { diag } from './perf/diag';
import { installPerfProbe } from './perf/probe';
import { installFirstGestureWarmup } from './shell/firstGesture';
import { installVisibilityWatch } from './shell/visibilityWatch';
import { parseLaunchUrl } from './shell/parseLaunchUrl';
import { registerResumableHooks } from './shell/registerLifecycles';
import { mountRenderer } from './shell/renderer';
import { bootDemoAvatar } from './shell/demo_boot';
import { buildAvatarFromBlob, type BuiltAvatar } from './shell/avatar_build';
import { bindForAudio, bindFromPortal, clearBindingCache } from './shell/portalBinding';
import { mountAudioStation, noopAnimSink } from './shell/audio_station';
import { installSpeechConsumer } from './shell/speechConsumer';
import { lazyEmotion, lazyTts } from './shell/lazy';
import { mountTranslucencySlider } from './shell/translucency_slider';
import { mountImportControl } from './shell/import_control';
import { mountSaveControl } from './shell/save_control';
import { mountDeviceVoice } from './shell/device_voice';
import { mountDebugConsole } from './shell/debug_console';
import { isDebugEnabled } from './shell/debug';

/** No-WebGPU-adapter tablets (e.g. many Android) expose `navigator.gpu` but
 *  `requestAdapter()` returns null. The ONNX runtime behind on-device STT probes
 *  navigator.gpu during init, and that failed probe blocks its WASM CPU backend
 *  from registering ("no available backend found"). If there's no real adapter,
 *  hide navigator.gpu BEFORE anything imports the runtime, so STT takes the WASM
 *  path cleanly. The avatar renderer already falls back to WebGL2 here, so this
 *  changes nothing for rendering. Best-effort; runs once at boot. (ADR-0026) */
async function hideDeadWebGpu(): Promise<void> {
  try {
    const nav = navigator as Navigator & { gpu?: { requestAdapter(): Promise<unknown> } };
    if (!nav.gpu) return;
    let adapter: unknown = null;
    try { adapter = await nav.gpu.requestAdapter(); } catch { adapter = null; }
    if (adapter == null) {
      Object.defineProperty(nav, 'gpu', { configurable: true, value: undefined });
      diag.push({ t: performance.now(), moduleId: 'shell.boot', kind: 'info',
        message: 'no WebGPU adapter — hid navigator.gpu so STT uses the WASM backend' });
    }
  } catch { /* best-effort */ }
}

async function boot(): Promise<void> {
  if (isDebugEnabled()) mountDebugConsole(); // 🐞 on-device console — only with ?debug
  await hideDeadWebGpu(); // must run before the renderer / transformers import
  const launch = parseLaunchUrl(window.location);
  const scenarioId  = launch?.scenarioId  ?? 'default';
  const characterId = launch?.characterId ?? 'default';

  // Phase 5.7 — fast startup + home-screen install for dedicated tablets:
  //  - name the home-screen icon per character (Add-to-Home-Screen reads the title),
  //  - register the unified app SW (app-shell cache + Kokoro passthrough) early so
  //    the shell caches on first load, and
  //  - request persistent storage so the cache survives restarts.
  // All best-effort — a failure here never blocks boot.
  if (characterId && characterId !== 'default') document.title = `VRAI · ${characterId}`;
  if ('serviceWorker' in navigator) {
    void navigator.serviceWorker.register('/app-sw.js').catch(() => { /* non-fatal */ });
  }
  if (navigator.storage?.persist) {
    void navigator.storage.persist().catch(() => { /* non-fatal */ });
  }
  // Manual "forget faces" (ADR-0027): `?forget` clears the cached skin/binding
  // before re-binding fresh — for handing a tablet on or re-pointing it.
  if (new URLSearchParams(window.location.search).has('forget')) {
    await clearBindingCache();
  }

  const deps = { diag, scenarioId, characterId };

  // FR-009 H4 — post-handoff VERBAL SURVEY (`?survey=1`): the station switches to
  // a voice questionnaire (answers ride the room-STT path, same as the audio
  // station). No 3D rig, no avatar. The instructor directs the tablet here after
  // the handoff; results land in the debrief (perception-vs-performance).
  if (new URLSearchParams(window.location.search).get('survey') === '1') {
    const surveyEl = document.getElementById('app') ?? document.body;
    if (launch?.apiBase) {
      const { mountSurveyStation } = await import('./shell/survey_station');
      mountSurveyStation(surveyEl, {
        apiBase: launch.apiBase, characterId, scenarioId,
        ...(launch.token ? { token: launch.token } : {}),
      });
    } else {
      surveyEl.textContent = 'Survey needs a portal connection (missing api= in the URL).';
    }
    return;
  }

  // FR-006 — AUDIO-ONLY station (`?mode=audio`): flat static portrait + the full
  // voice loop, no 3D rig / WebGPU / mesh pipeline. Boots only what it needs and
  // returns before any renderer work. Default for non-patient characters.
  if (launch?.mode === 'audio') {
    await Promise.all([
      audioPipeline.boot(deps),
      medsimAdapter.boot(deps),
      diagnosticPanel.boot(deps),
    ]);
    installFirstGestureWarmup();
    const appEl = document.getElementById('app') ?? document.body;
    const station = mountAudioStation(appEl, characterId);
    if (launch.apiBase) {
      mountDeviceVoice(appEl, {
        apiBase: launch.apiBase,
        characterId,
        scenarioId,
        wakeName: characterId,
        ...(launch.token ? { token: launch.token } : {}),
      });
    }
    installSpeechConsumer({
      adapter: medsimAdapter,
      audio: audioPipeline,
      anim: noopAnimSink(),          // no face — visemes/emotion are discarded
      loadTts: () => lazyTts().then((m) => m.ttsProvider),
      voice: () => medsimAdapter.currentBinding()?.voiceProfile,
    });
    const binding = await bindForAudio(launch, medsimAdapter);
    if (binding) {
      station.setCharacter({
        name: binding.displayName ?? binding.characterId,
        portrait: binding.sourcePhoto,
      });
    } else {
      diag.push({
        t: performance.now(), moduleId: 'main', kind: 'warn',
        message: 'audio station: portal bind failed — voice loop still live, portrait absent',
      });
    }
    diag.push({
      t: performance.now(), moduleId: 'main', kind: 'info',
      message: `VRAI audio-only station booted. scenarioId=${scenarioId} characterId=${characterId}`,
    });
    return;   // the entire 3D path below never runs in audio mode
  }

  await Promise.all([
    faceIngest.boot(deps),
    meshBuilder.boot(deps),
    shaderTranslucent.boot(deps),
    animationRuntime.boot(deps),
    audioPipeline.boot(deps),
    idleMotion.boot(deps),
    medsimAdapter.boot(deps),
    diagnosticPanel.boot(deps),
    memoryState.boot(deps),
  ]);

  registerResumableHooks();
  installVisibilityWatch();
  installFirstGestureWarmup();

  // Restore prior session if there is one.
  await memoryState.resumeAll(scenarioId, characterId);

  // Mount the renderer to the #stage canvas.
  const canvas = document.getElementById('stage') as HTMLCanvasElement | null;
  if (!canvas) throw new Error('main: #stage canvas not found');
  const renderer = await mountRenderer(canvas);
  const app = document.getElementById('app') ?? document.body;

  // Device voice (PTT + name-trigger) mounts FIRST and independently of the
  // avatar — it only needs the portal origin. So a slow, failed, or unreachable
  // portal bind can never strand the tablet without a way to talk. Off by
  // default (cloud STT — not for PHI, ADR-0025); tap to enable.
  if (launch?.apiBase) {
    mountDeviceVoice(app, {
      apiBase: launch.apiBase,
      characterId,
      scenarioId,
      wakeName: characterId,
      ...(launch.token ? { token: launch.token } : {}),
    });
  }

  // Drive the avatar from MedSim speech frames: emotion + on-device TTS
  // (ADR-0023). TTS loads lazily on the first spoken line. Independent of which
  // avatar (demo vs bound) is on screen — reads the binding lazily per frame.
  installSpeechConsumer({
    adapter: medsimAdapter,
    audio: audioPipeline,
    anim: animationRuntime,
    loadTts: () => lazyTts().then((m) => m.ttsProvider),
    voice: () => medsimAdapter.currentBinding()?.voiceProfile,
    loadEmotion: () => lazyEmotion().then((m) => m.emotionDriver),
  });

  // Show the demo avatar IMMEDIATELY so the screen never sits empty while the
  // (possibly slow / unreachable) portal bind is attempted in the background.
  // A demo-build failure must not take down the controls mounted above/below.
  let avatar: BuiltAvatar | null = null;
  try {
    avatar = await bootDemoAvatar(renderer);
  } catch (e) {
    diag.push({
      t: performance.now(), moduleId: 'main', kind: 'error',
      message: 'demo avatar build failed', data: e instanceof Error ? e.message : String(e),
    });
  }

  // Avatar-dependent controls (translucency slider, import, save) — only when an
  // avatar actually built. `avatar`/`slider`/`currentFace` are reassigned by both
  // the import control and the background bind hot-swap below.
  let slider: ReturnType<typeof mountTranslucencySlider> | null = null;
  let currentFace: Blob | null = null;
  if (avatar) {
    slider = mountTranslucencySlider(app, avatar.materialId, launch?.opacityLevel ?? 0.66,
      (f) => renderer.setFrameFill(f));

    // "Develop the face from an image": build the new avatar FIRST so a failed
    // import leaves the current one (and its slider) intact.
    mountImportControl(app, async (file) => {
      const cur = avatar;
      if (!cur) return;
      const opacity = slider?.getValue() ?? launch?.opacityLevel ?? 0.66;
      const next = await buildAvatarFromBlob(renderer, file, opacity);
      renderer.detachMesh(cur.meshId);
      slider?.dispose();
      avatar = next;
      currentFace = file;
      slider = mountTranslucencySlider(app, avatar.materialId, opacity,
        (f) => renderer.setFrameFill(f));
    });

    if (launch?.apiBase) {
      mountSaveControl(app, { apiBase: launch.apiBase, getFace: () => currentFace });
    }
  }

  renderer.start();

  // Dev diagnostics overlay. Self-gates to DEV / ?diag=1 — a no-op (and mounts
  // no DOM) in production, so this is safe to call unconditionally.
  diagnosticPanel.show();

  // Perf probe for the e2e/soak harness (window.__vraiPerf). Same DEV/?diag gate.
  installPerfProbe();

  // Morph-target QA panel (RB-001/ADR-0034 acceptance) — DEBUG-ONLY: loaded +
  // mounted only with ?debug, so it never ships in the production bundle. Drives
  // each ARKit-52 shape 0->1 on the live demo avatar to eyeball the baked rig.
  if (isDebugEnabled()) {
    void Promise.all([
      import('./shell/morph_qa_panel'),
      import('@modules/mesh_builder/impl/face_topology'),
      import('@modules/mesh_builder/impl/morph_basis'),
    ]).then(([qa, topo, mb]) => {
      qa.mountMorphQaPanel(app, animationRuntime, topo.MORPH_TARGETS, new Set(mb.bakedMorphNames()),
        (f) => renderer.setFrameFill(f));
    }).catch(() => { /* non-fatal dev tool */ });
    // On-device STT thermal soak (ADR-0032 pilot gate / OPT-007) — debug-only probe.
    void import('./shell/stt_soak').then((m) => { m.mountSttSoak(app); })
      .catch(() => { /* non-fatal dev tool */ });
  }

  diag.push({
    t: performance.now(), moduleId: 'main', kind: 'info',
    message: `VRAI Faces booted (demo${avatar ? '' : ' FAILED'}). `
      + `scenarioId=${scenarioId} characterId=${characterId}`,
  });

  // Background: bind the real MedSim character (portrait + speech WS), then
  // hot-swap the demo for it. Fail-soft — any failure (incl. an unreachable
  // portal) leaves the demo avatar in place rather than blanking the screen.
  if (launch?.apiBase && launch.characterId !== 'default') {
    void bindFromPortal(renderer, launch, medsimAdapter).then((bound) => {
      if (!bound) return;
      const prev = avatar;
      if (prev) renderer.detachMesh(prev.meshId);
      slider?.dispose();
      avatar = bound;
      currentFace = bound.binding.sourcePhoto;
      slider = mountTranslucencySlider(app, bound.materialId, bound.binding.opacityLevel,
        (f) => renderer.setFrameFill(f));
      diag.push({
        t: performance.now(), moduleId: 'main', kind: 'info',
        message: `bound ${bound.binding.characterId} — hot-swapped demo → portrait`,
      });
    }).catch((e: unknown) => {
      diag.push({
        t: performance.now(), moduleId: 'main', kind: 'warn',
        message: 'background bind failed; staying on demo',
        data: e instanceof Error ? e.message : String(e),
      });
    });
  }
}

boot().then(() => {
  // e2e boot signal — the full async boot chain (resume → renderer → demo →
  // background bind kicked off) finished. Tests should wait for THIS, not
  // `networkidle`: the app-shell service worker can satisfy the shell from
  // cache (and the demo-avatar build is a network-quiet CPU gap), so idle can
  // fire well before boot reaches the fire-and-forget portal bind.
  (window as Window & { __vraiBooted?: boolean }).__vraiBooted = true;
  window.dispatchEvent(new Event('vrai:booted'));
}).catch((e: unknown) => {
  diag.push({
    t: performance.now(), moduleId: 'main', kind: 'error',
    message: 'boot() failed',
    data: e instanceof Error ? e.message : String(e),
  });
  console.error('[vrai-faces] boot failed', e);
});
