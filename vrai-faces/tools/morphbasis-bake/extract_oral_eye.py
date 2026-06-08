#!/usr/bin/env python3
"""RB-003 Phase-2 Item 3: extract the ICT-FaceKit ORAL (gums+tongue+teeth) and EYE (sclera+iris)
sub-meshes from the local generic_neutral_mesh.obj (by usemtl material group), align them into the
MediaPipe canonical frame (reusing the RB-001 bake's Umeyama transform), and emit a compact JSON the
runtime loads into a BufferGeometry. Offline, deterministic, NO download (the ICT head is already in
_assets/). Source: USC ICT-FaceKit (MIT). Run: ./.venv/bin/python extract_oral_eye.py"""
from __future__ import annotations
import json
import numpy as np
from bake_morphbasis import load_obj_vertices, umeyama, apply_sim, ASSETS

DLIB_TO_MP = {30: 1, 8: 152, 36: 33, 39: 133, 42: 362, 45: 263, 48: 61, 54: 291, 0: 234, 16: 454, 27: 168, 57: 17}
OUT = ASSETS.parent.parent.parent / "packages/core/src/shell/oral_eye_mesh.json"


def parse_obj_parts(path):
    verts: list[tuple[float, float, float]] = []
    parts: dict[str, list[list[int]]] = {}
    cur = None
    with open(path) as f:
        for line in f:
            if line.startswith("v "):
                p = line.split(); verts.append((float(p[1]), float(p[2]), float(p[3])))
            elif line.startswith("usemtl "):
                cur = line.split()[1]; parts.setdefault(cur, [])
            elif line.startswith("f ") and cur is not None:
                parts[cur].append([int(t.split("/")[0]) - 1 for t in line.split()[1:]])
    return np.asarray(verts, dtype=np.float64), parts


verts, parts = parse_obj_parts(ASSETS / "generic_neutral_mesh.obj")
print("parts (faces each):", {k: len(v) for k, v in parts.items()})

# Align ICT -> MediaPipe canonical (same as the bake)
vidx = json.load(open(ASSETS / "vertex_indices.json"))
lmk = vidx["idx_to_landmark_verts"]
ictN = load_obj_vertices(ASSETS / "generic_neutral_mesh.obj")
mp = load_obj_vertices(ASSETS / "canonical_face_model.obj")
src = np.asarray([ictN[lmk[d]] for d in DLIB_TO_MP]); dst = np.asarray([mp[m] for m in DLIB_TO_MP.values()])
R, s, t = umeyama(src, dst)
mp_h = float(mp[:, 1].max() - mp[:, 1].min())
print(f"align scale s={s:.4f}  mp face height={mp_h:.3f}")


def extract(mats):
    faces = []
    for m in mats:
        faces += parts.get(m, [])
    used = sorted({i for f in faces for i in f})
    remap = {old: new for new, old in enumerate(used)}
    subV = apply_sim(verts[used], R, s, t)
    tris: list[tuple[int, int, int]] = []
    for f in faces:                       # fan-triangulate any quads
        r = [remap[i] for i in f]
        for k in range(1, len(r) - 1):
            tris.append((r[0], r[k], r[k + 1]))
    return subV, np.asarray(tris, dtype=np.int64)


# Separate COLOURABLE groups (teeth white, gums+tongue red, sclera white, iris coloured).
groups = {
    "teeth": ["M_Teeth"],
    "gumsTongue": ["M_GumsTongue"],
    "sclera": ["M_ScleraLeft", "M_ScleraRight"],
    "iris": ["M_IrisLeft", "M_IrisRight"],
}
out = {}
for name, mats in groups.items():
    V, F = extract(mats)
    c = V.mean(0)
    print(f"{name:11s}: {len(V):5d} v  {len(F):5d} tris  bbox min{V.min(0).round(2)} max{V.max(0).round(2)} centroid{c.round(2)}")
    out[name] = {
        "vertexCount": len(V),
        "positions": [round(float(x), 4) for x in V.reshape(-1)],
        "indices": [int(i) for i in F.reshape(-1)],
    }

doc = {
    "source": "USC ICT-FaceKit (MIT) generic_neutral_mesh -> MediaPipe canonical frame; RB-003 Item 3",
    "frame": "MediaPipe canonical (canonical_face_model.obj). The runtime computes a similarity from "
             "`canonical468` to the LIVE 468-vertex portrait mesh (shared topology) and applies it to "
             "every group, so the teeth/eyes land on the live mouth/eyes.",
    "canonicalHeight": round(mp_h, 6),
    # Canonical 468 positions (same frame as the groups) so the runtime can fit canonical -> live.
    "canonical468": [round(float(x), 4) for x in mp.reshape(-1)],
    "groups": out,
}
OUT.write_text(json.dumps(doc, separators=(",", ":")))
size = OUT.stat().st_size
print(f"\nwrote {OUT.name}: {size/1024:.0f} KB  groups: " + ", ".join(f"{k} {v['vertexCount']}v" for k, v in out.items()))
