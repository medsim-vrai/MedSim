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
  const DEVICE_JS_BUILD = 'v6.1.7';
  console.log('[MEDSIM device] booting build', DEVICE_JS_BUILD);
  const body = document.body;
  const JOIN  = body.dataset.joinCode;
  const STN   = body.dataset.stationId;
  const KIND  = body.dataset.deviceKind;
  const MODEL = body.dataset.deviceModel;

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
      AUDIO_URLS = b.audio_urls || {};
      STATE = b.state || {};
      SESSION_STATE = b.session_state || 'running';
      mountSkin(b.skin_svg || '');
      renderFold(STATE);
      applySessionState(SESSION_STATE);
      $loading.hidden = true;
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
    if (key === 'patient' && state.patient) return state.patient.name || state.patient.id;
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
      if (openBtn) openBtn.style.display = 'none';
      return;
    }
    // We have linked patients — the floating button shows when
    // dismissed so the operator can re-open.
    if (openBtn) openBtn.style.display = CHECKLIST_DISMISSED ? 'block' : 'none';
    if (CHECKLIST_DISMISSED) {
      const existing = document.getElementById('cabinet-checklist');
      if (existing) existing.remove();
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

  // M60 — Patient picker: cards for every patient in CHARACTERS.
  function _renderCabinetPicker() {
    const escape = (s) => String(s == null ? '' : s)
      .replace(/&/g, '&amp;').replace(/</g, '&lt;').replace(/>/g, '&gt;')
      .replace(/"/g, '&quot;').replace(/'/g, '&#39;');
    let panel = document.getElementById('cabinet-checklist');
    if (!panel) {
      panel = document.createElement('div');
      panel.id = 'cabinet-checklist';
      panel.style.cssText = 'position:fixed;left:0;right:0;bottom:0;'
        + 'max-height:62vh;overflow-y:auto;background:#f6f8fb;'
        + 'border-top:2px solid #2b3956;z-index:48;padding:10px 14px 16px;'
        + 'font-family:-apple-system,Helvetica,Arial;color:#1b2733;'
        + 'box-shadow:0 -4px 18px rgba(0,0,0,.18);';
      document.body.appendChild(panel);
    }
    let html = `<div style="display:flex;justify-content:space-between;align-items:center;margin-bottom:8px">
      <div>
        <strong style="font-size:14px;color:#2b3956">👤 Pick a patient</strong>
        <div style="font-size:11px;color:#6b7896;margin-top:2px">${CHARACTERS.length} patient${CHARACTERS.length === 1 ? '' : 's'} on linked encounters</div>
      </div>
      <button type="button" id="cabinet-checklist-close"
        style="background:transparent;color:#6b7896;border:1px solid #c2cad8;border-radius:6px;padding:4px 10px;font-size:18px;cursor:pointer;line-height:1;font-weight:700">✕</button>
    </div>`;
    html += '<div style="display:flex;flex-direction:column;gap:6px">';
    for (const ch of CHARACTERS) {
      const meds = ch.medications || [];
      const encLabel = ch.encounter_label ? ` · ${escape(ch.encounter_label)}` : '';
      html += `<button type="button" class="cabinet-pick-patient"
        data-char-id="${escape(ch.character_id)}"
        style="text-align:left;background:#fff;border:1px solid #dde2ee;border-radius:8px;
               padding:10px 14px;cursor:pointer;font-family:inherit;color:#1b2733;
               display:flex;justify-content:space-between;align-items:center;gap:8px">
        <div style="flex:1;min-width:0">
          <div style="font-size:14px;font-weight:700">${escape(ch.name)}</div>
          <div style="font-size:11px;color:#6b7896;margin-top:2px">
            ${escape(ch.location_label || '')}${encLabel} · MRN ${escape(ch.mrn || '—')}
          </div>
        </div>
        <div style="text-align:right;flex-shrink:0">
          <div style="background:#e9edf6;color:#3a4a6b;padding:2px 8px;border-radius:10px;font-size:11px;font-weight:600">
            ${meds.length} med${meds.length === 1 ? '' : 's'}
          </div>
          <div style="font-size:18px;color:#6b7896;margin-top:2px">→</div>
        </div>
      </button>`;
    }
    html += '</div>';
    panel.innerHTML = html;
    const closeBtn = document.getElementById('cabinet-checklist-close');
    if (closeBtn) closeBtn.addEventListener('click', () => {
      CHECKLIST_DISMISSED = true;
      renderCabinetChecklist();
    });
    panel.querySelectorAll('.cabinet-pick-patient').forEach((btn) => {
      btn.addEventListener('click', () => {
        SELECTED_CHAR_ID = btn.dataset.charId;
        renderCabinetChecklist();
      });
    });
  }

  // M60 — Drill into the selected patient's MAR. Extracted from the
  // pre-M60 inline render so the patient-picker shares the panel
  // chrome cleanly.
  function _renderCabinetMar(assignedChar) {
    let panel = document.getElementById('cabinet-checklist');
    if (!panel) {
      panel = document.createElement('div');
      panel.id = 'cabinet-checklist';
      panel.style.cssText = 'position:fixed;left:0;right:0;bottom:0;'
        + 'max-height:62vh;overflow-y:auto;background:#f6f8fb;'
        + 'border-top:2px solid #2b3956;z-index:48;padding:10px 14px 16px;'
        + 'font-family:-apple-system,Helvetica,Arial;color:#1b2733;'
        + 'box-shadow:0 -4px 18px rgba(0,0,0,.18);';
      document.body.appendChild(panel);
    }
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
    // M60 — only show the "← Patients" back-button when there's more
    // than one patient to return to. Single-patient carts collapse
    // the picker step entirely.
    const showBackBtn = (CHARACTERS && CHARACTERS.length > 1);
    const backBtn = showBackBtn
      ? `<button type="button" id="cabinet-checklist-back"
           style="background:transparent;color:#143b8a;border:1px solid #c2cad8;border-radius:6px;padding:4px 10px;font-size:12px;font-weight:700;cursor:pointer;margin-right:6px">
           ← Patients
         </button>`
      : '';
    const encLabel = ch.encounter_label ? ` · ${escape(ch.encounter_label)}` : '';
    let html = `<div style="display:flex;justify-content:space-between;align-items:center;margin-bottom:8px">
      <div style="display:flex;align-items:center;gap:6px;flex-wrap:wrap">
        ${backBtn}
        <div>
          <strong style="font-size:14px;color:#2b3956">💊 MAR · ${escape(ch.name)}</strong>
          <div style="font-size:11px;color:#6b7896;margin-top:2px">${escape(ch.location_label || '')}${encLabel} · MRN ${escape(ch.mrn || '—')} · ${meds.length} med${meds.length === 1 ? '' : 's'}</div>
        </div>
      </div>
      <button type="button" id="cabinet-checklist-close"
        style="background:transparent;color:#6b7896;border:1px solid #c2cad8;border-radius:6px;padding:4px 10px;font-size:18px;cursor:pointer;line-height:1;font-weight:700">✕</button>
    </div>`;
    if (!meds.length) {
      html += `<div style="padding:18px;background:#fff;border:1px dashed #d3d9e4;border-radius:8px;color:#6b7896;font-size:13px;text-align:center">No active MAR meds for this patient.</div>`;
    } else {
      html += `<div style="background:#fff;border:1px solid #dde2ee;border-radius:8px;padding:6px 12px">`;
      for (const med of meds) {
        const loc  = locationFor(med.name);
        const last = lastAdministered(ch.character_id, med.name);
        const hi   = med.high_alert ? `<span style="background:#fdecea;color:#962d22;border:1px solid #f5c0c1;padding:0 6px;border-radius:3px;font-size:10px;font-weight:700;margin-left:6px">HIGH-ALERT</span>` : '';
        const status = med.current_status
          ? `<span style="background:#e9edf6;color:#3a4a6b;padding:0 6px;border-radius:3px;font-size:10px;font-weight:600;margin-left:6px">${escape(med.current_status)}</span>`
          : '';
        const givenBadge = last
          ? `<span style="background:#dff5e3;color:#1d6334;border:1px solid #b1d8bd;padding:2px 8px;border-radius:4px;font-size:11px;font-weight:700">✓ GIVEN ${escape(new Date(last.ts * 1000).toLocaleTimeString([], {hour:'2-digit', minute:'2-digit'}))}</span>`
          : '';
        html += `<div style="display:flex;justify-content:space-between;align-items:center;padding:6px 0;border-top:1px solid #f0f3f8">
          <div style="flex:1;min-width:0">
            <div style="font-size:13px;font-weight:600">${escape(med.name)}${hi}${status}</div>
            <div style="font-size:11px;color:#6b7896;margin-top:2px">
              ${escape(med.dose || med.strength || '')} ${escape(med.route || '')} ·
              ${loc ? `📍 <code style="background:#eef0f4;padding:1px 4px;border-radius:3px">${escape(loc)}</code>` : `<span style="color:#9aa3b8">not stocked in this cart</span>`}
              ${med.rationale ? ` · ${escape(med.rationale)}` : ''}
            </div>
          </div>
          <div style="display:flex;gap:6px;align-items:center;margin-left:8px">
            ${givenBadge}
            <button type="button" class="cabinet-take-btn"
              data-char-id="${escape(ch.character_id)}" data-char-name="${escape(ch.name)}"
              data-med-name="${escape(med.name)}" data-dose="${escape(med.dose || med.strength || '')}"
              data-route="${escape(med.route || '')}" data-location="${escape(loc)}"
              style="background:#143b8a;color:#fff;border:0;border-radius:6px;padding:7px 12px;font-size:12px;font-weight:700;cursor:pointer;letter-spacing:.04em">✓ TAKE</button>
          </div>
        </div>`;
      }
      html += `</div>`;
    }
    panel.innerHTML = html;
    const closeBtn = document.getElementById('cabinet-checklist-close');
    if (closeBtn) closeBtn.addEventListener('click', () => {
      CHECKLIST_DISMISSED = true;
      renderCabinetChecklist();
    });
    // M60 — ← Patients button drops back to the picker.
    const backBtnEl = document.getElementById('cabinet-checklist-back');
    if (backBtnEl) backBtnEl.addEventListener('click', () => {
      SELECTED_CHAR_ID = null;
      renderCabinetChecklist();
    });
    panel.querySelectorAll('.cabinet-take-btn').forEach((btn) => {
      btn.addEventListener('click', () => {
        const d = btn.dataset;
        if (!AUDIO_UNLOCKED) unlockAudio();
        btn.disabled = true;
        const original = btn.textContent;
        btn.textContent = '…';
        sendEvent('cabinet.administer', {
          character_id:   d.charId,
          character_name: d.charName,
          med_name:       d.medName,
          dose:           d.dose,
          route:          d.route,
          med_location:   d.location,
          scan_used:      false,
          administered_by: (STATE && STATE.session_user) || 'student',
        }).finally(() => {
          setTimeout(() => { btn.disabled = false; btn.textContent = original; }, 800);
        });
      });
    });
  }

  // ── PROGRAM modal (student-facing pump programming) ────────────────
  // Cabinets have their own touchscreen workflow; only pumps get this.
  function injectProgramButton() {
    if (KIND === 'cabinet') return;
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
