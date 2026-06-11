// Tablet QR launches hit:
//   /face/<characterId>?scenario=<scenarioId>&opacity=0.66&api=<portal origin>
// The shell parses this and binds the avatar at boot.

export interface LaunchParams {
  characterId: string;
  scenarioId: string;
  /** 0..1; defaults to 0.66 (mid-translucent). */
  opacityLevel: number;
  /**
   * Portal origin the QR was generated from (URL-decoded). When present, the
   * shell fetches `${apiBase}/api/face/<id>/binding` to bind a real character
   * (portrait + speech WS URL). Absent for the standalone demo.
   */
  apiBase?: string;
  /** Opt-in device-capability token (ADR-0027); echoed back on /listen when present. */
  token?: string;
  /**
   * Station mode (FR-006). 'avatar' (default) = the full 3D talking head.
   * 'audio' = the lite station: flat static portrait + the complete voice loop
   * (speech playback + push-to-talk) — no 3D rig, no WebGPU; for low-cost tablets.
   */
  mode: 'avatar' | 'audio';
}

export function parseLaunchUrl(loc: Location): LaunchParams | null {
  const m = loc.pathname.match(/^\/face\/([^/]+)\/?$/);
  if (!m) return null;
  const characterId = decodeURIComponent(m[1] ?? '');
  if (!characterId) return null;
  const q = new URLSearchParams(loc.search);
  const scenarioId = q.get('scenario') ?? 'default';
  // NB: Number(null) === 0 and Number('') === 0, both finite — so we must
  // treat a missing/empty param as "absent" explicitly, otherwise the 0.66
  // default below is unreachable and a QR without ?opacity boots fully ghosted.
  const opacityStr = q.get('opacity');
  const opacityRaw = opacityStr === null || opacityStr === '' ? NaN : Number(opacityStr);
  const opacityLevel = Number.isFinite(opacityRaw)
    ? Math.max(0, Math.min(1, opacityRaw))
    : 0.66;

  const params: LaunchParams = {
    characterId, scenarioId, opacityLevel,
    mode: q.get('mode') === 'audio' ? 'audio' : 'avatar',
  };
  // URLSearchParams already percent-decodes, so `api` is the plain origin.
  // exactOptionalPropertyTypes: only set the key when actually present.
  const apiBase = q.get('api');
  if (apiBase !== null && apiBase.length > 0) params.apiBase = apiBase;
  const token = q.get('token');
  if (token !== null && token.length > 0) params.token = token;
  return params;
}
