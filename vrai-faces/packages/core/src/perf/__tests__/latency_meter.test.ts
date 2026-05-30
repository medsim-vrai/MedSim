import { describe, it, expect } from 'vitest';
import { mark, measure } from '../latency_meter';
import { diag } from '../diag';

function warnsFor(stage: string): number {
  return diag.timeline.toArray().filter(
    (e) => e.moduleId === 'perf.latency_meter' && e.kind === 'warn' && e.message === stage,
  ).length;
}

describe('latency_meter', () => {
  it('measures elapsed ms and consumes the mark', () => {
    mark('viseme_to_rendered_frame');
    const ms = measure('viseme_to_rendered_frame');
    expect(ms).toBeGreaterThanOrEqual(0);
    // The mark is consumed → a second measure with no fresh mark returns -1.
    expect(measure('viseme_to_rendered_frame')).toBe(-1);
  });

  it('returns -1 for an unmarked stage', () => {
    expect(measure('never_marked')).toBe(-1);
  });

  it('flags an over-budget stage as a warn (16ms frame budget)', () => {
    const before = warnsFor('viseme_to_rendered_frame');
    mark('viseme_to_rendered_frame');
    // Deterministically blow the 16ms local budget.
    const start = performance.now();
    while (performance.now() - start < 25) { /* spin */ }
    measure('viseme_to_rendered_frame', 'local');
    expect(warnsFor('viseme_to_rendered_frame')).toBe(before + 1);
  });

  it('records an under-budget stage as a metric, not a warn', () => {
    mark('prompt_to_first_audio_chunk');           // local budget 300ms
    const ms = measure('prompt_to_first_audio_chunk', 'local');
    expect(ms).toBeLessThan(300);
    const last = diag.timeline.toArray().reverse().find(
      (e) => e.moduleId === 'perf.latency_meter' && e.message === 'prompt_to_first_audio_chunk',
    );
    expect(last?.kind).toBe('metric');
  });
});
