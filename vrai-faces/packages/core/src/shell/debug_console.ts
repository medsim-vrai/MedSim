// On-device debug console (cable-free) — TEMPORARY pilot aid.
//
// Captures console.log/info/warn/error/debug + window errors + unhandled
// rejections into a tap-to-open, SELECTABLE panel, so a tablet can show full,
// untruncated errors (and the runtime's own internal logs) without USB /
// chrome://inspect. This is what surfaces the real reason the STT wasm backend
// won't register — the thrown error alone is truncated and omits it.
//
// TODO: gate behind ?debug=1 or remove once the on-device STT pilot is resolved.

const STYLE = `
#vrai-dbg-btn{position:fixed;left:8px;bottom:calc(8px + env(safe-area-inset-bottom,0px));z-index:2147483647;
  width:44px;height:44px;border:none;border-radius:22px;background:rgba(20,20,24,.85);color:#fff;font-size:20px;
  box-shadow:0 2px 8px rgba(0,0,0,.4)}
#vrai-dbg-panel{position:fixed;inset:6px;display:none;z-index:2147483646;background:rgba(8,10,16,.97);
  color:#d6e2ff;border:1px solid #2a3550;border-radius:10px;flex-direction:column;font:12px ui-monospace,Menlo,monospace}
#vrai-dbg-panel.open{display:flex}
#vrai-dbg-bar{display:flex;gap:8px;padding:8px;border-bottom:1px solid #2a3550}
#vrai-dbg-bar button{flex:0 0 auto;height:32px;padding:0 12px;border:none;border-radius:8px;background:#243049;color:#fff;font-size:13px}
#vrai-dbg-out{flex:1;margin:0;padding:8px;overflow:auto;white-space:pre-wrap;word-break:break-word;
  -webkit-user-select:text;user-select:text}
#vrai-dbg-out .err{color:#ff9b9b}#vrai-dbg-out .warn{color:#ffd479}
`;

function fmt(v: unknown): string {
  if (v instanceof Error) {
    const cause = (v as { cause?: unknown }).cause;
    return `${v.name}: ${v.message}` +
      (v.stack ? `\n${v.stack}` : '') +
      (cause !== undefined ? `\n  caused by: ${fmt(cause)}` : '');
  }
  if (typeof v === 'object' && v !== null) {
    try { return JSON.stringify(v); } catch { return String(v); }
  }
  return String(v);
}

export function mountDebugConsole(): void {
  if (typeof document === 'undefined' || document.getElementById('vrai-dbg-btn')) return;

  const lines: string[] = [];
  const MAX = 1000;
  const out = document.createElement('pre');
  out.id = 'vrai-dbg-out';

  const render = (): void => {
    out.textContent = lines.slice(-MAX).join('\n');
    out.scrollTop = out.scrollHeight;
  };
  const push = (level: string, args: unknown[]): void => {
    lines.push(`[${level}] ${args.map(fmt).join(' ')}`);
    render();
  };

  // Patch console (keep originals working).
  type ConsoleFn = (...a: unknown[]) => void;
  const c = console as unknown as Record<string, ConsoleFn>;
  for (const method of ['log', 'info', 'warn', 'error', 'debug']) {
    const orig = c[method];
    c[method] = (...a: unknown[]): void => {
      push(method, a);
      if (typeof orig === 'function') orig.apply(console, a);
    };
  }
  window.addEventListener('error', (e: ErrorEvent) => {
    push('uncaught', [e.message, `${e.filename}:${e.lineno}:${e.colno}`, e.error]);
  });
  window.addEventListener('unhandledrejection', (e: PromiseRejectionEvent) => {
    push('rejection', [e.reason]);
  });

  // UI
  const style = document.createElement('style');
  style.textContent = STYLE;
  document.head.appendChild(style);

  const panel = document.createElement('div');
  panel.id = 'vrai-dbg-panel';
  const bar = document.createElement('div');
  bar.id = 'vrai-dbg-bar';
  const mk = (label: string, fn: () => void): HTMLButtonElement => {
    const b = document.createElement('button');
    b.type = 'button';
    b.textContent = label;
    b.addEventListener('click', fn);
    return b;
  };
  bar.append(
    mk('Copy', () => { void navigator.clipboard?.writeText(lines.join('\n')); }),
    mk('Clear', () => { lines.length = 0; render(); }),
    mk('Close', () => panel.classList.remove('open')),
  );
  panel.append(bar, out);

  const btn = document.createElement('button');
  btn.id = 'vrai-dbg-btn';
  btn.type = 'button';
  btn.textContent = '🐞';
  btn.addEventListener('click', () => panel.classList.toggle('open'));

  document.body.append(panel, btn);
  push('info', [`debug console ready · COI=${String(crossOriginIsolated)} · gpu=${typeof navigator !== 'undefined' && 'gpu' in navigator}`]);
}
