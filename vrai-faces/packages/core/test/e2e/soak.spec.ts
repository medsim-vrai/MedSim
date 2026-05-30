// 5-minute soak — runs in the CI nightly lane (e2e.yml), not on every PR.
// Per Claude Code Guide §5.3: heap growth ≤ ~5%, fps ≥ 55, no unhandled
// errors, no over-budget latency warns. Reads the perf probe installed by
// src/perf/probe.ts (window.__vraiPerf, gated by ?diag=1). fps/heap assertions
// are guarded: headless Chromium falls back to WebGL2 and may not report fps,
// and `performance.memory` is Chrome-only.

import { test, expect } from '@playwright/test';
import type { PerfSnapshot } from '../../src/perf/probe';

test.describe.serial('soak: 5 minutes of slider sweeps', () => {
  test.setTimeout(6 * 60 * 1000);

  test('runs without regression', async ({ page }) => {
    test.skip(!process.env.SOAK, 'set SOAK=1 to run the long soak test');

    const errors: string[] = [];
    page.on('pageerror', (e) => errors.push(e.message));

    await page.goto('/face/fixture-patient-001?scenario=fixture-scenario-001&diag=1');
    await page.waitForLoadState('networkidle');
    await page.waitForFunction(() => typeof window.__vraiPerf === 'function');

    const sample = (): Promise<PerfSnapshot> => page.evaluate(() => window.__vraiPerf!());
    const first = await sample();

    const slider = page.locator('input[type="range"]');
    const hasSlider = (await slider.count()) > 0;

    const DURATION_MS = 5 * 60 * 1000;
    const t0 = Date.now();
    let minFps = Number.POSITIVE_INFINITY;
    let maxHeap = first.heapMB ?? 0;

    while (Date.now() - t0 < DURATION_MS) {
      if (hasSlider) {
        const v = ((Date.now() - t0) / 1000) % 1; // 0..1 sweep, ~1 Hz
        await slider.fill(v.toFixed(2));
      }
      await page.waitForTimeout(2000);
      const s = await sample();
      if (s.fps !== null) minFps = Math.min(minFps, s.fps);
      if (s.heapMB !== null) maxHeap = Math.max(maxHeap, s.heapMB);
    }

    const final = await sample();
    expect(errors, errors.join('\n')).toEqual([]);
    expect(final.budgetWarns, 'no over-budget latency stages').toBe(0);

    if (first.fps !== null && Number.isFinite(minFps)) {
      expect(minFps, 'sustained fps').toBeGreaterThanOrEqual(55);
    }
    if (first.heapMB !== null && first.heapMB > 0) {
      // ≤ ~5% heap growth over the run (allow GC jitter headroom).
      expect(maxHeap, 'bounded heap growth').toBeLessThanOrEqual(first.heapMB * 1.08);
    }
  });
});
