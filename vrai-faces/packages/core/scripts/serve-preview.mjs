// Build the production bundle, then serve it over `vite preview` (LAN host +
// the requested port). Used by the portal autostart's PREVIEW mode so a device
// gets the REAL app-shell cache + PWA: the dev server serves /src modules, but
// the service worker caches the hashed /assets/* that only a build produces.
//
// HTTPS/host come from vite.config (preview.https when the dev cert exists).
//
// Run from packages/core:  node scripts/serve-preview.mjs [port=5173]
import { build, preview } from 'vite';

const PORT = Number(process.argv[2]) || 5173;

await build(); // emits dist/ (shell + hashed assets + manifest + icons + app-sw.js)
const server = await preview({
  preview: { port: PORT, strictPort: true, host: true },
});
server.printUrls();
