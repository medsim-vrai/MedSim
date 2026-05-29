import type { Lifecycle } from './shared';

/**
 * Dev-only overlay. Off in production (no DOM nodes mounted).
 * Reads from the diag singleton in perf/diag.ts.
 */
export interface DiagnosticPanelModule extends Lifecycle {
  show(): void;
  hide(): void;
  /** True only when ?diag=1 is in the URL or DEV mode. */
  isAvailable(): boolean;
}
