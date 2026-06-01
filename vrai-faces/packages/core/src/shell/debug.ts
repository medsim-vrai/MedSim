// Debug instrumentation gate (Phase 6 cleanup, W1.2).
//
// The on-device 🐞 console (debug_console.ts) and the verbose [speak]/[STT]
// traces were pilot bring-up tooling. They stay in the build but only activate
// when the launch URL carries `debug` (?debug or #debug) or localStorage
// `vrai:debug` === '1' — so a normal tablet boot is quiet, yet a field device
// can be flipped into verbose mode (and the 🐞 console) without a redeploy:
//   …/face/<id>?scenario=<s>&debug      ← one-off
//   localStorage.setItem('vrai:debug','1'); location.reload()   ← sticky
//
// Durable diagnostics still go through diag.push() (the diagnostic_panel),
// which is ALWAYS recorded regardless of this gate; the wrappers below are
// developer console traces only.

let _enabled = false;
try {
  const hay = typeof location !== 'undefined' ? `${location.search}${location.hash}` : '';
  const sticky = typeof localStorage !== 'undefined' && localStorage.getItem('vrai:debug') === '1';
  _enabled = /\bdebug\b/.test(hay) || sticky;
} catch {
  _enabled = false; // SSR / locked storage → stay quiet
}

/** True when debug instrumentation should run (URL `debug` flag or localStorage). */
export function isDebugEnabled(): boolean {
  return _enabled;
}

/* Gated console wrappers — no-ops unless isDebugEnabled(). */
export const dlog = (...args: unknown[]): void => { if (_enabled) console.log(...args); };
export const dwarn = (...args: unknown[]): void => { if (_enabled) console.warn(...args); };
export const derror = (...args: unknown[]): void => { if (_enabled) console.error(...args); };
