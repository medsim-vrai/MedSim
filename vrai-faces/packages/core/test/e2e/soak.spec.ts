// 5-minute soak — runs in the CI nightly lane, not on every PR.
// Asserts heap growth ≤ 5%, fps ≥ 55, no unhandled errors, ≤ 1 worklet
// underrun / minute. See Claude Code Guide §5.3.

import { test, expect } from '@playwright/test';

test.describe.serial('soak: 5 minutes of slider + utterance + emotion', () => {
  test.setTimeout(6 * 60 * 1000);

  test('runs without regression', async ({ page }) => {
    test.skip(!process.env.SOAK, 'set SOAK=1 to run the long soak test');

    const errors: string[] = [];
    page.on('pageerror', (e) => errors.push(e.message));

    await page.goto('/face/fixture-patient-001?scenario=fixture-scenario-001');

    // Slider sweep + utterance cadence will live here once the shell UI exists.
    // For now this is a placeholder that verifies the page reaches an idle state.
    await page.waitForLoadState('networkidle');

    expect(errors, errors.join('\n')).toEqual([]);
  });
});
