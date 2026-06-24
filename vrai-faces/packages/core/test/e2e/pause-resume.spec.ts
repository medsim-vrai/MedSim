// ADR-0017 — the system can be paused (via tab hide / shell signal) and
// resumed from disk in another session without loss of scenario state.

import { test, expect } from '@playwright/test';

// Read the persisted session-state row directly from IndexedDB (in the page).
const recordExists = (page: import('@playwright/test').Page) =>
  page.evaluate(() => new Promise<boolean>((resolve) => {
    const req = indexedDB.open('vrai-faces', 1);
    req.onsuccess = () => {
      const db = req.result;
      try {
        const tx = db.transaction('session-state', 'readonly');
        const get = tx.objectStore('session-state').get(
          'fixture-scenario-001::fixture-patient-001',
        );
        get.onsuccess = () => resolve(get.result != null);
        get.onerror = () => resolve(false);
      } catch {
        resolve(false);   // store not created yet
      }
    };
    req.onerror = () => resolve(false);
  }));

test('pause writes IndexedDB and resume restores the binding', async ({ page }) => {
  await page.goto('/face/fixture-patient-001?scenario=fixture-scenario-001');
  // Wait for the FULL boot (not networkidle — the app-shell SW serves the shell
  // from cache, so idle fires before boot wires up the session to persist).
  await page.waitForFunction(
    () => (window as Window & { __vraiBooted?: boolean }).__vraiBooted === true);

  // Simulate the tab going to background — visibilityWatch triggers pauseAll().
  await page.evaluate(() => {
    Object.defineProperty(document, 'visibilityState', { value: 'hidden', configurable: true });
    document.dispatchEvent(new Event('visibilitychange'));
  });

  // pauseAll() persists asynchronously — poll until the row lands.
  await expect
    .poll(() => recordExists(page), { timeout: 5_000, message: 'pause persisted session-state' })
    .toBe(true);

  // …and it survives a reload (resumeAll reads it on the next boot).
  await page.reload();
  await page.waitForFunction(
    () => (window as Window & { __vraiBooted?: boolean }).__vraiBooted === true);
  expect(await recordExists(page)).toBe(true);
});
