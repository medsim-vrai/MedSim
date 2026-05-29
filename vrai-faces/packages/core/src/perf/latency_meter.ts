// Tracks the stages defined in Memory_management.MD §5 against budget.
// Modules call `mark(stage)` at the start and `measure(stage)` at the end.

import { diag } from './diag';

const BUDGETS_MS: Record<string, { local: number; cloud: number }> = {
  'prompt_to_first_audio_chunk':   { local: 300, cloud: 180 },
  'audio_chunk_to_first_viseme':   { local: 30,  cloud: 30  },
  'viseme_to_rendered_frame':      { local: 16,  cloud: 16  },
};

const marks = new Map<string, number>();

export function mark(stage: string): void {
  marks.set(stage, performance.now());
}

export function measure(stage: string, mode: 'local' | 'cloud' = 'local'): number {
  const start = marks.get(stage);
  if (start === undefined) return -1;
  const ms = performance.now() - start;
  marks.delete(stage);

  const budget = BUDGETS_MS[stage]?.[mode];
  diag.push({
    t: performance.now(),
    moduleId: 'perf.latency_meter',
    kind: budget !== undefined && ms > budget ? 'warn' : 'metric',
    message: stage,
    data: { ms, budget, mode },
  });
  return ms;
}
