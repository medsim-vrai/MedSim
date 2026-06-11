// ADR-0038 route policy: WHERE transcription runs, decided per device capability
// with a URL override. The field basis: whisper-tiny on the target Android CPU
// took 17 s for a 4.8 s clip — no-WebGPU devices route to the portal Mac.
import { describe, expect, it } from 'vitest';
import { resolveSttRoute } from '../device_stt';

describe('resolveSttRoute (ADR-0038)', () => {
  it('defaults WebGPU devices (iPad class) to the fully-on-device path', () => {
    expect(resolveSttRoute('', true)).toBe('local');
    expect(resolveSttRoute('?character=P-014', true)).toBe('local');
  });

  it('defaults no-WebGPU devices (audio stations) to the portal Mac', () => {
    expect(resolveSttRoute('', false)).toBe('portal');
    expect(resolveSttRoute('?character=P-006&mode=audio', false)).toBe('portal');
  });

  it('&stt=portal pins the room route even on WebGPU devices', () => {
    expect(resolveSttRoute('?stt=portal', true)).toBe('portal');
  });

  it('&stt=wasm / &stt=webgpu pin on-device even without WebGPU', () => {
    expect(resolveSttRoute('?stt=wasm', false)).toBe('local');
    expect(resolveSttRoute('?stt=webgpu', false)).toBe('local');
    expect(resolveSttRoute('#stt=wasm', false)).toBe('local');
  });

  it('ignores unrelated params and malformed values', () => {
    expect(resolveSttRoute('?stt=banana', false)).toBe('portal');
    expect(resolveSttRoute('?mystt=wasm', false)).toBe('portal');
  });
});
