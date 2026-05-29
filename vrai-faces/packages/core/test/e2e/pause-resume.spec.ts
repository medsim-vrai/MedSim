// ADR-0017 — the system can be paused (via tab hide / shell signal) and
// resumed from disk in another session without loss of scenario state.

import { test, expect } from '@playwright/test';

test('pause writes IndexedDB and resume restores the binding', async ({ page }) => {
  await page.goto('/face/fixture-patient-001?scenario=fixture-scenario-001');
  await page.waitForLoadState('networkidle');

  // Simulate the tab going to background — visibilityWatch triggers pauseAll().
  await page.evaluate(() => {
    Object.defineProperty(document, 'visibilityState', {
      value: 'hidden',
      configurable: true,
    });
    document.dispatchEvent(new Event('visibilitychange'));
  });

  // Give pauseAll() its async cycle.
  await page.waitForTimeout(200);

  // Re-open the page; resumeAll() should fire from main.ts boot.
  await page.reload();
  await page.waitForLoadState('networkidle');

  const restored = await page.evaluate(() => {
    return new Promise<boolean>((resolve) => {
      const req = indexedDB.open('vrai-faces', 1);
      req.onsuccess = () => {
        const db = req.result;
        const tx = db.transaction('session-state', 'readonly');
        const get = tx.objectStore('session-state').get(
          'fixture-scenario-001::fixture-patient-001',
        );
        get.onsuccess = () => resolve(get.result != null);
        get.onerror = () => resolve(false);
      };
      req.onerror = () => resolve(false);
    });
  });

  expect(restored).toBe(true);
});
