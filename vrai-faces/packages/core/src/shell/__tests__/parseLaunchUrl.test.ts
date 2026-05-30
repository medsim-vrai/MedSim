import { describe, it, expect } from 'vitest';
import { parseLaunchUrl } from '../parseLaunchUrl';

function fakeLoc(pathname: string, search = ''): Location {
  return { pathname, search } as unknown as Location;
}

describe('parseLaunchUrl', () => {
  it('parses /face/<id>?scenario=&opacity=', () => {
    const p = parseLaunchUrl(fakeLoc('/face/pt-001', '?scenario=s7&opacity=0.33'));
    expect(p).toEqual({ characterId: 'pt-001', scenarioId: 's7', opacityLevel: 0.33 });
  });

  it('parses the api origin (percent-decoded by URLSearchParams)', () => {
    const p = parseLaunchUrl(
      fakeLoc('/face/pt-001', '?scenario=s7&api=http%3A%2F%2Fhost%3A8765'),
    );
    expect(p?.apiBase).toBe('http://host:8765');
  });

  it('omits apiBase when api is absent or empty', () => {
    expect(parseLaunchUrl(fakeLoc('/face/x'))?.apiBase).toBeUndefined();
    expect(parseLaunchUrl(fakeLoc('/face/x', '?api='))?.apiBase).toBeUndefined();
  });

  it('clamps opacity out of range', () => {
    const p = parseLaunchUrl(fakeLoc('/face/x', '?opacity=99'));
    expect(p?.opacityLevel).toBe(1);
  });

  it('returns null on a non-face URL', () => {
    expect(parseLaunchUrl(fakeLoc('/'))).toBeNull();
  });

  it('defaults opacity to 0.66 when missing', () => {
    expect(parseLaunchUrl(fakeLoc('/face/x'))?.opacityLevel).toBe(0.66);
  });
});
