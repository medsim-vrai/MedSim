import { describe, it, expect } from 'vitest';
import { faceIngest } from '../index';

describe('face_ingest barrel', () => {
  it('exposes the Lifecycle surface', () => {
    expect(typeof faceIngest.boot).toBe('function');
    expect(typeof faceIngest.dispose).toBe('function');
    expect(typeof faceIngest.ingest).toBe('function');
  });
});
