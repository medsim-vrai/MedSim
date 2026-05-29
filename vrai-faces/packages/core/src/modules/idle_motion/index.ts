import type { IdleMotionModule } from '@contracts/idle_motion';
import { createImpl } from './impl/create';

export const idleMotion: IdleMotionModule = createImpl();
