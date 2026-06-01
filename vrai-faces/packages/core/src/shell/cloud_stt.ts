// Cloud STT stopgap (ADR-0025) — the browser's built-in Web Speech recognizer for
// device push-to-talk. NON-PHI: on Android Chrome the audio is sent to Google's
// cloud STT, so this is for live TESTING ONLY, never a PHI session. It exists as a
// fallback because on-device whisper (device_stt, ADR-0026) can't run on tablets
// with no WebGPU adapter (the ONNX wasm backend won't register there). It uses no
// ONNX / wasm / WebGPU, so it works where the on-device path doesn't.
//
// Implements the same DeviceSttHandle shape as device_stt so device_voice can swap
// the two. Off by default, behind an explicit "cloud (not PHI)" toggle.

import { diag } from '@perf/diag';
import type { DeviceSttHandle, DeviceSttMetrics } from './device_stt';

const MODULE = 'shell.cloudStt';

// Minimal typings for the (often-unprefixed-or-webkit) Web Speech API.
interface SRAlternative { transcript: string }
interface SRResult { isFinal: boolean; 0: SRAlternative }
interface SREvent { resultIndex: number; results: ArrayLike<SRResult> }
interface SRErrorEvent { error: string }
interface SpeechRecognitionLike {
  lang: string; continuous: boolean; interimResults: boolean; maxAlternatives: number;
  onresult: ((e: SREvent) => void) | null;
  onerror: ((e: SRErrorEvent) => void) | null;
  onend: (() => void) | null;
  start(): void; stop(): void; abort(): void;
}
type SRCtor = new () => SpeechRecognitionLike;

function getRecognitionCtor(): SRCtor | null {
  const w = window as unknown as { SpeechRecognition?: SRCtor; webkitSpeechRecognition?: SRCtor };
  return w.SpeechRecognition ?? w.webkitSpeechRecognition ?? null;
}

export function createCloudStt(): DeviceSttHandle {
  const Ctor = getRecognitionCtor();
  let rec: SpeechRecognitionLike | null = null;
  let finalText = '';
  let resolveStop: ((s: string) => void) | null = null;
  let lastMs: number | null = null;
  let t0 = 0;
  let err: string | null = Ctor ? null : 'Web Speech (cloud) not available in this browser';
  let timer: number | null = null;

  const settle = (): void => {
    if (resolveStop) { resolveStop(finalText.trim()); resolveStop = null; }
    if (timer !== null) { clearTimeout(timer); timer = null; }
  };

  return {
    isReady: (): boolean => Ctor !== null,
    metrics: (): DeviceSttMetrics => ({ backend: Ctor ? 'cloud' : null, loadMs: null, lastMs, error: err }),

    async start(): Promise<void> {
      if (!Ctor) throw new Error(err ?? 'no Web Speech');
      finalText = '';
      err = null;
      const r = new Ctor();
      r.lang = 'en-US';
      r.continuous = false;
      r.interimResults = false;
      r.maxAlternatives = 1;
      r.onresult = (e: SREvent): void => {
        for (let i = e.resultIndex; i < e.results.length; i++) {
          const res = e.results[i];
          if (res && res.isFinal) finalText += res[0].transcript;
        }
      };
      r.onerror = (e: SRErrorEvent): void => {
        err = e.error;
        diag.push({ t: performance.now(), moduleId: MODULE, kind: 'warn', message: 'cloud STT error', data: e.error });
      };
      r.onend = (): void => settle();
      rec = r;
      t0 = performance.now();
      r.start();
    },

    async stopAndTranscribe(): Promise<string> {
      const r = rec;
      if (!r) return '';
      const text = await new Promise<string>((resolve) => {
        resolveStop = resolve;
        try { r.stop(); } catch { settle(); resolve(finalText.trim()); }
        timer = window.setTimeout(settle, 5000); // safety: resolve even if onend never fires
      });
      lastMs = Math.round(performance.now() - t0);
      rec = null;
      return text;
    },

    dispose(): void {
      if (timer !== null) { clearTimeout(timer); timer = null; }
      try { rec?.abort(); } catch { /* noop */ }
      rec = null;
    },
  };
}
