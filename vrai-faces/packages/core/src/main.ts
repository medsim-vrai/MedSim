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
import { bindFromPortal, clearBindingCache } from './shell/portalBinding';
import { installSpeechConsumer } from './shell/speechConsumer';
import { lazyTts } from './shell/lazy';
import { mountTranslucencySlider } from './shell/translucency_slider';
import { mountImportControl } from './shell/import_control';
import { mountSaveControl } from './shell/save_control';
import { mountDeviceVoice } from './shell/device_voice';

async function boot(): Promise<void> {
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
    slider = mountTranslucencySlider(app, avatar.materialId, launch?.opacityLevel ?? 0.66);

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
      slider = mountTranslucencySlider(app, avatar.materialId, opacity);
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
      slider = mountTranslucencySlider(app, bound.materialId, bound.binding.opacityLevel);
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

boot().catch((e: unknown) => {
  diag.push({
    t: performance.now(), moduleId: 'main', kind: 'error',
    message: 'boot() failed',
    data: e instanceof Error ? e.message : String(e),
  });
  console.error('[vrai-faces] boot failed', e);
});
