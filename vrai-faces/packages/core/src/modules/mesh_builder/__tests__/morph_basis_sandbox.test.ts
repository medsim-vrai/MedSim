/**
 * Rig-lab sandbox basis override (`?rigBasis=<name>`), default OFF.
 *
 * Lets a candidate repair to the rigid-landmark drift (CN-rig audit) load in the REAL runtime from a
 * sibling asset, so it can be seen before it ever becomes the default. These tests pin the two things
 * that keep it safe in production: with no flag the loader is exactly the old single fetch, and a
 * missing / malformed / hostile flag falls back to the shipped basis rather than breaking a sim.
 */
import { afterEach, describe, expect, it, vi } from 'vitest';

import { resolveBasisUrls } from '../impl/morph_basis';

const SHIPPED = '/assets/face/face_mesh_morphbasis.json';

describe('resolveBasisUrls — flag → candidate URLs (pure)', () => {
  it('no flag → the shipped basis only (production path unchanged)', () => {
    expect(resolveBasisUrls('')).toEqual([SHIPPED]);
    expect(resolveBasisUrls('?scenario=abc&diag=1')).toEqual([SHIPPED]);
  });

  it('?rigBasis=<name> → the sandbox asset first, then the shipped basis as fallback', () => {
    expect(resolveBasisUrls('?rigBasis=feathered')).toEqual([
      '/assets/face/face_mesh_morphbasis.feathered.json',
      SHIPPED,
    ]);
  });

  it('reads the flag from the hash too, and is case-insensitive', () => {
    expect(resolveBasisUrls('#rigBasis=Feathered')[0]).toBe(
      '/assets/face/face_mesh_morphbasis.feathered.json',
    );
    expect(resolveBasisUrls('?x=1#rigBasis=midlinepinned')[0]).toBe(
      '/assets/face/face_mesh_morphbasis.midlinepinned.json',
    );
  });

  it('rigBasis=shipped is a no-op (the explicit way to ask for the default)', () => {
    expect(resolveBasisUrls('?rigBasis=shipped')).toEqual([SHIPPED]);
  });

  it('a leading non-alphanumeric value does not match → shipped only', () => {
    // `[a-z0-9]+` needs an alphanumeric immediately after `=`, so these never form a sandbox URL
    for (const q of ['?rigBasis=../secret', '?rigBasis=.evil', '?rigBasis=/etc', '?rigBasis=']) {
      expect(resolveBasisUrls(q)).toEqual([SHIPPED]);
    }
  });

  it('can NEVER point the fetch off the assets folder — the URL is always a sibling asset', () => {
    // `http://evil` captures only `http` (the match stops at `:`), `a/b` captures only `a`, etc.
    const hostile = ['?rigBasis=http://evil.com/x', '?rigBasis=a/b/c', '?rigBasis=x:8080', '?rigBasis=A1b2'];
    for (const q of hostile) {
      for (const url of resolveBasisUrls(q)) {
        expect(url).toMatch(/^\/assets\/face\/face_mesh_morphbasis\.[a-z0-9]*\.?json$/);
        expect(url).not.toContain(':');
        expect(url).not.toContain('..');
        expect(url).not.toContain('evil');
      }
    }
  });
});

// --- fetch integration: fresh module per case to reset the memoized loader --------------------------

const SANDBOX_DOC = { version: 1, vertexCount: 468, canonicalHeight: 17, shapes: { sandboxMark: [] } };
const SHIPPED_DOC = { version: 1, vertexCount: 468, canonicalHeight: 17, shapes: { shippedMark: [] } };
const SANDBOX_URL = '/assets/face/face_mesh_morphbasis.feathered.json';

function mockFetch(bodies: Record<string, unknown | undefined>) {
  return vi.fn(async (url: string) => {
    const doc = bodies[url];
    return doc === undefined
      ? { ok: false, status: 404, json: async () => null }
      : { ok: true, status: 200, json: async () => doc };
  });
}

async function freshLoader() {
  vi.resetModules();
  return import('../impl/morph_basis');
}

afterEach(() => vi.unstubAllGlobals());

describe('loadMorphBasis — sandbox override with fallback', () => {
  it('loads the sandbox asset when the flag is set', async () => {
    const fetchMock = mockFetch({ [SANDBOX_URL]: SANDBOX_DOC, [SHIPPED]: SHIPPED_DOC });
    vi.stubGlobal('fetch', fetchMock);
    const mb = await freshLoader();
    await mb.loadMorphBasis('?rigBasis=feathered');
    expect(mb.bakedMorphNames()).toEqual(['sandboxMark']);
    expect(fetchMock.mock.calls[0]![0]).toBe(SANDBOX_URL); // tried the sandbox first
  });

  it('falls back to the shipped basis when the sandbox asset is missing', async () => {
    const fetchMock = mockFetch({ [SHIPPED]: SHIPPED_DOC }); // sandbox 404s
    vi.stubGlobal('fetch', fetchMock);
    const mb = await freshLoader();
    await mb.loadMorphBasis('?rigBasis=feathered');
    expect(mb.bakedMorphNames()).toEqual(['shippedMark']);
    expect(fetchMock).toHaveBeenCalledTimes(2); // sandbox, then shipped
  });

  it('with no flag, fetches only the shipped basis', async () => {
    const fetchMock = mockFetch({ [SHIPPED]: SHIPPED_DOC, [SANDBOX_URL]: SANDBOX_DOC });
    vi.stubGlobal('fetch', fetchMock);
    const mb = await freshLoader();
    await mb.loadMorphBasis('');
    expect(mb.bakedMorphNames()).toEqual(['shippedMark']);
    expect(fetchMock).toHaveBeenCalledTimes(1);
    expect(fetchMock).toHaveBeenCalledWith(SHIPPED);
  });

  it('leaves the procedural rig in place when every candidate fails', async () => {
    vi.stubGlobal('fetch', mockFetch({})); // nothing resolves
    const mb = await freshLoader();
    await mb.loadMorphBasis('?rigBasis=feathered');
    expect(mb.bakedMorphNames()).toEqual([]); // BAKED stayed null → procedural fallback
  });
});
