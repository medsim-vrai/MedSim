import type {
  MedsimAdapterModule,
  MedsimSnapshot,
} from '@contracts/medsim_adapter';
import type {
  BootDeps,
  BlendshapeWeights,
  TtsVoiceId,
  VRAISpeechFrame,
  VraiAvatarBinding,
} from '@contracts/shared';
import { parseFrame } from './parse';
import { parseCharacterCard, voiceIdFromProfile } from './medsim_character';

const DEFAULT_OPACITY = 0.66;        // table mid-stop (matches the demo default)
const DEFAULT_VOICE = 'default' as TtsVoiceId;

function clamp01(n: number): number { return n < 0 ? 0 : n > 1 ? 1 : n; }

function str(o: Record<string, unknown>, ...keys: string[]): string | undefined {
  for (const k of keys) {
    const v = o[k];
    if (typeof v === 'string' && v.length > 0) return v;
  }
  return undefined;
}

function num(o: Record<string, unknown>, ...keys: string[]): number | undefined {
  for (const k of keys) {
    const v = o[k];
    if (typeof v === 'number' && Number.isFinite(v)) return v;
  }
  return undefined;
}

/** Decode a `data:` URI to a Blob locally (no network — keeps PHI on-device). */
function dataUriToBlob(uri: string): Blob | null {
  const m = /^data:([^;,]*)(;base64)?,(.*)$/s.exec(uri);
  if (!m) return null;
  const mime = m[1] || 'application/octet-stream';
  const body = m[3] ?? '';
  if (m[2]) {
    const bin = atob(body);
    const bytes = new Uint8Array(bin.length);
    for (let i = 0; i < bin.length; i++) bytes[i] = bin.charCodeAt(i);
    return new Blob([bytes], { type: mime });
  }
  return new Blob([decodeURIComponent(body)], { type: mime });
}

/** Pull a portrait Blob from the payload (a real Blob, or a `data:` URI). */
function extractPhoto(o: Record<string, unknown>): Blob {
  const candidate =
    o['sourcePhoto'] ?? o['photo'] ?? o['portrait'] ?? o['avatar'] ?? o['image'];
  if (candidate instanceof Blob) return candidate;
  if (typeof candidate === 'string' && candidate.startsWith('data:')) {
    const b = dataUriToBlob(candidate);
    if (b) return b;
  }
  throw new Error(
    'medsim_adapter.bindFromCharacter: character payload has no usable portrait ' +
    '(expected a Blob or data: URI under sourcePhoto/photo/portrait/avatar/image).',
  );
}

/** Read an explicit baseline-mood weights map; ignores label strings (the live
 *  emotion_driver owns label→weights). Out-of-range weights are clamped. */
function extractMood(o: Record<string, unknown>): BlendshapeWeights {
  const m = o['baselineMood'] ?? o['mood'];
  const out: BlendshapeWeights = {};
  if (m && typeof m === 'object') {
    for (const [k, v] of Object.entries(m as Record<string, unknown>)) {
      if (typeof v === 'number' && Number.isFinite(v)) out[k] = clamp01(v);
    }
  }
  return out;
}

/** Validate + normalize a MedSim character payload into a binding. Throws on
 *  anything it can't turn into a renderable avatar (fail-closed). */
function parseCharacter(raw: unknown): VraiAvatarBinding {
  if (!raw || typeof raw !== 'object') {
    throw new Error('medsim_adapter.bindFromCharacter: payload must be an object.');
  }
  const o = raw as Record<string, unknown>;

  // Prefer the REAL MedSim character card (schemas/character.json, §9); fall back
  // to the tolerant key-scan for synthetic/legacy payloads.
  const card = parseCharacterCard(raw);

  const characterId = card?.id ?? str(o, 'characterId', 'id');
  if (!characterId) {
    throw new Error('medsim_adapter.bindFromCharacter: payload missing characterId/id.');
  }

  // The MedSim card has no portrait — the portal attaches one at launch (Phase 4.3).
  const sourcePhoto = extractPhoto(o);
  const voiceProfile = card?.voice_profile
    ? voiceIdFromProfile(card.voice_profile)
    : ((str(o, 'voiceProfile', 'voice', 'voiceId') ?? DEFAULT_VOICE) as TtsVoiceId);
  const opacityLevel = clamp01(num(o, 'opacityLevel', 'opacity', 'translucency') ?? DEFAULT_OPACITY);
  const baselineMood = extractMood(o);   // card carries no weights; emotion_driver owns live mood
  const exportPath = str(o, 'exportPath');
  const ghostColor = str(o, 'ghostColor', 'baseColor');

  const binding: VraiAvatarBinding = {
    characterId, sourcePhoto, voiceProfile, baselineMood, opacityLevel,
  };
  // exactOptionalPropertyTypes: only set optional keys when present.
  if (exportPath !== undefined) binding.exportPath = exportPath;
  if (ghostColor !== undefined) binding.ghostColor = ghostColor;
  return binding;
}

export function createImpl(): MedsimAdapterModule {
  let _deps: BootDeps | null = null;
  let binding: VraiAvatarBinding | null = null;
  let lastSeq = 0;
  let transport: 'broadcast-channel' | 'websocket' | 'none' = 'none';
  const speechHandlers = new Set<(f: VRAISpeechFrame) => void>();
  let channel: BroadcastChannel | null = null;

  // Bridge: incoming raw → parsed → dispatch.
  function dispatch(raw: unknown): void {
    const f = parseFrame(raw);
    if (!f) return;                       // drop malformed; ADR-0014 fail-closed
    if (f.seq <= lastSeq) return;         // out-of-order or duplicate
    lastSeq = f.seq;
    for (const h of speechHandlers) h(f as VRAISpeechFrame);
  }

  // Same-origin speech transport (Memory_management.MD §6.2). The cross-app
  // WebSocket transport is a follow-up; BroadcastChannel covers the common
  // case where MedSim and VRAI Faces share an origin. Guarded so non-browser
  // environments (and unit tests, which never boot) simply stay 'none'.
  function connect(scenarioId: string): void {
    if (channel || typeof BroadcastChannel === 'undefined') return;
    channel = new BroadcastChannel(`vrai:${scenarioId}`);
    channel.onmessage = (ev: MessageEvent) => dispatch(ev.data);
    transport = 'broadcast-channel';
  }
  function disconnect(): void {
    if (channel) { channel.onmessage = null; channel.close(); channel = null; }
    transport = 'none';
  }

  return {
    async boot(deps) {
      _deps = deps;
      if (binding) connect(deps.scenarioId);   // resume listening if already bound
    },
    dispose() {
      disconnect();
      speechHandlers.clear();
      binding = null;
      lastSeq = 0;
      _deps = null;
    },

    async bindFromCharacter(raw: unknown): Promise<VraiAvatarBinding> {
      const result = parseCharacter(raw);
      binding = result;
      // Start receiving speech for this character (only once booted — keeps
      // unit tests from opening a channel).
      if (_deps?.scenarioId) connect(_deps.scenarioId);
      return result;
    },

    onSpeechFrame(handler) {
      speechHandlers.add(handler);
      return () => speechHandlers.delete(handler);
    },

    currentBinding() { return binding; },
    transport() { return transport; },

    // --- Resumable ---
    async pause()  { disconnect(); },                                    // close channel, keep binding
    async resume() { if (_deps?.scenarioId && binding) connect(_deps.scenarioId); },
    snapshot(): MedsimSnapshot {
      return { binding, lastSeq, transport };
    },
    async restore(s) {
      binding = s.binding;
      lastSeq = s.lastSeq;
      transport = s.transport;
    },
  };
}
