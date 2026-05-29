import type { Lifecycle, SessionState } from './shared';

/**
 * Owns the pause / resume persistence layer. Writes to IndexedDB so the
 * tablet can be put to sleep and a scenario picked up where it left off
 * (ADR-0017). Does NOT store PHI free-text (only structured state).
 */
export interface MemoryStateModule extends Lifecycle {
  /** Persist the aggregate state for this scenario+character. */
  save(state: SessionState): Promise<void>;

  /** Read the last persisted state, or null. */
  load(scenarioId: string, characterId: string): Promise<SessionState | null>;

  /** Wipe persistence for this scenario+character. */
  clear(scenarioId: string, characterId: string): Promise<void>;

  /** Register a module's snapshot/restore hooks for the global pause. */
  register(moduleId: string, hooks: SnapshotHooks): void;

  /** Pause every registered module and snapshot to disk. */
  pauseAll(): Promise<SessionState>;

  /** Restore every registered module from disk and resume. */
  resumeAll(scenarioId: string, characterId: string): Promise<void>;
}

export interface SnapshotHooks {
  snapshot(): unknown;
  restore(snap: unknown): Promise<void>;
  pause(): Promise<void>;
  resume(): Promise<void>;
}
