import type { EmotionDriverModule } from '@contracts/emotion_driver';
import { createImpl } from './impl/create';

export const emotionDriver: EmotionDriverModule = createImpl();
