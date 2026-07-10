# Rig-lab sandbox — preview a candidate morph basis in the live runtime

**Status:** dev tooling · default OFF · additive, reversible · 2026-07-10

A separate audit ([Cranial Nerve Face Rig] `docs/AUDIT_vrai_faces_rigid_drift.md`) found that the baked
ARKit basis drifts the seven landmarks the CN-rig measurement engine treats as bone-anchored. No
rig-side repair is a clean fix (pinning the landmarks tears the mesh; feathering deletes ~28% of the
eyelid motion), and the accepted fix is measurement-side. But we still want to *see* a candidate basis
in the real Three.js runtime before it could ever ship. This flag does that without touching the
default path.

## Use it

```
https://<app>/?rigBasis=feathered
```

Loads `/assets/face/face_mesh_morphbasis.feathered.json` instead of the shipped basis. The flag reads
from the query **or** the hash, and `<name>` is restricted to `[a-z0-9]+` — it can only ever name a
sibling asset (`face_mesh_morphbasis.<name>.json`), never a path outside `/assets/face/`. Confirm it's
active in the console:

```
[rig-lab] morph basis override active: /assets/face/face_mesh_morphbasis.feathered.json
```

`?rigBasis=shipped` (or no flag at all) is the default. If the named asset is missing or malformed, the
loader silently falls back to the shipped basis, then to the procedural rig — a bad flag never breaks a
session.

## Ship / generate a candidate

Candidate variants are produced by the CN-rig repo, which owns the repair math:

```
# in the Cranial Nerve Face Rig repo
python scripts/emit_sandbox_basis.py feathered_0.8cm \
  --out <this repo>/vrai-faces/packages/core/public/assets/face/face_mesh_morphbasis.feathered.json
```

Output is byte-compatible with `face_mesh_morphbasis.json` (sparse deltas as fractions of
`canonicalHeight`, same prune floor), so `morph_basis.ts` loads it unchanged. Other variants:
`rigid_zeroed`, `midline_pinned` — see the CN-rig `scripts/rig_lab.py` scorecard.

## Safety

- **Default OFF.** With no flag, `loadMorphBasis()` is the exact single fetch it always was
  (`resolveBasisUrls('')` → `['/assets/face/face_mesh_morphbasis.json']`).
- **Sandbox assets are DEV/TEST** — each carries a `source` field marking it so, and none is the
  default. They may be committed for convenience (fetched only under the flag) or generated on demand.
- Covered by `src/modules/mesh_builder/__tests__/morph_basis_sandbox.test.ts`.
