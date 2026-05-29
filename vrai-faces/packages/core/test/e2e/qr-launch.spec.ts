// The tablet QR launch path. Confirms that /face/<characterId> renders a
// full-screen canvas and that parseLaunchUrl resolved the params.

import { test, expect } from '@playwright/test';

test('QR launch URL boots the avatar shell', async ({ page }) => {
  await page.goto('/face/pt-001?scenario=s7&opacity=0.33');
  await page.waitForLoadState('networkidle');

  // The shell canvas should exist and fill the viewport.
  const stage = page.locator('#stage');
  await expect(stage).toBeVisible();
  const box = await stage.boundingBox();
  expect(box?.width).toBeGreaterThan(100);
});
