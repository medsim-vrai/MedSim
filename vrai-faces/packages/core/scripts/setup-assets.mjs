// Repopulates the git-ignored MediaPipe assets after a fresh clone + install.
// These are large/redundant binaries (~36 MB) so they live outside git; this
// script rebuilds them deterministically.
//
//   pnpm run setup:assets            # copy WASM, download model if missing, gen topology
//   pnpm run setup:assets --force    # also re-download the model
//
// - WASM  : copied from the installed @mediapipe/tasks-vision package (no network)
// - model : downloaded from Google MediaPipe storage (~3.75 MB, network)
// - topology JSON : regenerated from the vendored canonical_face_model.obj (no network)
//
// Local-first (ADR-0001): assets are served from the app origin, never a CDN at runtime.

import { copyFileSync, cpSync, existsSync, mkdirSync, readdirSync, writeFileSync } from 'node:fs';
import { createRequire } from 'node:module';
import { dirname, resolve } from 'node:path';
import { fileURLToPath } from 'node:url';

const here = dirname(fileURLToPath(import.meta.url));
const core = resolve(here, '..'); // packages/core
const force = process.argv.includes('--force');
const require = createRequire(import.meta.url);

// 1) WASM — copy from the installed package (reproducible, no network).
const wasmSrc = resolve(core, 'node_modules/@mediapipe/tasks-vision/wasm');
if (!existsSync(wasmSrc)) {
  throw new Error(`MediaPipe WASM not found at ${wasmSrc}\n  → run "pnpm install" first.`);
}
const wasmDst = resolve(core, 'public/assets/mediapipe/wasm');
mkdirSync(wasmDst, { recursive: true });
cpSync(wasmSrc, wasmDst, { recursive: true });
console.log('✓ WASM   → public/assets/mediapipe/wasm/');

// 1b) ONNX Runtime WASM for on-device STT (whisper via transformers.js, ADR-0026).
//     Copy the simd-threaded* runtime (.wasm + .mjs) from the SAME onnxruntime-web
//     the bundled @huggingface/transformers resolves to, so device_stt loads the
//     runtime from OUR origin (/assets/ort/) instead of jsdelivr at runtime —
//     local-first (ADR-0001) and the fix for "no available backend" on a contained
//     or flaky LAN. transformers picks the .asyncify build on non-Safari (single-
//     threaded, NO cross-origin isolation needed), so this needs no COOP/COEP.
//     No network — the files ship inside node_modules.
// Resolve the package mains (not /package.json — onnxruntime-web's exports map
// blocks that). dirname(ort main) is the dist/ dir that ships the .wasm/.mjs.
const tfEntry = require.resolve('@huggingface/transformers', { paths: [core] });
const ortDist = dirname(require.resolve('onnxruntime-web', { paths: [dirname(tfEntry)] }));
const ortDst = resolve(core, 'public/assets/ort');
mkdirSync(ortDst, { recursive: true });
let ortCopied = 0;
for (const f of readdirSync(ortDist)) {
  if (/^ort-wasm-simd-threaded.*\.(wasm|mjs)$/.test(f)) {
    copyFileSync(resolve(ortDist, f), resolve(ortDst, f));
    ortCopied++;
  }
}
if (ortCopied === 0) throw new Error(`No ORT runtime files found in ${ortDist}`);
console.log(`✓ ORT    → public/assets/ort/ (${ortCopied} runtime files)`);

// 2) model — download only if missing (or --force).
const MODEL_URL =
  'https://storage.googleapis.com/mediapipe-models/face_landmarker/face_landmarker/float16/1/face_landmarker.task';
const modelDst = resolve(core, 'public/assets/mediapipe/face_landmarker.task');
if (force || !existsSync(modelDst)) {
  console.log('↓ downloading face_landmarker.task (~3.75 MB)…');
  const res = await fetch(MODEL_URL);
  if (!res.ok) throw new Error(`model download failed: HTTP ${res.status} ${res.statusText}`);
  const buf = Buffer.from(await res.arrayBuffer());
  mkdirSync(dirname(modelDst), { recursive: true });
  writeFileSync(modelDst, buf);
  console.log(`✓ model  → public/assets/mediapipe/face_landmarker.task (${buf.length} bytes)`);
} else {
  console.log('• model  present — skipping (use --force to re-download)');
}

// 3) topology JSON — regenerate from the vendored .obj (no network).
await import('./gen-face-topology.mjs');

// 4) Kokoro local-first assets — model + curated voices (served by kokoro-sw.js,
//    ADR-0001). Paths mirror the HF repo so the SW maps them 1:1.
const KOKORO_BASE = 'https://huggingface.co/onnx-community/Kokoro-82M-v1.0-ONNX/resolve/main/';
const KOKORO_VOICES = ['af_heart', 'af_bella', 'af_nicole', 'af_sarah', 'af_sky', 'af_nova', 'am_adam', 'bf_emma'];
const KOKORO_FILES = [
  'config.json', 'tokenizer.json', 'tokenizer_config.json',
  'onnx/model_quantized.onnx',                    // q8 (~92 MB)
  ...KOKORO_VOICES.map((v) => `voices/${v}.bin`), // ~510 KB each
];
for (const rel of KOKORO_FILES) {
  const dst = resolve(core, 'public/assets/kokoro', rel);
  if (!force && existsSync(dst)) { console.log('• kokoro present:', rel); continue; }
  console.log('↓ kokoro', rel);
  const res = await fetch(KOKORO_BASE + rel);
  if (!res.ok) { console.warn(`  (skipped ${rel}: HTTP ${res.status})`); continue; }
  const buf = Buffer.from(await res.arrayBuffer());
  mkdirSync(dirname(dst), { recursive: true });
  writeFileSync(dst, buf);
}
console.log('✓ Kokoro → public/assets/kokoro/');

console.log('✓ assets ready.');
