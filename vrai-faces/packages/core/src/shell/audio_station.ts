// FR-006 — the AUDIO-ONLY station (lite mode, `?mode=audio`).
//
// For low-cost tablets and non-patient characters: a flat static portrait + the
// COMPLETE voice loop (speech playback in the character's voice + push-to-talk),
// with NO 3D rig, NO WebGPU, NO mesh/morph model fetches. The instructor picks
// this per character (🔊 Audio-only) and the QR carries `mode=audio`.
//
// What runs: medsim_adapter (speech frames over the WS), audio_pipeline
// (playback + priming), device_voice (PTT — on-device STT, WASM path is fine on
// cheap hardware), speechConsumer with a NO-OP animation sink (visemes are
// simply discarded — there is no face to move). What never loads: renderer,
// mesh_builder, shader, MediaPipe, the face topology/morph JSONs.

import type { AnimationRuntimeModule } from '@contracts/animation_runtime';
import type { BlendshapeWeights } from '@contracts/shared';
import { diag } from '@perf/diag';

const MODULE = 'shell.audioStation';

/** Viseme/emotion sink for a station with no face — satisfies speechConsumer. */
export function noopAnimSink(): AnimationRuntimeModule {
  const sink = {
    async boot(): Promise<void> { /* nothing to animate */ },
    dispose(): void { /* nothing held */ },
    pushVisemes(): void { /* no face — discard */ },
    setEmotion(_w: BlendshapeWeights, _ms?: number): void { /* no face */ },
  };
  return sink as unknown as AnimationRuntimeModule;
}

export interface AudioStationHandle {
  /** Swap in the bound character's portrait + name once the binding lands. */
  setCharacter(opts: { name: string; role?: string; portrait?: Blob }): void;
}

/**
 * Mount the flat-portrait station UI (replaces the 3D stage entirely).
 * Idempotent DOM: builds inside #app, hides the #stage canvas.
 */
export function mountAudioStation(app: HTMLElement, characterId: string): AudioStationHandle {
  const stage = document.getElementById('stage');
  if (stage) stage.style.display = 'none';

  const wrap = document.createElement('div');
  wrap.id = 'audio-station';
  wrap.style.cssText = [
    'position:fixed', 'inset:0', 'display:flex', 'flex-direction:column',
    'align-items:center', 'justify-content:center', 'gap:14px',
    'background:radial-gradient(ellipse at center, #11131a 0%, #000 75%)',
    'color:#fff', 'font-family:-apple-system,system-ui,sans-serif', 'z-index:1',
  ].join(';');

  const img = document.createElement('img');
  img.id = 'audio-portrait';
  img.alt = 'Character portrait';
  img.style.cssText = [
    'width:min(62vw,52vh)', 'height:min(62vw,52vh)', 'object-fit:cover',
    'border-radius:50%', 'border:3px solid rgba(255,255,255,0.18)',
    'box-shadow:0 12px 60px rgba(0,0,0,0.6)', 'background:#1a1d26',
  ].join(';');

  const name = document.createElement('div');
  name.id = 'audio-name';
  name.style.cssText = 'font-size:26px;font-weight:700;letter-spacing:0.02em;';
  name.textContent = characterId;

  const role = document.createElement('div');
  role.id = 'audio-role';
  role.style.cssText = 'font-size:14px;color:#9fb3d9;';

  const badge = document.createElement('div');
  badge.style.cssText = 'font-size:12px;color:#7a8194;border:1px solid #2a2f3d;'
    + 'border-radius:99px;padding:4px 12px;';
  badge.textContent = '🔊 Audio station — hold the button below to talk';

  wrap.append(img, name, role, badge);
  app.appendChild(wrap);
  diag.push({
    t: performance.now(), moduleId: MODULE, kind: 'info',
    message: `audio-only station mounted for ${characterId} (no 3D rig)`,
  });

  let lastUrl: string | null = null;
  return {
    setCharacter(opts): void {
      name.textContent = opts.name || characterId;
      role.textContent = opts.role ?? '';
      if (opts.portrait) {
        if (lastUrl) URL.revokeObjectURL(lastUrl);
        lastUrl = URL.createObjectURL(opts.portrait);
        img.src = lastUrl;
      }
    },
  };
}
