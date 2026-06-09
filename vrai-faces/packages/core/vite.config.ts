import { defineConfig } from 'vite';
import { fileURLToPath, URL } from 'node:url';
import { existsSync, readFileSync } from 'node:fs';

// HTTPS for tablet testing. Serving over https gives the device a *secure
// context*, which is what lets the avatar render under WebGPU and unlocks the
// push-to-talk mic (getUserMedia / Web Speech) + crypto.subtle. Reads the dev
// cert from scripts/make-dev-cert.sh (env override or the default certs dir);
// when absent we fall back to plain HTTP so nothing breaks without a cert.
function devHttps(): { key: Buffer; cert: Buffer } | undefined {
  try {
    const certPath = process.env.MEDSIM_TLS_CERT
      ?? fileURLToPath(new URL('../../../portal/data/certs/dev-cert.pem', import.meta.url));
    const keyPath = process.env.MEDSIM_TLS_KEY
      ?? fileURLToPath(new URL('../../../portal/data/certs/dev-key.pem', import.meta.url));
    if (existsSync(certPath) && existsSync(keyPath)) {
      return { cert: readFileSync(certPath), key: readFileSync(keyPath) };
    }
  } catch {
    // fall through to HTTP
  }
  return undefined;
}

const https = devHttps();

export default defineConfig({
  resolve: {
    alias: {
      '@': fileURLToPath(new URL('./src', import.meta.url)),
      '@contracts': fileURLToPath(new URL('./src/types', import.meta.url)),
      '@modules': fileURLToPath(new URL('./src/modules', import.meta.url)),
      '@utils': fileURLToPath(new URL('./src/utils', import.meta.url)),
      '@perf': fileURLToPath(new URL('./src/perf', import.meta.url)),
    },
  },
  server: {
    host: true,                 // expose on LAN so tablet QR launches reach it
    port: 5173,
    strictPort: true,
    // https when a dev cert exists, else plain HTTP. Spread so the key is absent
    // (not `undefined`) under exactOptionalPropertyTypes.
    ...(https ? { https } : {}),
  },
  preview: {
    host: true,
    port: 4173,
    ...(https ? { https } : {}),
  },
  worker: {
    format: 'es',
  },
  build: {
    target: 'esnext',
    sourcemap: true,
    // OPT-004: after moving the two mesh JSONs (oral_eye_mesh, morph basis) out to fetched
    // /assets/face/ files, the cold-load `index` shell is ~144 KB (was 836 KB). The remaining large
    // chunks are vendor: `three` (~748 KB, render-critical + eager) sits just under this limit; `kokoro`
    // (~2.1 MB TTS) and `transformers` (STT) are DYNAMICALLY imported, off the cold path — kokoro is the
    // one chunk that still trips the warning, an accepted lazy exception. Limit set so any NEW eager
    // bloat (e.g. something re-inlined into the shell) re-warns.
    chunkSizeWarningLimit: 800,
    rollupOptions: {
      output: {
        manualChunks: {
          // The whole app imports the WebGPU superset build (`three/webgpu`,
          // i.e. build/three.webgpu.js), not the bare `three` entry. Key the
          // vendor chunk on that exact specifier or it matches nothing and
          // Three's ~600 kB spills into the main bundle (empty `three` chunk).
          three: ['three/webgpu'],
          mediapipe: ['@mediapipe/tasks-vision'],
        },
      },
    },
  },
});
