// Device voice — DEMO / cloud STT (NOT for PHI). A hold-to-talk button and an
// optional name-trigger that listen on the tablet and POST the trainee's
// transcribed utterance to the portal (`${api}/api/face/<id>/listen`). The
// portal runs the character AI turn and pushes a VRAISpeechFrame, so the avatar
// answers in its own voice (reusing the Phase 4.3 speak path).
//
// This uses the browser's Web Speech API (SpeechRecognition), which streams mic
// audio to a cloud service — so it is OFF by default, gated behind an explicit
// "cloud voice — not for PHI" toggle, and is intended only for non-PHI live
// testing. The PHI-safe replacement (on-device wake-word + STT) is gated on
// RB-002 (ADR-0024 / ADR-0025): swap `name_trigger` + `device_stt` in behind
// this same UI once researched. Until then, this lets us test end to end.

import { diag } from '@perf/diag';

const MODULE = 'shell.deviceVoice';

export interface DeviceVoiceHandle {
  dispose(): void;
}

export interface DeviceVoiceOpts {
  apiBase: string;
  characterId: string;
  scenarioId: string;
  /** Initial wake name for the name-trigger; the tester can edit it live. */
  wakeName?: string;
}

// --- Minimal Web Speech API typings -----------------------------------------
// The DOM lib doesn't ship SpeechRecognition types and the vendor-prefixed
// constructor is untyped; we declare only the slice we use (no `any`).
interface SpeechAlternativeLike { readonly transcript: string; }
interface SpeechResultLike {
  readonly length: number;
  readonly isFinal: boolean;
  readonly [index: number]: SpeechAlternativeLike;
}
interface SpeechResultListLike {
  readonly length: number;
  readonly [index: number]: SpeechResultLike;
}
interface SpeechRecognitionEventLike {
  readonly resultIndex: number;
  readonly results: SpeechResultListLike;
}
interface SpeechRecognitionErrorLike { readonly error?: string; }
interface SpeechRecognitionLike {
  lang: string;
  continuous: boolean;
  interimResults: boolean;
  start(): void;
  stop(): void;
  abort(): void;
  onresult: ((e: SpeechRecognitionEventLike) => void) | null;
  onerror: ((e: SpeechRecognitionErrorLike) => void) | null;
  onend: (() => void) | null;
}
type SpeechRecognitionCtor = new () => SpeechRecognitionLike;

function getRecognitionCtor(): SpeechRecognitionCtor | null {
  const w = window as unknown as {
    SpeechRecognition?: SpeechRecognitionCtor;
    webkitSpeechRecognition?: SpeechRecognitionCtor;
  };
  return w.SpeechRecognition ?? w.webkitSpeechRecognition ?? null;
}

const STYLE_ID = 'vrai-voice-style';
const STYLE_CSS = `
.vrai-voice {
  position: fixed;
  left: 50%;
  bottom: calc(18px + env(safe-area-inset-bottom, 0px));
  transform: translateX(-50%);
  display: flex; flex-direction: column; align-items: stretch; gap: 8px;
  max-width: min(92vw, 460px);
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
.vrai-voice .vrai-voice-ptt { flex: 1; font-weight: 600; touch-action: none; }
.vrai-voice .vrai-voice-ptt.active { background: #b5532a; }
.vrai-voice .vrai-voice-controls { display: none; flex-direction: column; gap: 8px; }
.vrai-voice.vrai-voice-open .vrai-voice-controls { display: flex; }
.vrai-voice input[type="text"] {
  flex: 1; height: 36px; padding: 0 10px;
  border: 1px solid rgba(255,255,255,0.18); border-radius: 10px;
  background: rgba(255,255,255,0.06); color: #fff; font-size: 14px;
}
.vrai-voice label.vrai-voice-name { display: flex; align-items: center; gap: 8px; flex: 1; }
.vrai-voice .vrai-voice-note {
  font-size: 11px; color: #ffd6a8; line-height: 1.4;
}
.vrai-voice .vrai-voice-status { font-size: 12px; opacity: 0.85; min-height: 16px; }
.vrai-voice .vrai-voice-status.err { color: #ff9b9b; opacity: 1; }
`;

function ensureStyle(): void {
  if (document.getElementById(STYLE_ID)) return;
  const s = document.createElement('style');
  s.id = STYLE_ID;
  s.textContent = STYLE_CSS;
  document.head.appendChild(s);
}

type Mode = 'idle' | 'ptt' | 'name';

