import type { AnimationRuntimeModule } from '@contracts/animation_runtime';
import { createImpl } from './impl/create';

export const animationRuntime: AnimationRuntimeModule = createImpl();
