// The single allowed global. Modules push timeline events here and
// diagnostic_panel reads from it. Allocation budget: ~2 KB resident.

import type { DiagHandle, ModuleStat, TimelineEvent } from '@contracts/shared';

class RingLog<T> {
  private buf: Array<T | undefined>;
  private writeIdx = 0;
  private filled = false;
  constructor(private capacity: number) {
    this.buf = new Array<T | undefined>(capacity);
  }
  push(v: T): void {
    this.buf[this.writeIdx] = v;
    this.writeIdx = (this.writeIdx + 1) % this.capacity;
    if (this.writeIdx === 0) this.filled = true;
  }
  toArray(): T[] {
    const out: T[] = [];
    const start = this.filled ? this.writeIdx : 0;
    const len   = this.filled ? this.capacity : this.writeIdx;
    for (let i = 0; i < len; i++) {
      const idx = (start + i) % this.capacity;
      const v = this.buf[idx];
      if (v !== undefined) out.push(v);
    }
    return out;
  }
}

class Diag implements DiagHandle {
  readonly modules = new Map<string, ModuleStat>();
  readonly timeline = new RingLog<TimelineEvent>(2048);

  push(event: TimelineEvent): void {
    this.timeline.push(event);
  }

  set(moduleId: string, stat: Partial<ModuleStat>): void {
    const prev = this.modules.get(moduleId) ?? { state: 'idle' };
    this.modules.set(moduleId, { ...prev, ...stat });
  }
}

export const diag = new Diag();
