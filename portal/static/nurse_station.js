// MEDSIM V7 Phase 7 M27 — Nursing Station in-sim student page.
//
// Polls /api/room/state (room shape + per-encounter pills),
// /api/room/alarms (active alarms), and /api/encounter/{id}/telemetry
// per bed (compact telemetry strip). Renders one card per encounter
// with mini ECG, telemetry, device pills, and an alarm board at the
// top of the page.

(function () {
  'use strict';

  const cfg = window.NURSE_STATION || {};
  const $ = (id) => document.getElementById(id);
  const POLL_MS = 2000;

  let ecgCatalog = [];
  const bedECGControllers = new Map(); // encounter_id → ECGStrip controller

  function escapeHTML(s) {
    return String(s == null ? '' : s)
      .replace(/&/g, '&amp;').replace(/</g, '&lt;')
      .replace(/>/g, '&gt;').replace(/"/g, '&quot;');
  }

  async function bootECGCatalog() {
    try {
      const r = await fetch('/api/ecg/catalog', {credentials: 'same-origin'});
      if (r.ok) {
        const body = await r.json();
        ecgCatalog = body.catalog || [];
      }
    } catch (_) { /* no-op */ }
  }
  function rhythmById(id) {
    return ecgCatalog.find(e => e.id === id) || null;
  }

  function renderBedCard(enc) {
    const card = document.createElement('article');
    card.className = 'bed-card';
    card.dataset.encounterId = enc.encounter_id;
    card.innerHTML = `
      <h3>
        <span>${escapeHTML(enc.label || enc.scenario_name)}</span>
        <span class="bed-join">${escapeHTML(enc.join_code)}</span>
      </h3>
      <div class="telemetry">
        <div class="cell"><span class="label">HR</span>
          <span class="value" data-metric="hr">—</span></div>
        <div class="cell"><span class="label">BP</span>
          <span class="value" data-metric="bp">—/—</span></div>
        <div class="cell"><span class="label">SpO₂</span>
          <span class="value" data-metric="spo2">—</span></div>
        <div class="cell"><span class="label">RR</span>
          <span class="value" data-metric="rr">—</span></div>
        <div class="cell"><span class="label">T</span>
          <span class="value" data-metric="temp">—</span></div>
      </div>
      <div class="ecg-mini" data-ecg></div>
      <div class="pills" data-pills></div>
      <div class="bed-card-actions">
        <button type="button" class="ns-code-blue-btn"
                data-code-blue="${escapeHTML(enc.encounter_id)}"
                title="Fire a code.blue scene at this bed.">🚨 Code Blue</button>
      </div>
    `;
    // M50 — Code Blue button per bed card. POSTs to the new
    // /api/room/encounter/{eid}/nurse_code_blue route with the
    // nurse-station student's sid (validates the supervisor's
    // identity server-side). Same scene the instructor's
    // scene-inject would fire.
    const cbBtn = card.querySelector('[data-code-blue]');
    if (cbBtn) {
      cbBtn.addEventListener('click', async () => {
        if (!window.confirm(
          `Fire Code Blue at ${enc.label || enc.scenario_name}?\n\n`
          + `This injects a code.blue scene at the bed — alarms `
          + `+ chart entry are written immediately.`)) return;
        cbBtn.disabled = true;
        const eid = cbBtn.dataset.codeBlue;
        try {
          const r = await fetch(
            `/api/room/encounter/${encodeURIComponent(eid)}/nurse_code_blue`,
            {
              method: 'POST', credentials: 'same-origin',
              headers: {'Content-Type': 'application/json'},
              body: JSON.stringify({
                nurse_sid: (window.NURSE_STATION || {}).studentId || '',
              }),
            },
          );
          if (!r.ok) {
            const txt = await r.text();
            window.alert(`Code Blue failed (${r.status}): ${txt}`);
          }
        } catch (err) {
          window.alert('Code Blue network error: ' + err);
        } finally {
          cbBtn.disabled = false;
          pollOnce();
        }
      });
    }
    return card;
  }

  async function pollTelemetryForBed(card, encounter_id) {
    try {
      const r = await fetch(
        `/api/encounter/${encodeURIComponent(encounter_id)}/telemetry`,
        {credentials: 'same-origin'},
      );
      if (!r.ok) return;
      const t = await r.json();
      const overrides = new Set(t.overrides_active || []);
      const set = (metric, val, isOverride) => {
        const el = card.querySelector(`[data-metric="${metric}"]`);
        if (el) {
          el.textContent = val;
          el.classList.toggle('override', isOverride);
        }
      };
      set('hr',   t.hr   ?? '—', overrides.has('hr'));
      set('bp',   `${t.sbp ?? '—'}/${t.dbp ?? '—'}`,
                  overrides.has('sbp') || overrides.has('dbp'));
      set('spo2', t.spo2 != null ? t.spo2 : '—', overrides.has('spo2'));
      set('rr',   t.rr   ?? '—', overrides.has('rr'));
      set('temp', t.temp_f != null ? t.temp_f : '—', overrides.has('temp_f'));
    } catch (_) { /* no-op */ }
  }

  async function refreshECGForBed(card, encounter_id) {
    try {
      const r = await fetch(
        `/api/encounter/${encodeURIComponent(encounter_id)}/ecg`,
        {credentials: 'same-origin'},
      );
      if (!r.ok) return;
      const ecg = await r.json();
      const host = card.querySelector('[data-ecg]');
      if (!host) return;
      if (!ecg.enabled) {
        host.classList.add('disabled');
        host.innerHTML = '<p class="muted small">ECG off</p>';
        bedECGControllers.get(encounter_id)?.stop();
        bedECGControllers.delete(encounter_id);
        return;
      }
      host.classList.remove('disabled');
      const rhythm = ecg.rhythm || rhythmById(ecg.rhythm_id);
      if (!rhythm || !window.ECGStrip) return;
      const existing = bedECGControllers.get(encounter_id);
      if (existing) {
        existing.setRhythm(rhythm);
      } else {
        host.innerHTML = '';
        const ctrl = window.ECGStrip.attach(host,
          {rhythm, height: 70, secondsVisible: 5});
        bedECGControllers.set(encounter_id, ctrl);
      }
    } catch (_) { /* no-op */ }
  }

  function alarmsForEncounter(alarms, encounter_id) {
    return (alarms || []).filter(a => a.encounter_id === encounter_id);
  }

  function renderAlarmBoard(alarms) {
    const list = $('alarm-list');
    if (!list) return;
    if (!alarms.length) {
      list.innerHTML = '<li class="muted small">No active alarms.</li>';
      // M52 — alarms list went empty; reset the last-played map so
      // the next new alarm fires immediately even if the alarm_id
      // matches a recently-cleared one.
      _audioLastAt.clear();
      // M54 — also clear the fast-ticker cache so the danger-tier
      // ticker stops re-firing once the alarm board is empty.
      _lastAlarmsForAudio = [];
      return;
    }
    // M52 — Play clinical-alarm sounds REPEATEDLY until each alarm
    // clears.  Cadence depends on priority (see AUDIO_REPEAT_MS).
    // Server-side `alarm_sounds.annotate` adds `audio_url` per alarm.
    // M54 — Cache the list for the 700 ms fast ticker so danger-tier
    // alarms (code blue) re-fire faster than the 3 s state poll.
    _lastAlarmsForAudio = alarms;
    _playNewAlarmSounds(alarms);
    list.innerHTML = alarms.map(a => {
      // M50 — silenced alarms render greyed out with a badge so the
      // supervisor can see audio is muted but the breach is still
      // active. Cleared alarms don't reach here (filtered by the
      // server-side _apply_silenced).
      const silenced = a.silenced ? ' silenced' : '';
      const silencedBadge = a.silenced
        ? ' <span class="silenced-badge">🔇 silenced</span>' : '';
      return `
      <li class="severity-${escapeHTML(a.severity)}${silenced}">
        <span>
          <strong>${escapeHTML(a.label || a.kind)}</strong>
          <span class="muted small"> · ${escapeHTML(a.encounter_label || '')}</span>
          ${silencedBadge}
        </span>
        <span class="alarm-actions">
          <button type="button" data-silence="${escapeHTML(a.alarm_id)}"
                  title="Mute audio for 45 s without clearing the breach (audio resumes after if still active)">🔇 Silence</button>
          <button type="button" data-alarm="${escapeHTML(a.alarm_id)}">Clear</button>
        </span>
      </li>
    `;}).join('');
    list.querySelectorAll('button[data-alarm]').forEach(btn => {
      btn.addEventListener('click', async () => {
        btn.disabled = true;
        await fetch(`/api/alarm/${encodeURIComponent(btn.dataset.alarm)}/clear`,
                     {method: 'POST', credentials: 'same-origin'});
        pollOnce();
      });
    });
    // M50/M52 — silence button: POSTs to /api/alarm/{id}/silence (default 45s — M52).
    list.querySelectorAll('button[data-silence]').forEach(btn => {
      btn.addEventListener('click', async () => {
        btn.disabled = true;
        await fetch(`/api/alarm/${encodeURIComponent(btn.dataset.silence)}/silence`,
                     {method: 'POST', credentials: 'same-origin'});
        pollOnce();
      });
    });
  }

  // M49 + M52 + M54 — Clinical alarm audio dispatcher (repeating,
  // concurrent, tiered by severity).
  //
  // Each alarm dict the server emits carries `audio_url`,
  // `audio_priority`, and `severity` fields.
  //
  // M54 — Operator: "For higher priority alarms (low- medium-High)
  // the alarms sound more frequently. For example the sound loop for
  // a code blue should run continuously with minimal time gap".
  // Cadence is now four tiers driven by severity (with audio_priority
  // as a fallback for older alarm dicts):
  //
  //    danger   2500 ms  — code blue + dangerous rhythms; near-continuous
  //    high     5000 ms  — critical alarms
  //    medium  15000 ms  — warning alarms
  //    low     35000 ms  — info alarms (call bell, low-magnitude breaches)
  //
  // Pre-M54: high=8000, medium=20000, low=45000 — tightened across
  // the board. The new "danger" bucket gets a separate audio loop
  // that ticks every 700 ms (see _fastAudioTick below) so the 2.5 s
  // cadence isn't gated by the 3 s state-poll interval.
  //
  // Concurrency: each alarm gets its own `new Audio(url).play()` call
  // so the browser plays multiple WAVs simultaneously. Two beds in
  // simultaneous breach => two overlapping tones, intentionally
  // (matches real bedside monitor behaviour).
  //
  // Silenced alarms (`a.silenced=true`) skip the play call entirely.
  // The server-side _apply_silenced filter expires the silence after
  // 45 s by default (M52), so the very next poll after the window
  // lapses sees the alarm with `silenced=false` and the dispatcher
  // re-fires.
  //
  // When the active list drops an id (cleared, or auto-resolved by a
  // threshold returning to range), we delete its last-played entry so
  // a re-occurrence of the SAME alarm_id fires immediately.
  const AUDIO_REPEAT_MS = {
    danger:  2500,   // M54 — near-continuous (code blue / dangerous rhythms)
    high:    5000,   // critical
    medium: 15000,   // warning
    low:    35000,   // info
  };
  const _audioLastAt = new Map();   // alarm_id → ms timestamp
  // M54 — Cache of the last alarm payload from the 3 s state poll.
  // A faster ticker (700 ms) re-evaluates the dispatcher against
  // this cache so the danger tier truly fires every ~2.5 s instead
  // of being capped at the poll interval.
  let _lastAlarmsForAudio = [];
  function _audioCadenceTier(a) {
    // M54 — severity wins (so "danger" maps to its own tier even
    // though severity_to_priority on the server lumps it into "high"
    // for WAV lookup purposes). Fall back to audio_priority when
    // severity is missing.
    const sev = (a.severity || '').toLowerCase();
    if (sev === 'danger') return 'danger';
    return a.audio_priority || 'medium';
  }
  function _playNewAlarmSounds(alarms) {
    const active = new Set();
    const now = Date.now();
    alarms.forEach(a => {
      const sid = a.alarm_id;
      if (!sid) return;
      active.add(sid);
      // M50 — skip audio for silenced alarms. They stay visible on
      // the board with the 🔇 badge, but no sound until the silence
      // expires.
      if (a.silenced) return;
      const url = a.audio_url;
      if (!url) return;
      const tier = _audioCadenceTier(a);
      const cadence = AUDIO_REPEAT_MS[tier] || AUDIO_REPEAT_MS.medium;
      const last = _audioLastAt.get(sid) || 0;
      if (now - last < cadence) return;   // M52 — not yet time to re-fire
      _audioLastAt.set(sid, now);
      try {
        // M54 — Each alarm spawns its OWN Audio instance, so multiple
        // active alarms play CONCURRENTLY (HR + SpO2 + code blue all
        // overlap, intentional — matches a real bedside monitor).
        const audio = new Audio(url);
        audio.volume = 0.8;
        // Catch the autoplay-policy promise rejection cleanly —
        // the first user gesture on the page unlocks subsequent
        // plays; until then a few rejections are expected.
        const p = audio.play();
        if (p && typeof p.catch === 'function') {
          p.catch(() => {});
        }
      } catch (e) { /* DOM error — ignore */ }
    });
    // Drop alarm_ids that are no longer active so they re-fire if
    // the same breach occurs again (e.g. SpO2 dips, recovers, dips
    // again — operator hears the sound both times).
    for (const sid of Array.from(_audioLastAt.keys())) {
      if (!active.has(sid)) _audioLastAt.delete(sid);
    }
  }

  async function pollOnce() {
    try {
      const r = await fetch('/api/room/state', {credentials: 'same-origin'});
      if (r.status === 404) {
        $('ns-status').textContent = 'Room ended.';
        return;
      }
      if (!r.ok) return;
      const state = await r.json();
      const alarmsBody = await (await fetch('/api/room/alarms',
                                                {credentials: 'same-origin'})).json();
      renderAlarmBoard(alarmsBody.alarms || []);

      // Build (or reuse) one bed card per encounter.
      const grid = $('ns-grid');
      if (!grid) return;
      // First pass — render any missing cards.
      const wanted = new Set();
      state.encounters.forEach(enc => {
        wanted.add(enc.encounter_id);
        let card = grid.querySelector(`[data-encounter-id="${enc.encounter_id}"]`);
        if (!card) {
          card = renderBedCard(enc);
          grid.appendChild(card);
        }
        // Pills: alert pills (state + alarm count).
        const pills = card.querySelector('[data-pills]');
        const alarmCount = alarmsForEncounter(alarmsBody.alarms, enc.encounter_id).length;
        pills.innerHTML =
          `<span class="pill">${escapeHTML(enc.state.toUpperCase())}</span>` +
          (enc.chart_mode === 'private_clone'
            ? '<span class="pill">private clone</span>' : '') +
          (alarmCount
            ? `<span class="pill alarm">${alarmCount} alarm${alarmCount === 1 ? '' : 's'}</span>`
            : '') +
          `<span class="pill">${enc.device_stations} dev</span>` +
          `<span class="pill">${enc.chat_stations} chat</span>`;
        // Trigger per-bed telemetry + ECG fetches.
        pollTelemetryForBed(card, enc.encounter_id);
        refreshECGForBed(card, enc.encounter_id);
      });
      // Remove cards for encounters that disappeared (room shrunk).
      grid.querySelectorAll('.bed-card').forEach(card => {
        if (!wanted.has(card.dataset.encounterId)) card.remove();
      });
      // Empty-state hint.
      if (state.encounters.length === 0) {
        grid.innerHTML = '<p class="muted small">No encounters in this room yet.</p>';
      } else if (grid.querySelector('p.muted')) {
        // Drop initial "loading…" placeholder if any survived.
        const placeholders = grid.querySelectorAll('p.muted');
        placeholders.forEach(p => p.remove());
      }
      $('ns-status').textContent = `last poll ${new Date().toLocaleTimeString()}`;
    } catch (err) {
      console.warn('nurse_station poll failed', err);
      $('ns-status').textContent = 'Network error.';
    }
  }

  let pollTimer = null;
  function startPolling() {
    if (pollTimer) return;
    const tick = async () => { await pollOnce(); pollTimer = setTimeout(tick, POLL_MS); };
    tick();
  }
  document.addEventListener('visibilitychange', () => {
    if (document.hidden && pollTimer) { clearTimeout(pollTimer); pollTimer = null; }
    else if (!document.hidden && !pollTimer) startPolling();
  });

  // ── M48 — Alarm threshold settings ───────────────────────────────

  async function loadThresholds() {
    try {
      const r = await fetch('/api/room/alarm_thresholds',
                             {credentials: 'same-origin'});
      if (!r.ok) return;
      const body = await r.json();
      const t = body.thresholds || {};
      const setField = (id, val) => {
        const el = document.getElementById(id);
        if (el) el.value = (val == null) ? '' : val;
      };
      setField('th-hr-low',    (t.hr   || {}).low);
      setField('th-hr-high',   (t.hr   || {}).high);
      setField('th-spo2-low',  (t.spo2 || {}).low);
      setField('th-spo2-high', (t.spo2 || {}).high);
      setField('th-rr-low',    (t.rr   || {}).low);
      setField('th-rr-high',   (t.rr   || {}).high);
      // M50 — BP systolic + diastolic.
      setField('th-sbp-low',   (t.bp_systolic  || {}).low);
      setField('th-sbp-high',  (t.bp_systolic  || {}).high);
      setField('th-dbp-low',   (t.bp_diastolic || {}).low);
      setField('th-dbp-high',  (t.bp_diastolic || {}).high);
      const danger = new Set(t.dangerous_rhythms || []);
      document.querySelectorAll('[data-danger]').forEach(cb => {
        cb.checked = danger.has(cb.dataset.danger);
      });
    } catch (err) { console.warn('thresholds load failed', err); }
  }

  function readField(id) {
    const el = document.getElementById(id);
    if (!el || el.value.trim() === '') return null;
    const n = Number(el.value);
    return Number.isFinite(n) ? n : null;
  }

  async function saveThresholds(ev) {
    ev.preventDefault();
    const status = document.getElementById('ns-thresholds-status');
    const danger = Array.from(
      document.querySelectorAll('[data-danger]:checked'),
    ).map(cb => cb.dataset.danger);
    const body = {
      hr:   {low: readField('th-hr-low'),   high: readField('th-hr-high')},
      spo2: {low: readField('th-spo2-low'), high: readField('th-spo2-high')},
      rr:   {low: readField('th-rr-low'),   high: readField('th-rr-high')},
      // M50 — BP systolic + diastolic.
      bp_systolic:  {low: readField('th-sbp-low'),  high: readField('th-sbp-high')},
      bp_diastolic: {low: readField('th-dbp-low'),  high: readField('th-dbp-high')},
      dangerous_rhythms: danger,
    };
    if (status) status.textContent = 'saving…';
    try {
      const r = await fetch('/api/room/alarm_thresholds', {
        method: 'POST', credentials: 'same-origin',
        headers: {'Content-Type': 'application/json'},
        body: JSON.stringify(body),
      });
      if (!r.ok) {
        if (status) status.textContent = `save failed (${r.status})`;
        return;
      }
      if (status) status.textContent =
        `saved · ${new Date().toLocaleTimeString()}`;
    } catch (err) {
      if (status) status.textContent = 'network error';
    }
  }

  document.addEventListener('DOMContentLoaded', async () => {
    await bootECGCatalog();
    startPolling();
    // M48 — load + wire the threshold form.
    loadThresholds();
    const form = document.getElementById('ns-thresholds-form');
    if (form) form.addEventListener('submit', saveThresholds);
    // M54 — collapse/expand on header click.
    wireThresholdToggle();
    // M54 — Fast audio ticker. The 3 s state poll caches the latest
    // alarms list in _lastAlarmsForAudio; this 700 ms ticker re-runs
    // the dispatcher against that cache so the 2.5 s danger-tier
    // cadence isn't gated by the slower poll. Other tiers (high/
    // medium/low) all have cadences ≥ 5 s so they remain effectively
    // gated by the poll — only danger gets the boost.
    setInterval(() => {
      if (_lastAlarmsForAudio && _lastAlarmsForAudio.length) {
        _playNewAlarmSounds(_lastAlarmsForAudio);
      }
    }, 700);
  });

  // ── M54 — Collapsible threshold panel ──────────────────────────────
  //
  // Operator wants the threshold settings to roll up by default so
  // the alarm board owns the top of the page. Header (an h2) is
  // styled as a button; click toggles a `ns-collapsed` class on the
  // section. The form's display goes to none via CSS so the form
  // submit handler doesn't accidentally fire from a hidden input
  // (browsers skip submit on hidden forms).
  function wireThresholdToggle() {
    const section = document.getElementById('ns-thresholds');
    const toggle  = document.getElementById('ns-thresholds-toggle');
    if (!section || !toggle) return;
    const setState = (expanded) => {
      if (expanded) {
        section.classList.remove('ns-collapsed');
        toggle.setAttribute('aria-expanded', 'true');
      } else {
        section.classList.add('ns-collapsed');
        toggle.setAttribute('aria-expanded', 'false');
      }
    };
    toggle.addEventListener('click', () => {
      const expanded = !section.classList.contains('ns-collapsed');
      setState(!expanded);
    });
    // Keyboard accessibility — space/enter toggles when focused.
    toggle.addEventListener('keydown', (ev) => {
      if (ev.key === 'Enter' || ev.key === ' ') {
        ev.preventDefault();
        const expanded = !section.classList.contains('ns-collapsed');
        setState(!expanded);
      }
    });
  }
})();
