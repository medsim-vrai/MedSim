/* VRAI Faces app service worker (Phase 5.7) — unifies two jobs:
 *
 *  (1) Kokoro local-first passthrough (was kokoro-sw.js, ADR-0001): kokoro-js
 *      hardcodes huggingface.co model/voice URLs; serve the bundled copies under
 *      /assets/kokoro/ so the avatar speaks offline, network-fallback otherwise.
 *
 *  (2) App-shell runtime cache: a bedside tablet rarely changes its app, so after
 *      the first online load the shell + built assets are served from cache for
 *      near-instant startup + offline shell.
 *
 * DEV-SAFE: only navigations (network-first) and built /assets/* (cache-first)
 * are cached. Vite dev modules (/src, /@vite, /@fs), the HMR socket, and the
 * portal API all pass through untouched — HMR and the live encounter loop are
 * unaffected. (One SW per scope: this replaces the old kokoro-sw at scope "/".)
 *
 * The live AI reply loop still needs the portal — caching speeds STARTUP, not the
 * encounter. Bump CACHE_VERSION on a breaking shell change; activate() drops old.
 */
const CACHE_VERSION = 'vrai-shell-v10'; // v10: on-device STT uses the .asyncify ORT build (webgpuInit) — iPad WebGPU STT fix
const HF_PREFIX = 'https://huggingface.co/onnx-community/Kokoro-82M-v1.0-ONNX/resolve/main/';
const LOCAL_BASE = '/assets/kokoro/';

self.addEventListener('install', () => self.skipWaiting());

self.addEventListener('activate', (event) => event.waitUntil((async () => {
  const keys = await caches.keys();
  await Promise.all(
    keys.filter((k) => k.startsWith('vrai-shell-') && k !== CACHE_VERSION).map((k) => caches.delete(k)),
  );
  await self.clients.claim();
})()));

self.addEventListener('fetch', (event) => {
  const req = event.request;

  // (1) Kokoro model/voice assets → bundled-first, network fallback.
  // The page is cross-origin isolated (COEP require-corp, for on-device STT), so
  // this cross-origin (huggingface.co) request must come back embeddable: re-wrap
  // the bundled same-origin copy with Cross-Origin-Resource-Policy so TTS keeps
  // working under COEP. (Network fallback is returned as-is — rare.)
  if (req.url.startsWith(HF_PREFIX)) {
    const localUrl = LOCAL_BASE + req.url.slice(HF_PREFIX.length);
    event.respondWith((async () => {
      const local = await fetch(localUrl).catch(() => null);
      if (local && local.ok) {
        const headers = new Headers(local.headers);
        headers.set('Cross-Origin-Resource-Policy', 'cross-origin');
        return new Response(local.body, { status: local.status, statusText: local.statusText, headers });
      }
      return fetch(req);
    })());
    return;
  }

  const url = new URL(req.url);
  // Only touch same-origin GETs; everything else passes straight through.
  if (req.method !== 'GET' || url.origin !== self.location.origin) return;

  // (2a) Navigations → network-first (so a new deploy is picked up online),
  // cache fallback (so the shell still opens offline).
  if (req.mode === 'navigate') {
    event.respondWith((async () => {
      try {
        const net = await fetch(req);
        const cache = await caches.open(CACHE_VERSION);
        cache.put(req, net.clone());
        return net;
      } catch {
        return (await caches.match(req)) || (await caches.match('/')) || Response.error();
      }
    })());
    return;
  }

  // (2b) Built, content-hashed assets → cache-first + background revalidate.
  if (url.pathname.startsWith('/assets/')) {
    event.respondWith((async () => {
      const cache = await caches.open(CACHE_VERSION);
      const hit = await cache.match(req);
      const fetching = fetch(req)
        .then((r) => { if (r && r.ok) cache.put(req, r.clone()); return r; })
        .catch(() => null);
      return hit || (await fetching) || fetch(req);
    })());
    return;
  }
  // else: passthrough (vite /src, /@vite, /@fs, ws, etc.)
});
