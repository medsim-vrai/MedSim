// MedSim bind path: fetch the portal's bind document, bind it through
// medsim_adapter (which connects the speech transport — ADR-0007), and build
// the real avatar from the portal-attached portrait.
//
// The QR deep link carries `&api=<portal origin>` (server.py `_vrai_faces_url`).
// On boot the shell hits `${api}/api/face/<id>/binding` (portal/vrai_faces.py,
// Phase 4.3). Everything here fails soft: any network / HTTP / parse / bind
// error returns null so main.ts falls back to the standalone demo avatar.

import type { MedsimAdapterModule } from '@contracts/medsim_adapter';
import type { VraiAvatarBinding } from '@contracts/shared';
import { diag } from '@perf/diag';
import { buildAvatarFromBlob, type BuiltAvatar } from './avatar_build';
import type { LaunchParams } from './parseLaunchUrl';
import type { RendererHandle } from './renderer';

/** The slice of the Fetch API we use — keeps this unit-testable with a fake. */
export interface FetchLike {
  (url: string): Promise<{ ok: boolean; status: number; json(): Promise<unknown> }>;
}

const MODULE = 'shell.portalBinding';

const FETCH_TIMEOUT_MS = 5000;   // abort a hung portal fetch so it can't stall boot
const DEFAULT_RETRIES = 4;       // transient-failure retries (total tries = retries + 1)
const DEFAULT_RETRY_MS = 400;    // linear backoff base between retries

const sleep = (ms: number): Promise<void> => new Promise((r) => setTimeout(r, ms));

// ── Binding cache (Phase 5.7 "skin pack" · ADR-0027) ──────────────────────────
// The bind document carries the character's skin inlined as a data: URI, so
// caching it persists the device's own face for instant startup + offline. It's
// PHI-at-rest, so: NETWORK-FIRST (a reassigned skin shows on the next reload),
// CACHED FALLBACK only when the portal is unreachable, and each successful cache
// PURGES other characters' entries — clear-on-unpair, so only this device's
// paired face is ever stored. `clearBindingCache()` is the manual "forget faces".
const BINDING_CACHE = 'vrai-binding-v1';

async function cacheBinding(url: string, res: Response): Promise<void> {
  try {
    const cache = await caches.open(BINDING_CACHE);
    for (const req of await cache.keys()) {
      if (req.url !== url) void cache.delete(req); // clear-on-unpair
    }
    await cache.put(url, res);
  } catch { /* cache unavailable — non-fatal */ }
}

async function cachedBinding(url: string): Promise<Response | null> {
  try {
    const cache = await caches.open(BINDING_CACHE);
    return (await cache.match(url)) ?? null;
  } catch { return null; }
}

/** Clear all cached faces from this device (ADR-0027 "forget faces" control). */
export async function clearBindingCache(): Promise<void> {
  try { if (typeof caches !== 'undefined') await caches.delete(BINDING_CACHE); }
  catch { /* noop */ }
}

/**
 * Default fetch: abort-timeout + the network-first binding cache above (cached
 * fallback when the portal is unreachable). Unit tests inject their own fetchFn
 * and never hit this, so the Cache API is only touched in the real app.
 */
const cachingTimeoutFetch: FetchLike = async (url) => {
  const ctrl = new AbortController();
  const timer = setTimeout(() => ctrl.abort(), FETCH_TIMEOUT_MS);
  try {
    const res = await fetch(url, { signal: ctrl.signal });
    if (res.ok && typeof caches !== 'undefined') void cacheBinding(url, res.clone());
    return res;
  } catch (e) {
    if (typeof caches !== 'undefined') {
      const hit = await cachedBinding(url);
      if (hit) {
        diag.push({
          t: performance.now(), moduleId: MODULE, kind: 'info',
          message: 'portal unreachable — bound from cached face (offline)',
        });
        return hit;
      }
    }
    throw e;
  } finally {
    clearTimeout(timer);
  }
};

/**
 * Build the binding URL and fetch the bind document. Returns the parsed JSON
 * payload, or null on any network / HTTP / parse failure.
 */
