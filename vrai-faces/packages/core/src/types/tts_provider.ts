import type { Lifecycle, TtsVoiceId } from './shared';

/**
 * Pluggable TTS layer. The router enforces the tier→provider mapping
 * and the failover chain in Memory_management.MD §7 (ADR-0011..0015).
 */
export interface TtsProviderModule extends Lifecycle {
  warmup(): Promise<void>;

  speak(req: TtsRequest): AsyncIterable<TtsChunk>;

  /** What provider would be used right now for this tier? */
  activeProvider(tier: TtsTier): ProviderName | null;
}

export type TtsTier = 'primary' | 'hero' | 'conversational' | 'local';

export type ProviderName =
  | 'azure-hd-v2'
  | 'elevenlabs-v3'
  | 'cartesia-sonic-3'
  | 'aws-polly'
  | 'deepgram'
  | 'resemble'
  | 'headtts-kokoro'
  | 'piper-wasm';

export interface TtsRequest {
  text: string;
  voice: TtsVoiceId;
  tier: TtsTier;
  /** PHI classifier hint — see ADR-0014. */
  source: 'scripted' | 'trainee_input' | 'unknown';
  /** Optional emotion hint for providers that support it. */
  emotion?: string;
}

export interface TtsChunk {
  audio: ArrayBuffer;
  audioFormat: 'pcm16-24k' | 'opus' | 'mp3';
  /** Native visemes when the provider emits them (Azure, AWS Polly). */
  visemes?: Array<{ t: number; id: string; w: number }>;
  endOfUtterance?: boolean;
}
