import type { AvatarExporterModule } from '@contracts/avatar_exporter';
import { createImpl } from './impl/create';

export const avatarExporter: AvatarExporterModule = createImpl();
