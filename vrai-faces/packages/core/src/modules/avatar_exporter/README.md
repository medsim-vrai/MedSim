# avatar_exporter

## Purpose
Serializes the live mesh + material + morph targets to glTF 2.0 and
(optionally) VRM 1.0. Bakes the current `opacityLevel` into
`KHR_materials_transmission` and `extras.vraiOpacity`.

## Public contract
See `src/types/avatar_exporter.ts`. Barrel: `avatarExporter`.

## Dependencies
- `three` (`GLTFExporter`)
- `@contracts/*`
- VRM utility (deferred to a sub-impl file)

## Gotchas
- ARKit-52 morph names must match the canonical list. A lint rule in the
  impl folder asserts this on each export.
- Do NOT bake camera/lighting. Exports are scenario-portable.
- `extras.vraiOpacity` lets a re-import reconstruct the slider position.

## Tests
`__tests__/avatar_exporter.test.ts` — barrel shape only for now. Full
round-trip glTF asserts go into a future `test/unit/exporter.test.ts`
once the impl lands.
