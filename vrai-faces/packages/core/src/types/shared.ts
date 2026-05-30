// Cross-cutting types. Imported by most modules.
// Do not import from any module here — types only.

/** Boot → run → dispose contract; every module implements this. */
export interface Lifecycle {
  boot(deps: BootDeps): Promise<void>;
  dispose(): void;
}

/**
 * Pause/Resume contract (ADR-0017). Modules that hold runtime state must
 * implement `snapshot()` returning a structured-clone-safe value and
 * `restore()` accepting that same value. Modules that are pure
 * (e.g. shader_translucent, idle_motion) MAY omit this.
 */
export interface Resumable<TSnapshot = unknown> {
  pause(): Promise<void>;
  resume(): Promise<void>;
  snapshot(): TSnapshot;
  restore(s: TSnapshot): Promise<void>;
}

export interface BootDeps {
  /** A diagnostic registry handle; modules push events to it. */
  diag: DiagHandle;
  /** Per-scenario unique id; used as a namespace in memory_state. */
  scenarioId: string;
  /** Per-character unique id (the MedSim character primary key). */
  characterId: string;
  /** Optional AbortSignal; resolves to "dispose" when aborted. */
  signal?: AbortSignal;
}

export interface DiagHandle {
  push(event: TimelineEvent): void;
  set(moduleId: string, stat: Partial<ModuleStat>): void;
}

export interface TimelineEvent {
  t: number;                          // perf.now() ms
  moduleId: string;
  kind: 'info' | 'warn' | 'error' | 'metric';
  message: string;
  data?: unknown;
}

export interface ModuleStat {
  state: 'idle' | 'booting' | 'running' | 'paused' | 'failed' | 'disposed';
  lastError?: string;
  fps?: number;
  lastTickMs?: number;
}

/** ARKit-52 keyed weights. */
export type BlendshapeWeights = Record<string, number>;

/**
 * Wire format flowing from MedSim → VRAI Faces.
 * Identical over BroadcastChannel (same-origin) and WebSocket (cross-app).
 * See Memory_management.MD §6.2.
 */
export interface VRAISpeechFrame {
  v: 1;
  characterId: string;
  seq: number;
  audio?: ArrayBuffer;
  audioFormat?: 'pcm16-24k' | 'opus' | 'mp3';
  visemes?: Array<{ t: number; id: string; w: number }>;
  text?: string;
  endOfUtterance?: boolean;
  emotion?: { label: string; weights: BlendshapeWeights };
}

/** The contract bound when a MedSim scenario opens a character on the tablet. */
export interface VraiAvatarBinding {
  characterId: string;
  sourcePhoto: Blob;
  voiceProfile: TtsVoiceId;
  baselineMood: BlendshapeWeights;
  opacityLevel: number;               // 0..1
  exportPath?: string;
  /** Per-scenario ghost tint (Phase 0 decision 4); default clinical white if unset. */
  ghostColor?: string;
  /** Cross-app speech WebSocket endpoint (ADR-0007). When set, the adapter uses
   *  WebSocket transport; otherwise same-origin BroadcastChannel. */
  speechWsUrl?: string;
}

export type TtsVoiceId = string & { readonly __brand: 'TtsVoiceId' };

/** Aggregate persistable state — what memory_state writes to IndexedDB. */
export interface SessionState {
  v: 1;
  scenarioId: string;
  characterId: string;
  opacityLevel: number;
  lastBinding?: Pick<VraiAvatarBinding,
    'characterId' | 'voiceProfile' | 'baselineMood' | 'opacityLevel' | 'exportPath'>;
  /** Each module's own snapshot, keyed by moduleId. */
  modules: Record<string, unknown>;
  savedAt: number;                    // Date.now()
}
