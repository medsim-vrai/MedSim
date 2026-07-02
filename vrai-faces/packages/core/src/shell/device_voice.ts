// Device voice — ON-DEVICE push-to-talk (Phase 6, ADR-0026). A hold-to-talk
// button transcribes the trainee's utterance ENTIRELY on the device (whisper-tiny
// via transformers.js, WebGPU/WASM — see device_stt.ts) and POSTs the text to the
// portal (`${api}/api/face/<id>/listen`); the portal runs the character AI turn
// and pushes a VRAISpeechFrame, so the avatar answers (Phase 4.3 speak path).
//
// Microphone audio NEVER leaves the device (ADR-0001 / ADR-0014) — this replaces
// the cloud Web Speech stopgap (ADR-0025). Name-gated activation (a wake word) is
// DEFERRED (ADR-0026): no clean on-device keyword-spotter for arbitrary per-
// scenario names yet; when built it runs as fuzzy/phonetic matching over a
// rolling on-device STT buffer, behind this same UI. PTT-first, name-trigger-next.

import { diag } from '@perf/diag';
import { turnBegin, turnMark, onTurnComplete } from '@perf/turn_latency';
import { createDeviceStt, resolveSttRoute, type DeviceSttHandle } from './device_stt';
import { primeSpeechSynthesis } from './speechUnlock';
import { audioPipeline } from '../modules/audio_pipeline';
import { createCloudStt } from './cloud_stt';

const MODULE = 'shell.deviceVoice';

// Inline mic glyph. The old '🎤' emoji renders as a blank/tofu box on some desktops (why "Hold to
// talk" looked icon-less) — an inline SVG draws identically on every platform.
const MIC_SVG = '<svg width="17" height="17" viewBox="0 0 24 24" fill="none" stroke="currentColor"'
  + ' stroke-width="2" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true">'
  + '<path d="M12 2a3 3 0 0 0-3 3v6a3 3 0 0 0 6 0V5a3 3 0 0 0-3-3z"/>'
  + '<path d="M19 10v1a7 7 0 0 1-14 0v-1"/><line x1="12" y1="19" x2="12" y2="22"/></svg>';

export interface DeviceVoiceHandle {
  dispose(): void;
}

export interface DeviceVoiceOpts {
  apiBase: string;
  characterId: string;
  scenarioId: string;
  /** Reserved for the deferred name-trigger (ADR-0026); unused today. */
  wakeName?: string;
  /** Opt-in device-capability token (ADR-0027); echoed back on /listen when set. */
  token?: string;
}

const STYLE_ID = 'vrai-voice-style';
const STYLE_CSS = `
.vrai-voice {
  position: fixed;
  left: 50%;
  /* Sits ABOVE the translucency slider (bottom: 16px, ~44px tall) so the PTT +
     transcript never overlap it. */
  bottom: calc(72px + env(safe-area-inset-bottom, 0px));
  transform: translateX(-50%);
  display: flex; flex-direction: column; align-items: stretch; gap: 8px;
  /* FIXED width (not max-width) so the panel + button never resize as the status text changes
     length — the status wraps inside instead of stretching the button. */
  width: min(92vw, 420px); box-sizing: border-box;
  padding: 10px 14px; border-radius: 18px;
  background: rgba(20, 20, 24, 0.82);
  backdrop-filter: blur(12px); -webkit-backdrop-filter: blur(12px);
  color: #fff; font: 14px -apple-system, system-ui, sans-serif;
  z-index: 55; user-select: none; -webkit-user-select: none;
  box-shadow: 0 4px 16px rgba(0,0,0,0.35);
}
.vrai-voice .vrai-voice-row { display: flex; align-items: center; gap: 8px; }
.vrai-voice button {
  height: 40px; padding: 0 16px; border: none; border-radius: 12px;
  background: rgba(255,255,255,0.12); color: #fff; font-size: 14px; cursor: pointer;
}
.vrai-voice button:active, .vrai-voice button.active { background: rgba(255,255,255,0.26); }
.vrai-voice button[disabled] { opacity: 0.4; cursor: default; }
.vrai-voice .vrai-voice-toggle.on { background: #2f7d5b; }
.vrai-voice .vrai-voice-ptt { flex: 1; font-weight: 600; touch-action: none;
  display: inline-flex; align-items: center; justify-content: center; gap: 7px; }
.vrai-voice .vrai-voice-ptt.active { background: #b5532a; }
/* COLD state: the "Establish mic" prepare button — distinct (green) from the armed talk button. */
.vrai-voice .vrai-voice-ptt.establish { background: #2f7d5b; }
.vrai-voice .vrai-voice-ptt svg { flex: 0 0 auto; }
.vrai-voice .vrai-voice-opts { min-width: 42px; padding: 0 10px; font-size: 18px; flex: 0 0 auto; }
.vrai-voice .vrai-voice-controls { display: none; flex-direction: column; gap: 8px; }
.vrai-voice.vrai-voice-open .vrai-voice-controls { display: flex; }
.vrai-voice .vrai-voice-note { font-size: 11px; color: #bfe6cf; line-height: 1.4; }
.vrai-voice .vrai-voice-status { font-size: 12px; opacity: 0.85; min-height: 16px; }
.vrai-voice .vrai-voice-status.err { color: #ff9b9b; opacity: 1; }
.vrai-voice .vrai-voice-metrics { font-size: 11px; opacity: 0.6; min-height: 13px;
  font-variant-numeric: tabular-nums; }
.vrai-voice .vrai-voice-metrics.err { color: #ff9b9b; opacity: 1; word-break: break-word; }
`;

