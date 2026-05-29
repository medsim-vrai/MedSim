import { describe, it, expect } from 'vitest';
import { audioPipeline } from '../index';
import { createImpl } from '../impl/create';

describe('audio_pipeline', () => {
  it('throws if enqueue is called before prime (ADR-0008)', () => {
    expect(() => audioPipeline.enqueueAudio(new ArrayBuffer(8), 'pcm16-24k')).toThrow(
      /primeOnUserGesture/,
    );
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
    expect(ap.snapshot()).toEqual({ primed: true, queueDepth: 5 });
    ap.flush();
    expect(ap.snapshot().queueDepth).toBe(0);
    ap.dispose();
  });
});
