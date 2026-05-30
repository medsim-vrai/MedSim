/* Kokoro local-first service worker (ADR-0001).
 *
 * kokoro-js@1.2.x hardcodes the browser model + voice URLs to huggingface.co
 * (e.g. .../Kokoro-82M-v1.0-ONNX/resolve/main/voices/<id>.bin). We intercept
 * those requests and serve the copies bundled under /assets/kokoro/, so the
 * avatar speaks fully offline. If a file isn't bundled we fall back to the
 * network, so partial bundles still work.
 *
 * Populate /assets/kokoro via `pnpm --filter @vrai/core setup:assets`.
 */
const HF_PREFIX = 'https://huggingface.co/onnx-community/Kokoro-82M-v1.0-ONNX/resolve/main/';
const LOCAL_BASE = '/assets/kokoro/';

self.addEventListener('install', () => self.skipWaiting());
self.addEventListener('activate', (event) => event.waitUntil(self.clients.claim()));

self.addEventListener('fetch', (event) => {
  const url = event.request.url;
  if (!url.startsWith(HF_PREFIX)) return; // only Kokoro model/voice assets

  const localUrl = LOCAL_BASE + url.slice(HF_PREFIX.length);
  event.respondWith(
    fetch(localUrl)
      .then((res) => (res && res.ok ? res : fetch(event.request))) // bundled, else network
      .catch(() => fetch(event.request)),
  );
});
