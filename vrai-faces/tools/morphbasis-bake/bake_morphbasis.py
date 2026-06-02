#!/usr/bin/env python3
"""RB-001 bake (ADR-0034): ICT-FaceKit ARKit expression shapes -> MediaPipe-468 morph deltas.

Deterministic, OFFLINE. Replaces the procedural 4-of-52 basis with real ARKit-52 deltas baked
onto MediaPipe's canonical 468-vertex topology. Sources: USC ICT-FaceKit (MIT), MediaPipe
canonical_face_model.obj (Apache-2.0).

Method (cross-topology resample — ICT is 26,719 v, MediaPipe is 468 v):
  1. Umeyama similarity-align the ICT neutral to the MediaPipe neutral using shared dlib-68
     landmarks (ICT side via vertex_indices.json:idx_to_landmark_verts; MediaPipe side via
     well-known canonical indices below). Print the landmark residual + surface overlap as a
     trust check before transferring anything.
  2. For each MediaPipe vertex, find its nearest vertex on the aligned ICT neutral (ICT is dense,
     so nearest-vertex ~= nearest-surface-point).
  3. For each expression OBJ: delta_local = ict_expr - ict_neutral; sample at the nearest index;
     rotate+scale into the MediaPipe frame -> the 468-vertex morph delta.

Usage:  ./.venv/bin/python bake_morphbasis.py            # bakes every expression OBJ present in _assets/
        ./.venv/bin/python bake_morphbasis.py --poc      # proof-of-concept: alignment + the samples only
"""
from __future__ import annotations
import json
import sys
from pathlib import Path
import numpy as np

HERE = Path(__file__).resolve().parent
ASSETS = HERE / "_assets"
WORK = HERE / "_work"

# dlib-68 landmark index -> MediaPipe-468 vertex index, for a well-spread set of STABLE features.
# Used ONLY to similarity-align the two neutral meshes (least-squares, so robust to a stray point);
# the printed residual + overlap validate the choice. MediaPipe indices are the widely-documented
# canonical_face_model landmarks.
DLIB_TO_MP = {
    30: 1,    # nose tip
    8:  152,  # chin (menton)
    36: 33,   # right eye, outer corner
    39: 133,  # right eye, inner corner
    42: 362,  # left eye, inner corner
    45: 263,  # left eye, outer corner
    48: 61,   # mouth, right corner
    54: 291,  # mouth, left corner
    0:  234,  # right cheek / face contour
    16: 454,  # left cheek / face contour
    27: 168,  # nose bridge (top)
    57: 17,   # lower lip / chin crease (centre-bottom of mouth)
}


def load_obj_vertices(path: Path) -> np.ndarray:
    vs: list[tuple[float, float, float]] = []
    with open(path) as f:
        for line in f:
            if line.startswith("v "):
                p = line.split()
                vs.append((float(p[1]), float(p[2]), float(p[3])))
    return np.asarray(vs, dtype=np.float64)


def umeyama(src: np.ndarray, dst: np.ndarray):
    """Least-squares similarity transform (R, s, t) mapping src -> dst (Umeyama 1991).
    Returns (R, s, t) such that dst ~= s * (src @ R.T) + t."""
    n = src.shape[0]
    mu_s, mu_d = src.mean(0), dst.mean(0)
    Sc, Dc = src - mu_s, dst - mu_d
    var_s = (Sc ** 2).sum() / n
    cov = (Dc.T @ Sc) / n
    U, S, Vt = np.linalg.svd(cov)
    d = np.ones(3)
    if np.linalg.det(U) * np.linalg.det(Vt) < 0:
        d[-1] = -1.0  # enforce a proper rotation (no reflection)
    R = U @ np.diag(d) @ Vt
    s = float((S * d).sum() / var_s)
    t = mu_d - s * (mu_s @ R.T)
    return R, s, t


def apply_sim(p: np.ndarray, R, s, t) -> np.ndarray:
    return s * (p @ R.T) + t


def nearest_indices(query: np.ndarray, cloud: np.ndarray) -> np.ndarray:
    """For each row of query, the index of the nearest row in cloud (chunked, numpy-only)."""
    out = np.empty(query.shape[0], dtype=np.int64)
    c2 = (cloud ** 2).sum(1)  # |c|^2
    for i in range(query.shape[0]):
        d2 = c2 - 2.0 * (cloud @ query[i]) + (query[i] ** 2).sum()
        out[i] = int(np.argmin(d2))
    return out


