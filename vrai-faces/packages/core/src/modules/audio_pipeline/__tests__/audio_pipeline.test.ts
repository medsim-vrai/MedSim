import { describe, it, expect } from 'vitest';
import { audioPipeline } from '../index';
import { createImpl } from '../impl/create';

describe('audio_pipeline', () => {
  it('buffers audio enqueued before prime instead of dropping/throwing (opening line)', async () => {
    // The portal voices the opening line on WS-connect, BEFORE the first user gesture. Enqueuing
    // then must NOT throw — that used to discard the opening, so the character "started" silent on
    // desktop. It buffers until primeOnUserGesture() unlocks audio and flushes it.
    const ap = createImpl();
    expect(() => ap.enqueueAudio(new ArrayBuffer(8), 'pcm16-24k')).not.toThrow();
    await ap.primeOnUserGesture();
    expect(ap.snapshot().primed).toBe(true);
    ap.dispose();
  });

  it('viseme handler unsubscribe is idempotent', () => {
    const off = audioPipeline.onViseme(() => {});
    off();
    off();  // must not throw
  });
});

// State/guard coverage on a fresh instance (so the singleton above stays
// unprimed for its before-prime test). In Node/jsdom there is no AudioContext,
// so the graph degrades to a no-op: priming flips state, enqueue drops silently.
describe('audio_pipeline state (no-AudioContext env)', () => {
  it('prime flips primed and lets enqueue run without throwing', async () => {
    const ap = createImpl();
    await ap.primeOnUserGesture();
    expect(ap.snapshot().primed).toBe(true);
    expect(() => ap.enqueueAudio(new ArrayBuffer(8), 'pcm16-24k')).not.toThrow();
    ap.dispose();
  });

  it('flush resets queue depth and snapshot/restore round-trips', async () => {
    const ap = createImpl();
    await ap.restore({ primed: true, queueDepth: 5 });
    expect(ap.snapshot()).toEqual({ primed: true, queueDepth: 5, visemeSource: 'derived' });
    ap.flush();
    expect(ap.snapshot().queueDepth).toBe(0);
    ap.dispose();
  });
});

describe('audio_pipeline viseme source (ADR-0015)', () => {
  it('defaults to derived and round-trips the source through snapshot/restore', async () => {
    const ap = createImpl();
    expect(ap.snapshot().visemeSource).toBe('derived');   // default: energy bridge on

    ap.setVisemeSource('native');                          // provider streams its own visemes
    expect(ap.snapshot().visemeSource).toBe('native');

    const ap2 = createImpl();
    await ap2.restore(ap.snapshot());
    expect(ap2.snapshot().visemeSource).toBe('native');    // persists across pause/resume

    ap.dispose();
    ap2.dispose();
  });

  it('restore defaults to derived when the field is absent (older snapshots)', async () => {
    const ap = createImpl();
    await ap.restore({ primed: true, queueDepth: 0 });
    expect(ap.snapshot().visemeSource).toBe('derived');
    ap.dispose();
  });

  it('setVisemeSource is callable before prime without throwing', () => {
    const ap = createImpl();
    expect(() => ap.setVisemeSource('native')).not.toThrow();
    expect(() => ap.setVisemeSource('derived')).not.toThrow();
    ap.dispose();
  });
});
