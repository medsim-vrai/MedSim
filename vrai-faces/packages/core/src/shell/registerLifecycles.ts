// Wire every module's snapshot/restore hooks into memory_state so
// pauseAll()/resumeAll() picks them up automatically (ADR-0017).

import { memoryState } from '../modules/memory_state';
import { animationRuntime } from '../modules/animation_runtime';
import { audioPipeline } from '../modules/audio_pipeline';
import { medsimAdapter } from '../modules/medsim_adapter';

export function registerResumableHooks(): void {
  memoryState.register('animation_runtime', {
    snapshot: () => animationRuntime.snapshot(),
    restore:  (s) => animationRuntime.restore(s as ReturnType<typeof animationRuntime.snapshot>),
    pause:    () => animationRuntime.pause(),
    resume:   () => animationRuntime.resume(),
  });

  memoryState.register('audio_pipeline', {
    snapshot: () => audioPipeline.snapshot(),
    restore:  (s) => audioPipeline.restore(s as ReturnType<typeof audioPipeline.snapshot>),
    pause:    () => audioPipeline.pause(),
    resume:   () => audioPipeline.resume(),
  });

  memoryState.register('medsim_adapter', {
    snapshot: () => medsimAdapter.snapshot(),
    restore:  (s) => medsimAdapter.restore(s as ReturnType<typeof medsimAdapter.snapshot>),
    pause:    () => medsimAdapter.pause(),
    resume:   () => medsimAdapter.resume(),
  });
}
