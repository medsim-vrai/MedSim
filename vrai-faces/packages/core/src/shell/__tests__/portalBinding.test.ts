import { describe, it, expect } from 'vitest';
import { fetchBinding, bindFromPortal, type FetchLike } from '../portalBinding';
import type { BuiltAvatar } from '../avatar_build';
import type { RendererHandle } from '../renderer';
import type { LaunchParams } from '../parseLaunchUrl';
import type { MedsimAdapterModule } from '@contracts/medsim_adapter';
import type { TtsVoiceId, VraiAvatarBinding } from '@contracts/shared';

const renderer = {} as unknown as RendererHandle;

function okFetch(payload: unknown, capture?: (url: string) => void): FetchLike {
  return (url: string) => {
    capture?.(url);
    return Promise.resolve({ ok: true, status: 200, json: () => Promise.resolve(payload) });
  };
}

function binding(over: Partial<VraiAvatarBinding> = {}): VraiAvatarBinding {
  return {
    characterId: 'c', sourcePhoto: new Blob(['x']),
    voiceProfile: 'female:Samantha' as TtsVoiceId,
    baselineMood: {}, opacityLevel: 0.5, ...over,
  };
}

function fakeAdapter(over: Partial<MedsimAdapterModule>): MedsimAdapterModule {
  return {
    transport: () => 'websocket',
    bindFromCharacter: (_raw: unknown) => Promise.resolve(binding()),
    ...over,
  } as unknown as MedsimAdapterModule;
}

describe('fetchBinding', () => {
  it('builds the binding URL (strips trailing slash, encodes id) and returns json', async () => {
    let seen = '';
    const out = await fetchBinding('http://h:8765/', 'pt 1', 's7', 0.66,
      okFetch({ characterId: 'pt 1' }, (u) => { seen = u; }));
    expect(seen).toBe('http://h:8765/api/face/pt%201/binding?scenario=s7&opacity=0.66');
    expect(out).toEqual({ characterId: 'pt 1' });
  });

  it('returns null on a non-ok HTTP status', async () => {
    const fetchFn: FetchLike = () =>
      Promise.resolve({ ok: false, status: 404, json: () => Promise.resolve({}) });
    expect(await fetchBinding('http://h', 'c', 's', 0.66, fetchFn)).toBeNull();
  });

  it('returns null when fetch throws', async () => {
    const fetchFn: FetchLike = () => Promise.reject(new Error('network down'));
    expect(await fetchBinding('http://h', 'c', 's', 0.66, fetchFn)).toBeNull();
  });
});

describe('bindFromPortal', () => {
  const launch: LaunchParams = {
    characterId: 'c', scenarioId: 's7', opacityLevel: 0.66, apiBase: 'http://h',
  };

  it('returns null when there is no apiBase (demo path)', async () => {
    const { apiBase: _omit, ...noApi } = launch;
    const r = await bindFromPortal(renderer, noApi, fakeAdapter({}));
    expect(r).toBeNull();
  });

  it('fetches → binds → builds, returning the built avatar + binding', async () => {
    let blobSeen: Blob | null = null;
    let opacitySeen = -1;
    const buildAvatar = (_r: RendererHandle, blob: Blob, op: number): Promise<BuiltAvatar> => {
      blobSeen = blob; opacitySeen = op;
      return Promise.resolve({ meshId: 'm1', materialId: 'mat1' });
    };
    const r = await bindFromPortal(renderer, launch, fakeAdapter({}), {
      fetchFn: okFetch({ characterId: 'c' }),
      buildAvatar,
    });
    expect(r?.materialId).toBe('mat1');
    expect(r?.binding.characterId).toBe('c');
    expect(blobSeen).toBeInstanceOf(Blob);
    expect(opacitySeen).toBe(0.5); // binding.opacityLevel, not the launch default
  });

  it('returns null when the fetch fails (adapter never called)', async () => {
    let bindCalled = false;
    const adapter = fakeAdapter({
      bindFromCharacter: (_raw: unknown) => { bindCalled = true; return Promise.resolve(binding()); },
    });
    const fetchFn: FetchLike = () =>
      Promise.resolve({ ok: false, status: 500, json: () => Promise.resolve({}) });
    const r = await bindFromPortal(renderer, launch, adapter, { fetchFn, retries: 0 });
    expect(r).toBeNull();
    expect(bindCalled).toBe(false);
  });

  it('retries a transient fetch failure, then binds', async () => {
    let n = 0;
    const fetchFn: FetchLike = () => {
      n += 1;
      if (n < 3) return Promise.reject(new Error('transient'));   // fail the first two
      return Promise.resolve({ ok: true, status: 200, json: () => Promise.resolve({ characterId: 'c' }) });
    };
    const r = await bindFromPortal(renderer, launch, fakeAdapter({}), {
      fetchFn,
      buildAvatar: () => Promise.resolve({ meshId: 'm', materialId: 'mat' }),
      retryDelayMs: 1, // keep the test fast
    });
    expect(n).toBe(3);                 // failed twice, succeeded on the 3rd try
    expect(r?.binding.characterId).toBe('c');
  });

  it('returns null when bindFromCharacter rejects', async () => {
    const adapter = fakeAdapter({
      bindFromCharacter: (_raw: unknown) => Promise.reject(new Error('bad card')),
    });
    const r = await bindFromPortal(renderer, launch, adapter, {
      fetchFn: okFetch({ junk: true }),
      buildAvatar: () => Promise.resolve({ meshId: 'm', materialId: 'mat' }),
    });
    expect(r).toBeNull();
  });
});
