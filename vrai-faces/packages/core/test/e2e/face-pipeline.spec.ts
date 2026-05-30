// Verifies the LIVE MediaPipe path executes in a real browser. The demo boot
// drives mesh_builder.build(), which calls loadFaceTopology() → detectFaceLandmarks():
// that fetches the canonical topology JSON, the FaceLandmarker model, and the
// MediaPipe WASM, then initializes FaceLandmarker and runs detect(). Observing
// those three asset fetches (200) with no fatal page error proves the stack is
// wired and runs end-to-end — no real face required.
//
// NOTE (input-gated, NOT asserted here): confirming a REAL photo yields 478
// landmarks + a real face mesh needs a consented front-view portrait dropped at
// test/e2e/fixtures/portrait.png and driven through face_ingest → mesh_builder.
// We do not bundle a real face (facial-image policy); that is a QA step with a
// consented image. On the synthetic demo portrait the path correctly falls back.

import { test, expect } from '@playwright/test';

test('live MediaPipe pipeline loads its assets and runs in-browser', async ({ page }) => {
  const responses: Array<{ url: string; status: number }> = [];
  page.on('response', (r) => responses.push({ url: r.url(), status: r.status() }));
  const errors: string[] = [];
  page.on('pageerror', (e) => errors.push(e.message));

  await page.goto('/face/demo-001?scenario=e2e&opacity=0.66&diag=1');
  await page.waitForLoadState('networkidle');

  // The shell rendered.
  await expect(page.locator('#stage')).toBeVisible();

  // The live path fetched its three asset groups ⇒ FilesetResolver loaded the
  // WASM and FaceLandmarker.createFromOptions loaded the model, then detect() ran.
  const hit = (frag: string) => responses.find((r) => r.url.includes(frag));
  expect(hit('face_mesh_topology.json')?.status, 'topology asset served').toBe(200);
  expect(hit('face_landmarker.task')?.status, 'FaceLandmarker model fetched').toBe(200);
  expect(
    responses.some((r) => /vision_wasm.*\.wasm$/.test(r.url) && r.status === 200),
    'MediaPipe WASM fetched',
  ).toBe(true);

  // No uncaught error tore the pipeline down.
  expect(errors, `page errors: ${errors.join(' | ')}`).toEqual([]);
});
