import type { BlendshapeWeights, Lifecycle } from './shared';
import type { NormalizedPortrait } from './face_ingest';

export interface MeshBuilderModule extends Lifecycle {
  build(portrait: NormalizedPortrait): Promise<BuiltMesh>;
}

export interface BuiltMesh {
  meshId: string;
  /** Owning Three.BufferGeometry handle (kept opaque to consumers). */
  geometryRef: GeometryRef;
  /** Texture handle for diffuse map. */
  textureRef: TextureRef;
  /** ARKit-52 baseline weights for this identity (neutral expression). */
  baselineMood: BlendshapeWeights;
  vertexCount: number;
}

export type GeometryRef = { readonly __brand: 'GeometryRef'; readonly id: string };
export type TextureRef  = { readonly __brand: 'TextureRef';  readonly id: string };
