// FR-009 H4 — survey flow state machine (mocked fetch + fake STT).
import { describe, expect, it, vi } from 'vitest';
import { createSurveyFlow, type SurveyFlow } from '../survey_station';
import type { DeviceSttHandle } from '../device_stt';

function fakeStt(transcript: string): DeviceSttHandle {
  return {
    start: vi.fn(async () => undefined),
    stopAndTranscribe: vi.fn(async () => transcript),
    isReady: () => true,
    metrics: () => ({ backend: 'portal', loadMs: 0, lastMs: 0, error: null,
                      lastStages: null, emptyReason: null }),
    dispose: () => undefined,
  };
}

const QUESTIONS = [
  { id: 'completeness', text: 'How complete, 0–10?' },
  { id: 'top_three', text: 'Three most important things?' },
];

function fetchMock(posted: Array<{ url: string; body: unknown }>): typeof fetch {
  return (async (url: string | URL | Request, init?: RequestInit) => {
    const u = String(url);
    if (u.includes('/survey/answer')) {
      posted.push({ url: u, body: JSON.parse(String(init?.body ?? '{}')) });
      return new Response(JSON.stringify({ ok: true }), { status: 200 });
    }
    if (u.includes('/survey')) {
      return new Response(JSON.stringify({ ok: true, mode: 'offgoing', questions: QUESTIONS }),
                         { status: 200 });
    }
    return new Response('{}', { status: 404 });
  }) as unknown as typeof fetch;
}

async function drive(flow: SurveyFlow): Promise<void> { await flow.load(); }

describe('survey flow (H4)', () => {
  it('loads questions then walks PTT → review → confirm to the end', async () => {
    const posted: Array<{ url: string; body: unknown }> = [];
    const flow = createSurveyFlow({
      apiBase: 'https://h', characterId: 'P-040', scenarioId: 's',
      stt: fakeStt('Eight, I covered the meds.'), fetchFn: fetchMock(posted),
    });
    await drive(flow);
    expect(flow.state().phase).toBe('ready');
    expect(flow.state().total).toBe(2);

    // Q1: press → release → review → confirm.
    await flow.press(); expect(flow.state().phase).toBe('recording');
    await flow.release();
    expect(flow.state().phase).toBe('review');
    expect(flow.state().answer).toBe('Eight, I covered the meds.');
    await flow.confirm();
    expect(flow.state().index).toBe(1);
    expect(flow.state().phase).toBe('ready');

    // Q2: answer → confirm → done.
    await flow.press(); await flow.release(); await flow.confirm();
    expect(flow.state().phase).toBe('done');

    // Both answers were POSTed with their question ids.
    expect(posted.map((p) => (p.body as { q: string }).q)).toEqual(['completeness', 'top_three']);
    expect((posted[0]!.body as { text: string }).text).toBe('Eight, I covered the meds.');
  });

  it('redo discards the answer and returns to ready', async () => {
    const flow = createSurveyFlow({
      apiBase: 'https://h', characterId: 'P-040', scenarioId: 's',
      stt: fakeStt('um, not sure'), fetchFn: fetchMock([]),
    });
    await drive(flow);
    await flow.press(); await flow.release();
    expect(flow.state().phase).toBe('review');
    flow.redo();
    expect(flow.state().phase).toBe('ready');
    expect(flow.state().answer).toBe('');
  });

  it('surfaces an error when the survey endpoint says no handoff', async () => {
    const fetchErr = (async () =>
      new Response(JSON.stringify({ ok: false, error: 'no handoff in progress' }),
                   { status: 409 })) as unknown as typeof fetch;
    const flow = createSurveyFlow({
      apiBase: 'https://h', characterId: 'P-040', scenarioId: 's',
      stt: fakeStt(''), fetchFn: fetchErr,
    });
    await drive(flow);
    expect(flow.state().phase).toBe('error');
    expect(flow.state().error).toContain('no handoff');
  });

  it('confirm is a no-op without an answer (cannot skip a question silently)', async () => {
    const posted: Array<{ url: string; body: unknown }> = [];
    const flow = createSurveyFlow({
      apiBase: 'https://h', characterId: 'P-040', scenarioId: 's',
      stt: fakeStt(''), fetchFn: fetchMock(posted),
    });
    await drive(flow);
    await flow.confirm();                 // no answer yet
    expect(flow.state().index).toBe(0);
    expect(posted).toHaveLength(0);
  });
});
