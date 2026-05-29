import type { Lifecycle } from './shared';
import type { GeometryRef, TextureRef } from './mesh_builder';

export interface ShaderTranslucentModule extends Lifecycle {
  /** Build a translucent material wrapping a mesh. */
  build(opts: { geometry: GeometryRef; texture: TextureRef }): TranslucentMaterial;

  /** Set the slider value (0 = ghost, 1 = opaque). */
  setOpacity(materialId: string, level: number): void;

  /** Read the current settings (for export). */
  snapshot(materialId: string): TranslucentMaterialSnapshot;
}

export interface TranslucentMaterial { readonly id: string; }

export interface TranslucentMaterialSnapshot {
  opacityLevel: number;               // 0..1; the single slider value
  transmission: number;
  opacity: number;
  fresnelStrength: number;
  specularIntensity: number;
}
