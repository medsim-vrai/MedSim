// Generates public/assets/face/face_mesh_topology.json (triangulation only) from
// MediaPipe's canonical_face_model.obj.
//
// Source: https://github.com/google-ai-edge/mediapipe (Apache-2.0),
//   mediapipe/modules/face_geometry/data/canonical_face_model.obj
// The vendored .obj sits next to this script so regeneration works offline.
//
// Usage: node scripts/gen-face-topology.mjs [path/to/canonical_face_model.obj]
//
// We keep ONLY the connectivity: per-identity vertex positions come from live
// landmarks, and UVs are derived from those landmarks at build time (the portrait
// is the detected image). So the runtime asset is just { vertexCount, indices }.

import { readFileSync, writeFileSync, mkdirSync } from 'node:fs';
import { dirname, resolve } from 'node:path';
import { fileURLToPath } from 'node:url';

const here = dirname(fileURLToPath(import.meta.url));
const objPath = process.argv[2] ?? resolve(here, 'canonical_face_model.obj');
const outPath = resolve(here, '../public/assets/face/face_mesh_topology.json');

const text = readFileSync(objPath, 'utf8');

let vertexCount = 0;
const indices = [];
for (const raw of text.split('\n')) {
  const line = raw.trim();
  if (line.startsWith('v ')) {
    vertexCount++;
  } else if (line.startsWith('f ')) {
    const toks = line.split(/\s+/).slice(1);
    if (toks.length !== 3) throw new Error(`non-triangle face (n=${toks.length}): ${line}`);
    for (const t of toks) {
      // OBJ face token is "v", "v/vt", or "v/vt/vn" (1-based). Take the vertex index.
      const vi = parseInt(t.split('/')[0], 10);
      if (!Number.isInteger(vi) || vi < 1) throw new Error(`bad face vertex index: "${t}"`);
      indices.push(vi - 1); // 1-based → 0-based
    }
  }
}

for (const i of indices) {
  if (i < 0 || i >= vertexCount) throw new Error(`index ${i} out of range 0..${vertexCount - 1}`);
}

mkdirSync(dirname(outPath), { recursive: true });
// Compact (no whitespace) — this ships in the bundle.
writeFileSync(outPath, JSON.stringify({ vertexCount, indices }));
console.log(
  `wrote ${outPath}\n  vertexCount=${vertexCount}  triangles=${indices.length / 3}  indices=${indices.length}`,
);
