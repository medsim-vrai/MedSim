import type { FaceIngestModule } from '@contracts/face_ingest';
import { createImpl } from './impl/create';

export const faceIngest: FaceIngestModule = createImpl();
