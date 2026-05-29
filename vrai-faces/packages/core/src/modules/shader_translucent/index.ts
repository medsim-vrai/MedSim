import type { ShaderTranslucentModule } from '@contracts/shader_translucent';
import { createImpl } from './impl/create';

export const shaderTranslucent: ShaderTranslucentModule = createImpl();
