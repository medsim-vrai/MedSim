// Cross-module unit test — exercises the seam from medsim_adapter's
// parsed VRAISpeechFrame into animation_runtime's snapshot. Lives at the
// workspace test/unit/ level (not in a single module's __tests__) because
// it asserts a boundary contract, not a single module's behavior.

import { describe, it, expect } from 'vitest';
import { parseFrame } from '@modules/medsim_adapter/impl/parse';
import { animationRuntime } from '@modules/animation_runtime';

describe('speech frame → animation runtime', () => {
  it('a parsed frame with visemes is buffered by the runtime', () => {
    const frame = parseFrame({
      v: 1,
      characterId: 'c1',
      seq: 99,
      visemes: [
        { t: 0,   id: 'jawOpen',    w: 0.4 },
        { t: 120, id: 'mouthFunnel', w: 0.3 },
      ],
    });
    expect(frame).not.toBeNull();

    // Reset runtime state then push the parsed visemes.
    animationRuntime.setEmotion({});
    const before = animationRuntime.snapshot().pendingVisemes.length;
    animationRuntime.pushVisemes(
      frame!.visemes!.map((v) => ({ t: v.t, weights: { [v.id]: v.w } })),
    );
    const after = animationRuntime.snapshot().pendingVisemes.length;
    expect(after).toBe(before + 2);
  });

  it('an emotion payload becomes the new baseline', () => {
    const frame = parseFrame({
      v: 1, characterId: 'c1', seq: 1,
      emotion: { label: 'worried', weights: { browInnerUp: 0.5, mouthFrownLeft: 0.3 } },
    });
    animationRuntime.setEmotion(frame!.emotion!.weights);
    const snap = animationRuntime.snapshot();
    expect(snap.emotionWeights.browInnerUp).toBeCloseTo(0.5);
    expect(snap.emotionWeights.mouthFrownLeft).toBeCloseTo(0.3);
  });
});
