import type { DiagnosticPanelModule } from '@contracts/diagnostic_panel';
import { createImpl } from './impl/create';

export const diagnosticPanel: DiagnosticPanelModule = createImpl();
