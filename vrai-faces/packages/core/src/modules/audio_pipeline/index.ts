import type { AudioPipelineModule } from '@contracts/audio_pipeline';
import { createImpl } from './impl/create';

export const audioPipeline: AudioPipelineModule = createImpl();
