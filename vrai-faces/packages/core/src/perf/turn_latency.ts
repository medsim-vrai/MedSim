// Bedside-loop latency profiler (Track 2 · ADR-0026 latency chase). Records the PERCEIVED turn —
// PTT release → first audio enqueued — and its stage breakdown, so on-device profiling produces
// NUMBERS, not impressions. A tiny singleton the loop stages mark(); it reports when the turn
// completes (first audio). No PHI: stage names + millisecond timings only (ADR-0014 message-only).
//
// Stages (marked from the shell): release (PTT up) → stt (transcript ready) → listenSent (POST
// /listen) → listenResp (portal ack) → frame (VRAISpeechFrame arrives) → audio (first chunk enqueued).
// Derived segments: stt = STT · ai = /listen round-trip (AI turn) · net = frame delivery · tts =
// on-device synth (~0 when the portal pre-synthesized the audio).

let marks: Record<string, number> = {};
let active = false;
let listeners: Array<(s: TurnSummary) => void> = [];

export interface TurnSummary {
  totalMs: number;
  sttMs: number | null;
  aiMs: number | null;
  netMs: number | null;
  ttsMs: number | null;
  line: string;
}

/** PTT release — start a fresh turn (resets the marks). */
export function turnBegin(): void {
  marks = { release: performance.now() };
  active = true;
}

/** Stamp a stage. No-op outside an active turn, so stray frames don't start one; the FIRST `audio`
 *  closes the turn and emits the summary (later chunks are ignored). */
export function turnMark(stage: string): void {
  if (!active) return;
  marks[stage] = performance.now();
  if (stage === 'audio') {
    active = false;
    emit();
  }
}

function seg(a: string, b: string): number | null {
  const x = marks[a];
  const y = marks[b];
  return x !== undefined && y !== undefined ? Math.round(y - x) : null;
}

function emit(): void {
  const totalMs = seg('release', 'audio');
  if (totalMs === null) return;
  const sttMs = seg('release', 'stt');
  const aiMs = seg('listenSent', 'listenResp');
  const netMs = seg('listenResp', 'frame');
  const ttsMs = seg('frame', 'audio');
  const part = (label: string, v: number | null): string => (v !== null ? ` · ${label} ${v}` : '');
  const line = `loop ${totalMs}ms${part('stt', sttMs)}${part('ai', aiMs)}${part('net', netMs)}${part('tts', ttsMs)}`;
  const summary: TurnSummary = { totalMs, sttMs, aiMs, netMs, ttsMs, line };
  for (const cb of listeners) cb(summary);
}

/** Subscribe to completed-turn summaries (the shell renders them; debug console logs them). */
export function onTurnComplete(cb: (s: TurnSummary) => void): () => void {
  listeners.push(cb);
  return () => { listeners = listeners.filter((x) => x !== cb); };
}
