// V6 — Device station client. One file, no framework. The page shell
// (device_app.html) exposes <body data-...> attributes; this script:
//
//   1. Fetches /api/device/{station_id}/bootstrap to get the SVG skin, the
//      spec.json, the audio URLs, the current state fold, and the
//      ControlSession state (running | paused | ended).
//   2. Mounts the SVG inline into #device-skin, then walks the DOM binding
//      tap/click handlers to every element whose id matches the spec's
//      control map (hardkeys, softkeys, touch targets).
//   3. Opens a WebSocket to /ws/device/{station_id} and processes:
//        type=fold         — repaint the state fold (re-render screen fields)
//        type=inject       — instructor-fired alarm; play tone, animate badge
//        type=assign       — character reassignment; refresh patient strip
//        type=state        — pause/resume; halt audio, gate input, show banner
//        type=rejected     — paused-input feedback
//   4. Falls back to HTTP POST /api/device/{station_id}/event if the WS is
//      down (auto-reconnect with exponential backoff).
//
// State is reconstructed from the server's fold on every message — we never
// keep client-side derived state that the server doesn't see, so pause /
// resume is exact and tablet refresh "just works".

(function () {
  // V6.1.2 — server now projects live volume/time in the engine fold itself,
  // so the device display advances even when the client-side interpolator
  // can't run (e.g. cached old JS, very slow tablet). Bumping the build
  // marker confirms on the tablet which JS is actually executing.
  const DEVICE_JS_BUILD = 'v6.2.3';   // FR-012 — vent waveforms grow; controls drop lower
  console.log('[MEDSIM device] booting build', DEVICE_JS_BUILD);
  const body = document.body;
  const JOIN  = body.dataset.joinCode;
  const STN   = body.dataset.stationId;
  const KIND  = body.dataset.deviceKind;
  const MODEL = body.dataset.deviceModel;
  const IS_MONITOR = (KIND === 'telemetry_monitor');   // FR-012 advanced device
  const IS_VENTILATOR = (KIND === 'ventilator');
  const IS_VENT_MONITOR = (KIND === 'vent_monitor');
  const IS_VENT = IS_VENTILATOR || IS_VENT_MONITOR;

  const $loading = document.getElementById('device-loading');
  const $skin    = document.getElementById('device-skin');
  const $paused  = document.getElementById('paused-banner');
  const $audio   = document.getElementById('device-audio');

  let SPEC = null;             // spec.json
  let STATION = null;          // station row {id, label, device_kind, …}
  let CHARACTERS = [];         // V6.1.6 — cabinets: [{character_id,name,mrn,location_label,medications:[...]}]
  let ASSIGNED_CHAR_ID = null; // V6.1.7 — id of the character the instructor has assigned to THIS device
  let CHECKLIST_DISMISSED = false; // user tapped X — don't auto-show until next assignment change
  let AUDIO_URLS = {};         // tone_id → /static/devices/audio/.../tone.wav
  let STATE = null;            // last engine fold
  let PHYS = null;             // FR-012 — last physiology snapshot (advanced devices)
  let VENT = null;             // FR-012 — last ventilator / vent-monitor view
  let SESSION_STATE = 'running';
  let WS = null;
  let WS_BACKOFF = 1000;
  const CURRENTLY_LOOPING = new Set();   // tone_ids currently looping locally

  // ── Bootstrap ───────────────────────────────────────────────────────
  async function bootstrap() {
    try {
      const r = await fetch(`/api/device/${STN}/bootstrap`);
      if (!r.ok) {
        // V6 — extract the JSON error body so the operator sees a
        // useful message instead of just "bootstrap 500".
        let detail = `bootstrap ${r.status}`;
        try {
          const errBody = await r.json();
          if (errBody.detail) detail = errBody.detail;
        } catch (e) { /* not JSON */ }
        console.error('[MEDSIM device] bootstrap failed:', r.status, detail);
        throw new Error(detail);
      }
      const b = await r.json();
      SPEC = b.spec || {};
      STATION = b.station || {};
      CHARACTERS = b.characters || [];     // V6.1.6 — med-cart roster
      ASSIGNED_CHAR_ID = b.character_id || null;   // V6.1.7 — instructor-assigned patient
      // #2 — default the MAR/screen patient up front so scr-patient shows the
      // real patient on first paint: prefer the instructor-assigned patient,
      // else the only linked patient (single-bed cart).
      if (SELECTED_CHAR_ID == null) {
        if (ASSIGNED_CHAR_ID) SELECTED_CHAR_ID = ASSIGNED_CHAR_ID;
        else if (CHARACTERS.length === 1) SELECTED_CHAR_ID = CHARACTERS[0].character_id;
      }
      AUDIO_URLS = b.audio_urls || {};
      STATE = b.state || {};
      PHYS = b.physiology || null;         // FR-012 — advanced-device physiology
      VENT = b.vent || null;               // FR-012 — ventilator / vent-monitor view
      SESSION_STATE = b.session_state || 'running';
      mountSkin(b.skin_svg || '');
      renderFold(STATE);
      applySessionState(SESSION_STATE);
      if (IS_MONITOR) startMonitor();      // FR-012 D3b — live vitals + waveforms
      if (IS_VENT) startVent();            // FR-012 D5b — vent display + controls
      $loading.hidden = true;
      _ensureFsButton();                   // FR-012 — fullscreen re-entry affordance
      // Show the audio-unlock overlay immediately on iOS — one tap there
      // primes every alarm tone so async inject .play() calls succeed
      // later. On desktop Chrome the autoplay policy is more permissive,
      // but the overlay still appears once per page load and the first
      // tap on the chassis SVG also dismisses it (see onControlTap).
      showAudioUnlockOverlay();
      connectWS();
    } catch (e) {
      $loading.textContent = `Bootstrap failed: ${e.message}. Retrying in 3s…`;
      setTimeout(bootstrap, 3000);
    }
  }

  // ── SVG skin mount + input binding ──────────────────────────────────
  function mountSkin(svgText) {
    $skin.innerHTML = svgText;
    const svg = $skin.querySelector('svg');
    if (!svg) return;
    // Bind a tap handler on every element whose id starts with a known
    // control prefix. The spec's screens / control map declares which IDs
    // exist; we don't require it to enumerate every one (the skin is the
    // source of truth for what exists on the chassis).
    const CONTROL_PREFIXES = ['key-', 'softkey-', 'btn-', 'touch-'];
    // V6 — also bind any screen field declared programmable in spec.json
    // so students can tap a field on the chassis to focus it for editing.
    const progFieldIds = new Set(
      ((SPEC.programming && SPEC.programming.fields) || []).map((f) => f.id)
    );
    svg.querySelectorAll('[id]').forEach((el) => {
      const id = el.getAttribute('id');
      const isControl    = CONTROL_PREFIXES.some((p) => id.startsWith(p));
      const isProgField  = progFieldIds.has(id);
      if (isControl || isProgField) {
        el.classList.add('svg-hit');
        if (isProgField) el.classList.add('prog-field');
        el.addEventListener('click', (e) => onControlTap(id, el));
        el.addEventListener('touchstart', (e) => { e.preventDefault(); onControlTap(id, el); }, {passive: false});
      }
    });
  }

  // ── Live display interpolation ──────────────────────────────────────
  // When a pump is running, the engine only emits pump.tick events when
  // the device calls run_tick (on user activity). Between those events,
  // we want scr-vi (volume infused) to *grow* and scr-time (time
  // remaining) to *count down* on screen — exactly like a real pump.
  // Approach: capture the moment renderFold was called as STATE_TS,
  // remember rate + infused, then on each 1-second tick compute the
  // projected value: infused_now = infused_at_state + rate * elapsed.
  // Cap at VTBI. No server round-trip. The next real fold (from a
  // user tap, alarm, or operator time-advance) re-anchors the values.
  let STATE_TS = 0;                                // ms of last *anchor*
  // V6.1.1 — Bug: the HTTP polling fallback (and any redundant WS fold)
  // re-anchored STATE_TS every 2s, so the interpolator's elapsed_h was
  // always ≤ 2 s and the on-screen time-remaining looked frozen at the
  // minute resolution (a real Alaris ticks once per ~36 s at 100 mL/hr).
  // Fix: keep a signature of the engine's TRUE infusion state and only
  // re-anchor when it changes (operator advance, programming change,
  // pump.tick, completion). Idle polls echoing the same numbers leave
  // STATE_TS alone, so elapsed_h keeps growing and the display ticks.
  let ENGINE_SIG = '';                             // signature of last fold
  function _engineSignature(s) {
    if (!s) return '';
    if (s.channels) {
      // pump_iv — encode each channel's running/rate/infused
      const parts = Object.keys(s.channels).sort().map((k) => {
        const c = s.channels[k];
        return `${k}:${c.running ? 'R' : '-'}:${c.rate_ml_hr || 0}:${c.infused_ml || 0}:${c.vtbi_ml || 0}`;
      });
      return parts.join('|');
    }
    // pump_enteral — single-channel
    return `${s.running ? 'R' : '-'}:${s.rate_ml_hr || 0}:${s.fed_ml || 0}:${s.volume_ml || 0}:${s.mode || ''}`;
  }
  function _liveInfused(channelOrState, vtbiCap) {
    if (!channelOrState || !STATE_TS) return null;
    const baseInfused = channelOrState.infused_ml ?? channelOrState.fed_ml;
    const rate        = channelOrState.rate_ml_hr;
    if (baseInfused == null || rate == null) return null;
    if (!channelOrState.running) return baseInfused;   // not infusing → frozen
    if (SESSION_STATE !== 'running')   return baseInfused;
    const elapsed_h   = (Date.now() - STATE_TS) / 3.6e6;
    const projected   = baseInfused + rate * elapsed_h;
    return Math.min(projected, vtbiCap || projected);
  }
  function _liveOMNIFed(state) {
    if (!state || !STATE_TS) return null;
    const baseFed = state.fed_ml;
    const rate    = state.rate_ml_hr;
    if (baseFed == null || rate == null) return null;
    if (!state.running)               return baseFed;
    if (SESSION_STATE !== 'running')  return baseFed;
    const elapsed_h = (Date.now() - STATE_TS) / 3.6e6;
    return Math.min(baseFed + rate * elapsed_h, state.volume_ml || (baseFed + rate * elapsed_h));
  }
  function _fmtTimeRemaining(volRemain, rate) {
    if (rate == null || rate <= 0 || volRemain == null || volRemain <= 0) return null;
    const totalMin = Math.round((volRemain / rate) * 60);
    const h = Math.floor(totalMin / 60);
    const m = totalMin % 60;
    return h > 0 ? `${h}h ${String(m).padStart(2, '0')}m` : `${m} min`;
  }
  function applyLiveDisplay() {
    if (!STATE || !$skin) return;
    const svg = $skin.querySelector('svg');
    if (!svg) return;
    if (KIND === 'pump_iv' && STATE.channels) {
      // For each channel, update scr-vi + (optional) scr-time. v6.0 SVGs
      // share field IDs across channels; we pick the first running channel
      // or fall back to channel A.
      const channels = STATE.channels || {};
      const ch = Object.values(channels).find((c) => c.running)
              || channels.A || Object.values(channels)[0];
      if (!ch) return;
      const vi = _liveInfused(ch, ch.vtbi_ml);
      const vie = svg.querySelector('#scr-vi');
      if (vie && vi != null) vie.textContent = String(Math.round(vi));
      const remain = (ch.vtbi_ml || 0) - (vi || 0);
      const tte = svg.querySelector('#scr-time');
      const t = _fmtTimeRemaining(remain, ch.rate_ml_hr);
      if (tte && t) tte.textContent = t;
    } else if (KIND === 'pump_enteral') {
      const fed = _liveOMNIFed(STATE);
      const vie = svg.querySelector('#scr-vi') || svg.querySelector('#scr-fed');
      if (vie && fed != null) vie.textContent = String(Math.round(fed));
      const remain = (STATE.volume_ml || 0) - (fed || 0);
      const tte = svg.querySelector('#scr-time');
      const t = _fmtTimeRemaining(remain, STATE.rate_ml_hr);
      if (tte && t) tte.textContent = t;
    } else if (KIND === 'cabinet') {
      // V6.1.4 — scr-clock ticks the wall-clock every second on cabinet
      // skins so the display feels alive (matches a real Pyxis / Omnicell).
      const clk = svg.querySelector('#scr-clock');
      if (clk) {
        const d = new Date();
        const hh = String(d.getHours()).padStart(2, '0');
        const mm = String(d.getMinutes()).padStart(2, '0');
        clk.textContent = `${hh}:${mm}`;
      }
    }
  }
  setInterval(applyLiveDisplay, 1000);

  // ── State fold rendering ────────────────────────────────────────────
  function renderFold(state) {
    if (!state) return;
    STATE = state;
    // V6.1.1 — only re-anchor STATE_TS when the engine's authoritative
    // infusion numbers actually changed. Polling echoes (or redundant WS
    // folds) keep the previous anchor so the local interpolator's
    // elapsed_h keeps accumulating and the displayed VI / time-remaining
    // continues to advance second-by-second.
    const sig = _engineSignature(state);
    if (sig !== ENGINE_SIG) {
      STATE_TS = Date.now();
      ENGINE_SIG = sig;
    }
    const svg = $skin.querySelector('svg');
    if (!svg) return;

    // 1. Screen background colour (enteral pumps use this heavily).
    if (SPEC.screen_color_by_state && state.screen) {
      const color = SPEC.screen_color_by_state[state.screen];
      const screenBg = svg.querySelector('#screen-bg');
      if (color && screenBg) screenBg.setAttribute('fill', color);
    }

    // 2. Generic field replacement. For any scr-<field> text node in the
    // skin, if state has a same-named key (e.g. scr-rate → state.rate_ml_hr
    // or state.channels.A.rate_ml_hr), update its text content.
    svg.querySelectorAll('text[id^="scr-"]').forEach((t) => {
      const id = t.getAttribute('id').slice(4);   // strip "scr-"
      const val = lookupField(state, id);
      if (val !== undefined && val !== null) t.textContent = String(val);
    });

    // 3. LED indicators: led-<name>. Recolour by alarm tier or running flag.
    svg.querySelectorAll('[id^="led-"]').forEach((led) => {
      const name = led.getAttribute('id').slice(4);
      led.setAttribute('fill', ledColour(name, state));
    });

    // 4. Active alarms — visually flag the chassis AND drive audio loops.
    // An alarm record carries `silenced_until` (epoch seconds). Real pumps
    // mute audio on Silence but keep the red visual until Clear; we mirror
    // that — chassis flashes if ANY alarm is active, but per-tone audio
    // honours the silence window and auto-resumes when it expires.
    const alarmsArr = (state.active_alarms || []).map(
      (a) => typeof a === 'string' ? {tone: a, silenced_until: 0} : a);
    if (alarmsArr.length) {
      svg.classList.add('alarm-active');
      const nowSec = Date.now() / 1000;
      const audible = new Set(
        alarmsArr.filter((a) => (a.silenced_until || 0) <= nowSec)
                 .map((a) => a.tone));
      const allWanted = new Set(alarmsArr.map((a) => a.tone));
      // Stop loops for cleared alarms or currently-silenced alarms.
      for (const tone of [...CURRENTLY_LOOPING]) {
        if (!audible.has(tone)) stopLoop(tone);
      }
      // Start loops for audible alarms.
      // Audio loops only play in 'running' state. 'configured' (pre-start)
      // and 'paused' both silence the device; 'ended' too.
      const playableState = SESSION_STATE === 'running';
      for (const tone of audible) {
        if (!CURRENTLY_LOOPING.has(tone) && playableState) {
          startLoop(tone);
        }
      }
      // If any alarm is silenced, schedule a re-render at the soonest
      // un-silence so the loop resumes automatically. Without this the
      // user would have to tap something to trigger the next render.
      if (allWanted.size > audible.size) {
        scheduleSilenceExpiryRender(alarmsArr, nowSec);
      }
    } else {
      svg.classList.remove('alarm-active');
      for (const tone of [...CURRENTLY_LOOPING]) stopLoop(tone);
    }
    // V6.1.6 — cabinets: re-render the patient checklist so newly-
    // administered meds get their ✓ badge + timestamp.
    if (KIND === 'cabinet') renderCabinetChecklist();
  }

  let _silenceExpiryTimer = null;
  function scheduleSilenceExpiryRender(alarms, nowSec) {
    if (_silenceExpiryTimer) clearTimeout(_silenceExpiryTimer);
    let soonest = Infinity;
    for (const a of alarms) {
      const u = a.silenced_until || 0;
      if (u > nowSec && u < soonest) soonest = u;
    }
    if (soonest === Infinity) return;
    const ms = Math.max(200, Math.ceil((soonest - nowSec) * 1000) + 50);
    _silenceExpiryTimer = setTimeout(() => { renderFold(STATE); }, ms);
  }

  function lookupField(state, key) {
    // 1. Spec-declared programming field → engine attribute. Authoritative
    // map: scr-rate → state.rate_ml_hr (or state.channels.A.rate_ml_hr
    // when per_channel). Without this, fields show the SVG's default
    // text and never reflect programming changes.
    const fields = (SPEC.programming && SPEC.programming.fields) || [];
    const fid = 'scr-' + key;
    const f   = fields.find((x) => x.id === fid);
    if (f) {
      if (f.per_channel && state.channels) {
        const ch = f.default_channel || PROG.channel || 'A';
        const c  = state.channels[ch];
        if (c && c[f.attribute] !== undefined) return c[f.attribute];
      }
      if (state[f.attribute] !== undefined) return state[f.attribute];
    }
    // 1b. V6.1.3 — common IV-pump per-channel screen fields the spec
    // doesn't bother to declare individually (drug name, channel letter,
    // dose / dose unit, running status). Without this, pressing
    // pump.program would update the engine state + transcript but the
    // chassis would keep showing the prior drug name forever. Pick the
    // channel the user is currently focused on (PROG.channel) so the
    // screen mirrors the just-programmed channel.
    if (KIND === 'pump_iv' && state.channels) {
      // Pick a channel: PROG.channel (the one the user is interacting with)
      // wins; else the running channel; else the spec default; else 'A'.
      // Mirrors a real Alaris where the screen shows the active or last-
      // touched module.
      const runningCh = Object.keys(state.channels).find(
        (k) => state.channels[k] && state.channels[k].running);
      const ch = PROG.channel || runningCh
              || (SPEC.programming && SPEC.programming.default_channel) || 'A';
      const c  = state.channels[ch];
      if (c) {
        if (key === 'drug') {
          // Empty drug → blank the field (avoid lingering "Norepinephrine"
          // from a previous program). Real pumps clear the drug line when
          // a Basic Infusion (no drug library) is programmed.
          return c.drug_label || c.drug_code || '';
        }
        if (key === 'channel') return ch;
        if (key === 'dose') {
          if (c.dose == null) return '';
          return c.dose_unit ? `${c.dose} ${c.dose_unit}` : String(c.dose);
        }
        if (key === 'status') {
          if (c.running) return 'INFUSING';
          if (c.paused)  return 'PAUSED';
          if (c.vtbi_ml > 0) return 'PROGRAMMED';
          return 'IDLE';
        }
      }
    }
    // 1c. V6.1.4 — enteral pump per-screen fields. The OMNI / Joey /
    // EnteraLite / Compat Ella / Sentinel skins use different IDs for
    // the same underlying state (volume_ml, fed_ml, flush_volume_ml,
    // mode, running). Map them all centrally so each skin re-uses the
    // engine without needing per-model JS.
    if (KIND === 'pump_enteral' && state) {
      if (key === 'vtbi' || key === 'volume') {
        return state.volume_ml != null ? Math.round(state.volume_ml) : '';
      }
      if (key === 'flush') {
        return state.flush_volume_ml != null ? Math.round(state.flush_volume_ml) : '';
      }
      if (key === 'mode') return state.mode || '';
      if (key === 'dose') return '';   // enteral has no dose concept
      if (key === 'run')  return state.running ? 'RUN' : 'STOP';
      if (key === 'drug') return '';   // enteral has no drug library
      if (key === 'status') {
        if (state.completed) return 'COMPLETE';
        if (state.running)   return 'FEEDING';
        if (state.paused)    return 'PAUSED';
        if (state.volume_ml > 0) return 'PROGRAMMED';
        return 'IDLE';
      }
    }
    // 1d. V6.1.4 — cabinet screen fields. Pyxis et al. share IDs:
    //   scr-patient, scr-med, scr-loc, scr-clock.
    // patient is handled in step 5 below; med and loc here. clock is
    // refreshed by applyLiveDisplay every second.
    if (KIND === 'cabinet' && state) {
      if (key === 'med') {
        const mid = state.selected_med;
        if (!mid) return '';
        const meds = state.medications || {};
        const m = meds[mid];
        return (m && (m.label || m.name)) || mid;
      }
      if (key === 'loc') return (STATION && STATION.label) || '';
      if (key === 'user') return state.session_user || '';
    }
    // 2. Direct property.
    if (key in state) return state[key];
    // 3. snake-case key → camelCase fallback.
    const camel = key.replace(/-([a-z])/g, (_, c) => c.toUpperCase());
    if (camel in state) return state[camel];
    // 4. Pump channel shorthand: scr-rate-a → state.channels.A.rate_ml_hr
    const chMatch = key.match(/^(.+)-([a-zA-Z])$/);
    if (chMatch && state.channels) {
      const [, prop, ch] = chMatch;
      const c = state.channels[ch.toUpperCase()];
      if (c) {
        const cand = `${prop.replace(/-/g, '_')}_ml_hr`;
        if (cand in c) return c[cand];
        if (prop in c) return c[prop];
      }
    }
    // 5. Cabinet shorthand.
    if (key === 'patient') {
      // HIPAA: the cabinet SCREEN never shows a patient name — the skin's
      // "MARTIN, ELENA" placeholder is blanked. The real name appears only in the
      // MAR overlay, and only when the scenario is running + a patient is picked.
      return '';
    }
    if (key === 'user'    && state.session_user) return state.session_user;
    return undefined;
  }

  function ledColour(name, state) {
    // Active alarm → red. Same on every device.
    if (name === 'alarm' && state.active_alarms && state.active_alarms.length) return '#D7382E';
    // Generic run indicator — green if anything is infusing/feeding.
    if (name === 'run') {
      if (state.channels) {
        return Object.values(state.channels).some((c) => c.running) ? '#3DA35D' : '#5b6470';
      }
      // Enteral pumps have no channels dict — state.running is top-level.
      return state.running ? '#3DA35D' : '#5b6470';
    }
    if (name === 'battery' && state.battery_warning) {
      return state.battery_warning === 'depleted' ? '#D7382E' : '#E6A032';
    }
    // AC indicator — green if battery isn't depleted (mains simulated as
    // present). Matches the visual on a real pump that sits idle but on
    // the wall.
    if (name === 'ac') {
      return state.battery_warning === 'depleted' ? '#5b6470' : '#3DA35D';
    }
    // Per-channel run LEDs: led-ch-a → state.channels.A.running.
    const chMatch = name.match(/^ch-([a-z])$/);
    if (chMatch && state.channels) {
      const c = state.channels[chMatch[1].toUpperCase()];
      return (c && c.running) ? '#3DA35D' : '#5b6470';
    }
    // Cabinet online LED — green whenever the device successfully booted
    // (we have a valid STATE).
    if (name === 'online' && KIND === 'cabinet') return '#3DA35D';
    // Caution / info / line-check — model-specific advisories. Default
    // off; concrete engines can override later.
    return '#5b6470';
  }

  // ── Audio playback ──────────────────────────────────────────────────
  // We hold one HTMLAudioElement per actively looping tone. One-shots use
  // the shared #device-audio element.
  //
  // iOS Chrome (and Safari) blocks Audio().play() unless the element has
  // been "unlocked" by a prior play() call inside a real user gesture.
  // Alarm injection arrives async (via WebSocket message), so the element
  // would be silently blocked. The audio-unlock overlay below sits over
  // the device until the user taps once; on tap we iterate through every
  // known tone, create+play+pause each Audio element with the real source
  // URL, which leaves them in the "user-activated" state. Subsequent
  // programmatic .play() on any of them then succeeds even from async
  // contexts (alarm inject, fold-on-poll, anything).
  const LOOP_NODES = new Map();         // tone_id → HTMLAudioElement
  let AUDIO_UNLOCKED = false;

  function _audioFor(tone) {
    let el = LOOP_NODES.get(tone);
    if (!el) {
      el = new Audio(AUDIO_URLS[tone]);
      el.preload = 'auto';
      LOOP_NODES.set(tone, el);
    }
    return el;
  }

  function unlockAudio() {
    // Called inside a user-gesture handler. Prime every known tone so
    // subsequent async .play() calls succeed under iOS autoplay rules.
    if (AUDIO_UNLOCKED) return Promise.resolve();
    _enterFullscreen();   // FR-012 — bedside device goes chrome-less on the first tap
    const tones = Object.keys(AUDIO_URLS || {});
    const primes = tones.map((tone) => {
      const el = _audioFor(tone);
      el.src = AUDIO_URLS[tone];   // make sure src is set
      el.muted = true;
      return el.play().then(() => {
        el.pause();
        el.currentTime = 0;
        el.muted = false;
      }).catch(() => { /* ignore — best effort */ });
    });
    // Also prime the shared one-shot element.
    try {
      $audio.src = (AUDIO_URLS[tones[0]] || '');
      $audio.muted = true;
      const p = $audio.play();
      if (p && typeof p.then === 'function') {
        primes.push(p.then(() => { $audio.pause(); $audio.muted = false; })
                     .catch(() => {}));
      }
    } catch (e) {}
    return Promise.all(primes).then(() => {
      AUDIO_UNLOCKED = true;
      hideAudioUnlockOverlay();
    });
  }

  function startLoop(tone) {
    const url = AUDIO_URLS[tone];
    if (!url) { console.warn('[MEDSIM device] no audio url for tone', tone); return; }
    const el = _audioFor(tone);
    el.loop = true;
    el.src = url;
    el.play().then(() => {
      CURRENTLY_LOOPING.add(tone);
    }).catch((err) => {
      console.warn('[MEDSIM device] startLoop blocked for', tone, '— audio not unlocked yet:', err && err.name);
      showAudioUnlockOverlay();
    });
  }
  function stopLoop(tone) {
    const el = LOOP_NODES.get(tone);
    if (el) { try { el.pause(); el.currentTime = 0; } catch (e) {} }
    CURRENTLY_LOOPING.delete(tone);
  }
  function playOneShot(tone) {
    const url = AUDIO_URLS[tone];
    if (!url) return;
    $audio.src = url;
    $audio.play().catch((err) => {
      console.warn('[MEDSIM device] one-shot blocked for', tone, err && err.name);
      showAudioUnlockOverlay();
    });
  }

  // ── Audio-unlock overlay ────────────────────────────────────────────
  function showAudioUnlockOverlay() {
    if (AUDIO_UNLOCKED) return;
    let ov = document.getElementById('device-audio-unlock');
    if (ov) { ov.hidden = false; return; }
    ov = document.createElement('div');
    ov.id = 'device-audio-unlock';
    ov.style.cssText = 'position:fixed;inset:0;background:rgba(10,35,79,.94);'
      + 'color:#fff;display:flex;flex-direction:column;align-items:center;'
      + 'justify-content:center;z-index:100;font-family:-apple-system,Helvetica,Arial;'
      + 'padding:32px;text-align:center;cursor:pointer;';
    // Platform-aware rationale — both iOS and Android Chrome block
    // programmatic audio.play() until a real user gesture has unlocked
    // the page. Wording per platform helps trainees not blame the app.
    var ua = navigator.userAgent || '';
    var isIOS = /iPad|iPhone|iPod/.test(ua)
              || (navigator.platform === 'MacIntel' && navigator.maxTouchPoints > 1);
    var isAndroid = /Android/i.test(ua);
    var rationale = isIOS
      ? 'iOS blocks audio playback until you tap. Tap once and every alarm tone for the rest of this session will sound automatically.'
      : isAndroid
        ? 'Chrome blocks audio playback until you interact with the page. Tap once and every alarm tone for the rest of this session will sound automatically.'
        : 'Browsers block audio playback until you interact with the page. Tap once and every alarm tone for the rest of this session will sound automatically.';
    ov.innerHTML =
      '<div style="font-size:48px;margin-bottom:14px">🔊</div>'
      + '<div style="font-size:18px;font-weight:600;max-width:380px;line-height:1.4">'
      + 'Tap here to enable alarm audio</div>'
      + '<div style="font-size:13px;margin-top:10px;color:#a8c0f0;max-width:340px;line-height:1.5">'
      + rationale + '</div>';
    const handler = (e) => { e.preventDefault(); unlockAudio(); };
    ov.addEventListener('click', handler);
    ov.addEventListener('touchend', handler, { passive: false });
    document.body.appendChild(ov);
  }
  function hideAudioUnlockOverlay() {
    const ov = document.getElementById('device-audio-unlock');
    if (ov) ov.remove();
  }

  // ── Fullscreen — a bedside device should hide the browser chrome ────
  // The Fullscreen API needs a user gesture, so we request it on the first
  // "tap to enable" (Android Chrome + desktop honour it). iOS Safari doesn't
  // support element fullscreen — there the chrome-less path is Add to Home
  // Screen (the PWA manifest is display:fullscreen + apple-mobile-web-app-capable).
  function _fsActive() {
    return !!(document.fullscreenElement || document.webkitFullscreenElement);
  }
  function _enterFullscreen() {
    if (_fsActive()) return;
    const el = document.documentElement;
    const req = el.requestFullscreen || el.webkitRequestFullscreen
             || el.webkitRequestFullScreen;
    if (!req) return;                       // iOS Safari — no element fullscreen
    try {
      const p = req.call(el);
      if (p && typeof p.catch === 'function') p.catch(() => {});
    } catch (e) { /* best effort */ }
  }
  function _ensureFsButton() {
    let b = document.getElementById('device-fs-btn');
    if (!b) {
      b = document.createElement('button');
      b.id = 'device-fs-btn';
      b.type = 'button';
      b.textContent = '⛶';
      b.title = 'Full screen';
      b.setAttribute('aria-label', 'Enter full screen');
      b.style.cssText = 'position:fixed;right:10px;bottom:10px;z-index:46;'
        + 'width:46px;height:46px;border:0;border-radius:10px;padding:0;'
        + 'background:rgba(20,30,45,.62);color:#cfe0f2;font-size:22px;'
        + 'line-height:46px;cursor:pointer;';
      b.addEventListener('click', _enterFullscreen);
      document.body.appendChild(b);
    }
    b.hidden = _fsActive();                  // only show when NOT already fullscreen
  }
  document.addEventListener('fullscreenchange', _ensureFsButton);
  document.addEventListener('webkitfullscreenchange', _ensureFsButton);

  // ── Input ───────────────────────────────────────────────────────────
  function onControlTap(id, el) {
    // Every SVG control tap is a real user gesture — prime audio if
    // the unlock overlay was skipped or dismissed.
    if (!AUDIO_UNLOCKED) unlockAudio();
    if (SESSION_STATE === 'paused' || SESSION_STATE === 'configured' || SESSION_STATE === 'ended') {
      flashPaused();
      return;
    }
    // V6 — when the PROGRAM modal is open, route numeric / decimal /
    // clear keys to the currently-focused input field. Lets students
    // use the SVG number pad like a real Alaris in addition to the
    // iOS keyboard. Saves a non-fault tap from going to engine.handle.
    if (routeKeyToModalInput(id)) return;
    // V6 — faithful on-chassis programming. Numeric pad + screen-field
    // tap + advance keys all drive the spec-declared programming state
    // machine (no modal needed). Returns true when consumed so we don't
    // double-fire via controlToEvent.
    if (routeKeyToProgramming(id)) return;
    // Tap feedback — even unwired keys flash briefly so the user knows
    // their tap registered. Avoids the "is this dead?" perception.
    if (el && el.classList) {
      el.classList.add('svg-hit-active');
      setTimeout(() => el.classList.remove('svg-hit-active'), 200);
    }
    // Map the tapped SVG id → engine event. Per-device specs may carry
    // explicit mappings; in their absence we derive a sensible default
    // from the prefix.
    const ev = controlToEvent(id);
    if (!ev) return;
    sendEvent(ev.type, ev.payload || {});
  }

  // ── SVG numeric pad → open PROGRAM modal input ──────────────────────
  // When the modal is up, the SVG number / decimal / clear keys behave
  // like a real Alaris number pad: they edit the currently-focused
  // input. If no input is focused yet, route to the rate field by
  // default (it's the most common starting point). Returns true when
  // the key was consumed so onControlTap stops further processing.
  function routeKeyToModalInput(id) {
    const modal = document.getElementById('device-program-modal');
    if (!modal) return false;
    // Pick the focused input, or default to the rate input.
    let target = (document.activeElement && modal.contains(document.activeElement)
                  && (document.activeElement.tagName === 'INPUT'))
                 ? document.activeElement
                 : modal.querySelector('#pgm-rate');
    if (!target) return false;
    const fire = (newVal) => {
      target.value = newVal;
      target.dispatchEvent(new Event('input', {bubbles: true}));
      try { target.focus(); } catch (e) {}
    };
    if (/^key-([0-9])$/.test(id)) {
      const digit = id.slice(-1);
      fire((target.value || '') + digit);
      return true;
    }
    if (id === 'key-decimal') {
      if (!String(target.value || '').includes('.')) fire((target.value || '') + '.');
      return true;
    }
    if (id === 'key-clear') {
      fire('');
      return true;
    }
    return false;
  }

  // ── On-chassis programming state machine ────────────────────────────
  // Drives student-facing pump programming via the SVG function keys +
  // numeric pad. Per-pump tab order, focused field, channel context, and
  // dirty-set come from spec.json's `programming` block — same code
  // handles Alaris (per-channel rate+VTBI) and Kangaroo OMNI (single-
  // channel rate+volume+flush).
  //
  // Flow:
  //   tap a screen field (or first numeric key)  → field focused
  //   numeric / decimal keys                     → buffer grows
  //   clear key                                  → buffer empties
  //   advance key (channel-select / soft key)    → commit current field,
  //                                                 move focus to next
  //   start key                                  → commit ALL dirty +
  //                                                 fire pump.program +
  //                                                 fire pump.start
  const PROG = {
    channel:     null,      // 'A'|'B'|'' depending on pump
    focused:     null,      // field id, e.g. 'scr-rate'
    drafts:      {},        // {channel: {attribute: value}}
    buffer:      '',        // typing-in-progress for the focused field
  };

  function _progFieldById(id) {
    return ((SPEC.programming && SPEC.programming.fields) || []).find((f) => f.id === id);
  }
  function _progDraft(ch) {
    if (!PROG.drafts[ch]) PROG.drafts[ch] = {};
    return PROG.drafts[ch];
  }
  function _progCommitBuffer() {
    if (PROG.focused == null || PROG.buffer === '') return;
    const f = _progFieldById(PROG.focused);
    if (!f) { PROG.buffer = ''; return; }
    const value = f.allow_decimal ? parseFloat(PROG.buffer) : parseInt(PROG.buffer, 10);
    if (!isFinite(value)) { PROG.buffer = ''; return; }
    _progDraft(PROG.channel)[f.attribute] = value;
    PROG.buffer = '';
  }
  function _progRefreshDisplay() {
    const svg = $skin.querySelector('svg');
    if (!svg || !SPEC.programming) return;
    // Render the buffer in the focused field, and any committed drafts
    // in their fields. Highlight focused field with a yellow outline.
    for (const f of SPEC.programming.fields) {
      const el = svg.querySelector('#' + f.id);
      if (!el) continue;
      el.classList.toggle('prog-focused', f.id === PROG.focused);
      if (f.id === PROG.focused && PROG.buffer !== '') {
        el.textContent = PROG.buffer + '_';   // visible cursor
      } else {
        const draft = (_progDraft(PROG.channel)[f.attribute]);
        if (draft !== undefined) el.textContent = String(draft);
      }
    }
  }
  function _progFocus(fieldId) {
    // Commit whatever was being typed before moving focus.
    _progCommitBuffer();
    PROG.focused = fieldId;
    const svg = $skin.querySelector('svg');
    const el = svg && svg.querySelector('#' + fieldId);
    if (el) el.classList.add('prog-focused');
    _progRefreshDisplay();
  }
  function _progAdvanceFocus() {
    const fields = (SPEC.programming && SPEC.programming.fields) || [];
    if (!fields.length) return;
    _progCommitBuffer();
    let idx = fields.findIndex((f) => f.id === PROG.focused);
    idx = (idx + 1) % fields.length;
    _progFocus(fields[idx].id);
  }
  function _progSendIfReady(eventType) {
    // Build a pump.program / feed.program payload from the drafts.
    if (!SPEC.programming) return;
    _progCommitBuffer();
    const ch = PROG.channel || SPEC.programming.default_channel || '';
    const draft = _progDraft(ch);
    if (Object.keys(draft).length === 0) return;
    const payload = {...draft};
    if (ch) payload.channel = ch;
    if (SPEC.programming.auto_drug && !payload.drug_code) {
      const drug = (SPEC.drug_library || []).find((d) => d.code === SPEC.programming.auto_drug);
      if (drug) {
        payload.drug_code = drug.code;
        payload.drug_label = drug.label;
        payload.library_used = !!drug.limits;
        payload.soft_override = false;
      }
    }
    sendEvent(eventType, payload);
    PROG.drafts[ch] = {};   // clear so a subsequent edit starts fresh
    PROG.focused = null;
    PROG.buffer = '';
    _progRefreshDisplay();
  }

  // Returns true if the tap was consumed by the programming state machine.
  function routeKeyToProgramming(id) {
    if (KIND === 'cabinet') return false;        // cabinets program differently
    const prog = SPEC.programming;
    if (!prog) return false;

    // Channel switching (Alaris key-mod1-select / mod2-select)
    if (prog.channel_keys && id in prog.channel_keys) {
      _progCommitBuffer();
      PROG.channel = prog.channel_keys[id];
      _progRefreshDisplay();
      return true;
    }

    // Tap on a programmable screen field → focus it.
    if (_progFieldById(id)) {
      if (!PROG.channel) PROG.channel = prog.default_channel || 'A';
      _progFocus(id);
      return true;
    }

    // STEPPER input mode (e.g., Kangaroo OMNI): up/down arrows
    // increment/decrement the focused field by its declared `step`.
    // No numeric pad on this chassis. First press auto-focuses field 0.
    if (prog.input_mode === 'stepper' && (id === prog.inc_key || id === prog.dec_key)) {
      if (!PROG.focused) {
        if (!PROG.channel) PROG.channel = prog.default_channel || '';
        const first = (prog.fields || [])[0];
        if (first) _progFocus(first.id);
      }
      const f = _progFieldById(PROG.focused);
      if (!f) return false;
      const draft = _progDraft(PROG.channel);
      const current = (draft[f.attribute] !== undefined)
        ? draft[f.attribute]
        : ((STATE && STATE[f.attribute]) || 0);
      const step = f.step || 1;
      const delta = (id === prog.inc_key) ? step : -step;
      let next = Number(current) + delta;
      if (f.min !== undefined && next < f.min) next = f.min;
      if (f.max !== undefined && next > f.max) next = f.max;
      draft[f.attribute] = next;
      PROG.buffer = String(next);
      _progRefreshDisplay();
      return true;
    }

    // NUMERIC-PAD input mode (Alaris-style): digits build a buffer,
    // decimal/clear edit it. Auto-focuses first field if no field active.
    if (/^key-([0-9])$/.test(id) || id === 'key-decimal' || id === prog.clear_key) {
      if (!PROG.focused) {
        if (!PROG.channel) PROG.channel = prog.default_channel || 'A';
        const first = (prog.fields || [])[0];
        if (first) _progFocus(first.id);
      }
      const f = _progFieldById(PROG.focused);
      if (!f) return false;
      if (/^key-([0-9])$/.test(id)) {
        if (PROG.buffer.length >= (f.max_digits || 6)) return true;
        PROG.buffer += id.slice(-1);
      } else if (id === 'key-decimal') {
        if (f.allow_decimal && !PROG.buffer.includes('.')) PROG.buffer += '.';
      } else if (id === prog.clear_key) {
        PROG.buffer = '';
      }
      _progRefreshDisplay();
      return true;
    }

    // Advance keys → commit + move to next field.
    if ((prog.advance_keys || []).includes(id)) {
      _progAdvanceFocus();
      return true;
    }

    // Start keys → commit + fire program + start.
    if (prog.start_keys && id in prog.start_keys) {
      const ch = prog.start_keys[id];
      if (ch) PROG.channel = ch;
      const evtKind = (KIND === 'pump_enteral') ? 'feed' : 'pump';
      // 1) Ensure power is on (real pumps need this; engine accepts it idempotently).
      if (!STATE || !STATE.power) sendEvent(evtKind + '.power', {state: 'on'});
      // 2) Commit any drafted program.
      _progSendIfReady(evtKind + '.program');
      // 3) Start (with channel for IV pumps).
      const startPayload = ch ? {channel: ch} : {};
      sendEvent(evtKind + '.start', startPayload);
      return true;
    }

    return false;
  }

  function controlToEvent(id) {
    // Cabinet: btn-login, btn-remove, etc. — most route to a cabinet.* event.
    if (id.startsWith('btn-')) {
      const verb = id.slice(4);
      if (verb === 'login')  return { type: 'auth.login', payload: { user: 'J. Rivera, RN', method: 'bioid' } };
      if (verb === 'logout') return { type: 'auth.logout', payload: {} };
      if (['remove','return','waste','count','discrepancies','override'].includes(verb))
        return { type: 'cabinet.select_verb', payload: { verb } };
      if (verb === 'accept') return { type: 'cabinet.scan_verify', payload: { result: 'match' } };
      if (verb === 'cancel') return { type: 'auth.logout', payload: {} };
      return null;
    }
    // Pump hardkeys. Default = pump.<verb>; spec.controls may declare special cases.
    if (id === 'key-onoff' || id === 'key-power')
      return { type: KIND === 'pump_enteral' ? 'feed.power' : 'pump.power',
               payload: { state: STATE && STATE.power ? 'off' : 'on' } };
    if (id === 'key-start')   return { type: KIND === 'pump_enteral' ? 'feed.start' : 'pump.start',  payload: { channel: 'A' } };
    if (id === 'key-pause')   return { type: KIND === 'pump_enteral' ? 'feed.pause' : 'pump.pause',  payload: { channel: 'A' } };
    if (id === 'key-stop')    return { type: KIND === 'pump_enteral' ? 'feed.stop'  : 'pump.stop',   payload: { channel: 'A' } };
    // Alaris module-channel hardkeys: key-mod1-start / -pause / -off → channel A;
    // key-mod2-* → channel B. Maps to the same pump.* engine events as the
    // generic key-start / key-pause / key-stop.
    const modMatch = id.match(/^key-mod([12])-(start|pause|off|select)$/);
    if (modMatch) {
      const channel = modMatch[1] === '1' ? 'A' : 'B';
      const verb    = modMatch[2];
      if (verb === 'start')  return { type: 'pump.start', payload: { channel } };
      if (verb === 'pause')  return { type: 'pump.pause', payload: { channel } };
      if (verb === 'off')    return { type: 'pump.stop',  payload: { channel } };
      // 'select' is a UI-only focus shift on the real device; no engine event needed.
      return null;
    }
    if (id === 'key-silence') {
      // V6.1.2 — Silence the first AUDIBLE alarm. We also immediately
      // .pause() the local Audio element so the user hears silence on
      // tap (zero latency), even before the server round-trip persists
      // the silenced_until. The server-side fold will reaffirm.
      const nowSec = Date.now() / 1000;
      const alarms = (STATE && STATE.active_alarms || []);
      console.log('[MEDSIM device] key-silence pressed. alarms:', alarms,
                  'currently looping:', [...CURRENTLY_LOOPING]);
      const a = alarms.find((x) => (x.silenced_until || 0) <= nowSec);
      // Fallback — if the fold doesn't yet know about the alarm but a
      // loop is actively playing on the device, silence THAT tone. This
      // covers the race where the inject event was streamed via WS push
      // but the next fold poll hasn't returned yet on a slow tablet.
      const tone = (a && a.tone) || [...CURRENTLY_LOOPING][0];
      if (!tone) {
        console.log('[MEDSIM device] silence pressed but no audible alarm');
        return null;
      }
      // Immediate local mute. The server fold will reaffirm shortly.
      stopLoop(tone);
      return { type: 'alarm.silenced',
               payload: { tone, until: nowSec + (SPEC.silence_seconds || 120) } };
    }
    if (id === 'key-clear') {
      // Clear the first AUDIBLE alarm if any; if all are silenced, clear
      // the first one (so Clear always succeeds in releasing the visual).
      const nowSec = Date.now() / 1000;
      const alarms = (STATE && STATE.active_alarms || []);
      const a = alarms.find((x) => (x.silenced_until || 0) <= nowSec) || alarms[0];
      if (!a) return null;
      return { type: 'alarm.cleared', payload: { tone: a.tone } };
    }
    return null;
  }

  // ── WebSocket lifecycle ─────────────────────────────────────────────
  let WS_ATTEMPTS = 0;
  let POLL_TIMER = null;

  // M43-followup — Connection badge in the upper-right of every device
  // tablet was visual noise for students (flashing OFFLINE · HTTP 409
  // every 2 s because of the stale state route — fixed server-side
  // too). It's now hidden by default; pass ?debug=conn in the URL to
  // surface it for troubleshooting.
  //
  // The state lifecycle still runs (we still know whether we're on
  // WS, polling, or offline — the dispatcher just doesn't paint a
  // visible badge).
  const _SHOW_CONN_BADGE = (() => {
    try {
      const qs = new URLSearchParams(window.location.search);
      return qs.get('debug') === 'conn' || qs.get('debug') === '1';
    } catch (e) { return false; }
  })();
  let _CONN_STATE = { mode: '', detail: '' };
  function setStatus(mode, detail) {
    // mode: 'ws' | 'polling' | 'offline'
    _CONN_STATE = { mode, detail: detail || '' };
    if (!_SHOW_CONN_BADGE) {
      // Strip any stale badge if it was previously injected (e.g.
      // operator toggled the query param mid-session).
      const stale = document.getElementById('device-conn-badge');
      if (stale) stale.remove();
      return;
    }
    let badge = document.getElementById('device-conn-badge');
    if (!badge) {
      badge = document.createElement('div');
      badge.id = 'device-conn-badge';
      badge.style.cssText = 'position:fixed;top:8px;right:8px;z-index:50;'
        + 'padding:4px 10px;border-radius:4px;font-size:11px;font-weight:600;'
        + 'letter-spacing:.08em;color:#fff;font-family:-apple-system,Helvetica,Arial;';
      document.body.appendChild(badge);
    }
    const colors = { ws: '#3DA35D', polling: '#E6A032', offline: '#D7382E' };
    badge.style.background = colors[mode] || '#5b6470';
    badge.textContent = (mode === 'ws' ? 'LIVE' : mode === 'polling' ? 'POLLING' : 'OFFLINE')
      + (detail ? ' · ' + detail : '');
  }

  function connectWS() {
    if (WS && WS.readyState <= 1) return;
    WS_ATTEMPTS += 1;
    const proto = window.location.protocol === 'https:' ? 'wss:' : 'ws:';
    try {
      WS = new WebSocket(`${proto}//${window.location.host}/ws/device/${STN}`);
    } catch (e) {
      console.error('[MEDSIM device] WS construct failed:', e);
      setStatus('polling', 'WS unavailable');
      startPolling();
      return;
    }
    WS.onopen = () => {
      WS_BACKOFF = 1000; WS_ATTEMPTS = 0;
      stopPolling();
      setStatus('ws');
    };
    WS.onmessage = (e) => {
      let msg; try { msg = JSON.parse(e.data); } catch { return; }
      if (msg.type === 'fold')   { renderFold(msg.state); }
      else if (msg.type === 'inject') {
        const tone = msg.tone;
        if (tone) playOneShot(tone);          // pre-fold cue
        if (msg.state) renderFold(msg.state); // engine will start the loop via fold
      }
      else if (msg.type === 'assign') {
        // V6.1.7 — track the assigned character id and pop the cabinet
        // checklist (for med carts) so the student sees their patient's
        // meds the moment the instructor picks them. Resetting
        // CHECKLIST_DISMISSED forces the panel to re-show even if the
        // student previously tapped the X.
        ASSIGNED_CHAR_ID = msg.character_id || null;
        CHECKLIST_DISMISSED = false;
        if (msg.state) renderFold(msg.state);
        else if (KIND === 'cabinet') renderCabinetChecklist();
      }
      else if (msg.type === 'clear') {
        // V6 — instructor cleared one or more alarms remotely. The new
        // fold has them removed from active_alarms, so a render pass
        // will stopLoop() each tone automatically.
        if (msg.state) renderFold(msg.state);
      }
      else if (msg.type === 'state')    { applySessionState(msg.state); }
      else if (msg.type === 'rejected') { flashPaused(); }
      else if (msg.type === 'time_advanced') {
        // V6.1.5 — operator pressed +N min on the control panel. Show a
        // brief banner regardless of whether the engine state changed
        // (it doesn't change if no channel was running). Without this
        // banner the operator presses the button and sees no feedback
        // on devices that weren't infusing.
        showTimeAdvancedToast(msg.minutes, msg.applied);
      }
    };
    WS.onclose = (e) => {
      WS = null;
      console.warn('[MEDSIM device] WS closed', e && e.code, e && e.reason);
      // After two failed connects, give up on WS and switch to polling.
      // Common on iOS Chrome + macOS firewall: the WS upgrade is blocked
      // even though HTTP works. Polling keeps alarms + state in sync.
      if (WS_ATTEMPTS >= 2) {
        setStatus('polling', 'no WS — using HTTP poll');
        startPolling();
      } else {
        setStatus('offline', 'reconnecting…');
      }
      setTimeout(connectWS, WS_BACKOFF);
      WS_BACKOFF = Math.min(WS_BACKOFF * 2, 30000);
    };
    WS.onerror = () => { try { WS.close(); } catch (e) {} };
  }

  // ── HTTP polling fallback ───────────────────────────────────────────
  // Polls /api/device/{station_id}/state every 2s; renders the returned
  // fold; detects new alarms by comparing tone sets and plays cues.
  // Survives WS failure entirely (no instructor inject ever lost).
  async function pollOnce() {
    try {
      const r = await fetch(`/api/device/${STN}/state?_t=${Date.now()}`);
      if (!r.ok) { setStatus('offline', 'HTTP ' + r.status); return; }
      const data = await r.json();
      if (data.session_state) applySessionState(data.session_state);
      if (data.state) renderFold(data.state);
      // After the first successful poll, badge stays "POLLING"
      if (!document.getElementById('device-conn-badge')?.textContent?.includes('POLLING')) {
        setStatus('polling');
      }
    } catch (e) {
      setStatus('offline', 'network');
    }
  }
  function startPolling() {
    if (POLL_TIMER) return;
    POLL_TIMER = setInterval(pollOnce, 2000);
    pollOnce();   // immediate first poll
  }
  function stopPolling() {
    if (POLL_TIMER) { clearInterval(POLL_TIMER); POLL_TIMER = null; }
  }

  async function sendEvent(eventType, payload) {
    if (WS && WS.readyState === 1) {
      WS.send(JSON.stringify({ type: 'event', event_type: eventType, payload }));
      return;
    }
    // HTTP fallback — used both during polling mode and as a safety net.
    try {
      const r = await fetch(`/api/device/${STN}/event`, {
        method: 'POST', headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ type: eventType, payload }),
      });
      if (r.status === 423) { flashPaused(); return; }
      const j = await r.json();
      if (j && j.state) renderFold(j.state);
    } catch (e) {
      console.error('[MEDSIM device] event POST failed:', e);
    }
  }

  // ── Pause / resume ──────────────────────────────────────────────────
  function applySessionState(state) {
    SESSION_STATE = state;
    // V6.1 — 'configured' is now a pre-start gate. Treat it like pause:
    // device shows a "waiting for instructor" banner, alarm loops are
    // suppressed, but the chassis still renders so the operator can
    // preview the layout + ensure devices joined cleanly. Instructor
    // must explicitly press Start to flip to 'running'.
    const blocked = state === 'paused' || state === 'ended' || state === 'configured';
    if (blocked) {
      $paused.hidden = false;
      $paused.textContent =
        state === 'ended'      ? 'SCENARIO ENDED' :
        state === 'configured' ? 'WAITING — INSTRUCTOR HAS NOT STARTED THE SCENARIO' :
                                  'SCENARIO PAUSED';
      // Silence every looping alarm tone immediately.
      for (const tone of [...CURRENTLY_LOOPING]) stopLoop(tone);
    } else {
      $paused.hidden = true;
      // On resume, re-evaluate fold so any alarms still active re-loop.
      if (STATE) renderFold(STATE);
    }
  }

  function flashPaused() {
    $paused.hidden = false;
    $paused.style.animation = 'none';
    void $paused.offsetWidth;
    $paused.style.animation = 'alarm-flash 700ms ease-in-out 3 alternate';
  }

  // V6.1.5 — visible feedback when the operator presses +N min on the
  // control panel. Engine state only advances for currently-running
  // channels, so for a programmed-but-not-yet-started pump the volume /
  // time-remaining numbers can't change. Without this banner the
  // operator would conclude the button was broken. The toast appears
  // for every device kind, including cabinets.
  function showTimeAdvancedToast(minutes, applied) {
    let el = document.getElementById('device-time-toast');
    if (!el) {
      el = document.createElement('div');
      el.id = 'device-time-toast';
      el.style.cssText = 'position:fixed;left:50%;top:18%;transform:translateX(-50%);'
        + 'background:#143b8a;color:#fff;border-radius:10px;padding:14px 24px;'
        + 'font-size:18px;font-weight:700;letter-spacing:.05em;z-index:55;'
        + 'box-shadow:0 4px 16px rgba(0,0,0,.3);text-align:center;'
        + 'transition:opacity 300ms ease-in-out;';
      document.body.appendChild(el);
    }
    const label = (minutes >= 60 && minutes % 60 === 0)
      ? `${minutes / 60} HR`
      : `${minutes} MIN`;
    el.innerHTML = `⏩ TIME ADVANCED +${label}`
      + (applied ? '' : `<div style="font-size:11px;font-weight:500;margin-top:4px;opacity:.85">(no infusion running)</div>`);
    el.style.opacity = '1';
    clearTimeout(el._hideTimer);
    el._hideTimer = setTimeout(() => { el.style.opacity = '0'; }, 2800);
  }

  // ── Heartbeat ───────────────────────────────────────────────────────
  setInterval(() => {
    if (WS && WS.readyState === 1) WS.send(JSON.stringify({ type: 'heartbeat' }));
    else fetch(`/api/device/${STN}/heartbeat`, { method: 'POST' }).catch(() => {});
  }, 15000);

  // ── FR-012 D3b — telemetry-monitor live rendering ───────────────────
  // The monitor is not button-driven: it paints live vitals + scrolling
  // waveforms from the `physiology` snapshot the server attaches to
  // bootstrap/state. Numerics + the alarm fold refresh on a light 1.5 s
  // poll (which also surfaces auto-fired alarms); waveforms animate
  // locally via requestAnimationFrame (HR/RR-driven) and freeze on pause.
  const _MON_LANES = {
    ecg:   { id: 'wave-ecg',   x0: 12, x1: 690, base: 110, amp: 34 },
    pleth: { id: 'wave-pleth', x0: 12, x1: 690, base: 250, amp: 26 },
    resp:  { id: 'wave-resp',  x0: 12, x1: 690, base: 390, amp: 22 },
  };
  const _MON_WINDOW_S = 4;     // seconds visible — narrower window = more px per beat
  const _MON_STEP_PX = 2;      // fine x sampling so the sharp QRS peak never aliases/flickers
  const _MON_RHYTHM_LABEL = {
    nsr: 'Sinus rhythm', sinus: 'Sinus rhythm',
    sinus_brady: 'Sinus bradycardia', sinus_tachy: 'Sinus tachycardia',
    asystole: 'ASYSTOLE', vfib: 'VF', vf: 'VF',
    vtach_mono: 'VT', vtach_poly: 'Torsades (VT)', vtach: 'VT', vt: 'VT',
    afib: 'A-fib', aflutter: 'A-flutter', pea: 'PEA', paced: 'Paced',
  };
  const _MON_ALARM_LABEL = {
    asystole: 'ASYSTOLE', vfib: 'VF', vtach: 'VT', brady_severe: 'SEVERE BRADY',
    tachy_severe: 'SEVERE TACHY', spo2_low: 'SpO2 LOW', apnea: 'APNEA',
    brady: 'BRADY', tachy: 'TACHY', rr_high: 'RR HIGH', nibp_high: 'NIBP HIGH',
    nibp_low: 'NIBP LOW', pvc_frequent: 'PVCs', afib: 'A-FIB', leads_off: 'LEADS OFF',
  };
  let _monPhysTimer = null, _monRAF = null, _monT0 = 0;

  function startMonitor() {
    _monT0 = performance.now();
    bindMonitorNumerics();
    renderMonitorAlarmBanner();
    if (_monPhysTimer) clearInterval(_monPhysTimer);
    _monPhysTimer = setInterval(pollMonitorPhysiology, 1500);
    if (!_monRAF) _monRAF = requestAnimationFrame(monitorFrame);
  }

  async function pollMonitorPhysiology() {
    try {
      const r = await fetch(`/api/device/${STN}/state?_t=${Date.now()}`);
      if (!r.ok) return;
      const j = await r.json();
      if (j.session_state) applySessionState(j.session_state);
      if (j.physiology) PHYS = j.physiology;
      if (j.state) renderFold(j.state);          // surfaces auto-fired alarms
      bindMonitorNumerics();
      renderMonitorAlarmBanner();
    } catch (e) { /* offline — keep last values until next poll */ }
  }

  function _monVital(k, dflt) {
    const v = (PHYS && PHYS.vitals) ? PHYS.vitals[k] : null;
    return (typeof v === 'number' && isFinite(v)) ? v : dflt;
  }
  function _monSetText(svg, id, txt) {
    const e = svg && svg.querySelector('#' + id);
    if (e) e.textContent = txt;
  }
  function bindMonitorNumerics() {
    const svg = $skin && $skin.querySelector('svg'); if (!svg) return;
    const hr = _monVital('hr', null), spo2 = _monVital('spo2', null);
    const rr = _monVital('rr', null), etco2 = _monVital('etco2', null);
    const sbp = _monVital('sbp', null), dbp = _monVital('dbp', null);
    _monSetText(svg, 'scr-hr',    hr    != null ? String(Math.round(hr))    : '--');
    _monSetText(svg, 'scr-spo2',  spo2  != null ? String(Math.round(spo2))  : '--');
    _monSetText(svg, 'scr-rr',    rr    != null ? String(Math.round(rr))    : '--');
    _monSetText(svg, 'scr-etco2', etco2 != null ? String(Math.round(etco2)) : '--');
    _monSetText(svg, 'scr-nibp',
      (sbp != null && dbp != null) ? `${Math.round(sbp)}/${Math.round(dbp)}` : '--/--');
    const rhy = (PHYS && PHYS.rhythm) ? String(PHYS.rhythm).toLowerCase() : 'nsr';
    _monSetText(svg, 'scr-rhythm', _MON_RHYTHM_LABEL[rhy] || rhy);
  }

  function renderMonitorAlarmBanner() {
    const tones = ((STATE && STATE.active_alarms) || [])
      .map((a) => (typeof a === 'string' ? a : a.tone));
    let el = document.getElementById('monitor-alarm-banner');
    if (!tones.length) { if (el) el.hidden = true; return; }
    if (!el) {
      el = document.createElement('div');
      el.id = 'monitor-alarm-banner';
      el.style.cssText = 'position:fixed;top:0;left:0;right:0;z-index:40;'
        + 'background:#c0271d;color:#fff;font:700 16px/1.25 -apple-system,Helvetica,Arial;'
        + 'letter-spacing:.08em;padding:8px 14px;text-align:center;';
      document.body.appendChild(el);
    }
    el.hidden = false;
    el.textContent = '⚠ ' + tones.map((t) => _MON_ALARM_LABEL[t] || t.toUpperCase()).join('   ·   ');
  }

  // Waveform morphology (phase in [0,1) within one cycle).
  function _ecgShape(phase, rhythm) {
    rhythm = rhythm || 'nsr';
    if (rhythm === 'asystole') return 0;
    if (rhythm === 'vfib' || rhythm === 'vf')
      return 0.45 * Math.sin(phase * Math.PI * 17) + 0.30 * Math.sin(phase * Math.PI * 29 + 1);
    if (rhythm.indexOf('vtach') === 0 || rhythm === 'vt')   // vtach_mono / vtach_poly
      return 0.85 * Math.sin(phase * Math.PI * 2);
    let y = 0;
    y += 0.12 * Math.exp(-Math.pow((phase - 0.15) / 0.035, 2));   // P
    y -= 0.10 * Math.exp(-Math.pow((phase - 0.255) / 0.014, 2));  // Q
    y += 1.00 * Math.exp(-Math.pow((phase - 0.28) / 0.016, 2));   // R (widened: anti-flicker)
    y -= 0.18 * Math.exp(-Math.pow((phase - 0.305) / 0.016, 2));  // S
    y += 0.22 * Math.exp(-Math.pow((phase - 0.50) / 0.05, 2));    // T
    return y;
  }
  function _plethShape(phase) {
    return Math.exp(-Math.pow((phase - 0.18) / 0.12, 2))
         + 0.28 * Math.exp(-Math.pow((phase - 0.42) / 0.09, 2));
  }
  function _respShape(phase) { return 0.5 * (1 - Math.cos(phase * Math.PI * 2)); }

  function _monDrawLane(svg, lane, freqHz, shapeFn, tNow) {
    const el = svg.querySelector('#' + lane.id); if (!el) return;
    const w = lane.x1 - lane.x0;
    const pts = [];
    for (let x = lane.x0; x <= lane.x1; x += _MON_STEP_PX) {
      const frac = (x - lane.x0) / w;
      const lt = tNow - _MON_WINDOW_S * (1 - frac);   // older samples to the left
      let phase = (lt * freqHz) % 1; if (phase < 0) phase += 1;
      const y = lane.base - lane.amp * shapeFn(phase);
      pts.push(x.toFixed(0) + ',' + y.toFixed(1));
    }
    el.setAttribute('points', pts.join(' '));
  }
  function monitorFrame(now) {
    _monRAF = requestAnimationFrame(monitorFrame);
    const svg = $skin && $skin.querySelector('svg'); if (!svg) return;
    if (SESSION_STATE !== 'running') return;   // freeze on pause / ended / configured
    const tNow = (now - _monT0) / 1000;
    const hrHz = Math.max(20, _monVital('hr', 72)) / 60;
    const rrHz = Math.max(4, _monVital('rr', 14)) / 60;
    const rhythm = (PHYS && PHYS.rhythm) ? String(PHYS.rhythm).toLowerCase() : 'nsr';
    _monDrawLane(svg, _MON_LANES.ecg,   hrHz, (p) => _ecgShape(p, rhythm), tNow);
    _monDrawLane(svg, _MON_LANES.pleth, hrHz, _plethShape, tNow);
    _monDrawLane(svg, _MON_LANES.resp,  rrHz, _respShape, tNow);
  }

  // ── FR-012 D5b — ventilator + vent-monitor client ───────────────────
  // Vent devices render a dedicated DOM screen (not the SVG skin): scrolling
  // airway pressure/flow/volume scalars + numerics; for the ventilator, the
  // mode + setting controls POST /vent/set (the physiology coupling then moves
  // the patient) plus maneuvers; for the vent monitor, P-V/F-V loops. Alarms get
  // a banner + Silence/Clear (the SVG key-* buttons are hidden in this mode).
  let _ventScalarsCx = null, _ventLoopsCx = null, _ventRAF = null, _ventT0 = 0, _ventPollTimer = null;

  function _ventMode(s) {
    return /^(PC-CMV|PRVC|PSV|CPAP|PC)$/i.test((s && s.mode) || '') ? 'PC' : 'VC';
  }
  function _ventDerived(s) {
    const rr = Math.max(1, +s.rr || 14);
    const period = 60 / rr;
    const ti = s.inspiratory_time_s ? +s.inspiratory_time_s : period / (1 + (+s.ie_ratio || 2));
    const tau = Math.max(0.05, (+s.resistance_cmh2o_l_s || 10) * ((+s.compliance_ml_cmh2o || 50) / 1000));
    return { period, ti, tau, mode: _ventMode(s) };
  }
  function _ventPoint(s, d, tb) {
    const vt = +s.tidal_volume_ml || 450, peep = +s.peep || 5;
    const r = +s.resistance_cmh2o_l_s || 10, c = +s.compliance_ml_cmh2o || 50;
    const inspFlow = (vt / 1000) / d.ti, leak = (+s.leak_fraction || 0) * vt;
    if (tb <= d.ti) {
      const frac = d.ti > 0 ? tb / d.ti : 1;
      let v, f, p;
      if (d.mode === 'PC') {
        const rise = Math.max(0.05, 0.5 * d.tau);
        v = vt * (1 - Math.exp(-tb / rise));
        f = (vt / 1000) / rise * Math.exp(-tb / rise);
        p = peep + ((+s.pip || 18) - peep);
      } else {
        v = vt * frac; f = inspFlow; p = peep + f * r + v / c;
        if (s.flow_starvation) p -= 4 * Math.sin(Math.PI * frac);
      }
      if (s.overdistension && frac > 0.7) p += 80 * Math.pow(frac - 0.7, 2);
      return { p, f, v };
    }
    const te = tb - d.ti, decay = Math.exp(-te / d.tau);
    const v = leak + (vt - leak) * decay;
    let f = -((vt - leak) / 1000) / d.tau * decay;
    const p = peep + (vt / c) * decay;
    if (s.secretions) f += 0.06 * Math.sin(2 * Math.PI * 8 * te) * decay;
    return { p, f, v };
  }

  function _settings() { return (VENT && VENT.settings) || {}; }

  function startVent() {
    if ($skin) $skin.style.display = 'none';
    buildVentPanel();
    _ventT0 = performance.now();
    if (!_ventRAF) _ventRAF = requestAnimationFrame(ventFrame);
    if (_ventPollTimer) clearInterval(_ventPollTimer);
    _ventPollTimer = setInterval(pollVent, 1500);
  }

  async function pollVent() {
    try {
      const r = await fetch(`/api/device/${STN}/state?_t=${Date.now()}`);
      if (!r.ok) return;
      const j = await r.json();
      if (j.session_state) applySessionState(j.session_state);
      if (j.vent) VENT = j.vent;
      if (j.state) renderFold(j.state);
      renderVentNumerics(); renderVentAlarms();
      if (IS_VENTILATOR) { renderVentModes(); renderVentControls(); } else { drawVentLoops(); }
    } catch (e) { /* offline — keep last */ }
  }

  function _vel(tag, css, html) {
    const e = document.createElement(tag);
    if (css) e.style.cssText = css;
    if (html != null) e.innerHTML = html;
    return e;
  }
  function _ventBtnCss(bg, fg) {
    return 'border:0;border-radius:8px;padding:12px 16px;font-size:15px;font-weight:600;'
      + 'background:' + bg + ';color:' + (fg || '#cfe0f2') + ';cursor:pointer;';
  }
  function _sizeVentCanvas(c) {
    if (!c) return;
    const dpr = window.devicePixelRatio || 1;
    c.width = c.clientWidth * dpr; c.height = c.clientHeight * dpr;
    c.getContext('2d').setTransform(dpr, 0, 0, dpr, 0, 0);
  }

  function buildVentPanel() {
    if (document.getElementById('device-vent')) return;
    const panel = _vel('div', 'position:fixed;inset:0;z-index:5;background:#05070b;color:#e6e6e6;'
      + 'font-family:-apple-system,Helvetica,Arial;display:flex;flex-direction:column;overflow:auto;');
    panel.id = 'device-vent';
    const head = _vel('div', 'display:flex;align-items:center;gap:10px;padding:8px 14px;background:#10151e;');
    head.innerHTML = '<strong style="color:#cfe8ff;font-size:16px">'
      + (IS_VENTILATOR ? 'Ventilator' : 'Ventilator Display') + '</strong>';
    const modeWrap = _vel('span', 'margin-left:auto;display:flex;gap:6px;flex-wrap:wrap;justify-content:flex-end');
    modeWrap.id = 'vent-modes';
    head.appendChild(modeWrap);
    panel.appendChild(head);
    const banner = _vel('div', 'display:none'); banner.id = 'vent-alarm-banner';
    panel.appendChild(banner);
    const sc = document.createElement('canvas'); sc.id = 'vent-scalars';
    // FR-012 — grow to fill the panel so the waveforms open up; controls sit below.
    sc.style.cssText = 'width:100%;flex:1 1 auto;min-height:200px;display:block;background:#05070b';
    panel.appendChild(sc);
    const num = _vel('div', 'display:flex;flex-wrap:wrap;gap:6px;padding:8px 12px;background:#0b0f16');
    num.id = 'vent-numerics';
    panel.appendChild(num);
    if (IS_VENTILATOR) {
      const ctl = _vel('div', 'padding:8px 12px'); ctl.id = 'vent-controls';
      panel.appendChild(ctl);
      const man = _vel('div', 'display:flex;gap:8px;flex-wrap:wrap;padding:0 12px 8px');
      [['insp_hold', 'Insp hold'], ['exp_hold', 'Exp hold'], ['o2_100', '100% O2']].forEach(([kind, label]) => {
        const b = _vel('button', _ventBtnCss('#1a2636'), label);
        b.addEventListener('click', () => ventManeuver(kind));
        man.appendChild(b);
      });
      panel.appendChild(man);
    } else {
      const lc = document.createElement('canvas'); lc.id = 'vent-loops';
      lc.style.cssText = 'width:100%;height:190px;display:block;background:#05070b';
      panel.appendChild(lc);
    }
    const ac = _vel('div', 'display:flex;gap:8px;padding:8px 12px');
    const sil = _vel('button', _ventBtnCss('#3a2730', '#f3c4cd'), 'Silence');
    sil.addEventListener('click', silenceActive);
    const clr = _vel('button', _ventBtnCss('#1a2636'), 'Clear');
    clr.addEventListener('click', clearActive);
    ac.appendChild(sil); ac.appendChild(clr);
    panel.appendChild(ac);
    document.body.appendChild(panel);
    _ventScalarsCx = sc.getContext('2d');
    _sizeVentCanvas(sc);
    if (!IS_VENTILATOR) { _ventLoopsCx = document.getElementById('vent-loops').getContext('2d'); _sizeVentCanvas(document.getElementById('vent-loops')); }
    window.addEventListener('resize', () => {
      _sizeVentCanvas(sc); _sizeVentCanvas(document.getElementById('vent-loops'));
    });
    renderVentModes(); renderVentNumerics(); renderVentAlarms();
    if (IS_VENTILATOR) renderVentControls(); else drawVentLoops();
  }

  function renderVentModes() {
    const wrap = document.getElementById('vent-modes'); if (!wrap) return;
    const cur = _settings().mode || '';
    if (!IS_VENTILATOR) { wrap.textContent = cur; wrap.style.color = '#bcd8ff'; return; }
    wrap.innerHTML = '';
    ((VENT && VENT.modes) || []).forEach((m) => {
      const on = m === cur;
      const b = _vel('button', 'border:0;border-radius:6px;padding:6px 10px;font-size:13px;font-weight:600;cursor:pointer;'
        + (on ? 'background:#1f3550;color:#bcd8ff' : 'background:#16202c;color:#8aa0b6'), m);
      b.addEventListener('click', () => setVentControl('mode', m));
      wrap.appendChild(b);
    });
  }
  function renderVentNumerics() {
    const host = document.getElementById('vent-numerics'); if (!host) return;
    const n = (VENT && VENT.numerics) || {};
    const fio2 = n.fio2 != null ? Math.round(n.fio2 * 100) + '%' : '—';
    const tiles = [['Ppeak', n.ppeak, '#f2c14e'], ['Pplat', n.pplateau, '#f2c14e'],
      ['PEEP', n.peep, '#e6e6e6'], ['Vt', n.vt_exhaled_ml, '#33d6e6'], ['RR', n.rr, '#39d353'],
      ['MV', n.minute_vent_l, '#39d353'], ['FiO2', fio2, '#33d6e6'], ['I:E', n.ie, '#e6e6e6']];
    host.innerHTML = tiles.map(([lab, val, col]) =>
      '<div style="min-width:62px;background:#10151e;border-radius:6px;padding:4px 8px">'
      + '<div style="font-size:11px;color:#8aa0b6">' + lab + '</div>'
      + '<div style="font-size:21px;font-weight:700;color:' + col + '">' + (val == null ? '—' : val) + '</div></div>').join('');
  }
  function renderVentControls() {
    const host = document.getElementById('vent-controls'); if (!host) return;
    const avail = (VENT && VENT.available) || [], ranges = (VENT && VENT.ranges) || {}, s = _settings();
    host.innerHTML = '';
    const grid = _vel('div', 'display:grid;grid-template-columns:repeat(auto-fit,minmax(150px,1fr));gap:8px');
    avail.forEach((k) => {
      const spec = ranges[k]; if (!spec) return;
      const val = s[k];
      const disp = (k === 'fio2' && val != null) ? Math.round(val * 100) + '%' : (val == null ? '—' : val);
      const tile = _vel('div', 'background:#121a25;border:1px solid #26344a;border-radius:10px;padding:8px');
      tile.innerHTML = '<div style="font-size:12px;color:#8aa0b6">' + spec.label
        + (spec.unit ? ' (' + spec.unit + ')' : '') + '</div>'
        + '<div style="display:flex;align-items:center;gap:8px;margin-top:4px">'
        + '<button data-d="-1" style="' + _stepCss() + '">−</button>'
        + '<div style="flex:1;text-align:center;font-size:22px;font-weight:700;color:#cfe0f2">' + disp + '</div>'
        + '<button data-d="1" style="' + _stepCss() + '">+</button></div>';
      tile.querySelectorAll('button').forEach((btn) => btn.addEventListener('click', () => {
        const cur = (typeof s[k] === 'number') ? s[k] : spec.default;
        const next = Math.min(spec.hi, Math.max(spec.lo, cur + (+btn.dataset.d) * spec.step));
        setVentControl(k, Math.round(next * 10000) / 10000);
      }));
      grid.appendChild(tile);
    });
    host.appendChild(grid);
  }
  function _stepCss() {
    return 'width:46px;height:46px;border:0;border-radius:8px;background:#1f3550;color:#cfe0f2;'
      + 'font-size:24px;font-weight:700;cursor:pointer';
  }
  function renderVentAlarms() {
    const tones = ((STATE && STATE.active_alarms) || []).map((a) => typeof a === 'string' ? a : a.tone);
    const el = document.getElementById('vent-alarm-banner'); if (!el) return;
    if (!tones.length) { el.style.display = 'none'; return; }
    el.style.cssText = 'display:block;background:#c0271d;color:#fff;font-weight:700;'
      + 'letter-spacing:.06em;padding:8px 14px;text-align:center';
    el.textContent = '⚠ ' + tones.map((t) => t.replace(/_/g, ' ').toUpperCase()).join('   ·   ');
  }

  async function setVentControl(param, value) {
    try {
      const r = await fetch(`/api/device/${STN}/vent/set`, {
        method: 'POST', headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ param, value }),
      });
      const j = await r.json();
      if (j && j.vent) { VENT = j.vent; renderVentModes(); renderVentNumerics(); renderVentControls(); }
    } catch (e) { /* ignore */ }
  }
  async function ventManeuver(kind) {
    try {
      const r = await fetch(`/api/device/${STN}/vent/maneuver`, {
        method: 'POST', headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ kind }),
      });
      const res = ((await r.json()) || {}).result || {};
      let msg = kind;
      if (res.pplateau != null) msg = 'Pplateau ' + res.pplateau + ' cmH2O';
      else if (res.auto_peep != null) msg = 'Auto-PEEP ' + res.auto_peep + ' (total ' + res.total_peep + ')';
      else if (res.fio2 != null) msg = 'FiO2 → 100%';
      _ventToast(msg); pollVent();
    } catch (e) { /* ignore */ }
  }
  function _ventToast(text) {
    let t = document.getElementById('vent-toast');
    if (!t) {
      t = _vel('div', 'position:fixed;left:50%;top:14%;transform:translateX(-50%);background:#143b8a;'
        + 'color:#fff;padding:12px 20px;border-radius:10px;font-weight:700;z-index:60;transition:opacity .3s');
      t.id = 'vent-toast'; document.body.appendChild(t);
    }
    t.textContent = text; t.style.opacity = '1';
    clearTimeout(t._h); t._h = setTimeout(() => { t.style.opacity = '0'; }, 2600);
  }

  function _audibleTone() {
    const now = Date.now() / 1000, alarms = (STATE && STATE.active_alarms) || [];
    const a = alarms.find((x) => (x.silenced_until || 0) <= now);
    return (a && a.tone) || [...CURRENTLY_LOOPING][0] || (alarms[0] && alarms[0].tone) || null;
  }
  function silenceActive() {
    const tone = _audibleTone(); if (!tone) return;
    stopLoop(tone);
    sendEvent('alarm.silenced', { tone, until: Date.now() / 1000 + (SPEC.silence_seconds || 120) });
  }
  function clearActive() {
    const a = ((STATE && STATE.active_alarms) || [])[0]; if (!a) return;
    sendEvent('alarm.cleared', { tone: a.tone });
  }

  const _VENT_LANES = [
    { k: 'p', label: 'Paw  cmH2O', color: '#f2c14e', lo: -2, hi: 45 },
    { k: 'f', label: 'Flow  L/s', color: '#39d353', lo: -1.3, hi: 1.3 },
    { k: 'v', label: 'Vol  mL', color: '#33d6e6', lo: 0, hi: 1 },
  ];
  function ventFrame(now) {
    _ventRAF = requestAnimationFrame(ventFrame);
    const cx = _ventScalarsCx; if (!cx) return;
    const c = cx.canvas, dpr = window.devicePixelRatio || 1;
    // Keep the backing store matched to the flex-computed client box (so the
    // waveforms fill the grown canvas + survive rotation/resize).
    if (c.width !== Math.round(c.clientWidth * dpr) || c.height !== Math.round(c.clientHeight * dpr)) {
      _sizeVentCanvas(c);
    }
    if (SESSION_STATE !== 'running') return;
    const W = c.clientWidth, H = c.clientHeight;
    cx.clearRect(0, 0, W, H);
    const s = _settings(), d = _ventDerived(s), vt = +s.tidal_volume_ml || 450;
    const lanes = _VENT_LANES.map((l) => (l.k === 'v' ? { ...l, hi: vt * 1.2 } : l));
    const laneH = H / lanes.length, win = Math.max(6, d.period * 2.2), tNow = (now - _ventT0) / 1000;
    lanes.forEach((lane, i) => {
      const y0 = i * laneH;
      cx.strokeStyle = '#1b232f'; cx.lineWidth = 1;
      cx.beginPath(); cx.moveTo(0, y0 + laneH); cx.lineTo(W, y0 + laneH); cx.stroke();
      cx.fillStyle = '#8aa0b6'; cx.font = '11px Arial'; cx.fillText(lane.label, 6, y0 + 14);
      cx.strokeStyle = lane.color; cx.lineWidth = 2; cx.beginPath();
      for (let x = 0; x <= W; x += 2) {
        const lt = tNow - win * (1 - x / W);
        let tb = lt % d.period; if (tb < 0) tb += d.period;
        const norm = (_ventPoint(s, d, tb)[lane.k] - lane.lo) / (lane.hi - lane.lo);
        const y = (y0 + laneH) - Math.max(0, Math.min(1, norm)) * laneH * 0.9;
        if (x === 0) cx.moveTo(x, y); else cx.lineTo(x, y);
      }
      cx.stroke();
    });
  }
  function drawVentLoops() {
    const cx = _ventLoopsCx; if (!cx) return;
    const c = cx.canvas, W = c.clientWidth, H = c.clientHeight;
    cx.clearRect(0, 0, W, H);
    const s = _settings(), d = _ventDerived(s), vt = +s.tidal_volume_ml || 450, half = W / 2;
    const pts = [];
    for (let i = 0; i <= 120; i++) pts.push(_ventPoint(s, d, (i / 120) * d.period));
    cx.fillStyle = '#8aa0b6'; cx.font = '11px Arial';
    cx.fillText('P–V', 8, 14); cx.fillText('F–V', half + 8, 14);
    cx.strokeStyle = '#33d6e6'; cx.lineWidth = 2; cx.beginPath();
    pts.forEach((pt, i) => {
      const x = 10 + (pt.p / 45) * (half - 24), y = H - 12 - (pt.v / (vt * 1.1)) * (H - 30);
      if (i === 0) cx.moveTo(x, y); else cx.lineTo(x, y);
    });
    cx.stroke();
    cx.strokeStyle = '#39d353'; cx.beginPath();
    pts.forEach((pt, i) => {
      const x = half + 10 + (pt.v / (vt * 1.1)) * (half - 24), y = H / 2 - (pt.f / 1.3) * (H / 2 - 18);
      if (i === 0) cx.moveTo(x, y); else cx.lineTo(x, y);
    });
    cx.stroke();
  }

  // ── V6.1.6 / V6.1.7 / M60 — Cabinet (med-cart) patient picker + MAR
  // Hidden by default so the chassis SVG stays visible. The 👤 PATIENT
  // LIST button at the bottom-left pops up a PATIENT PICKER listing
  // every patient character on every encounter linked to this cart
  // (M47 + M59 bugfix #2 ensure CHARACTERS is the full multi-bed
  // roster). Tap a patient → drill into THAT patient's MAR. ← back
  // returns to the picker.
  //
  // Pre-M60 the cart only showed the MAR for the SINGLE instructor-
  // assigned character (delivered via WS assign event); without an
  // assignment the panel stayed empty even when patients were linked.
  //
  // M60 — local state `SELECTED_CHAR_ID` (separate from the
  // server-side ASSIGNED_CHAR_ID) tracks which patient the student
  // is currently looking at. Initialized to ASSIGNED_CHAR_ID for
  // back-compat (instructor-pushed assign drills straight into the
  // MAR like before); operator can override locally at any time.
  let SELECTED_CHAR_ID = null;
  let HIGHLIGHTED_MED = null;   // the MAR med row highlighted (the single button bar acts on it)
  function injectCabinetChecklist() {
    if (KIND !== 'cabinet') return;
    if (!document.getElementById('cabinet-checklist-open')) {
      const btn = document.createElement('button');
      btn.id = 'cabinet-checklist-open';
      btn.type = 'button';
      btn.textContent = '👤 PATIENT LIST';
      btn.style.cssText = 'position:fixed;left:12px;bottom:12px;z-index:49;'
        + 'background:#143b8a;color:#fff;border:0;border-radius:8px;'
        + 'padding:12px 18px;font-size:13px;font-weight:700;letter-spacing:.06em;'
        + 'box-shadow:0 4px 16px rgba(0,0,0,.25);cursor:pointer;'
        + 'font-family:-apple-system,Helvetica,Arial;display:none;';
      btn.addEventListener('click', () => {
        // M60 — opening the picker resets local selection so the
        // operator lands on the patient list, not back inside the
        // last-viewed MAR. Floating button = "show me everyone".
        SELECTED_CHAR_ID = null;
        CHECKLIST_DISMISSED = false;
        renderCabinetChecklist();
      });
      document.body.appendChild(btn);
    }
    renderCabinetChecklist();
  }

  // M60 — Render either:
  //   (a) Patient picker (all CHARACTERS) when no SELECTED_CHAR_ID,
  //   (b) Selected patient's MAR with ← back to picker.
  // Re-runs after every fold so recently-administered meds show
  // their ✓ + timestamp.
  function renderCabinetChecklist() {
    if (KIND !== 'cabinet') return;
    const openBtn = document.getElementById('cabinet-checklist-open');
    // HIPAA gate: no patient picker / MAR / name until the scenario is RUNNING
    // (started) AND a patient is picked. Before start (configured/paused/ended)
    // the cart stays locked — no PHI on screen. Re-runs when applySessionState
    // flips to 'running' (which calls renderFold → here).
    if (SESSION_STATE !== 'running') {
      const existing = document.getElementById('cabinet-checklist');
      if (existing) existing.remove();
      document.body.classList.remove('cab-mar-open');
      if (openBtn) openBtn.style.display = 'none';
      return;
    }
    // M60 — default SELECTED_CHAR_ID to ASSIGNED_CHAR_ID once on
    // first render so instructor-driven assigns drill straight into
    // the MAR like pre-M60. Subsequent picker opens override this.
    if (SELECTED_CHAR_ID == null && ASSIGNED_CHAR_ID) {
      SELECTED_CHAR_ID = ASSIGNED_CHAR_ID;
    }
    const haveAnyChars = CHARACTERS && CHARACTERS.length > 0;
    // Without any linked patients, nothing to show.
    if (!haveAnyChars) {
      const existing = document.getElementById('cabinet-checklist');
      if (existing) existing.remove();
      document.body.classList.remove('cab-mar-open');
      if (openBtn) openBtn.style.display = 'none';
      return;
    }
    // We have linked patients — the floating button shows when
    // dismissed so the operator can re-open.
    if (openBtn) openBtn.style.display = CHECKLIST_DISMISSED ? 'block' : 'none';
    if (CHECKLIST_DISMISSED) {
      const existing = document.getElementById('cabinet-checklist');
      if (existing) existing.remove();
      document.body.classList.remove('cab-mar-open');
      return;
    }
    const selectedChar = SELECTED_CHAR_ID && CHARACTERS.find(
      (c) => c.character_id === SELECTED_CHAR_ID);
    // ── (a) Patient picker — no character selected. ──────────────
    if (!selectedChar) {
      _renderCabinetPicker();
      return;
    }
    // ── (b) Drill into the selected patient's MAR. ───────────────
    _renderCabinetMar(selectedChar);
  }

  // The cabinet MAR + patient-picker render as a Pyxis-styled OVERLAY over the
  // cart graphic's own footprint (CSS .cab-over, mounted inside #device-root), so
  // they sit on the same area as the screen rather than beside it. One creator.
  function _cabinetPanelEl() {
    let panel = document.getElementById('cabinet-checklist');
    if (!panel) {
      panel = document.createElement('div');
      panel.id = 'cabinet-checklist';
    }
    panel.className = 'cab-over';
    panel.style.cssText = '';
    const host = document.getElementById('device-root') || document.body;
    if (panel.parentNode !== host) host.appendChild(panel);
    return panel;
  }

  // Patient picker — Pyxis-styled list inside the overlay.
  function _renderCabinetPicker() {
    const escape = (s) => String(s == null ? '' : s)
      .replace(/&/g, '&amp;').replace(/</g, '&lt;').replace(/>/g, '&gt;')
      .replace(/"/g, '&quot;').replace(/'/g, '&#39;');
    const panel = _cabinetPanelEl();
    let rows = '';
    for (const ch of CHARACTERS) {
      const meds = ch.medications || [];
      const encLabel = ch.encounter_label ? ` · ${escape(ch.encounter_label)}` : '';
      rows += `<button type="button" class="cab-pick-row" data-char-id="${escape(ch.character_id)}">
        <span style="flex:1;min-width:0">
          <span class="nm">${escape(ch.name)}</span>
          <span class="meta">${escape(ch.location_label || '')}${encLabel} · MRN ${escape(ch.mrn || '—')}</span>
        </span>
        <span class="cnt">${meds.length} med${meds.length === 1 ? '' : 's'} →</span>
      </button>`;
    }
    panel.innerHTML = `<div class="cab-over-panel">
      <div class="cab-over-head">
        <span class="ttl">👤 Select a patient</span>
        <span class="sub">${CHARACTERS.length} patient${CHARACTERS.length === 1 ? '' : 's'}</span>
        <button type="button" class="x" id="cabinet-checklist-close">✕</button>
      </div>
      <div class="cab-over-list">${rows}</div>
    </div>`;
    const closeBtn = document.getElementById('cabinet-checklist-close');
    if (closeBtn) closeBtn.addEventListener('click', () => {
      CHECKLIST_DISMISSED = true;
      renderCabinetChecklist();
    });
    panel.querySelectorAll('.cab-pick-row').forEach((btn) => {
      btn.addEventListener('click', () => {
        SELECTED_CHAR_ID = btn.dataset.charId;
        HIGHLIGHTED_MED = null;
        if (STATE) renderFold(STATE); else renderCabinetChecklist();
      });
    });
  }

  // M60 — Drill into the selected patient's MAR. Extracted from the
  // pre-M60 inline render so the patient-picker shares the panel
  // chrome cleanly.
  function _renderCabinetMar(assignedChar) {
    const panel = _cabinetPanelEl();
    const adminLog = (STATE && STATE.administrations) || [];
    const cabinetMeds = (STATE && STATE.medications) || {};
    function locationFor(medName) {
      const needle = String(medName || '').toLowerCase().split(' ')[0];
      if (!needle) return '';
      for (const mid in cabinetMeds) {
        const m = cabinetMeds[mid];
        if (m && String(m.name || '').toLowerCase().includes(needle)) {
          return m.location || '';
        }
      }
      return '';
    }
    function lastAdministered(charId, medName) {
      for (let i = adminLog.length - 1; i >= 0; i--) {
        const a = adminLog[i];
        if (a.character_id === charId
            && String(a.med_name || '').toLowerCase() === String(medName || '').toLowerCase()) {
          return a;
        }
      }
      return null;
    }
    const escape = (s) => String(s == null ? '' : s)
      .replace(/&/g, '&amp;').replace(/</g, '&lt;').replace(/>/g, '&gt;')
      .replace(/"/g, '&quot;').replace(/'/g, '&#39;');
    const ch = assignedChar;
    const meds = ch.medications || [];
    const showBackBtn = (CHARACTERS && CHARACTERS.length > 1);
    const encLabel = ch.encounter_label ? ` · ${escape(ch.encounter_label)}` : '';
    // The single button bar acts on the highlighted med (if still in this list).
    const hiMed = meds.find((m) => m.name === HIGHLIGHTED_MED) || null;
    let rows = '';
    if (!meds.length) {
      rows = `<div class="cab-empty">No active MAR meds for this patient.</div>`;
    } else {
      for (const med of meds) {
        const loc  = locationFor(med.name);
        const last = lastAdministered(ch.character_id, med.name);
        const hi   = med.high_alert ? `<span class="tag hi">HIGH-ALERT</span>` : '';
        const status = med.current_status ? `<span class="tag st">${escape(med.current_status)}</span>` : '';
        const badge = last ? (function () {
          const t = escape(new Date(last.ts * 1000).toLocaleTimeString([], {hour: '2-digit', minute: '2-digit'}));
          const a = last.action || 'administer';
          if (a === 'return') return `<span class="badge ret">↩ RETURNED ${t}</span>`;
          if (a === 'waste')  return `<span class="badge wst">🗑 WASTED ${t}</span>`;
          return `<span class="badge giv">✓ GIVEN ${t}</span>`;
        })() : '';
        const sel = (med.name === HIGHLIGHTED_MED) ? ' selected' : '';
        rows += `<div class="cab-med-row${sel}" data-med-name="${escape(med.name)}" role="button" tabindex="0">
          <span style="flex:1;min-width:0">
            <span class="nm">${escape(med.name)}${hi}${status}</span>
            <span class="meta">${escape(med.dose || med.strength || '')} ${escape(med.route || '')}${loc ? ` · 📍 ${escape(loc)}` : ' · not stocked in this cart'}${med.rationale ? ` · ${escape(med.rationale)}` : ''}</span>
          </span>
          ${badge}
        </div>`;
      }
    }
    const dis = hiMed ? '' : 'disabled';
    panel.innerHTML = `<div class="cab-over-panel">
      <div class="cab-over-head">
        ${showBackBtn ? '<button type="button" class="x" id="cabinet-checklist-back">← Patients</button>' : ''}
        <span class="ttl">💊 MAR · ${escape(ch.name)}</span>
        <span class="sub">${escape(ch.location_label || '')}${encLabel} · MRN ${escape(ch.mrn || '—')} · ${meds.length} med${meds.length === 1 ? '' : 's'}</span>
        <button type="button" class="x" id="cabinet-checklist-close">✕</button>
      </div>
      <div class="cab-over-list">${rows}</div>
      <div class="cab-over-bar">
        <button type="button" class="cab-verb give" data-action="administer" ${dis}>✓ Remove &amp; give</button>
        <button type="button" class="cab-verb ret" data-action="return" ${dis}>↩ Return</button>
        <button type="button" class="cab-verb waste" data-action="waste" ${dis}>🗑 Waste</button>
        <span class="cab-verb-hint">${hiMed ? escape(hiMed.name) : 'Tap a medication above'}</span>
      </div>
    </div>`;
    const closeBtn = document.getElementById('cabinet-checklist-close');
    if (closeBtn) closeBtn.addEventListener('click', () => {
      CHECKLIST_DISMISSED = true;
      renderCabinetChecklist();
    });
    const backBtnEl = document.getElementById('cabinet-checklist-back');
    if (backBtnEl) backBtnEl.addEventListener('click', () => {
      SELECTED_CHAR_ID = null; HIGHLIGHTED_MED = null;
      if (STATE) renderFold(STATE); else renderCabinetChecklist();
    });
    // Highlight one med (single selection); the button bar then acts on it.
    panel.querySelectorAll('.cab-med-row').forEach((row) => {
      const pick = () => { HIGHLIGHTED_MED = row.dataset.medName; renderCabinetChecklist(); };
      row.addEventListener('click', pick);
      row.addEventListener('keydown', (e) => {
        if (e.key === 'Enter' || e.key === ' ') { e.preventDefault(); pick(); }
      });
    });
    // The single Remove/Return/Waste bar acts on the highlighted med.
    panel.querySelectorAll('.cab-verb').forEach((btn) => {
      btn.addEventListener('click', () => {
        if (btn.disabled || !hiMed) return;
        const action = btn.dataset.action || 'administer';
        if (!AUDIO_UNLOCKED) unlockAudio();
        panel.querySelectorAll('.cab-verb').forEach((b) => { b.disabled = true; });
        const original = btn.textContent;
        btn.textContent = '…';
        sendEvent('cabinet.administer', {
          action:          action,
          character_id:    ch.character_id,
          character_name:  ch.name,
          med_name:        hiMed.name,
          dose:            hiMed.dose || hiMed.strength || '',
          route:           hiMed.route || '',
          med_location:    locationFor(hiMed.name),
          scan_used:       false,
          administered_by: (STATE && STATE.session_user) || 'student',
        }).finally(() => {
          setTimeout(() => { btn.textContent = original; renderCabinetChecklist(); }, 700);
        });
      });
    });
  }

  // ── PROGRAM modal (student-facing pump programming) ────────────────
  // ONLY real pumps get the on-screen programming workflow. Cabinets have their
  // own touchscreen; monitors / ventilator / PIA must never show a PROGRAM PUMP
  // button (FR-012 — it was leaking onto the advanced devices).
  function injectProgramButton() {
    if (KIND !== 'pump_iv' && KIND !== 'pump_enteral') return;
    if (document.getElementById('device-program-btn')) return;
    const btn = document.createElement('button');
    btn.id = 'device-program-btn';
    btn.type = 'button';
    btn.textContent = '⚙ PROGRAM PUMP';
    btn.style.cssText = 'position:fixed;left:12px;bottom:12px;z-index:50;'
      + 'background:#143b8a;color:#fff;border:0;border-radius:8px;'
      + 'padding:14px 22px;font-size:14px;font-weight:700;letter-spacing:.08em;'
      + 'box-shadow:0 4px 16px rgba(0,0,0,.25);cursor:pointer;'
      + 'font-family:-apple-system,Helvetica,Arial;';
    btn.addEventListener('click', () => {
      if (!AUDIO_UNLOCKED) unlockAudio();   // also primes audio
      openProgramModal();
    });
    document.body.appendChild(btn);
  }

  function openProgramModal() {
    const existing = document.getElementById('device-program-modal');
    if (existing) existing.remove();
    const isEnteral = KIND === 'pump_enteral';
    const channels  = (SPEC.channels || ['A']);
    const drugs     = (SPEC.drug_library || []);
    const modes     = (SPEC.modes || ['continuous']);
    const defaults  = SPEC.default_program || {};

    const root = document.createElement('div');
    root.id = 'device-program-modal';
    root.style.cssText = 'position:fixed;inset:0;background:rgba(15,23,42,.55);'
      + 'z-index:90;display:flex;align-items:center;justify-content:center;'
      + 'padding:16px;font-family:-apple-system,Helvetica,Arial;';
    root.innerHTML = `
      <div style="background:#fff;color:#0a234f;max-width:420px;width:100%;
                  border-radius:10px;padding:22px;max-height:92vh;overflow-y:auto;
                  box-shadow:0 10px 40px rgba(0,0,0,.3)">
        <h2 style="margin:0 0 4px;font-size:18px">Program ${isEnteral ? 'feed' : 'infusion'}</h2>
        <p style="color:#6b7896;font-size:13px;margin:0 0 6px">
          ${isEnteral ? 'Pick a mode then enter rate + volume.' :
            'Pick a channel and a drug, then enter rate + VTBI. Soft-limit overrides are logged.'}
        </p>
        <p style="color:#3a4a6b;font-size:12px;margin:0 0 14px;background:#f4f7fc;padding:6px 8px;border-radius:4px">
          💡 You can also use the pump's <em>number pad</em> on the SVG — taps go to whichever field is focused. Tap CLEAR on the pump to empty a field.
        </p>
        <form id="pgm-form">
          ${isEnteral ? '' : `
            <label style="display:block;margin:10px 0 4px;font-size:12px;font-weight:600;color:#3a4a6b">Channel</label>
            <select id="pgm-channel" style="width:100%;padding:9px;font-size:15px;border:1px solid #dde2ee;border-radius:6px">
              ${channels.map(c => `<option value="${c}">Channel ${c}</option>`).join('')}
            </select>`}
          ${isEnteral ? `
            <label style="display:block;margin:10px 0 4px;font-size:12px;font-weight:600;color:#3a4a6b">Mode</label>
            <select id="pgm-mode" style="width:100%;padding:9px;font-size:15px;border:1px solid #dde2ee;border-radius:6px">
              ${modes.map(m => `<option value="${m}"${m === defaults.mode ? ' selected' : ''}>${m}</option>`).join('')}
            </select>` : `
            <label style="display:block;margin:10px 0 4px;font-size:12px;font-weight:600;color:#3a4a6b">Drug</label>
            <select id="pgm-drug" style="width:100%;padding:9px;font-size:15px;border:1px solid #dde2ee;border-radius:6px">
              ${drugs.map(d => `<option value="${d.code}">${d.label}</option>`).join('')}
            </select>`}
          <label style="display:block;margin:10px 0 4px;font-size:12px;font-weight:600;color:#3a4a6b">Rate (mL/hr)</label>
          <input id="pgm-rate" type="text" inputmode="decimal" pattern="[0-9]*\\.?[0-9]*"
                 value="${defaults.rate_ml_hr || ''}"
                 style="width:100%;padding:9px;font-size:15px;border:1px solid #dde2ee;border-radius:6px">
          <label style="display:block;margin:10px 0 4px;font-size:12px;font-weight:600;color:#3a4a6b">
            ${isEnteral ? 'Volume (mL)' : 'VTBI — volume to be infused (mL)'}
          </label>
          <input id="pgm-vtbi" type="text" inputmode="decimal" pattern="[0-9]*\\.?[0-9]*"
                 value="${defaults.volume_ml || ''}"
                 style="width:100%;padding:9px;font-size:15px;border:1px solid #dde2ee;border-radius:6px">
          <div id="pgm-warning" style="margin-top:10px;padding:8px 10px;border-radius:6px;font-size:12px;display:none"></div>
          <div style="margin-top:18px;display:flex;gap:8px;justify-content:flex-end">
            <button type="button" id="pgm-cancel" style="background:#eee;color:#3a4a6b;border:0;border-radius:6px;padding:9px 16px;font-weight:600;cursor:pointer">Cancel</button>
            <button type="submit" style="background:#143b8a;color:#fff;border:0;border-radius:6px;padding:9px 16px;font-weight:600;cursor:pointer">Confirm</button>
          </div>
        </form>
      </div>`;
    document.body.appendChild(root);

    const warn = root.querySelector('#pgm-warning');
    const setWarn = (msg, kind) => {
      if (!msg) { warn.style.display = 'none'; return; }
      warn.style.display = 'block';
      warn.textContent = msg;
      if (kind === 'block') {
        warn.style.background = '#fdecea'; warn.style.color = '#962d22';
      } else {
        warn.style.background = '#fff5d6'; warn.style.color = '#7a5400';
      }
    };
    let pendingOverride = false;

    const validateAndDescribe = () => {
      pendingOverride = false;
      if (isEnteral) { setWarn(''); return {ok: true}; }
      const drug = drugs.find((d) => d.code === root.querySelector('#pgm-drug').value);
      if (!drug || !drug.limits || !drug.limits.rate_ml_hr) { setWarn(''); return {ok: true}; }
      const lim = drug.limits.rate_ml_hr;
      const rate = parseFloat(root.querySelector('#pgm-rate').value) || 0;
      if (rate < lim.hard_min || rate > lim.hard_max) {
        setWarn(`Rate ${rate} mL/hr is outside Guardrails hard limits (${lim.hard_min}–${lim.hard_max}). Blocked.`, 'block');
        return {ok: false};
      }
      if (rate < lim.soft_min || rate > lim.soft_max) {
        setWarn(`Rate ${rate} mL/hr is outside soft limits (${lim.soft_min}–${lim.soft_max}). Confirm to override (logged).`, 'soft');
        pendingOverride = true;
        return {ok: true, soft_override: true};
      }
      setWarn('');
      return {ok: true};
    };
    root.querySelector('#pgm-form').addEventListener('input', validateAndDescribe);
    if (!isEnteral) root.querySelector('#pgm-drug').addEventListener('change', validateAndDescribe);

    root.querySelector('#pgm-cancel').addEventListener('click', () => root.remove());
    root.addEventListener('click', (e) => { if (e.target === root) root.remove(); });
    root.querySelector('#pgm-form').addEventListener('submit', async (e) => {
      e.preventDefault();
      const check = validateAndDescribe();
      if (!check.ok) return;
      const rate = parseFloat(root.querySelector('#pgm-rate').value) || 0;
      const vtbi = parseFloat(root.querySelector('#pgm-vtbi').value) || 0;
      if (isEnteral) {
        await sendEvent('feed.program', {
          mode: root.querySelector('#pgm-mode').value,
          rate_ml_hr: rate,
          volume_ml:  vtbi,
        });
      } else {
        const drug = drugs.find((d) => d.code === root.querySelector('#pgm-drug').value);
        const ch = root.querySelector('#pgm-channel').value;
        // V6.1.3 — keep the SVG screen lookup in sync with which channel
        // the user just programmed via the modal. Without this, scr-drug
        // / scr-channel / scr-dose stay pinned to the previously-focused
        // channel (e.g. the screen kept showing Norepinephrine after the
        // user reprogrammed channel A with a different med).
        PROG.channel = ch;
        await sendEvent('pump.program', {
          channel:        ch,
          drug_code:      drug ? drug.code  : '',
          drug_label:     drug ? drug.label : '',
          rate_ml_hr:     rate,
          vtbi_ml:        vtbi,
          library_used:   !!(drug && drug.limits),
          soft_override:  !!check.soft_override,
        });
      }
      root.remove();
    });
  }

  // Re-add the PROGRAM button (pumps) or CHECKLIST (cabinets) whenever
  // the page settles. mountSkin() can clobber siblings during a re-render,
  // so be defensive.
  const _origMountSkin = mountSkin;
  mountSkin = function (svgText) {
    _origMountSkin(svgText);
    injectProgramButton();
    injectCabinetChecklist();
  };

  // Kick off.
  bootstrap();
})();
