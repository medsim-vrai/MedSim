// The MedSim bind path in a real browser (the shell seam). A QR carrying
// `?api=<portal origin>` makes the shell fetch `${api}/api/face/<id>/binding`;
// here we mock that endpoint with a valid character card + an inlined portrait,
// then assert the shell took the BOUND path (fetched the doc, built the avatar,
// no crash) rather than the demo fallback. No portal needed.

import { test, expect } from '@playwright/test';

// A minimal-but-valid MedSim card (schemas/character.json shape).
const CARD = {
  id: 'rn-amy',
  name: 'Amy',
  role: 'bedside RN',
  voice: {
    register: 'warm',
    sentence_length: 'medium',
    examples: ['Hi there.', 'How are you feeling?', "Let's take a look."],
  },
  knowledge_boundary: 'nursing scope',
  scene_contract: ['no diagnosis'],
  voice_profile: { gender: 'female', language: 'en-US', voice_hints: ['Samantha'] },
};

// 1×1 transparent PNG — a stand-in portrait the adapter decodes locally.
const PNG =
  'data:image/png;base64,iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAQAAAC1HAwCAAAAC0lEQVR42mNk' +
  '+M9QDwADhgGAWjR9awAAAABJRU5ErkJggg==';

test('binds a real character from a mocked portal binding', async ({ page }) => {
  let bindHits = 0;
  // Note: no speechWsUrl in the payload → the adapter uses same-origin
  // BroadcastChannel, so the test doesn't depend on a live WebSocket server.
  await page.route('**/api/face/*/binding*', async (route) => {
    bindHits += 1;
    await route.fulfill({
      status: 200,
      contentType: 'application/json',
      body: JSON.stringify({ ...CARD, sourcePhoto: PNG, opacityLevel: 0.5, ghostColor: '#cfe8ff' }),
    });
  });

  const errors: string[] = [];
  page.on('pageerror', (e) => errors.push(e.message));

  const api = encodeURIComponent('http://localhost:4173');
  await page.goto(`/face/rn-amy?scenario=e2e&opacity=0.66&api=${api}&diag=1`);

  // NOT networkidle: the portal bind is fire-and-forget at the END of boot
  // (main.ts), and the app-shell service worker can satisfy the shell from
  // cache — so "idle" can fire before boot reaches the bind. Wait for the
  // bind request to actually land.
  await expect
    .poll(() => bindHits, { timeout: 15_000, message: 'shell fetched the bind document' })
    .toBeGreaterThanOrEqual(1);
  await expect(page.locator('#stage')).toBeVisible();
  expect(errors, `page errors: ${errors.join(' | ')}`).toEqual([]);
});
