// MEDSIM V7 M51 — Patient Integrated Alarm device-side JS.
//
// Tablet UI for a bedside PIA. Four big buttons (Call Bell, Bed
// Alarm, Code Blue, Intercom). Press → POST /api/device/{sid}/event
// with type=`pia.button` + payload {action}. Server hook (see
// portal/devices/routes.py `_handle_pia_button`) routes each action:
//
//   call_bell / bed_alarm → device_event alarm.injected (M26 surfaces)
//   code_blue             → scenes.apply(enc, code.blue) — cascades
//                           through the existing alarm bus + WS push
//   intercom_request      → chart event + transcript entry
//
// The PIA also polls /api/room/alarms every 3s. When ANY code-blue
// alarm is active ANYWHERE in the room (this bed OR a sibling bed),
// the screen flashes red with the originating encounter's label — so
// students at every bed see WHERE the code is.
//
// Audio: pulls from the M49 clinical_alarms library:
//   call_bell  → 02_call_bell.wav
//   bed_alarm  → 01_bed_exit_alarm.wav
//   code_blue  → 03_code_blue.wav

(function () {
  'use strict';

  const cfg = window.PIA_CONFIG || {};
  const $ = (id) => document.getElementById(id);

  const SOUNDS = {
    call_bell:  '/static/sounds/clinical_alarms/02_call_bell.wav',
    bed_alarm:  '/static/sounds/clinical_alarms/01_bed_exit_alarm.wav',
    code_blue:  '/static/sounds/clinical_alarms/03_code_blue.wav',
  };

  // ── Audio playback (one-shot per press). ──────────────────────────
  function playSound(key) {
    const url = SOUNDS[key];
    if (!url) return;
    try {
      const a = new Audio(url);
      a.volume = 0.85;
      const p = a.play();
      if (p && typeof p.catch === 'function') p.catch(() => {});
    } catch (e) { /* ignore */ }
  }

  // ── Button press → POST device event. ─────────────────────────────
  async function pressAction(action) {
    if (!action) return;
    try {
      const r = await fetch(
        `/api/device/${encodeURIComponent(cfg.stationId)}/event`,
        {
          method: 'POST',
          headers: {'Content-Type': 'application/json'},
          body: JSON.stringify({
            type: 'pia.button',
            payload: {action, by: 'patient'},
          }),
        },
      );
      const data = await r.json().catch(() => ({}));
      const last = $('pia-last-event');
      if (last) {
        last.textContent = `${niceLabel(action)} sent · ${new Date().toLocaleTimeString()}`;
      }
      // Local sound cue mirrors what the M49 system will play on the
      // Nursing Station — gives the bedside student immediate audio
      // feedback that the press registered.
      playSound(action);
      // Flash the frame for any alarm-style press (code_blue is
      // already flashed by the cascade banner below).
      if (action !== 'intercom_request') {
        flashFrame(action);
      } else {
        flashFrame('intercom');
      }
      return data;
    } catch (err) {
      const last = $('pia-last-event');
      if (last) last.textContent = `Network error: ${err}`;
    }
  }

  function niceLabel(action) {
    return {
      call_bell:        '🔔 Call bell',
      bed_alarm:        '🛏 Bed alarm',
      code_blue:        '🚨 Code Blue',
      intercom_request: '🎙 Intercom request',
    }[action] || action;
  }

  // ── Flash the screen frame for visual alarm feedback. ─────────────
  //
  // CSS classes (`pia-flash-call-bell`, `pia-flash-bed-alarm`,
  // `pia-flash-code-blue`, `pia-flash-intercom`) drive alternating-
  // color keyframes. We clear the class after 4 seconds so the
  // screen returns to normal — except for `code_blue` where the
  // cascade-banner takes over while the alarm is still active.
  let _flashTimer = null;
  function flashFrame(kind) {
    const frame = $('pia-frame');
    if (!frame) return;
    // Remove any existing flash class so a new press restarts the
    // animation cleanly.
    frame.classList.remove(
      'pia-flash-call-bell',
      'pia-flash-bed-alarm',
      'pia-flash-code-blue',
      'pia-flash-intercom',
    );
    // force reflow so the next add() restarts the animation
    void frame.offsetWidth;
    const cls = {
      call_bell: 'pia-flash-call-bell',
      bed_alarm: 'pia-flash-bed-alarm',
      code_blue: 'pia-flash-code-blue',
      intercom:  'pia-flash-intercom',
    }[kind];
    if (!cls) return;
    frame.classList.add(cls);
    if (_flashTimer) clearTimeout(_flashTimer);
    _flashTimer = setTimeout(() => {
      frame.classList.remove(cls);
    }, 4000);
  }

  // ── Wire buttons. ──────────────────────────────────────────────────
  document.addEventListener('DOMContentLoaded', () => {
    document.querySelectorAll('[data-action]').forEach(btn => {
      btn.addEventListener('click', async () => {
        const confirmMsg = btn.dataset.confirm;
        if (confirmMsg && !window.confirm(confirmMsg)) return;
        btn.disabled = true;
        try {
          await pressAction(btn.dataset.action);
        } finally {
          // Brief lock-out so an over-zealous tap doesn't double-fire.
          setTimeout(() => { btn.disabled = false; }, 800);
        }
      });
    });
    startCascadePoll();
  });

  // ── Cascade poller: room-wide alarm awareness. ───────────────────
  //
  // Every 3s, fetch /api/room/alarms. If ANY code-blue alarm is
  // active anywhere in the room, show the cascade banner with the
  // alarm's encounter_label so this bedside knows "Code Blue at
  // Bed 2" even though THIS bed is calm. The frame also gets the
  // pia-flash-code-blue class while the cascade is active.
  //
  // M52 + M54 — Operator: "Repeat alarm sounds until cleared … the
  // sound loop for a code blue should run continuously with minimal
  // time gap". We replace the one-shot _cascadeKey dedupe with a
  // per-alarm last-played timestamp + 2.5 s cadence (M54, was 8 s in
  // M52) so the bedside hears the code-blue tone near-continuously
  // until the alarm clears — matching real bedside monitor behaviour
  // for the highest-priority alarm. Flash still re-triggers only on
  // a NEW alarm set so the screen animation doesn't restart every
  // poll.
  const CASCADE_AUDIO_REPEAT_MS = 2500;
  let _cascadeKey = '';
  const _cascadeAudioLastAt = new Map();   // alarm_id → ms timestamp
  async function pollCascade() {
    try {
      const r = await fetch('/api/room/alarms');
      if (!r.ok) return;
      const body = await r.json();
      const alarms = body.alarms || [];
      const codeBlues = alarms.filter(a => {
        const k = (a.kind || '').toLowerCase();
        return k.indexOf('code.blue') >= 0 || k.indexOf('code_blue') >= 0;
      });
      const banner = $('pia-cascade');
      const text   = $('pia-cascade-text');
      const frame  = $('pia-frame');
      if (!codeBlues.length) {
        if (banner) banner.hidden = true;
        if (frame)  frame.classList.remove('pia-cascade-active');
        _cascadeKey = '';
        _cascadeAudioLastAt.clear();
        return;
      }
      // Build a key from the active code-blue alarm ids so we only
      // re-trigger the FLASH when a NEW code blue starts.  Audio is
      // gated separately on the per-alarm last-played map below so
      // the tone keeps repeating until the alarm clears.
      const key = codeBlues.map(a => a.alarm_id).sort().join('|');
      if (banner && text) {
        banner.hidden = false;
        const locations = Array.from(new Set(
          codeBlues.map(a => a.encounter_label || 'a bed')
        )).join(', ');
        text.textContent = `CODE BLUE — ${locations}`;
      }
      if (frame) frame.classList.add('pia-cascade-active');
      if (key !== _cascadeKey) {
        _cascadeKey = key;
        flashFrame('code_blue');
      }
      // M52 — Repeating audio. Each active code-blue alarm gets its
      // own 8 s cadence — if multiple beds are coding, each tone
      // fires on its own clock. Silenced alarms skip.
      const now = Date.now();
      const activeIds = new Set();
      codeBlues.forEach(a => {
        const sid = a.alarm_id;
        if (!sid) return;
        activeIds.add(sid);
        if (a.silenced) return;
        const last = _cascadeAudioLastAt.get(sid) || 0;
        if (now - last < CASCADE_AUDIO_REPEAT_MS) return;
        _cascadeAudioLastAt.set(sid, now);
        playSound('code_blue');
      });
      // Drop ids no longer active so a re-occurrence fires immediately.
      for (const sid of Array.from(_cascadeAudioLastAt.keys())) {
        if (!activeIds.has(sid)) _cascadeAudioLastAt.delete(sid);
      }
    } catch (err) { /* ignore */ }
  }
  function startCascadePoll() {
    pollCascade();
    setInterval(pollCascade, 3000);
  }

  // Heartbeat so the operator's connected-stations roster shows the
  // PIA as online.
  setInterval(() => {
    fetch(`/api/device/${encodeURIComponent(cfg.stationId)}/heartbeat`,
          {method: 'POST'}).catch(() => {});
  }, 15000);
})();
