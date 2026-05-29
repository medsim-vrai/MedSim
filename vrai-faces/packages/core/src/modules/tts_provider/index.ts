import type { TtsProviderModule } from '@contracts/tts_provider';
import { createImpl } from './impl/create';

export const ttsProvider: TtsProviderModule = createImpl();
