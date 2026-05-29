import { describe, it, expect } from 'vitest';
import { DroppingQueue } from '../dropping_queue';

describe('DroppingQueue', () => {
  it('drops oldest when over capacity', () => {
    const q = new DroppingQueue<number>(3);
    q.push(1); q.push(2); q.push(3); q.push(4);
    expect(q.popAll()).toEqual([2, 3, 4]);
    expect(q.dropCount()).toBe(1);
  });
  it('never blocks the producer', () => {
    const q = new DroppingQueue<number>(2);
    for (let i = 0; i < 1000; i++) q.push(i);
    expect(q.size()).toBe(2);
    expect(q.dropCount()).toBe(998);
  });
});
