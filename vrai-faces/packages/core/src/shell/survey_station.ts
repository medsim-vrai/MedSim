// FR-009 H4 — post-handoff verbal survey station. After the handoff the trainee
// answers ~6 questions by VOICE; each answer is transcribed (same room-STT path
// as the audio station) and POSTed to the portal. No score is shown here — the
// survey is FORMATIVE and the instructor sees the perception-vs-performance
// comparison in the debrief (H5). Audio never leaves the room (ADR-0038).

import { createDeviceStt, type DeviceSttHandle } from './device_stt';

export interface SurveyQuestion { id: string; text: string; }
export type SurveyPhase =
  | 'loading' | 'error' | 'ready' | 'recording' | 'review' | 'saving' | 'done';

export interface SurveyFlowDeps {
  apiBase: string;
  characterId: string;
  scenarioId: string;
  token?: string;
  stt: DeviceSttHandle;
  fetchFn?: typeof fetch;
}

export interface SurveyFlowState {
  phase: SurveyPhase;
  index: number;          // current question index
  total: number;
  question: SurveyQuestion | null;
  answer: string;         // the transcribed answer awaiting confirm
  error: string;
}

export interface SurveyFlow {
  state(): SurveyFlowState;
  load(): Promise<void>;
  press(): Promise<void>;     // PTT down — begin capture
  release(): Promise<void>;   // PTT up — transcribe → review
  confirm(): Promise<void>;   // accept the answer → POST → next
  redo(): void;               // discard the answer → re-record
  onChange(cb: () => void): void;
}

function base(b: string): string { return b.replace(/\/+$/, ''); }

function surveyUrl(d: SurveyFlowDeps): string {
  const q = new URLSearchParams();
  q.set('scenario', d.scenarioId);
  q.set('character', d.characterId);
  if (d.token) q.set('token', d.token);
  return `${base(d.apiBase)}/api/face/${encodeURIComponent(d.characterId)}/survey?${q.toString()}`;
}

function answerUrl(d: SurveyFlowDeps): string {
  const q = new URLSearchParams();
  q.set('scenario', d.scenarioId);
  q.set('character', d.characterId);
  if (d.token) q.set('token', d.token);
  return `${base(d.apiBase)}/api/face/${encodeURIComponent(d.characterId)}/survey/answer?${q.toString()}`;
}

/** The survey state machine — pure of the DOM, so it unit-tests with a mocked
 *  fetch + a fake STT handle. */
export function createSurveyFlow(deps: SurveyFlowDeps): SurveyFlow {
  const doFetch = deps.fetchFn ?? fetch;
  let questions: SurveyQuestion[] = [];
  let index = 0;
  let phase: SurveyPhase = 'loading';
  let answer = '';
  let error = '';
  const listeners: Array<() => void> = [];
  const emit = (): void => { for (const cb of listeners) cb(); };

  function state(): SurveyFlowState {
    return {
      phase, index, total: questions.length,
      question: questions[index] ?? null, answer, error,
    };
  }

  async function load(): Promise<void> {
    phase = 'loading'; error = ''; emit();
    try {
      const r = await doFetch(surveyUrl(deps));
      const j = (await r.json().catch(() => null)) as
        { ok?: boolean; questions?: SurveyQuestion[]; error?: string } | null;
      if (!r.ok || !j || j.ok !== true || !j.questions?.length) {
        phase = 'error'; error = j?.error ?? 'no survey available'; emit(); return;
      }
      questions = j.questions; index = 0; answer = ''; phase = 'ready'; emit();
    } catch {
      phase = 'error'; error = 'could not reach the portal'; emit();
    }
  }

  async function press(): Promise<void> {
    if (phase !== 'ready' && phase !== 'review') return;
    answer = ''; phase = 'recording'; emit();
    await deps.stt.start();
  }

  async function release(): Promise<void> {
    if (phase !== 'recording') return;
    const text = await deps.stt.stopAndTranscribe();
    answer = text; phase = 'review'; emit();
  }

  async function confirm(): Promise<void> {
    if (phase !== 'review' || !answer) return;
    const cur = questions[index];
    if (!cur) return;
    phase = 'saving'; emit();
    try {
      await doFetch(answerUrl(deps), {
        method: 'POST',
        headers: { 'content-type': 'application/json' },
        body: JSON.stringify({ q: cur.id, text: answer }),
      });
    } catch { /* best-effort — never strand the trainee mid-survey */ }
    index += 1; answer = '';
    phase = index >= questions.length ? 'done' : 'ready';
    emit();
  }

  function redo(): void {
    if (phase === 'review') { answer = ''; phase = 'ready'; emit(); }
  }

  function onChange(cb: () => void): void { listeners.push(cb); }

  return { state, load, press, release, confirm, redo, onChange };
}

