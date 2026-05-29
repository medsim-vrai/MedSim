import type { MedsimAdapterModule } from '@contracts/medsim_adapter';
import { createImpl } from './impl/create';

export const medsimAdapter: MedsimAdapterModule = createImpl();
