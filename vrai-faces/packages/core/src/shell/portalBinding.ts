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
  const fetchFn = deps.fetchFn ?? (fetch as unknown as FetchLike);
  const buildAvatar = deps.buildAvatar ?? buildAvatarFromBlob;

  const payload = await fetchBinding(
    launch.apiBase, launch.characterId, launch.scenarioId, launch.opacityLevel, fetchFn,
  );
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

  const built = await buildAvatar(renderer, binding.sourcePhoto, binding.opacityLevel);
  diag.push({
    t: performance.now(), moduleId: MODULE, kind: 'info',
    message: `bound ${binding.characterId} (transport=${adapter.transport()})`,
  });
  return { ...built, binding };
}
