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
  if (typeof location === 'undefined') return inDev;
  const diagFlag = new URLSearchParams(location.search).get('diag') === '1';
  // The iPad debug QR carries `?debug` (or #debug) — surface the diagnostics panel
  // there too, since the production dist build has import.meta.env.DEV === false.
  const debugFlag = /\bdebug\b/.test(`${location.search}${location.hash}`);
  return inDev || diagFlag || debugFlag;
}

export function createImpl(): DiagnosticPanelModule {
  let _deps: BootDeps | null = null;
  let root: HTMLDivElement | null = null;
  let fpsEl: HTMLDivElement | null = null;
  let modsEl: HTMLDivElement | null = null;
  let logEl: HTMLDivElement | null = null;
  let bodyEl: HTMLDivElement | null = null;
  let caretEl: HTMLSpanElement | null = null;
  let collapsed = true;   // minimized by default — tap the header to expand
  let timer: ReturnType<typeof setInterval> | null = null;

  function el<K extends keyof HTMLElementTagNameMap>(
    tag: K, style: string, text?: string,
  ): HTMLElementTagNameMap[K] {
    const n = document.createElement(tag);
    n.setAttribute('style', style);
    if (text !== undefined) n.textContent = text;
    return n;
  }

  function applyCollapsed(): void {
    if (bodyEl) bodyEl.style.display = collapsed ? 'none' : 'block';
    if (caretEl) caretEl.textContent = collapsed ? '▸' : '▾';
    if (root) root.style.width = collapsed ? 'auto' : '320px';
  }

  function toggleCollapsed(): void {
    collapsed = !collapsed;
    applyCollapsed();
    if (!collapsed) render();   // refresh immediately on expand
  }

  function mount(): void {
    root = el('div',
      'position:fixed;top:8px;right:8px;max-width:320px;max-height:90vh;overflow:hidden;' +
      'z-index:99999;background:rgba(12,12,16,.86);color:#ddd;border-radius:8px;' +
      'font:11px/1.45 ui-monospace,SFMono-Regular,Menlo,monospace;padding:8px 10px;' +
      'box-shadow:0 2px 12px rgba(0,0,0,.5);pointer-events:none;');
    root.id = PANEL_ID;

    // The header doubles as the minimize toggle. The panel is click-through
    // (pointer-events:none) so it never blocks the avatar; the header opts back IN
    // to pointer events so a tap collapses/expands the diagnostics body.
    const header = el('div',
      'display:flex;justify-content:space-between;align-items:center;gap:10px;' +
      'font-weight:700;color:#fff;letter-spacing:.04em;cursor:pointer;pointer-events:auto;');
    header.appendChild(el('span', '', 'VRAI · diagnostics'));
    caretEl = el('span', 'opacity:.7;', '▸');
    header.appendChild(caretEl);
    header.addEventListener('click', toggleCollapsed);

    bodyEl = el('div', 'margin-top:4px;');
    fpsEl = el('div', 'margin-bottom:6px;color:#8fd6c0;');
    modsEl = el('div', 'margin-bottom:6px;');
    logEl = el('div', 'border-top:1px solid #333;padding-top:4px;');
    bodyEl.appendChild(fpsEl);
    bodyEl.appendChild(modsEl);
    bodyEl.appendChild(logEl);

    root.appendChild(header);
    root.appendChild(bodyEl);
    document.body.appendChild(root);
    applyCollapsed();   // start minimized
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
    root = fpsEl = modsEl = logEl = bodyEl = caretEl = null;
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
