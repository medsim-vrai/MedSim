import type { MemoryStateModule } from '@contracts/memory_state';
import { createImpl } from './impl/create';

export const memoryState: MemoryStateModule = createImpl();
