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

import { cpSync, existsSync, mkdirSync, writeFileSync } from 'node:fs';
import { dirname, resolve } from 'node:path';
import { fileURLToPath } from 'node:url';

const here = dirname(fileURLToPath(import.meta.url));
const core = resolve(here, '..'); // packages/core
const force = process.argv.includes('--force');

// 1) WASM — copy from the installed package (reproducible, no network).
const wasmSrc = resolve(core, 'node_modules/@mediapipe/tasks-vision/wasm');
if (!existsSync(wasmSrc)) {
  throw new Error(`MediaPipe WASM not found at ${wasmSrc}\n  → run "pnpm install" first.`);
}
const wasmDst = resolve(core, 'public/assets/mediapipe/wasm');
mkdirSync(wasmDst, { recursive: true });
cpSync(wasmSrc, wasmDst, { recursive: true });
console.log('✓ WASM   → public/assets/mediapipe/wasm/');

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
