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
import { installFirstGestureWarmup } from './shell/firstGesture';
import { installVisibilityWatch } from './shell/visibilityWatch';
import { parseLaunchUrl } from './shell/parseLaunchUrl';
import { registerResumableHooks } from './shell/registerLifecycles';
import { mountRenderer } from './shell/renderer';
import { bootDemoAvatar } from './shell/demo_boot';
import { mountTranslucencySlider } from './shell/translucency_slider';

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

  // Bring up the demo avatar — placeholder topology + procedural portrait.
  const { materialId } = await bootDemoAvatar(renderer);

  // Mount the translucency slider against the demo material. Initial
  // value matches what demo_boot picked (0.66 mid-stop).
  const app = document.getElementById('app') ?? document.body;
  mountTranslucencySlider(app, materialId, launch?.opacityLevel ?? 0.66);

  renderer.start();

  // Dev diagnostics overlay. Self-gates to DEV / ?diag=1 — a no-op (and mounts
  // no DOM) in production, so this is safe to call unconditionally.
  diagnosticPanel.show();

  diag.push({
    t: performance.now(), moduleId: 'main', kind: 'info',
    message: `VRAI Faces booted. scenarioId=${scenarioId} characterId=${characterId}`,
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
