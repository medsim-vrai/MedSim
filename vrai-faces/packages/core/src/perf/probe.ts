// Read-only perf probe for the e2e / soak harness. Exposes `window.__vraiPerf()`
// returning the live fps (animation_runtime's diag stat), the JS heap in MB
// (Chrome only — `performance.memory` is non-standard), and the count of
// over-budget latency_meter warns. Gated to DEV / ?diag=1 exactly like the
// diagnostic panel, so production never installs a global.

import { diag } from './diag';

export interface PerfSnapshot {
  /** animation_runtime rolling fps, or null if not reporting yet. */
  fps: number | null;
  /** used JS heap in MB (Chrome `performance.memory`), or null elsewhere. */
  heapMB: number | null;
  /** perf.latency_meter 'warn' events so far (stages that blew their §5 budget). */
  budgetWarns: number;
}

declare global {
  interface Window {
    __vraiPerf?: () => PerfSnapshot;
  }
}

function snapshot(): PerfSnapshot {
  const anim = diag.modules.get('animation_runtime');
  const mem = (performance as unknown as { memory?: { usedJSHeapSize: number } }).memory;
  const budgetWarns = diag.timeline.toArray().filter(
    (e) => e.moduleId === 'perf.latency_meter' && e.kind === 'warn',
  ).length;
  return {
    fps: typeof anim?.fps === 'number' ? anim.fps : null,
    heapMB: mem ? Math.round((mem.usedJSHeapSize / 1048576) * 10) / 10 : null,
    budgetWarns,
  };
}

/** Install the probe when DEV or ?diag=1 (mirrors diagnostic_panel gating). */
export function installPerfProbe(): void {
  const dev = Boolean((import.meta as { env?: { DEV?: boolean } }).env?.DEV);
  const flagged =
    typeof location !== 'undefined' &&
    new URLSearchParams(location.search).get('diag') === '1';
  if (!dev && !flagged) return;
  if (typeof window === 'undefined') return;
  window.__vraiPerf = snapshot;
}
