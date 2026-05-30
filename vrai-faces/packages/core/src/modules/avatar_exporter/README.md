# avatar_exporter

## Purpose
Serializes the live mesh + material + morph targets to glTF 2.0 and
(optionally) VRM 1.0. Bakes the current `opacityLevel` into
`KHR_materials_transmission` and `extras.vraiOpacity`.

## Public contract
See `src/types/avatar_exporter.ts`. Barrel: `avatarExporter`.

## Dependencies
- `@contracts/*`
- `@utils/resource_registry` — reads the bound geometry back by ref
- (NO `three/addons` `GLTFExporter` — see Gotchas)

## Gotchas
- HAND-ROLLED writer, deliberately NOT `three/addons` `GLTFExporter`: that addon
  imports the classic `three` entry and would load a second Three-core instance
  beside the app's `three/webgpu`, reintroducing the "multiple instances of
  Three" unlit-avatar bug. Geometry is read back from the shared registry
  (already on `three/webgpu`).
- ARKit-52 morph names come from `geometry.userData.morphTargetNames`
  (mesh_builder owns the canonical list) and export as `mesh.extras.targetNames`,
  so the blendshape set round-trips by name.
- Morph targets bake as per-primitive `targets[]` (POSITION deltas) with
  `mesh.weights` all 0; the whole block is omitted for unrigged/placeholder
  geometry. Today the deltas are mesh_builder's procedural basis; a real rig
  swaps in via the same path.
- Do NOT bake camera/lighting. Exports are scenario-portable.
- `extras.vraiOpacity` lets a re-import reconstruct the slider position.

## Tests
`__tests__/avatar_exporter.test.ts` — valid glTF 2.0 container; opacity baking
(`KHR_materials_transmission` + `extras.vraiOpacity`/`vraiBaselineMood`); the VRM
`VRMC_vrm` extension; and morph-target baking (named `targets[]` + weights +
accessor bounds, omitted when unrigged).