# --- ICT stem -> ARKit-52 canonical naming (the names mesh_builder/avatar_exporter use) ---
# 18 bases are left/right in both: ICT "_L"/"_R" -> ARKit "Left"/"Right".
_LR_BASES = ["browDown", "browOuterUp", "cheekSquint", "eyeBlink", "eyeLookDown", "eyeLookIn",
             "eyeLookOut", "eyeLookUp", "eyeSquint", "eyeWide", "mouthDimple", "mouthFrown",
             "mouthLowerDown", "mouthPress", "mouthSmile", "mouthStretch", "mouthUpperUp", "noseSneer"]
# 13 are centre/unified in both — ICT name already matches ARKit.
_PASSTHROUGH = ["jawForward", "jawLeft", "jawOpen", "jawRight", "mouthClose", "mouthFunnel",
                "mouthLeft", "mouthPucker", "mouthRight", "mouthRollLower", "mouthRollUpper",
                "mouthShrugLower", "mouthShrugUpper"]
# ARKit-unified, but ICT splits L/R -> sum the halves.
_MERGE = {"browInnerUp": ("browInnerUp_L", "browInnerUp_R"), "cheekPuff": ("cheekPuff_L", "cheekPuff_R")}
# tongueOut (ARKit #52) is absent from ICT -> omitted (documented; low clinical relevance).
OUT_JSON = HERE.parent.parent / "packages/core/src/modules/mesh_builder/impl/face_mesh_morphbasis.json"


def emit_arkit_json(results: dict, canonical_height: float, eps: float = 0.01) -> dict:
    """Map ICT deltas -> ARKit-52 names (+ eyesClosed), normalize to canonical height,
    sparse-prune, and write face_mesh_morphbasis.json. Deltas are stored as FRACTIONS of
    the canonical face height so morph_basis.ts can rescale them to the live mesh."""
    arkit: dict = {}
    for base in _LR_BASES:
        if base + "_L" in results:
            arkit[base + "Left"] = results[base + "_L"]
        if base + "_R" in results:
            arkit[base + "Right"] = results[base + "_R"]
    for name in _PASSTHROUGH:
        if name in results:
            arkit[name] = results[name]
    for uni, (l, r) in _MERGE.items():
        if l in results and r in results:
            arkit[uni] = results[l] + results[r]
    # Supplemental AU43 (ADR-0034): sustained eye closure = the eyeBlink lid geometry, both eyes.
    if "eyeBlink_L" in results and "eyeBlink_R" in results:
        arkit["eyesClosed"] = results["eyeBlink_L"] + results["eyeBlink_R"]

    shapes: dict = {}
    for name, d in sorted(arkit.items()):
        frac = d / canonical_height
        mag = np.sqrt((d ** 2).sum(1))
        idxs = np.where(mag > eps)[0]
        shapes[name] = [[int(i), round(float(frac[i, 0]), 6), round(float(frac[i, 1]), 6),
                         round(float(frac[i, 2]), 6)] for i in idxs]
    doc = {
        "version": 1,
        "source": "ICT-FaceKit (MIT) -> MediaPipe-468 (Apache-2.0); RB-001/ADR-0034 deformation-transfer bake",
        "vertexCount": 468,
        "normalization": "delta = fraction of canonical face height; multiply by the live mesh height at load",
        "canonicalHeight": round(float(canonical_height), 6),
        "shapeCount": len(shapes),
        "shapes": shapes,
    }
    OUT_JSON.parent.mkdir(parents=True, exist_ok=True)
    OUT_JSON.write_text(json.dumps(doc, separators=(",", ":")))
    return doc


