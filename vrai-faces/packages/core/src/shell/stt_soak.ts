// On-device STT thermal soak — DEBUG-ONLY (mounted by main.ts only with ?debug).
//
// ADR-0032 pilot gate / OPT-007 (docs/OPTIMIZATION-REGISTER.md): confirm the WebGPU
// STT path doesn't thermally throttle over a sustained session. It runs whisper
// inference repeatedly (with a small gap) on a FIXED silent buffer for ~20 min — a
// constant workload, so any latency rise over time is throttling, not input
// variance. Live readout + a stop button; reports baseline→end creep + a pass/fail
// verdict. Uses its own device-STT handle, but the model is module-cached so there's
// no second download/load. Never ships in a normal boot.

import { createDeviceStt, type DeviceSttHandle } from './device_stt';

const SOAK_MS = 20 * 60 * 1000;   // 20-min thermal gate (ADR-0032)
const GAP_MS = 1000;              // pause between inferences → sustained, not pathological
const BASELINE_MS = 120_000;      // first 2 min = thermal baseline
const READY_TIMEOUT_MS = 60_000;  // give up if the model never loads
const THROTTLE_PCT = 15;          // end-vs-baseline rise beyond this = throttling

const delay = (ms: number): Promise<void> => new Promise((r) => { window.setTimeout(r, ms); });

function median(xs: number[]): number {
  if (xs.length === 0) return 0;
  const s = [...xs].sort((a, b) => a - b);
  const m = Math.floor(s.length / 2);
  const hi = s[m] ?? 0;                       // noUncheckedIndexedAccess → guard the | undefined
  if (s.length % 2 === 1) return hi;
  const lo = s[m - 1] ?? hi;
  return Math.round((lo + hi) / 2);
}

function clock(ms: number): string {
  const sec = Math.floor(ms / 1000);
  return `${Math.floor(sec / 60)}:${String(sec % 60).padStart(2, '0')}`;
}

const STYLE_ID = 'vrai-soak-style';
const CSS = `
.vrai-soak { position: fixed; top: calc(8px + env(safe-area-inset-top,0px)); left: 8px;
  z-index: 60; max-width: min(86vw, 380px); padding: 8px 10px; border-radius: 12px;
  background: rgba(20,20,24,.82); backdrop-filter: blur(10px); -webkit-backdrop-filter: blur(10px);
  color: #fff; font: 12px -apple-system, system-ui, sans-serif; box-shadow: 0 3px 12px rgba(0,0,0,.35); }
.vrai-soak button { height: 34px; padding: 0 12px; border: none; border-radius: 9px;
  background: #2f7d5b; color: #fff; font: 600 13px -apple-system, system-ui, sans-serif; cursor: pointer; }
.vrai-soak button.run { background: #b5532a; }
.vrai-soak .out { margin-top: 6px; font-variant-numeric: tabular-nums; line-height: 1.4; opacity: .92; }
.vrai-soak .out.warn { color: #ff9b9b; opacity: 1; }
.vrai-soak .out.ok { color: #bfe6cf; opacity: 1; }
`;

export interface SttSoakHandle { dispose(): void; }

/** Mount the debug-only thermal-soak panel. */
export function mountSttSoak(host: HTMLElement): SttSoakHandle {
  if (!document.getElementById(STYLE_ID)) {
    const s = document.createElement('style');
    s.id = STYLE_ID; s.textContent = CSS; document.head.appendChild(s);
  }
  const panel = document.createElement('div');
  panel.className = 'vrai-soak';
  const btn = document.createElement('button');
  btn.type = 'button';
  btn.textContent = '🔥 STT soak (20 min)';
  const out = document.createElement('div');
  out.className = 'out';
  out.textContent = 'thermal soak — constant whisper load, watches for throttling';
  panel.append(btn, out);
  host.appendChild(panel);

  let running = false;
  let stt: DeviceSttHandle | null = null;

  const setOut = (msg: string, cls = ''): void => { out.textContent = msg; out.className = `out ${cls}`; };

  async function run(): Promise<void> {
    if (running) { running = false; return; }          // re-tap = stop
    running = true;
    btn.textContent = '■ Stop soak'; btn.classList.add('run');
    stt = createDeviceStt();
    const probe = stt.soakStep?.bind(stt);
    if (!probe) { setOut('soak unsupported on this STT backend', 'warn'); running = false; return; }

    const samples: { t: number; ms: number }[] = [];
    const t0 = performance.now();
    setOut('loading model…');
    while (running && performance.now() - t0 < SOAK_MS) {
      const ms = await probe();
      const elapsed = performance.now() - t0;
      if (ms < 0) {                                     // model not ready yet
        if (elapsed > READY_TIMEOUT_MS) { setOut('model never became ready — aborting', 'warn'); break; }
        await delay(300); continue;
      }
      samples.push({ t: elapsed, ms });
      const base = median(samples.filter((x) => x.t <= BASELINE_MS).map((x) => x.ms));
      const recent = median(samples.slice(-5).map((x) => x.ms));
      const creep = base > 0 ? Math.round(((recent - base) / base) * 100) : 0;
      setOut(`soak ${clock(elapsed)} · #${samples.length} · now ${ms}ms · base ${base}ms · ${creep >= 0 ? '+' : ''}${creep}%`);
      await delay(GAP_MS);
    }

    const total = performance.now() - t0;
    if (samples.length > 0) {
      const base = median(samples.filter((x) => x.t <= BASELINE_MS).map((x) => x.ms));
      const end = median(samples.slice(-10).map((x) => x.ms));
      const creep = base > 0 ? Math.round(((end - base) / base) * 100) : 0;
      const throttled = creep > THROTTLE_PCT;
      setOut(
        `done: ${samples.length} takes · ${clock(total)} · base ${base}ms → end ${end}ms `
        + `(${creep >= 0 ? '+' : ''}${creep}%) · ${throttled ? '⚠ THROTTLING' : '✓ no throttling'}`,
        throttled ? 'warn' : 'ok',
      );
    }
    stt?.dispose(); stt = null;
    running = false;
    btn.textContent = '🔥 STT soak (20 min)'; btn.classList.remove('run');
  }

  const onClick = (): void => { void run(); };
  btn.addEventListener('click', onClick);

  return {
    dispose(): void {
      running = false;
      btn.removeEventListener('click', onClick);
      stt?.dispose(); stt = null;
      panel.remove();
    },
  };
}