export async function fetchBinding(
  apiBase: string,
  characterId: string,
  scenarioId: string,
  opacityLevel: number,
  fetchFn: FetchLike,
): Promise<unknown | null> {
  const base = apiBase.replace(/\/+$/, '');
  const url =
    `${base}/api/face/${encodeURIComponent(characterId)}/binding` +
    `?scenario=${encodeURIComponent(scenarioId)}&opacity=${opacityLevel.toFixed(2)}`;
  try {
    const res = await fetchFn(url);
    if (!res.ok) {
      diag.push({
        t: performance.now(), moduleId: MODULE, kind: 'warn',
        message: `binding fetch HTTP ${res.status}`, data: url,
      });
      return null;
    }
    return await res.json();
  } catch (e) {
    diag.push({
      t: performance.now(), moduleId: MODULE, kind: 'warn',
      message: 'binding fetch failed', data: e instanceof Error ? e.message : String(e),
    });
    return null;
  }
}

export interface BindResult extends BuiltAvatar {
  binding: VraiAvatarBinding;
}

export interface BindDeps {
  fetchFn?: FetchLike;
  /** Injectable for tests; defaults to the real three.js pipeline. */
  buildAvatar?: (r: RendererHandle, blob: Blob, opacity: number) => Promise<BuiltAvatar>;
  /** Transient-failure retries before falling back to demo. Default 4. */
  retries?: number;
  /** Linear backoff base (ms) between retries. Default 400. */
  retryDelayMs?: number;
}

/**
 * Fetch → bind → build. `adapter.bindFromCharacter()` validates the card and
 * connects the speech transport (WebSocket when the payload carries
 * `speechWsUrl`). Returns null on any failure so the caller falls back to demo.
 */
export async function bindFromPortal(
  renderer: RendererHandle,
  launch: LaunchParams,
  adapter: MedsimAdapterModule,
  deps: BindDeps = {},
): Promise<BindResult | null> {
  if (!launch.apiBase) return null;
  const fetchFn = deps.fetchFn ?? cachingTimeoutFetch;
  const buildAvatar = deps.buildAvatar ?? buildAvatarFromBlob;
  const retries = deps.retries ?? DEFAULT_RETRIES;
  const retryDelayMs = deps.retryDelayMs ?? DEFAULT_RETRY_MS;

  // The cross-app bind fetch can transiently fail (portal still starting up, a
  // momentary blip). Retry with linear backoff before giving up to the demo, so
  // a single miss doesn't strand the avatar on the demo for the whole session.
  let payload: unknown | null = null;
  for (let attempt = 0; attempt <= retries; attempt++) {
    payload = await fetchBinding(
      launch.apiBase, launch.characterId, launch.scenarioId, launch.opacityLevel, fetchFn,
    );
    if (payload !== null) break;
    if (attempt < retries) {
      diag.push({
        t: performance.now(), moduleId: MODULE, kind: 'info',
        message: `binding not ready (attempt ${attempt + 1}/${retries + 1}); retrying`,
      });
      await sleep(retryDelayMs * (attempt + 1));
    }
  }
  if (payload === null) return null;

  let binding: VraiAvatarBinding;
  try {
    binding = await adapter.bindFromCharacter(payload);
  } catch (e) {
    diag.push({
      t: performance.now(), moduleId: MODULE, kind: 'error',
      message: 'bindFromCharacter rejected', data: e instanceof Error ? e.message : String(e),
    });
    return null;
  }

  try {
    const built = await buildAvatar(renderer, binding.sourcePhoto, binding.opacityLevel);
    diag.push({
      t: performance.now(), moduleId: MODULE, kind: 'info',
      message: `bound ${binding.characterId} (transport=${adapter.transport()})`,
    });
    return { ...built, binding };
  } catch (e) {
    // A bad/undecodable portrait must not blank the screen — fall back to demo.
    diag.push({
      t: performance.now(), moduleId: MODULE, kind: 'error',
      message: 'avatar build from binding failed; falling back to demo',
      data: e instanceof Error ? e.message : String(e),
    });
    return null;
  }
}