def main() -> int:
    poc = "--poc" in sys.argv
    WORK.mkdir(exist_ok=True)
    vidx = json.load(open(ASSETS / "vertex_indices.json"))
    lmk_verts = vidx["idx_to_landmark_verts"]  # dlib-68 -> ICT vertex index

    ict_neutral = load_obj_vertices(ASSETS / "generic_neutral_mesh.obj")
    mp = load_obj_vertices(ASSETS / "canonical_face_model.obj")
    print(f"ICT neutral: {ict_neutral.shape[0]} v   MediaPipe: {mp.shape[0]} v")

    # --- build landmark correspondence + align -------------------------------
    src_lm, dst_lm = [], []
    for dlib_i, mp_i in DLIB_TO_MP.items():
        src_lm.append(ict_neutral[lmk_verts[dlib_i]])
        dst_lm.append(mp[mp_i])
    src_lm, dst_lm = np.asarray(src_lm), np.asarray(dst_lm)
    R, s, t = umeyama(src_lm, dst_lm)

    # trust checks
    proj = apply_sim(src_lm, R, s, t)
    lm_res = float(np.sqrt(((proj - dst_lm) ** 2).sum(1)).mean())
    face_extent = float(np.linalg.norm(mp.max(0) - mp.min(0)))
    ict_aligned = apply_sim(ict_neutral, R, s, t)
    nn = nearest_indices(mp, ict_aligned)
    overlap = float(np.sqrt(((mp - ict_aligned[nn]) ** 2).sum(1)).mean())
    print("\n== ALIGNMENT TRUST CHECK ==")
    print(f"  scale s              : {s:.4f}")
    print(f"  landmark RMS residual: {lm_res:.4f}  ({100*lm_res/face_extent:.2f}% of face extent {face_extent:.2f})")
    print(f"  neutral surface overlap (mean MP->ICT nearest dist): {overlap:.4f}  ({100*overlap/face_extent:.2f}%)")
    good = lm_res < 0.08 * face_extent and overlap < 0.05 * face_extent
    print(f"  verdict: {'OK — alignment trustworthy' if good else 'POOR — fix landmark indices before trusting deltas'}")

    # --- transfer each expression present in _assets -------------------------
    samples = ["jawOpen", "mouthSmile_L", "browDown_L"]
    expr_files = sorted(p for p in ASSETS.glob("*.obj")
                        if p.stem not in ("generic_neutral_mesh", "canonical_face_model")
                        and not p.stem.startswith("identity"))
    if poc:
        expr_files = [ASSETS / f"{n}.obj" for n in samples if (ASSETS / f"{n}.obj").exists()]

    print(f"\n== TRANSFER ({len(expr_files)} shape(s)) ==")
    results = {}
    for p in expr_files:
        ev = load_obj_vertices(p)
        if ev.shape[0] != ict_neutral.shape[0]:
            print(f"  {p.stem:18s} SKIP (vertex count {ev.shape[0]} != neutral)")
            continue
        delta_local = ev - ict_neutral                     # ICT-frame per-vertex motion
        delta_mp = s * (delta_local[nn] @ R.T)              # -> MediaPipe frame, sampled at 468
        mag = np.sqrt((delta_mp ** 2).sum(1))
        moved = int((mag > 0.05).sum())
        c = mp[mag > 0.05].mean(0) if moved else np.zeros(3)
        print(f"  {p.stem:18s} max|d|={mag.max():.3f}  mean={mag.mean():.4f}  moved>{0.05}:{moved:3d}/468  region~[{c[0]:+.1f},{c[1]:+.1f},{c[2]:+.1f}]")
        results[p.stem] = delta_mp
    np.savez(WORK / "poc_deltas.npz", **{k: v.astype(np.float32) for k, v in results.items()})
    print(f"\nSaved {len(results)} delta set(s) -> {WORK / 'poc_deltas.npz'}")

    # Emit the ARKit-named basis once the full set is present (51 ICT shapes -> 51 ARKit + eyesClosed).
    if not poc and len(results) >= 51:
        canon_h = float(mp[:, 1].max() - mp[:, 1].min())
        doc = emit_arkit_json(results, canon_h)
        size = OUT_JSON.stat().st_size
        nz = sum(len(v) for v in doc["shapes"].values())
        print(f"\n== EMIT == {OUT_JSON.name}: {doc['shapeCount']} ARKit shapes, "
              f"{nz} sparse deltas, canonicalHeight={doc['canonicalHeight']}, {size/1024:.0f} KB")
        print("  names:", ", ".join(sorted(doc["shapes"].keys())))
    return 0 if good else 2


if __name__ == "__main__":
    raise SystemExit(main())
