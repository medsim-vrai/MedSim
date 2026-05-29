import type { MeshBuilderModule } from '@contracts/mesh_builder';
import { createImpl } from './impl/create';

export const meshBuilder: MeshBuilderModule = createImpl();