function ensureStyle(): void {
  if (document.getElementById(STYLE_ID)) return;
  const s = document.createElement('style');
  s.id = STYLE_ID;
  s.textContent = STYLE_CSS;
  document.head.appendChild(s);
}

function micSupported(): boolean {
  return typeof navigator !== 'undefined'
    && !!navigator.mediaDevices
    && typeof navigator.mediaDevices.getUserMedia === 'function'
    && typeof MediaRecorder !== 'undefined';
}

export function mountDeviceVoice(
  container: HTMLElement,
  opts: DeviceVoiceOpts,
): DeviceVoiceHandle {
  ensureStyle();

  const panel = document.createElement('div');
  panel.className = 'vrai-voice';
  panel.setAttribute('role', 'group');
  panel.setAttribute('aria-label', 'Device voice (on-device push-to-talk)');

  // Main row: ONE Hold-to-talk button + a small ⚙ that expands the speech options
  // (cloud-voice toggle + pilot metrics) during testing, then collapses. `toggleBtn`
  // is now that ⚙ — it shows/hides the options; the STT auto-enables on mount.
  const mainRow = document.createElement('div');
  mainRow.className = 'vrai-voice-row';
  const toggleBtn = document.createElement('button');
  toggleBtn.type = 'button';
  toggleBtn.className = 'vrai-voice-opts';
  toggleBtn.textContent = '⚙';
  toggleBtn.setAttribute('aria-label', 'Speech options');
  const pttBtn = document.createElement('button');
  pttBtn.type = 'button';
  pttBtn.className = 'vrai-voice-ptt establish';
  // Content is set by renderPhase() below — COLD shows "Establish mic", WARM shows "Hold to talk".
  mainRow.append(toggleBtn, pttBtn);

  const status = document.createElement('div');
  status.className = 'vrai-voice-status';

  // Collapsible options (behind ⚙): cloud-voice toggle + privacy note + pilot metrics.
  const controls = document.createElement('div');
  controls.className = 'vrai-voice-controls';

  const note = document.createElement('div');
  note.className = 'vrai-voice-note';
  note.textContent = 'On-device speech recognition — your audio stays on this device.';

  // Cloud fallback (ADR-0025) — browser Web Speech, for tablets where on-device
  // STT can't run. NON-PHI: audio leaves the device. Opt-in, off by default.
  const cloudBtn = document.createElement('button');
  cloudBtn.type = 'button';
  cloudBtn.className = 'vrai-voice-toggle';
  cloudBtn.textContent = '☁︎ Use cloud voice (testing · not PHI)';

  // Pilot readout (ADR-0026): backend + cold-load + last-take latency, so the
  // on-device validation produces numbers instead of impressions.
  const metricsEl = document.createElement('div');
  metricsEl.className = 'vrai-voice-metrics';

  // Loop-latency readout (Track 2): release → first audio, with the stage breakdown.
  const loopEl = document.createElement('div');
  loopEl.className = 'vrai-voice-metrics';

  controls.append(note, cloudBtn, metricsEl, loopEl);
  // Bottom-anchored column: PTT sits at the BOTTOM (just above the translucency
  // slider), the transcript/status directly above it, options above that.
  panel.append(controls, status, mainRow);
  container.appendChild(panel);

  // Loop-latency profile (Track 2): render the release→audio breakdown when a turn completes + log it.
  const offTurn = onTurnComplete((sLat) => {
    loopEl.textContent = sLat.line;
    diag.push({ t: performance.now(), moduleId: MODULE, kind: 'info', message: sLat.line });
  });

  function renderMetrics(): void {
    const m = stt?.metrics();
    metricsEl.classList.remove('err');
    if (!m) { metricsEl.textContent = ''; return; }
    if (m.error) {                              // surface the load failure on-screen
      metricsEl.textContent = `STT unavailable: ${m.error}`;
      metricsEl.classList.add('err');
      return;
    }
    if (!m.backend) { metricsEl.textContent = ''; return; }
    const cold = m.loadMs !== null ? ` · cold ${m.loadMs}ms` : '';
    const last = m.lastMs !== null ? ` · last ${m.lastMs}ms` : '';
    // Per-take phase split (ADR-0026 latency chase): rec flush · decode · resample
    // · whisper inference · clip length — shows where the warm ~2s actually goes.
    const g = m.lastStages;
    const split = g
      ? ` · [rec ${g.recMs} · dec ${g.decodeMs} · rs ${g.resampleMs} · asr ${g.inferMs} · clip ${g.clipMs}]`
      : '';
    const why = m.emptyReason ? ` · last take empty: ${m.emptyReason}` : '';
    metricsEl.textContent = `STT: ${m.backend}${cold}${last}${split}${why}`;
  }

  function setStatus(msg: string, isErr = false): void {
    status.textContent = msg;
    status.classList.toggle('err', isErr);
  }

  if (!micSupported()) {
    pttBtn.disabled = true;
    panel.classList.add('vrai-voice-open');
    setStatus('Microphone capture not available in this browser.', true);
    return { dispose() { panel.remove(); } };
  }

  let stt: DeviceSttHandle | null = null;
  let useCloud = false; // ADR-0025 cloud fallback (non-PHI), opt-in
  const makeStt = (): DeviceSttHandle => (useCloud ? createCloudStt() : createDeviceStt({
    apiBase: opts.apiBase,
    characterId: opts.characterId,
    scenarioId: opts.scenarioId,
    ...(opts.token ? { token: opts.token } : {}),
  }));
  // ADR-0038: same route decision device_stt makes — drives the honest privacy
  // labels (room-local Mac vs fully on-device).
  const isRoomRoute = resolveSttRoute(
    typeof location !== 'undefined' ? location.search + location.hash : '',
    typeof navigator !== 'undefined'
      && !!(navigator as unknown as { gpu?: unknown }).gpu,
  ) === 'portal';
  const READY_MSG = isRoomRoute
    ? 'Voice ready — transcribed on the instructor’s Mac (in-room). Hold to talk.'
    : 'On-device voice ready — hold to talk.';
  const NOTE_MSG = isRoomRoute
    ? 'Room speech recognition — audio goes only to the instructor’s Mac, never a third party.'
    : 'On-device speech recognition — your audio stays on this device.';
  note.textContent = NOTE_MSG;
  let on = false;
  let busy = false;                       // transcribing a take
  let startP: Promise<void> | null = null; // in-flight start(), so stop waits for it
  let readyPoll: number | null = null;     // polls model readiness to show metrics

  // Short "thinking" fillers in the character's voice — fetched once, played on hold-to-talk release to
  // cover the dead air while the reply synthesizes (and to keep the OS output awake). Best-effort: if
  // the fetch fails, warmHold() falls back to the inaudible keep-awake noise.
  let fillerClips: ArrayBuffer[] = [];
  void (async () => {
    try {
      const base = opts.apiBase.replace(/\/+$/, '');
      const qs = new URLSearchParams({ scenario: opts.scenarioId }).toString();
      const res = await fetch(`${base}/api/face/${encodeURIComponent(opts.characterId)}/fillers?${qs}`);
      const j = (await res.json()) as { fillers?: string[] };
      fillerClips = (j.fillers ?? [])
        .map((b64) => {
          const bin = atob(b64);
          const bytes = new Uint8Array(bin.length);
          for (let i = 0; i < bin.length; i++) bytes[i] = bin.charCodeAt(i);
          return bytes.buffer;
        })
        .filter((b) => b.byteLength > 1);
    } catch { /* best-effort — no fillers, warmHold uses the silent keep-awake */ }
  })();

  // Two-step activation. COLD shows "Establish mic": one tap PREPARES (unlock audio so the character
  // can be heard, grant the mic permission up front, warm the recognizer) WITHOUT starting the
  // conversation. It then becomes "Hold to talk" — the ONLY control that sends input and expects a
  // reply. Replaces the old hidden "first press just warms, press again to talk" that confused users.
  type Phase = 'cold' | 'warming' | 'warm';
  let phase: Phase = 'cold';
  let establishing = false;

  function renderPhase(): void {
    pttBtn.classList.toggle('establish', phase === 'cold');
    if (phase === 'warming') {
      pttBtn.disabled = true;
      pttBtn.textContent = 'Preparing mic…';
      return;
    }
    pttBtn.disabled = false;
    if (phase === 'cold') {
      pttBtn.innerHTML = `${MIC_SVG}<span>Establish mic</span>`;
      pttBtn.setAttribute('aria-label', 'Establish microphone — prepare to talk');
    } else {
      pttBtn.innerHTML = `${MIC_SVG}<span>Hold to talk</span>`;
      pttBtn.setAttribute('aria-label', 'Hold to talk');
    }
  }

  // Confirm mic access + surface the browser permission prompt up front, without recording a take.
  async function probeMic(): Promise<boolean> {
    try {
      const s = await navigator.mediaDevices.getUserMedia({ audio: true });
      s.getTracks().forEach((t) => t.stop());   // release immediately — we only needed grant + a check
      return true;
    } catch { return false; }
  }

  // "Establish mic" — PREPARE only; never sends a turn or starts the conversation.
  async function establish(): Promise<void> {
    if (phase === 'warm' || establishing) return;
    establishing = true;
    phase = 'warming';
    renderPhase();
    setStatus('Preparing microphone…');
    primeSpeechSynthesis();                 // in-gesture: unlock iOS speech
    void audioPipeline.primeOnUserGesture(); // unlock playback (also flushes the buffered opening line)
    if (!on) setMaster(true);               // create the recognizer handle + warm the route
    // Open the mic ONCE and keep it for the whole session (reliable multi-turn — re-acquiring per
    // take dropped takes 2+). The cloud engine self-manages its mic, so fall back to a probe there.
    const ok = stt?.acquireMic ? await stt.acquireMic() : await probeMic();
    if (!ok) {
      phase = 'cold';
      renderPhase();
      setStatus('Microphone blocked — allow mic access for this site, then tap Establish mic.', true);
      establishing = false;
      return;
    }
    phase = 'warm';
    renderPhase();
    setStatus(READY_MSG);
    audioPipeline.warmOutput();  // wake the output sink now (the opening, if any, plays next)
    establishing = false;
  }

  function sendUtterance(text: string): void {
    const clean = text.trim();
    if (!clean) return;
    setStatus(`Heard: “${clean}” — sending…`);
    const t0 = performance.now();   // measure the /listen round-trip (LLM + TTS + transfer)
    turnMark('listenSent');         // loop-latency: POST /listen
    const base = opts.apiBase.replace(/\/+$/, '');
    const url = `${base}/api/face/${encodeURIComponent(opts.characterId)}/listen`;
    // CORS "simple" request (no application/json header → no preflight); the
    // portal's request.json() parses the body regardless of content-type.
    const payload: { text: string; scenario: string; token?: string } =
      { text: clean, scenario: opts.scenarioId };
    if (opts.token) payload.token = opts.token; // ADR-0027 capability (when enforced)
    void fetch(url, { method: 'POST', body: JSON.stringify(payload) })
      .then(async (r) => {
        turnMark('listenResp');     // loop-latency: portal acked the AI turn
        const j = (await r.json().catch(() => null)) as { ok?: boolean; mode?: string } | null;
        const secs = ((performance.now() - t0) / 1000).toFixed(1);
        if (r.ok && j?.ok) {
          const how = j.mode === 'ai' ? 'character replied'
            : j.mode === 'echo' ? 'echoed (no running scenario)'
            : (j.mode ?? 'sent');
          setStatus(`“${clean}” → ${how} ✓ (${secs}s)`);
        } else {
          setStatus(`Send failed (${secs}s)`, true);
        }
      })
      .catch(() => setStatus('Send failed (portal unreachable)', true));
  }

  function setMaster(enabled: boolean): void {
    on = enabled;
    // The voice warms lazily on the FIRST PTT press (see onPttDown), so the button
    // stays pressable while off; readiness shows in the status line. The ⚙ (onToggle)
    // drives the options panel, not this.
    if (enabled) {
      if (!stt) stt = makeStt(); // on-device (warms model) or cloud, per the toggle
      const s = stt;
      setStatus(s.isReady()
        ? READY_MSG
        : 'Loading on-device voice model… (first time, ~once).');
      renderMetrics();
      // Surface backend + cold-load as soon as the model finishes warming.
      if (!s.isReady() && readyPoll === null) {
        readyPoll = window.setInterval(() => {
          const failed = s.metrics().error !== null;
          if (!on || s.isReady() || failed) {
            if (readyPoll !== null) { clearInterval(readyPoll); readyPoll = null; }
            if (on && s.isReady()) setStatus(READY_MSG);
            else if (on && failed) setStatus('Voice unavailable — details below.', true);
            renderMetrics();
          }
        }, 400);
      }
      diag.push({
        t: performance.now(), moduleId: MODULE, kind: 'info',
        message: isRoomRoute
          ? 'push-to-talk enabled (room route: audio → instructor Mac only, ADR-0038)'
          : 'on-device push-to-talk enabled (whisper-tiny, audio stays on device)',
      });
    } else {
      if (readyPoll !== null) { clearInterval(readyPoll); readyPoll = null; }
      stt?.dispose();
      stt = null;
      setStatus('');
      renderMetrics();
    }
  }

  // --- listeners (sync handlers; async work runs in a void IIFE) ---
  // ⚙ toggles the collapsible speech options (cloud-voice toggle + metrics).
  const onToggle = (): void => { panel.classList.toggle('vrai-voice-open'); };

  const onCloudToggle = (): void => {
    useCloud = !useCloud;
    cloudBtn.classList.toggle('on', useCloud);
    cloudBtn.textContent = useCloud
      ? '☁︎ Cloud voice ON (testing · not PHI)'
      : '☁︎ Use cloud voice (testing · not PHI)';
    note.textContent = useCloud
      ? '⚠︎ Cloud recognizer — audio leaves the device (Google). Testing only, NOT for PHI.'
      : NOTE_MSG;
    if (on) { setMaster(false); setMaster(true); } // re-create with the chosen engine
  };

  const onPttDown = (ev: Event): void => {
    ev.preventDefault();
    // FR-021: capture the pointer for the whole hold — a slight finger drift off the
    // button mid-sentence was firing pointerleave → onPttUp, truncating the utterance
    // and sending the partial. With capture, only a real release (pointerup) ends the take.
    if (typeof PointerEvent !== 'undefined' && ev instanceof PointerEvent) {
      try { pttBtn.setPointerCapture(ev.pointerId); } catch { /* unsupported — harmless */ }
    }
    // COLD / warming: the button reads "Establish mic" — PREPARE only, never record (see establish()).
    if (phase !== 'warm') { void establish(); return; }
    // WARM: this press is a real talk turn. Keep audio live (idempotent) so the reply can be heard.
    void audioPipeline.primeOnUserGesture();
    if (busy || !stt) return;
    // Re-prime iOS speechSynthesis from THIS gesture so the async reply (seconds after
    // release) can speak — iOS won't start an utterance without a recent user gesture.
    primeSpeechSynthesis();
    // New turn: stop the character's still-playing/queued audio and reset the scheduler, so the upcoming
    // reply plays immediately instead of queued behind a previous (long) line (playhead far ahead).
    // (No output warm-up DURING recording — with echo-cancellation off it would leak into the mic; the
    // DAC is kept awake AFTER release via warmHold() in onPttUp instead.)
    audioPipeline.flush();
    pttBtn.classList.add('active');
    setStatus('Listening…');
    const s = stt;
    startP = s.start().catch((e: unknown) => {
      pttBtn.classList.remove('active');
      setStatus('Microphone permission needed', true);
      diag.push({
        t: performance.now(), moduleId: MODULE, kind: 'warn',
        message: 'getUserMedia/start failed', data: e instanceof Error ? e.message : String(e),
      });
      throw e;
    });
  };

  const onPttUp = (ev: Event): void => {
    ev.preventDefault();
    const s = stt;
    if (phase !== 'warm' || !s || !pttBtn.classList.contains('active')) return;
    // The mic suspends the playback AudioContext on iOS; resume it from THIS release gesture
    // (resume() needs a user gesture on iOS — the async one at reply time hangs) so the
    // character's reply, arriving seconds later, plays. Pairs with the keep-alive source.
    void audioPipeline.resume();
    // Spin the OS hardware output (DAC) up the instant the student releases, so the first reply isn't
    // dropped while the DAC wakes from the near-silent keep-alive (the turn-1 silence). NO filler here —
    // only the inaudible keep-awake noise: nothing is spoken until the prompt is transcribed below. The
    // student has released and isn't recording, so this can't leak into the mic.
    audioPipeline.warmHold();
    pttBtn.classList.remove('active');
    busy = true;
    turnBegin();                          // t0 for the loop-latency profile (release → first audio)
    setStatus('Transcribing…');
    void (async () => {
      try {
        await startP;                       // ensure recording actually began
        const text = await s.stopAndTranscribe();
        turnMark('stt');                    // transcript ready (release → here = STT)
        renderMetrics();                    // surface backend + latency for the pilot
        if (text) {
          // Prompt is now confirmed — only NOW play the audible "thinking" filler to cover the synthesis
          // wait (the keep-awake noise from release is still running underneath, holding the DAC awake).
          audioPipeline.warmHold(fillerClips);
          sendUtterance(text);
        }
        else {
          const why = s.metrics().emptyReason;   // FR-006: name the cause, not just the symptom
          setStatus(why ? `(no speech — ${why})` : '(no speech detected)', true);
        }
      } catch {
        setStatus('Transcription failed', true);
      } finally {
        busy = false;
        startP = null;
      }
    })();
  };

  toggleBtn.addEventListener('click', onToggle);
  cloudBtn.addEventListener('click', onCloudToggle);
  pttBtn.addEventListener('pointerdown', onPttDown);
  pttBtn.addEventListener('pointerup', onPttUp);
  pttBtn.addEventListener('pointerleave', onPttUp);
  pttBtn.addEventListener('pointercancel', onPttUp);

  // Initial COLD render: the button reads "Establish mic" with a single on-screen hint (replaces the
  // old portal "tap the screen to enable audio" banner, which never worked).
  renderPhase();
  setStatus('Tap “Establish mic” to prepare — then hold to talk.');

  return {
    dispose() {
      offTurn();
      toggleBtn.removeEventListener('click', onToggle);
      cloudBtn.removeEventListener('click', onCloudToggle);
      pttBtn.removeEventListener('pointerdown', onPttDown);
      pttBtn.removeEventListener('pointerup', onPttUp);
      pttBtn.removeEventListener('pointerleave', onPttUp);
      pttBtn.removeEventListener('pointercancel', onPttUp);
      if (readyPoll !== null) { clearInterval(readyPoll); readyPoll = null; }
      stt?.dispose();
      stt = null;
      panel.remove();
    },
  };
}
