import { defineConfig } from 'vite';
import { fileURLToPath, URL } from 'node:url';

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
  },
  preview: {
    host: true,
    port: 4173,
  },
  worker: {
    format: 'es',
  },
  build: {
    target: 'esnext',
    sourcemap: true,
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
