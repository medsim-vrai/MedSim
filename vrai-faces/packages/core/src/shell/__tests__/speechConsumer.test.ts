import { describe, it, expect } from 'vitest';
import { installSpeechConsumer } from '../speechConsumer';
import type { AnimationRuntimeModule } from '@contracts/animation_runtime';
import type {
  AudioPipelineModule, VisemeHandler, VisemeSource,
} from '@contracts/audio_pipeline';
import type { MedsimAdapterModule } from '@contracts/medsim_adapter';
import type { TtsChunk, TtsProviderModule, TtsRequest } from '@contracts/tts_provider';
import type { BlendshapeWeights, TtsVoiceId, VRAISpeechFrame } from '@contracts/shared';

type AudioFmt = 'pcm16-24k' | 'opus' | 'mp3';

function makeFakes() {
  const rec = {
    emotion: [] as Array<{ weights: BlendshapeWeights; ease: number | undefined }>,
    visemePushes: [] as Array<Array<{ t: number; weights: BlendshapeWeights }>>,
    enqueued: [] as Array<{ fmt: AudioFmt }>,
    visemeSources: [] as VisemeSource[],
    ttsReqs: [] as TtsRequest[],
    offFrame: false,
    offViseme: false,
  };
  let frameHandler: ((f: VRAISpeechFrame) => void) | null = null;
  let visemeHandler: VisemeHandler | null = null;
  let chunks: TtsChunk[] = [
    { audio: new ArrayBuffer(4), audioFormat: 'pcm16-24k' },
    { audio: new ArrayBuffer(4), audioFormat: 'pcm16-24k' },
  ];

  const adapter = {
    onSpeechFrame: (h: (f: VRAISpeechFrame) => void) => {
      frameHandler = h;
      return () => { rec.offFrame = true; };
    },
    currentBinding: () => null,
    transport: () => 'websocket',
  } as unknown as MedsimAdapterModule;

  const audio = {
    onViseme: (h: VisemeHandler) => {
      visemeHandler = h;
      return () => { rec.offViseme = true; };
    },
    setVisemeSource: (s: VisemeSource) => { rec.visemeSources.push(s); },
    enqueueAudio: (_a: ArrayBuffer, fmt: AudioFmt) => { rec.enqueued.push({ fmt }); },
  } as unknown as AudioPipelineModule;

  const anim = {
    setEmotion: (weights: BlendshapeWeights, ease?: number) => {
      rec.emotion.push({ weights, ease });
    },
    pushVisemes: (frames: Array<{ t: number; weights: BlendshapeWeights }>) => {
      rec.visemePushes.push(frames);
    },
  } as unknown as AnimationRuntimeModule;

  const tts = {
    speak: (req: TtsRequest): AsyncIterable<TtsChunk> => {
      rec.ttsReqs.push(req);
      return (async function* gen() { for (const c of chunks) yield c; })();
    },
  } as unknown as TtsProviderModule;

  return {
    rec,
    deps: {
      adapter, audio, anim,
      loadTts: () => Promise.resolve(tts),
      voice: () => 'v1' as TtsVoiceId,
    },
    emit: (f: VRAISpeechFrame) => frameHandler?.(f),
    emitViseme: (v: { t: number; id: string; w: number }) => visemeHandler?.(v),
    setChunks: (c: TtsChunk[]) => { chunks = c; },
  };
}

// One macrotask flushes the serialized speak() microtask chain.
const flush = (): Promise<void> => new Promise((r) => setTimeout(r, 0));

describe('installSpeechConsumer', () => {
  it('drives emotion immediately from a frame', () => {
    const f = makeFakes();
    installSpeechConsumer(f.deps);
    f.emit({ v: 1, characterId: 'c', seq: 1, emotion: { label: 'concern', weights: { browInnerUp: 0.4 } } });
    expect(f.rec.emotion).toHaveLength(1);
    expect(f.rec.emotion[0]?.weights.browInnerUp).toBe(0.4);
    expect(f.rec.emotion[0]?.ease).toBe(180);
  });

  it('synthesizes text frames via local TTS and enqueues audio', async () => {
    const f = makeFakes();
    installSpeechConsumer(f.deps);
    f.emit({ v: 1, characterId: 'c', seq: 1, text: 'hello', emotion: { label: 'concern', weights: {} } });
    await flush();
    expect(f.rec.ttsReqs).toHaveLength(1);
    expect(f.rec.ttsReqs[0]).toMatchObject({
      text: 'hello', voice: 'v1', tier: 'local', source: 'scripted', emotion: 'concern',
    });
    expect(f.rec.enqueued).toHaveLength(2);
    expect(f.rec.visemeSources).toEqual(['derived', 'derived']); // no chunk visemes
  });

  it('uses the native viseme source + pushes provider visemes when present', async () => {
    const f = makeFakes();
    f.setChunks([{ audio: new ArrayBuffer(4), audioFormat: 'pcm16-24k', visemes: [{ t: 0, id: 'jawOpen', w: 0.7 }] }]);
    installSpeechConsumer(f.deps);
    f.emit({ v: 1, characterId: 'c', seq: 1, text: 'ah' });
    await flush();
    expect(f.rec.visemeSources).toEqual(['native']);
    const last = f.rec.visemePushes[f.rec.visemePushes.length - 1];
    expect(last).toEqual([{ t: 0, weights: { jawOpen: 0.7 } }]);
  });

  it('bridges energy-derived visemes into the animation runtime', () => {
    const f = makeFakes();
    installSpeechConsumer(f.deps);
    f.emitViseme({ t: 5, id: 'jawOpen', w: 0.3 });
    expect(f.rec.visemePushes).toEqual([[{ t: 5, weights: { jawOpen: 0.3 } }]]);
  });

  it('does not synthesize when no voice is bound yet', async () => {
    const f = makeFakes();
    installSpeechConsumer({ ...f.deps, voice: () => undefined });
    f.emit({ v: 1, characterId: 'c', seq: 1, text: 'hello' });
    await flush();
    expect(f.rec.ttsReqs).toHaveLength(0);
    expect(f.rec.enqueued).toHaveLength(0);
  });

  it('unsubscribe tears down both subscriptions', () => {
    const f = makeFakes();
    const off = installSpeechConsumer(f.deps);
    off();
    expect(f.rec.offFrame).toBe(true);
    expect(f.rec.offViseme).toBe(true);
  });
});
