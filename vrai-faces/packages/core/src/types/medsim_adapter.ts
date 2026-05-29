import type { Lifecycle, Resumable, VRAISpeechFrame, VraiAvatarBinding } from './shared';

/**
 * The ONLY module that knows about MedSim. Reads scenario character
 * definitions (read-only) and owns the BroadcastChannel / WebSocket
 * speech interop.
 */
export interface MedsimAdapterModule extends Lifecycle, Resumable<MedsimSnapshot> {
  /** Load a character binding from a MedSim scenario character payload. */
  bindFromCharacter(raw: unknown): Promise<VraiAvatarBinding>;

  /** Subscribe to incoming speech frames. */
  onSpeechFrame(handler: (f: VRAISpeechFrame) => void): () => void;

  /** Currently bound character, if any. */
  currentBinding(): VraiAvatarBinding | null;

  /** Connection transport that's active right now. */
  transport(): 'broadcast-channel' | 'websocket' | 'none';
}

export interface MedsimSnapshot {
  binding: VraiAvatarBinding | null;
  lastSeq: number;
  transport: 'broadcast-channel' | 'websocket' | 'none';
}
