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
import { buildAvatarFromBlob } from './shell/avatar_build';
import { bindFromPortal } from './shell/portalBinding';
import { installSpeechConsumer } from './shell/speechConsumer';
import { lazyTts } from './shell/lazy';
import { mountTranslucencySlider } from './shell/translucency_slider';
import { mountImportControl } from './shell/import_control';
import { mountSaveControl } from './shell/save_control';

async function boot(): Promise<void> {
  const launch = parseLaunchUrl(window.location);
  const scenarioId  = launch?.scenarioId  ?? 'default';
  const characterId = launch?.characterId ?? 'default';

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

  // If the QR carried a portal origin, bind a real MedSim character: fetch the
  // bind doc (portrait + speech WS URL), bind it (connects the speech
  // transport), and build the avatar from the attached portrait. Any failure
  // falls back to the standalone demo so the tablet always shows something.
  const bound = (launch?.apiBase && launch.characterId !== 'default')
    ? await bindFromPortal(renderer, launch, medsimAdapter)
    : null;
  let avatar = bound ?? await bootDemoAvatar(renderer);

  // Drive the avatar from MedSim speech frames: emotion + on-device TTS
  // (ADR-0023). TTS loads lazily on the first spoken line.
  installSpeechConsumer({
    adapter: medsimAdapter,
    audio: audioPipeline,
    anim: animationRuntime,
    loadTts: () => lazyTts().then((m) => m.ttsProvider),
    voice: () => medsimAdapter.currentBinding()?.voiceProfile,
  });

  // Mount the translucency slider against the active material.
  const app = document.getElementById('app') ?? document.body;
  const initialOpacity = bound?.binding.opacityLevel ?? launch?.opacityLevel ?? 0.66;
  let slider = mountTranslucencySlider(app, avatar.materialId, initialOpacity);

  // The face the "Save skin" control persists: the imported portrait once one is
  // picked, else the bound character's portrait.
  let currentFace: Blob | null = bound?.binding.sourcePhoto ?? null;

  // "Develop the face from an image": import a portrait and rebuild the avatar
  // from it. Build the new avatar FIRST so a failed import leaves the current
  // one (and its slider) intact; the control surfaces the error.
  mountImportControl(app, async (file) => {
    const opacity = slider.getValue();
    const next = await buildAvatarFromBlob(renderer, file, opacity);
    renderer.detachMesh(avatar.meshId);
    slider.dispose();
    avatar = next;
    currentFace = file;
    slider = mountTranslucencySlider(app, avatar.materialId, opacity);
  });

  // "Save skin" → the portal's skin library (only when we know the portal origin).
  if (launch?.apiBase) {
    mountSaveControl(app, { apiBase: launch.apiBase, getFace: () => currentFace });
  }

  renderer.start();

  // Dev diagnostics overlay. Self-gates to DEV / ?diag=1 — a no-op (and mounts
  // no DOM) in production, so this is safe to call unconditionally.
  diagnosticPanel.show();

  // Perf probe for the e2e/soak harness (window.__vraiPerf). Same DEV/?diag gate.
  installPerfProbe();

  diag.push({
    t: performance.now(), moduleId: 'main', kind: 'info',
    message: `VRAI Faces booted (${bound ? 'bound' : 'demo'}). `
      + `scenarioId=${scenarioId} characterId=${characterId}`,
  });
}

boot().catch((e: unknown) => {
  diag.push({
    t: performance.now(), moduleId: 'main', kind: 'error',
    message: 'boot() failed',
    data: e instanceof Error ? e.message : String(e),
  });
  console.error('[vrai-faces] boot failed', e);
});