const STYLE_ID = 'vrai-survey-style';
const STYLE_CSS = `
.vrai-survey { position: fixed; inset: 0; display: flex; flex-direction: column;
  align-items: center; justify-content: center; gap: 18px; padding: 24px;
  background: radial-gradient(circle at 50% 35%, #16243f, #0a1424);
  color: #fff; font: 17px -apple-system, system-ui, sans-serif; text-align: center; }
.vrai-survey .q-count { font-size: 13px; color: #9fb6e0; letter-spacing: .04em; }
.vrai-survey .q-text { font-size: 21px; font-weight: 600; max-width: 640px; line-height: 1.4; }
.vrai-survey .ans { min-height: 40px; max-width: 640px; font-size: 16px; color: #d8e6ff;
  background: rgba(255,255,255,.08); border-radius: 12px; padding: 10px 14px; }
.vrai-survey button { height: 52px; padding: 0 26px; border: none; border-radius: 14px;
  background: rgba(255,255,255,.14); color: #fff; font-size: 16px; font-weight: 600;
  cursor: pointer; touch-action: none; }
.vrai-survey button.ptt { background: #2f7d5b; min-width: 220px; }
.vrai-survey button.ptt.active { background: #b5532a; }
.vrai-survey .row { display: flex; gap: 12px; flex-wrap: wrap; justify-content: center; }
.vrai-survey .done { font-size: 22px; font-weight: 700; }
.vrai-survey .muted { font-size: 14px; color: #9fb6e0; }
`;

function ensureStyle(): void {
  if (document.getElementById(STYLE_ID)) return;
  const s = document.createElement('style');
  s.id = STYLE_ID; s.textContent = STYLE_CSS;
  document.head.appendChild(s);
}

export interface SurveyStationOpts {
  apiBase: string;
  characterId: string;
  scenarioId: string;
  token?: string;
}

export interface SurveyStationHandle { dispose(): void; }

/** Mount the full survey UI: a question card with a hold-to-talk button, a
 *  transcript review (keep / re-record), and a closing "see your instructor". */
export function mountSurveyStation(
  container: HTMLElement, opts: SurveyStationOpts,
): SurveyStationHandle {
  ensureStyle();
  const stt = createDeviceStt({
    apiBase: opts.apiBase, characterId: opts.characterId, scenarioId: opts.scenarioId,
    ...(opts.token ? { token: opts.token } : {}),
  });
  const flow = createSurveyFlow({
    apiBase: opts.apiBase, characterId: opts.characterId, scenarioId: opts.scenarioId,
    ...(opts.token ? { token: opts.token } : {}),
    stt,
  });

  const panel = document.createElement('div');
  panel.className = 'vrai-survey';
  container.appendChild(panel);

  function render(): void {
    const s = flow.state();
    if (s.phase === 'loading') { panel.innerHTML = '<div class="muted">Loading your survey…</div>'; return; }
    if (s.phase === 'error') {
      panel.innerHTML = `<div class="q-text">Survey unavailable</div><div class="muted">${s.error}</div>`;
      return;
    }
    if (s.phase === 'done') {
      panel.innerHTML = '<div class="done">✓ Handoff complete</div>'
        + '<div class="muted">Thank you — please see your instructor for the debrief.</div>';
      return;
    }
    const q = s.question;
    const counter = `Question ${s.index + 1} of ${s.total}`;
    const talkLabel = s.phase === 'recording' ? '● Listening — release to stop' : '🎤 Hold to answer';
    let controls = `<button class="ptt${s.phase === 'recording' ? ' active' : ''}" id="ptt">${talkLabel}</button>`;
    if (s.phase === 'review') {
      controls = '<div class="row">'
        + '<button id="confirm">✓ Keep answer</button>'
        + '<button id="redo">↺ Re-record</button></div>';
    }
    if (s.phase === 'saving') controls = '<div class="muted">Saving…</div>';
    panel.innerHTML =
      `<div class="q-count">${counter}</div>`
      + `<div class="q-text">${q ? q.text : ''}</div>`
      + (s.answer ? `<div class="ans">“${s.answer}”</div>` : '<div class="ans muted">Your answer appears here.</div>')
      + controls;

    const ptt = panel.querySelector<HTMLButtonElement>('#ptt');
    if (ptt) {
      ptt.onpointerdown = (e) => { e.preventDefault(); void flow.press(); };
      ptt.onpointerup = (e) => { e.preventDefault(); void flow.release(); };
      ptt.onpointercancel = () => { void flow.release(); };
    }
    panel.querySelector<HTMLButtonElement>('#confirm')?.addEventListener('click', () => void flow.confirm());
    panel.querySelector<HTMLButtonElement>('#redo')?.addEventListener('click', () => flow.redo());
  }

  flow.onChange(render);
  render();
  void flow.load();

  return {
    dispose(): void {
      try { stt.dispose(); } catch { /* noop */ }
      panel.remove();
    },
  };
}
