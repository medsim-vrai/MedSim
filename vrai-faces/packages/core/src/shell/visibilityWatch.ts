// Tablet lifecycle: when the page is hidden or the battery is critical,
// snapshot everything and let the runtime free GPU buffers. Capacitor
// shells fire `appStateChange` too — those wrappers should call
// `pauseFromShell()` directly.

import { memoryState } from '../modules/memory_state';

export function installVisibilityWatch(): void {
  document.addEventListener('visibilitychange', () => {
    if (document.visibilityState === 'hidden') {
      void memoryState.pauseAll();
    }
  });
}

export async function pauseFromShell(): Promise<void> {
  await memoryState.pauseAll();
}

export async function resumeFromShell(scenarioId: string, characterId: string): Promise<void> {
  await memoryState.resumeAll(scenarioId, characterId);
}
