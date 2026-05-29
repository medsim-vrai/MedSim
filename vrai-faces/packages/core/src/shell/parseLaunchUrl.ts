// Tablet QR launches hit:
//   /face/<characterId>?scenario=<scenarioId>&opacity=0.66
// The shell parses this and binds the avatar at boot.

export interface LaunchParams {
  characterId: string;
  scenarioId: string;
  /** 0..1; defaults to 0.66 (mid-translucent). */
  opacityLevel: number;
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
  return { characterId, scenarioId, opacityLevel };
}
