import { describe, it, expect } from 'vitest';
import { idleMotion } from '../index';

type W = Record<string, number>;

describe('idle_motion determinism', () => {
  it('same seed → same flutter sequence', () => {
    idleMotion.setSeed(42);
    const a: W = {};
    idleMotion.sample(0, a);
    idleMotion.sample(50, a);

    idleMotion.setSeed(42);
    const b: W = {};
    idleMotion.sample(0, b);
    idleMotion.sample(50, b);

    expect(a.eyeBlinkLeft).toBeCloseTo(b.eyeBlinkLeft!);
    expect(a.eyeBlinkRight).toBeCloseTo(b.eyeBlinkRight!);
  });

  it('same seed → identical 100-frame blink + gaze sequence', () => {
    const run = (): number[] => {
      idleMotion.setSeed(99);
      const series: number[] = [];
      for (let i = 0; i < 100; i++) {
        const f: W = {};
        idleMotion.sample(i * 16.7, f);
        series.push(f.eyeBlinkLeft ?? 0, f.eyeLookInLeft ?? 0, f.eyeLookUpLeft ?? 0);
      }
      return series;
    };
    expect(run()).toEqual(run());
  });
});

describe('idle_motion blink', () => {
  it('fires a near-full lid closure within the 6 s max interval', () => {
    idleMotion.setSeed(7);
    let peak = 0;
    for (let t = 0; t <= 8000; t += 16.7) {
      const f: W = {};
      idleMotion.sample(t, f);
      peak = Math.max(peak, f.eyeBlinkLeft ?? 0);
    }
    expect(peak).toBeGreaterThan(0.9);
  });

  it('keeps both lids symmetric every frame', () => {
    idleMotion.setSeed(7);
    for (let t = 0; t <= 8000; t += 16.7) {
      const f: W = {};
      idleMotion.sample(t, f);
      expect(f.eyeBlinkLeft ?? 0).toBeCloseTo(f.eyeBlinkRight ?? 0);
    }
  });
});

describe('idle_motion micro-saccades', () => {
  it('produces eyeLook gaze output within ~2 s', () => {
    idleMotion.setSeed(3);
    let sawGaze = false;
    for (let t = 0; t <= 2500 && !sawGaze; t += 16.7) {
      const f: W = {};
      idleMotion.sample(t, f);
      const gaze =
        (f.eyeLookInLeft ?? 0) + (f.eyeLookOutLeft ?? 0) +
        (f.eyeLookInRight ?? 0) + (f.eyeLookOutRight ?? 0) +
        (f.eyeLookUpLeft ?? 0) + (f.eyeLookDownLeft ?? 0) +
        (f.eyeLookUpRight ?? 0) + (f.eyeLookDownRight ?? 0);
      if (gaze > 0.01) sawGaze = true;
    }
    expect(sawGaze).toBe(true);
  });
});
