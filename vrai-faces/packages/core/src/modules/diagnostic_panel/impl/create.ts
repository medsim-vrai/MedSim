import type { DiagnosticPanelModule } from '@contracts/diagnostic_panel';
import type { BootDeps, TimelineEvent } from '@contracts/shared';
import { diag } from '@perf/diag';

/**
 * Dev-only diagnostics overlay. Reads the `diag` singleton (perf/diag.ts) and
 * paints a small fixed panel: a frame-rate line, one row per module
 * (state · fps, plus any lastError), and a tail of recent timeline events
 * colour-coded by kind. Pure DOM — no framework, no new dependency.
 *
 * Gated to DEV or `?diag=1` (see `available()`): production never mounts a node.
 * Guarded for non-DOM environments (SSR / unit tests without jsdom) so `show()`
 * is a no-op there. The refresh is a cheap 4 Hz interval — diagnostics don't
 * need the render frame rate.
 *
 * PHI note: only the authored `event.message` string is rendered, never
 * `event.data` (which can carry arbitrary payloads). Keeps the panel honest to
 * the ADR-0014 spirit even though it is dev-only and unmounted in production.
 */

const PANEL_ID = 'vrai-diag';
const REFRESH_MS = 250;
const MAX_EVENTS = 14;

const KIND_COLOR: Record<TimelineEvent['kind'], string> = {
  info: '#9cdcfe',
  warn: '#dcdcaa',
  error: '#f48771',
  metric: '#b5cea8',
};

function isAvailable(): boolean {
  const inDev = typeof import.meta !== 'undefined'
    ? Boolean((import.meta as { env?: { DEV?: boolean } }).env?.DEV)
    : false;
  const flag = typeof location !== 'undefined' &&
    new URLSearchParams(location.search).get('diag') === '1';
  return inDev || flag;
}

export function createImpl(): DiagnosticPanelModule {
  let _deps: BootDeps | null = null;
  let root: HTMLDivElement | null = null;
  let fpsEl: HTMLDivElement | null = null;
  let modsEl: HTMLDivElement | null = null;
  let logEl: HTMLDivElement | null = null;
  let timer: ReturnType<typeof setInterval> | null = null;

  function el<K extends keyof HTMLElementTagNameMap>(
    tag: K, style: string, text?: string,
  ): HTMLElementTagNameMap[K] {
    const n = document.createElement(tag);
    n.setAttribute('style', style);
    if (text !== undefined) n.textContent = text;
    return n;
  }

  function mount(): void {
    root = el('div',
      'position:fixed;top:8px;right:8px;width:320px;max-height:90vh;overflow:hidden;' +
      'z-index:99999;background:rgba(12,12,16,.86);color:#ddd;border-radius:8px;' +
      'font:11px/1.45 ui-monospace,SFMono-Regular,Menlo,monospace;padding:8px 10px;' +
      'box-shadow:0 2px 12px rgba(0,0,0,.5);pointer-events:none;');
    root.id = PANEL_ID;
    fpsEl = el('div', 'margin-bottom:6px;color:#8fd6c0;');
    modsEl = el('div', 'margin-bottom:6px;');
    logEl = el('div', 'border-top:1px solid #333;padding-top:4px;');
    root.appendChild(el('div', 'font-weight:700;color:#fff;margin-bottom:4px;letter-spacing:.04em;', 'VRAI · diagnostics'));
    root.appendChild(fpsEl);
    root.appendChild(modsEl);
    root.appendChild(logEl);
    document.body.appendChild(root);
  }

  function render(): void {
    if (!root) return;

    // Frame rate: prefer animation_runtime's reported tick time.
    const ar = diag.modules.get('animation_runtime');
    if (fpsEl) {
      const ms = ar?.lastTickMs;
      const fps = ar?.fps ?? (ms ? 1000 / ms : undefined);
      fpsEl.textContent = fps !== undefined
        ? `${fps.toFixed(0)} fps · ${ms !== undefined ? ms.toFixed(1) : '—'} ms`
        : 'fps —';
    }

    // One row per module, sorted for a stable layout.
    if (modsEl) {
      modsEl.textContent = '';
      for (const id of Array.from(diag.modules.keys()).sort()) {
        const s = diag.modules.get(id)!;
        const row = el('div', 'display:flex;justify-content:space-between;gap:8px;');
        row.appendChild(el('span', 'color:#bbb;overflow:hidden;text-overflow:ellipsis;', id));
        const right = `${s.state}${s.fps !== undefined ? ` · ${s.fps.toFixed(0)}f` : ''}`;
        row.appendChild(el('span', `color:${s.state === 'failed' ? '#f48771' : '#9cf'};`, right));
        modsEl.appendChild(row);
        if (s.lastError) modsEl.appendChild(el('div', 'color:#f48771;white-space:pre-wrap;', s.lastError));
      }
    }

    // Timeline tail (message only — see PHI note above).
    if (logEl) {
      logEl.textContent = '';
      for (const e of diag.timeline.toArray().slice(-MAX_EVENTS)) {
        logEl.appendChild(el('div',
          `color:${KIND_COLOR[e.kind]};white-space:nowrap;overflow:hidden;text-overflow:ellipsis;`,
          `${e.moduleId}: ${e.message}`));
      }
    }
  }

  function teardown(): void {
    if (timer !== null) { clearInterval(timer); timer = null; }
    if (root) root.remove();
    root = fpsEl = modsEl = logEl = null;
  }

  return {
    async boot(deps) { _deps = deps; },
    dispose() { teardown(); _deps = null; },

    show() {
      void _deps;
      if (!isAvailable() || typeof document === 'undefined') return;   // never mount in prod / SSR
      if (!root) mount();
      render();
      if (timer === null && typeof setInterval !== 'undefined') {
        timer = setInterval(render, REFRESH_MS);
      }
    },

    hide() { teardown(); },

    isAvailable() { return isAvailable(); },
  };
}