export function mountDeviceVoice(
  container: HTMLElement,
  opts: DeviceVoiceOpts,
): DeviceVoiceHandle {
  ensureStyle();

  const panel = document.createElement('div');
  panel.className = 'vrai-voice';
  panel.setAttribute('role', 'group');
  panel.setAttribute('aria-label', 'Device voice (cloud, not for PHI)');

  const toggleRow = document.createElement('div');
  toggleRow.className = 'vrai-voice-row';
  const toggleBtn = document.createElement('button');
  toggleBtn.type = 'button';
  toggleBtn.className = 'vrai-voice-toggle';
  toggleBtn.textContent = '🎙 Enable push-to-talk';
  toggleRow.append(toggleBtn);

  const controls = document.createElement('div');
  controls.className = 'vrai-voice-controls';

  const note = document.createElement('div');
  note.className = 'vrai-voice-note';
  note.textContent =
    'Cloud speech-to-text (Web Speech API) — for non-PHI testing only. '
    + 'Audio leaves the device. On-device voice is gated on RB-002.';

  const pttRow = document.createElement('div');
  pttRow.className = 'vrai-voice-row';
  const pttBtn = document.createElement('button');
  pttBtn.type = 'button';
  pttBtn.className = 'vrai-voice-ptt';
  pttBtn.textContent = '🎤 Hold to talk';
  pttRow.append(pttBtn);

  const nameRow = document.createElement('div');
  nameRow.className = 'vrai-voice-row';
  const nameLabel = document.createElement('label');
  nameLabel.className = 'vrai-voice-name';
  const nameChk = document.createElement('input');
  nameChk.type = 'checkbox';
  const nameChkText = document.createElement('span');
  nameChkText.textContent = 'Name trigger';
  nameLabel.append(nameChk, nameChkText);
  const nameInput = document.createElement('input');
  nameInput.type = 'text';
  nameInput.maxLength = 40;
  nameInput.placeholder = 'character name';
  nameInput.value = opts.wakeName ?? opts.characterId;
  nameInput.setAttribute('aria-label', 'Wake name');
  nameRow.append(nameLabel, nameInput);

  const status = document.createElement('div');
  status.className = 'vrai-voice-status';

  controls.append(note, pttRow, nameRow, status);
  panel.append(toggleRow, controls);
  container.appendChild(panel);

  function setStatus(msg: string, isErr = false): void {
    status.textContent = msg;
    status.classList.toggle('err', isErr);
  }

  const Ctor = getRecognitionCtor();
  if (!Ctor) {
    toggleBtn.disabled = true;
    panel.classList.add('vrai-voice-open');
    setStatus('Speech recognition not available in this browser.', true);
    return {
      dispose() { panel.remove(); },
    };
  }
  // Non-null alias so the nested closures below keep the narrowed type.
  const RecognitionCtor: SpeechRecognitionCtor = Ctor;

  let rec: SpeechRecognitionLike | null = null;
  let mode: Mode = 'idle';
  let masterOn = false;
  let nameWanted = false;
  let disposed = false;

  function wakeNeedle(): string {
    return (nameInput.value || opts.wakeName || opts.characterId).trim().toLowerCase();
  }

  function sendUtterance(text: string): void {
    const clean = text.trim();
    if (!clean) return;
    setStatus(`Heard: “${clean}” — sending…`);
    const base = opts.apiBase.replace(/\/+$/, '');
    const url = `${base}/api/face/${encodeURIComponent(opts.characterId)}/listen`;
    // NB: send as a CORS "simple" request — NO `content-type: application/json`
    // header (which would force a preflight OPTIONS that, cross-origin over the
    // self-signed-CA HTTPS dev cert, gets blocked on iOS Safari — the symptom
    // "STT made on device but not received by the computer"). With the default
    // text/plain body the POST is sent directly, like the save-skin POST that
    // works; the portal's `request.json()` parses the body regardless of type.
    void fetch(url, {
      method: 'POST',
      body: JSON.stringify({ text: clean, scenario: opts.scenarioId }),
    })
      .then(async (r) => {
        const j = (await r.json().catch(() => null)) as
          { ok?: boolean; mode?: string; reply?: string } | null;
        if (r.ok && j?.ok) {
          const how = j.mode === 'ai' ? 'character replied'
            : j.mode === 'echo' ? 'echoed (no running scenario)'
            : (j.mode ?? 'sent');
          setStatus(`“${clean}” → ${how} ✓`);
        } else {
          setStatus('Send failed', true);
        }
      })
      .catch(() => setStatus('Send failed (portal unreachable)', true));
  }

  function clearRec(): void {
    if (!rec) return;
    rec.onresult = null;
    rec.onerror = null;
    rec.onend = null;
    try { rec.abort(); } catch { /* not started */ }
    rec = null;
  }

  function handleResult(e: SpeechRecognitionEventLike): void {
    let finalText = '';
    for (let i = e.resultIndex; i < e.results.length; i++) {
      const res = e.results[i];
      if (!res || !res.isFinal || res.length === 0) continue;
      const alt = res[0];
      if (alt) finalText += alt.transcript;
    }
    finalText = finalText.trim();
    if (!finalText) return;
    if (mode === 'name') {
      const needle = wakeNeedle();
      if (needle && finalText.toLowerCase().includes(needle)) {
        sendUtterance(finalText);
      } else {
        setStatus(`(idle — say “${nameInput.value || opts.characterId}” to address)`);
      }
    } else if (mode === 'ptt') {
      sendUtterance(finalText);
    }
  }

  function handleEnd(): void {
    if (disposed) return;
    if (mode === 'ptt') {
      mode = 'idle';
      if (masterOn && nameWanted) startName();
      return;
    }
    if (mode === 'name') {
      // Browsers periodically end a continuous session; restart if still wanted.
      if (masterOn && nameWanted) {
        try { rec?.start(); } catch { /* already starting */ }
      } else {
        mode = 'idle';
      }
    }
  }

  function makeRec(continuous: boolean): SpeechRecognitionLike {
    const r = new RecognitionCtor();
    r.lang = 'en-US';
    r.continuous = continuous;
    r.interimResults = false;
    r.onresult = handleResult;
    r.onerror = (e) => setStatus(`Voice error: ${e.error ?? 'unknown'}`, true);
    r.onend = handleEnd;
    return r;
  }

  function startName(): void {
    if (!masterOn || !nameWanted) return;
    clearRec();
    rec = makeRec(true);
    mode = 'name';
    try {
      rec.start();
      setStatus(`Listening for “${nameInput.value || opts.characterId}”…`);
    } catch { /* will retry via handleEnd */ }
  }

  function startPtt(): void {
    if (!masterOn) return;
    clearRec();
    rec = makeRec(false);
    mode = 'ptt';
    try { rec.start(); setStatus('Listening…'); } catch { mode = 'idle'; }
  }

  function setMaster(on: boolean): void {
    masterOn = on;
    toggleBtn.textContent = on ? '🎙 Push-to-talk ON · cloud (not PHI)' : '🎙 Enable push-to-talk';
    toggleBtn.classList.toggle('on', on);
    panel.classList.toggle('vrai-voice-open', on);
    if (on) {
      setStatus('On — hold to talk, or enable the name trigger.');
      diag.push({
        t: performance.now(), moduleId: MODULE, kind: 'warn',
        message: 'cloud voice enabled (Web Speech API; not PHI-safe — demo only)',
      });
      if (nameWanted) startName();
    } else {
      nameWanted = false;
      nameChk.checked = false;
      clearRec();
      mode = 'idle';
      setStatus('');
    }
  }

  // --- listeners ---
  const onToggle = (): void => setMaster(!masterOn);

  const onPttDown = (ev: Event): void => {
    ev.preventDefault();
    if (!masterOn) return;
    pttBtn.classList.add('active');
    startPtt();
  };
  const onPttUp = (ev: Event): void => {
    ev.preventDefault();
    pttBtn.classList.remove('active');
    if (mode === 'ptt') { try { rec?.stop(); } catch { /* noop */ } }
  };

  const onNameChange = (): void => {
    nameWanted = nameChk.checked;
    if (masterOn && nameWanted) startName();
    else if (mode === 'name') { clearRec(); mode = 'idle'; setStatus('Name trigger off.'); }
  };

  toggleBtn.addEventListener('click', onToggle);
  pttBtn.addEventListener('pointerdown', onPttDown);
  pttBtn.addEventListener('pointerup', onPttUp);
  pttBtn.addEventListener('pointerleave', onPttUp);
  pttBtn.addEventListener('pointercancel', onPttUp);
  nameChk.addEventListener('change', onNameChange);

  return {
    dispose() {
      disposed = true;
      toggleBtn.removeEventListener('click', onToggle);
      pttBtn.removeEventListener('pointerdown', onPttDown);
      pttBtn.removeEventListener('pointerup', onPttUp);
      pttBtn.removeEventListener('pointerleave', onPttUp);
      pttBtn.removeEventListener('pointercancel', onPttUp);
      nameChk.removeEventListener('change', onNameChange);
      clearRec();
      panel.remove();
    },
  };
}
