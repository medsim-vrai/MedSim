import type { Lifecycle } from './shared';
import type { BuiltMesh } from './mesh_builder';
import type { TranslucentMaterialSnapshot } from './shader_translucent';

export interface AvatarExporterModule extends Lifecycle {
  exportGLB(input: ExportInput): Promise<Blob>;
  exportVRM(input: ExportInput): Promise<Blob>;
}

export interface ExportInput {
  mesh: BuiltMesh;
  translucency: TranslucentMaterialSnapshot;
  /** Bake the current opacity into KHR_materials_transmission + extras.vraiOpacity. */
  bakeOpacity: boolean;
}
