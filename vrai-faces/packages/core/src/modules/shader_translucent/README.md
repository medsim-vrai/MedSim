# shader_translucent

## Purpose
Wraps `THREE.MeshPhysicalNodeMaterial` with a real TSL Fresnel rim and
exposes the single `opacityLevel ∈ [0, 1]` slider — the only user-facing
translucency control. Memory_management.MD §4 is the table of record.

## Public contract
See `src/types/shader_translucent.ts`. Barrel: `shaderTranslucent`.

## Dependencies
- `three` (the `three/webgpu` superset — node materials + TSL helpers come
  from the same module instance; `three/tsl` resolves to the same build)
- `@contracts/*`

## Gotchas
- The slider drives ONE value. Never expose `transmission`, `opacity`,
  etc., to the UI — they are derivatives. `mapOpacity()` is the only
  legal place to compute them.
- `dispose()` must call `material.dispose()` on Three — leaking GPU
  memory across scenarios is the #1 way to break the soak test.
- `setOpacity()` is uniform-only and must not recompile per call. The rim
  strength rides on a TSL `uniform()` so its updates are uniform writes.
  (One exception is unavoidable: the first move off fully-opaque enables
  the transmission shader path inside `MeshPhysicalNodeMaterial` — a single
  recompile. Steady-state slides never recompile.)
- We render through `WebGPURenderer` (ADR-0009), so the Fresnel rim is a
  TSL node graph, **not** `onBeforeCompile` — that hook is WebGLRenderer-
  only and never fires here.

## Tests
`__tests__/shader_translucent.test.ts` — verifies the `mapOpacity` table
matches the four anchor rows from Memory_management.MD §4, that `build()`
produces a `MeshPhysicalNodeMaterial` carrying a Fresnel `emissiveNode`,
that `setOpacity()` is uniform-only in steady state (same node object,
`version` unchanged), and that `snapshot()` round-trips the slider value.
