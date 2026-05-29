import { describe, it, expect } from 'vitest';
import { memoryState } from '../index';

describe('memory_state', () => {
  it('exposes pause/resume + register surface', () => {
    expect(typeof memoryState.save).toBe('function');
    expect(typeof memoryState.load).toBe('function');
    expect(typeof memoryState.register).toBe('function');
    expect(typeof memoryState.pauseAll).toBe('function');
    expect(typeof memoryState.resumeAll).toBe('function');
  });
});
