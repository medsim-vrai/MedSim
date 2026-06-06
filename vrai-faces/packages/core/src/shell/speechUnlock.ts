// iOS audio-gesture unlock for the browser-speech path.
//
// iOS Safari unlocks `window.speechSynthesis` ONLY from inside a real user gesture
// (the same restriction as the Web Audio AudioContext — ADR-0008). The bedside
// reply is voiced ASYNCHRONOUSLY: the character answers seconds after the trainee
// releases push-to-talk, with no live gesture on the stack. Without a gesture-time
// prime iOS silently refuses to start the utterance — no audio, and the `onstart`-
// driven jaw lip-sync never fires (the symptom we hit on the iPad).
//
// FINDING (2026-06-06, on iPad — ADR-0037): this does NOT reliably unlock iOS WebKit for
// async speech — even primed from a fresh PTT gesture, iOS still silently refused the reply
// (no `onstart`, no `onerror`). On iOS the character voice therefore comes from server-side
// TTS played through the AudioContext, NOT from speechSynthesis. This prime is kept because
// (a) it DOES work on real Chromium (where speechSynthesis isn't gesture-locked) as a
// last-ditch fallback, and (b) it warms the async voice list. Call SYNCHRONOUSLY from inside
// a pointer/gesture handler. Best-effort and never throws.

export function primeSpeechSynthesis(): void {
  try {
    const synth = typeof window !== 'undefined' ? window.speechSynthesis : undefined;
    if (!synth || typeof SpeechSynthesisUtterance === 'undefined') return;
    const u = new SpeechSynthesisUtterance(' ');
    u.volume = 0; // inaudible — the unlock is the speak() CALL, not its output
    synth.speak(u);
  } catch {
    /* best-effort: a browser without a usable speechSynthesis just won't unlock */
  }
}
