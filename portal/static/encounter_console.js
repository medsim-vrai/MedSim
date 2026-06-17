// MEDSIM V7 Phase 7 — Per-Patient Console (M22 scaffold + M25 rich).
//
// Polls the encounter's telemetry every 1s, renders the ECG strip
// continuously, lists bound devices from /api/room/state, and lets
// the operator set per-metric telemetry overrides + change the ECG
// rhythm + enable/disable the ECG display.

(function () {
  'use strict';

  const cfg = window.ENCOUNTER_CONSOLE || {};
  const $ = (id) => document.getElementById(id);
  const TELEMETRY_POLL_MS = 1000;
  const STATE_POLL_MS     = 2000;

  let ecgController = null;
  let ecgCatalog    = [];
  let telemetryTimer = null;
  let stateTimer     = null;

  function escapeHTML(s) {
    return String(s == null ? '' : s)
      .replace(/&/g, '&amp;').replace(/</g, '&lt;')
      .replace(/>/g, '&gt;').replace(/"/g, '&quot;');
  }

  // ── Setup: load ECG catalog and current encounter ECG state ─────
  async function bootECG() {
    const r = await fetch('/api/ecg/catalog', {credentials: 'same-origin'});
    if (!r.ok) return;
    const body = await r.json();
    ecgCatalog = body.catalog || [];

    // Populate the rhythm picker.
    const picker = $('ecg-waveform-picker');
    if (picker) {
      picker.innerHTML = ecgCatalog.map(e =>
        `<option value="${e.id}">${e.label}</option>`).join('');
      picker.disabled = false;
      picker.addEventListener('change', async () => {
        await postEcg({rhythm_id: picker.value});
      });
    }

    // Enabled toggle.
    const toggle = $('ecg-enabled');
    if (toggle) {
      toggle.disabled = false;
      toggle.addEventListener('change', async () => {
        await postEcg({enabled: toggle.checked});
      });
    }

    // Fetch the encounter's current ECG state.
    const r2 = await fetch(
      `/api/encounter/${encodeURIComponent(cfg.encounterId)}/ecg`,
      {credentials: 'same-origin'},
    );
    if (r2.ok) {
      const ecg = await r2.json();
      if (picker) picker.value = ecg.rhythm_id;
      if (toggle) toggle.checked = !!ecg.enabled;
      mountECG(ecg);
    }
  }

  function mountECG(ecg) {
    const canvas = $('ecg-canvas');
    if (!canvas) return;
    if (!ecg.enabled) {
      canvas.innerHTML = '<p class="muted small">ECG display disabled. Toggle "Show ECG…" above to start.</p>';
      ecgController?.stop();
      ecgController = null;
      return;
    }
    if (!ecg.rhythm) {
      canvas.innerHTML = '<p class="muted small">Unknown rhythm.</p>';
      return;
    }
    if (ecgController) {
      ecgController.setRhythm(ecg.rhythm);
    } else if (window.ECGStrip) {
      ecgController = window.ECGStrip.attach(canvas, {
        rhythm: ecg.rhythm, height: 110, secondsVisible: 6,
      });
    }
  }

  async function postEcg(patch) {
    const r = await fetch(
      `/api/encounter/${encodeURIComponent(cfg.encounterId)}/ecg`,
      {method: 'POST', credentials: 'same-origin',
       headers: {'Content-Type': 'application/json'},
       body: JSON.stringify(patch)},
    );
    if (!r.ok) return;
    mountECG(await r.json());
  }

  // ── FR-012 — ventilator clinical-state picker ───────────────────
  // Pick a state and the vent settings + patient condition + vitals all align
  // (the telemetry strip + monitor + nurse station follow). Per-parameter
  // injects / vent controls still fine-tune.
  async function bootVentState() {
    const picker = $('vent-state-picker');
    if (!picker) return;
    try {
      const r = await fetch('/api/vent/state_presets', {credentials: 'same-origin'});
      if (!r.ok) return;
      const presets = (await r.json()).presets || [];
      picker.innerHTML = '<option value="">— select a state —</option>'
        + presets.map(p => `<option value="${p.id}">${p.label}</option>`).join('');
      picker.disabled = false;
      picker.addEventListener('change', async () => {
        if (!picker.value) return;
        await fetch(`/api/encounter/${encodeURIComponent(cfg.encounterId)}/vent_state`,
          {method: 'POST', credentials: 'same-origin',
           headers: {'Content-Type': 'application/json'},
           body: JSON.stringify({state_id: picker.value})});
      });
    } catch (e) { /* best effort */ }
  }

  // ── Telemetry strip ─────────────────────────────────────────────
  //
  // M48 — Per-metric refresh cadence. The server poll runs every 1 s
  // (TELEMETRY_POLL_MS) so the underlying number is always fresh,
  // but the *displayed* value commits at the cadence below per
  // metric to match real bedside monitor refresh rates:
  //   spo2 → 10 s, rr → 30 s, temp → 60 s, bp → 120 s
  //   hr   → 10 s (continuous-ish)
  // Operator scene/inject (via /api/encounter/{id}/scene or
  // /telemetry/override) forces an immediate refresh because the
  // server-side `as_of` timestamp jumps forward — the client sees a
  // newer reading than the last cadence-stamped value.
  const METRIC_CADENCE_MS = {
    hr:     10_000,
    sbp:   120_000,
    dbp:   120_000,
    spo2:   10_000,
    rr:     30_000,
    temp_f: 60_000,
  };
  // Last-committed value per metric + the timestamp we committed it.
  // Initialized to nulls so the very first poll commits everything.
  const _committed = {hr: null, sbp: null, dbp: null, spo2: null,
                       rr: null, temp_f: null};
  const _committedAt = {hr: 0, sbp: 0, dbp: 0, spo2: 0, rr: 0, temp_f: 0};

  function _maybeCommit(metric, latestValue, now) {
    const cadence = METRIC_CADENCE_MS[metric] || 1000;
    const last = _committedAt[metric] || 0;
    // First commit, OR cadence elapsed, OR the server's value
    // genuinely changed (operator inject / override) → commit now.
    if (last === 0 || (now - last) >= cadence
        || _committed[metric] !== latestValue) {
      _committed[metric]   = latestValue;
      _committedAt[metric] = now;
      return true;
    }
    return false;
  }

  async function pollTelemetry() {
    try {
      const r = await fetch(
        `/api/encounter/${encodeURIComponent(cfg.encounterId)}/telemetry`,
        {credentials: 'same-origin'},
      );
      if (!r.ok) return;
      const t = await r.json();
      const now = Date.now();
      // Commit per-metric on cadence. The DISPLAYED value is the last
      // committed value, not the live server value.
      _maybeCommit('hr',     t.hr,     now);
      _maybeCommit('sbp',    t.sbp,    now);
      _maybeCommit('dbp',    t.dbp,    now);
      _maybeCommit('spo2',   t.spo2,   now);
      _maybeCommit('rr',     t.rr,     now);
      _maybeCommit('temp_f', t.temp_f, now);
      $('t-hr').textContent   = _committed.hr ?? '—';
      $('t-bp').textContent   = `${_committed.sbp ?? '—'}/${_committed.dbp ?? '—'}`;
      $('t-spo2').textContent = _committed.spo2 != null ? `${_committed.spo2}%` : '—';
      $('t-rr').textContent   = _committed.rr ?? '—';
      $('t-temp').textContent = _committed.temp_f != null ? `${_committed.temp_f}°F` : '—';
      // Visual override indicator — color the overridden cells.
      const overrides = new Set(t.overrides_active || []);
      const map = {hr: 't-hr', sbp: 't-bp', spo2: 't-spo2',
                    rr: 't-rr', temp_f: 't-temp'};
      Object.entries(map).forEach(([metric, elId]) => {
        const el = $(elId);
        if (el) el.style.color = overrides.has(metric)
          ? '#962d22' : '#1a2a4a';
      });
      const last = $('telemetry-last-update');
      if (last) last.textContent =
        `last poll ${new Date().toLocaleTimeString()}` +
        (overrides.size ? ` · overrides: ${[...overrides].join(', ')}` : '');

      if (!$('override-grid').dataset.populated) {
        renderOverrideControls();
      }
    } catch (err) {
      console.warn('telemetry poll failed', err);
    }
  }

  function renderOverrideControls() {
    const host = $('override-grid');
    if (!host) return;
    host.dataset.populated = '1';
    host.innerHTML = '';
    const metrics = [
      {key: 'hr',     label: 'HR',     step: 1,   min: 20,  max: 220},
      {key: 'sbp',    label: 'SBP',    step: 1,   min: 40,  max: 220},
      {key: 'dbp',    label: 'DBP',    step: 1,   min: 20,  max: 140},
      {key: 'spo2',   label: 'SpO₂',   step: 1,   min: 50,  max: 100},
      {key: 'rr',     label: 'RR',     step: 1,   min: 4,   max: 50},
      {key: 'temp_f', label: 'Temp',   step: 0.1, min: 90,  max: 108},
    ];
    metrics.forEach(m => {
      const cell = document.createElement('div');
      cell.className = 'override-cell';
      cell.innerHTML = `
        <label class="small muted">${m.label}
          <input type="number" data-metric="${m.key}" step="${m.step}"
                 min="${m.min}" max="${m.max}" placeholder="—">
        </label>
        <button type="button" data-clear="${m.key}" class="link small muted">clear</button>
      `;
      host.appendChild(cell);
    });
    host.querySelectorAll('input[data-metric]').forEach(inp => {
      inp.addEventListener('change', async () => {
        const metric = inp.dataset.metric;
        const value  = inp.value === '' ? null : Number(inp.value);
        if (value === null) {
          await postOverride({clear: metric});
        } else {
          await postOverride({[metric]: value});
        }
      });
    });
    host.querySelectorAll('button[data-clear]').forEach(btn => {
      btn.addEventListener('click', async () => {
        await postOverride({clear: btn.dataset.clear});
        const inp = host.querySelector(`input[data-metric="${btn.dataset.clear}"]`);
        if (inp) inp.value = '';
      });
    });
  }

  async function postOverride(patch) {
    await fetch(
      `/api/encounter/${encodeURIComponent(cfg.encounterId)}/telemetry/override`,
      {method: 'POST', credentials: 'same-origin',
       headers: {'Content-Type': 'application/json'},
       body: JSON.stringify(patch)},
    );
    pollTelemetry();
  }

  // ── Device list + state poll ────────────────────────────────────
  async function pollState() {
    try {
      const r = await fetch('/api/room/state', {credentials: 'same-origin'});
      if (r.status === 404) {
        $('enc-state').textContent = 'NO ROOM';
        return;
      }
      if (!r.ok) return;
      const state = await r.json();
      const enc = state.encounters.find(e => e.encounter_id === cfg.encounterId);
      if (!enc) {
        $('enc-state').textContent = 'NOT FOUND';
        return;
      }
      $('enc-state').textContent = (enc.state || '').toUpperCase();
      // M53 — surface the free-text lead label from Multi-Patient
      // Control as a read-only reference banner. The M30 roster-
      // picked lead is handled separately by the picker below.
      _updateLeadLabelRef(enc.lead_label || '');
    } catch (err) {
      console.warn('state poll failed', err);
    }
  }

  // M53 + M57 — Show/hide the lead label in three places on every
  // state poll:
  //   * the prominent header pill at the top of the page
  //     (`#lead-student-banner` + `#lead-student-name`)
  //   * the read-only banner inside the lead-student card
  //     (`#lead-label-ref` + `#lead-label-ref-text`)
  //   * the empty-state hint inside the lead-student card
  //     (`#lead-empty-hint`)
  //
  // The lead_label is server-derived; the bedside instructor doesn't
  // edit it here (the editor lives on Multi-Patient Control). When
  // the operator types a label there, this function surfaces the
  // change on the next 2 s state poll. The template also pre-renders
  // both surfaces server-side so labels already set are visible on
  // first paint without waiting for the poll.
  //
  // Empty label → ref banner hidden, empty-state hint shown.
  //
  // M57 — pre-fix this also fell back to a stashed M30 roster pick
  // when the M53 label was empty (via `nameSpan.dataset.rosterName`).
  // The M30 picker has been removed, so the fallback path is gone.
  function _updateLeadLabelRef(label) {
    const clean = (label || '').trim();
    // Card-level banner.
    const ref  = $('lead-label-ref');
    const text = $('lead-label-ref-text');
    if (ref && text) {
      if (clean) {
        ref.hidden = false;
        text.textContent = clean;
      } else {
        ref.hidden = true;
        text.textContent = '';
      }
    }
    // M57 — Empty-state hint shows when no label is set so the card
    // isn't visually empty.
    const emptyHint = $('lead-empty-hint');
    if (emptyHint) emptyHint.hidden = !!clean;
    // Header pill — make the lead label PROMINENT next to the
    // encounter title so the operator sees it at a glance.
    const hdr     = $('lead-student-banner');
    const hdrName = $('lead-student-name');
    if (hdr && hdrName) {
      if (clean) {
        hdr.hidden = false;
        hdrName.textContent = clean;
      } else {
        hdr.hidden = true;
        hdrName.textContent = '';
      }
    }
  }

  // ── M45 — Inline device control cards ────────────────────────────
  //
  // After a device is added via the "Managed devices" modal, render
  // its full control surface inline in the Devices card so the
  // instructor doesn't have to reopen the modal for everyday
  // operations (inject alarm, clear, reassign, advance time).
  //
  // Data comes from /api/device/roster?join=<encounter join code>
  // (M43 — that route is now multi-patient aware).  Polls every 3s
  // alongside the existing state/telemetry/transcript loops.

  // Tone catalog per device kind. Hard-coded here to avoid an extra
  // round-trip on every poll; the server-side authoritative catalog
  // lives in portal/devices/engine/alarms.py and validates each
  // inject call, so a stale client list at worst causes the server
  // to 400 with a clear error.  Tone IDs MUST match the server's
  // catalog (PUMP_ALARMS / CABINET_ALERTS in alarms.py) — this is
  // a curated subset of the most common training alarms.
  const DEVICE_TONE_CATALOG = {
    pump_iv: [
      'occlusion_downstream', 'occlusion_upstream', 'air_in_line',
      'low_battery', 'depleted_battery', 'infusion_complete',
      'door_open', 'system_error',
    ],
    pump_enteral: [
      'occlusion_downstream', 'occlusion_upstream',
      'low_battery', 'feed_complete', 'near_end_prealarm',
    ],
    cabinet: [
      'discrepancy_alert', 'witness_required', 'inventory_low',
      'drawer_open', 'network_offline', 'security_alert',
    ],
  };
  const KIND_LABEL = {
    pump_iv: '💧 IV pump',
    pump_enteral: '🥣 Enteral pump',
    cabinet: '🛒 Med cart',
    call_bell: '🔔 Call bell',
    bed_alarm: '🛏 Bed alarm',
    code_blue_button: '🚨 Code blue',
    fire_alarm: '🚒 Fire alarm',
    // M51 — Patient Integrated Alarm (PIA).
    patient_integrated_alarm: '📟 Patient Integrated Alarm',
  };

  // Persona display name lookup so the assignment dropdown can show
  // names, not just persona ids.  Built from /api/encounter/{id}/voices
  // when bootVoices runs — we cache `encVoiceBody.personas`.
  function personaNameFor(pid) {
    const personas = (encVoiceBody && encVoiceBody.personas) || [];
    const hit = personas.find(p => p.id === pid);
    return hit ? hit.name : pid;
  }

  async function pollDevices() {
    const devList = $('device-list');
    if (!devList) return;
    try {
      const r = await fetch(
        `/api/device/roster?join=${encodeURIComponent(cfg.joinCode || '')}`,
        {credentials: 'same-origin'},
      );
      if (!r.ok) return;
      const body = await r.json();
      renderDeviceCards(body.stations || []);
    } catch (err) {
      console.warn('device poll failed', err);
    }
  }

  function renderDeviceCards(stations) {
    const devList = $('device-list');
    if (!devList) return;
    if (!stations.length) {
      devList.innerHTML =
        '<li class="muted small">No devices bound to this encounter. Click <strong>🔧 Managed devices</strong> above to add one.</li>';
      return;
    }
    devList.innerHTML = stations.map(s => renderDeviceCard(s)).join('');
    // Wire per-card actions.
    devList.querySelectorAll('[data-act]').forEach(el => {
      el.addEventListener('click', () => onDeviceAction(el));
    });
    devList.querySelectorAll('select[data-assign]').forEach(sel => {
      sel.addEventListener('change', () => onDeviceAssign(sel));
    });
  }

  function renderDeviceCard(s) {
    const kindLabel = KIND_LABEL[s.device_kind] || s.device_kind;
    const onlineDot = s.online
      ? '<span class="dev-dot dev-online" title="Online">●</span>'
      : '<span class="dev-dot dev-offline" title="Offline (waiting for heartbeat)">●</span>';
    const tones = DEVICE_TONE_CATALOG[s.device_kind] || [];
    const isPump = (s.device_kind === 'pump_iv' || s.device_kind === 'pump_enteral');
    const isCabinet = s.device_kind === 'cabinet';
    const personas = (encVoiceBody && encVoiceBody.personas) || [];
    const assignOpts =
      '<option value="">— unassigned —</option>' +
      personas.map(p =>
        `<option value="${escapeHTML(p.id)}"${p.id === s.character_id ? ' selected' : ''}>`
        + `${escapeHTML(p.name || p.id)}</option>`
      ).join('');
    const activeAlarms = (s.active_alarms || []).map(a => {
      const silenced = a.silenced ? ' (silenced)' : '';
      return `<li class="dev-alarm-row">
        <span class="dev-alarm-tone">${escapeHTML(a.tone)}${silenced}</span>
        <button type="button" class="dev-btn-sm"
                data-act="clear-one" data-station="${escapeHTML(s.station_id)}"
                data-tone="${escapeHTML(a.tone)}">Clear</button>
      </li>`;
    }).join('');
    const toneOptions = tones.map(t =>
      `<option value="${escapeHTML(t)}">${escapeHTML(t)}</option>`,
    ).join('');
    const cabinetNote = isCabinet
      ? '<p class="muted small" style="margin:6px 0 0">Med cart (room-level) — reassignment + cart MAR managed at the room level.</p>'
      : '';
    // M51 — Instructor mirror controls for the Patient Integrated
    // Alarm. Mirrors the 4 student-side buttons (call bell, bed
    // alarm, code blue, intercom) — pressing here fires the same
    // server-side handler as the bedside tablet would.
    const isPia = s.device_kind === 'patient_integrated_alarm';
    const piaPanel = isPia ? `
      <div class="device-card-pia">
        <p class="muted small" style="margin:6px 0 4px">📟 Instructor mirror — fire any event on this bed's PIA tablet.</p>
        <div class="pia-mirror-row">
          <button type="button" class="dev-btn-sm pia-mirror-btn"
                  data-act="pia" data-pia-action="call_bell"
                  data-station="${escapeHTML(s.station_id)}">🔔 Call Bell</button>
          <button type="button" class="dev-btn-sm pia-mirror-btn"
                  data-act="pia" data-pia-action="bed_alarm"
                  data-station="${escapeHTML(s.station_id)}">🛏 Bed Alarm</button>
          <button type="button" class="dev-btn-sm pia-mirror-btn pia-mirror-cb"
                  data-act="pia" data-pia-action="code_blue"
                  data-station="${escapeHTML(s.station_id)}">🚨 Code Blue</button>
          <button type="button" class="dev-btn-sm pia-mirror-btn"
                  data-act="pia" data-pia-action="intercom_request"
                  data-station="${escapeHTML(s.station_id)}">🎙 Intercom</button>
        </div>
      </div>` : '';
    // M46 — Per-device QR strip. The device's join URL is the same
    // shape /api/device/register returned at mint time
    // (`/device/join?code=<join>&station=<sid>`). We don't need a
    // separate API call — construct it from the encounter's join
    // code (cfg.joinCode) + this station's id, then hit the
    // shared /api/qr.svg endpoint. Operators can scan with a phone
    // OR print the encounter's QR sheet (M41) which now includes
    // these device QRs.
    const joinCode = cfg.joinCode || '';
    const deviceJoinUrl =
      `${window.location.origin}/device/join?code=${encodeURIComponent(joinCode)}`
      + `&station=${encodeURIComponent(s.station_id)}`;
    const qrSrc = `/api/qr.svg?data=${encodeURIComponent(deviceJoinUrl)}`;
    return `<li class="device-card" data-station-id="${escapeHTML(s.station_id)}">
      <div class="device-card-header">
        <span class="device-card-name">${kindLabel} · <strong>${escapeHTML(s.label || s.device_model)}</strong></span>
        <span class="device-card-meta">${onlineDot} ${escapeHTML(s.runtime_state || '')}</span>
      </div>
      <div class="device-card-qr">
        <img class="device-card-qr-img" src="${qrSrc}"
             alt="QR for ${escapeHTML(s.label || s.device_model)}">
        <code class="device-card-qr-url">${escapeHTML(deviceJoinUrl)}</code>
      </div>
      <div class="device-card-assignment">
        <label class="small muted">Patient
          <select data-assign data-station="${escapeHTML(s.station_id)}">${assignOpts}</select>
        </label>
        <span class="dev-pid muted small">${escapeHTML(s.station_id)}</span>
      </div>
      ${activeAlarms ? `<ul class="dev-alarm-list">${activeAlarms}</ul>` : ''}
      <div class="device-card-actions">
        ${tones.length ? `
          <select class="dev-tone-picker" data-station="${escapeHTML(s.station_id)}">
            ${toneOptions}
          </select>
          <button type="button" class="dev-btn-sm dev-btn-inject"
                  data-act="inject" data-station="${escapeHTML(s.station_id)}">⚠ Inject</button>
        ` : ''}
        ${(s.active_alarms && s.active_alarms.length) ? `
          <button type="button" class="dev-btn-sm"
                  data-act="clear-all" data-station="${escapeHTML(s.station_id)}">✓ Clear all</button>
        ` : ''}
        ${isPump ? `
          <span class="dev-time-group">
            <button type="button" class="dev-btn-sm" data-act="advance" data-station="${escapeHTML(s.station_id)}" data-minutes="5">+5m</button>
            <button type="button" class="dev-btn-sm" data-act="advance" data-station="${escapeHTML(s.station_id)}" data-minutes="15">+15m</button>
            <button type="button" class="dev-btn-sm" data-act="advance" data-station="${escapeHTML(s.station_id)}" data-minutes="60">+1h</button>
          </span>
        ` : ''}
      </div>
      ${cabinetNote}
      ${piaPanel}
    </li>`;
  }

  async function onDeviceAction(el) {
    const station = el.dataset.station;
    const act     = el.dataset.act;
    if (!station || !act) return;
    el.disabled = true;
    try {
      if (act === 'inject') {
        const card  = el.closest('.device-card');
        const picker = card?.querySelector('.dev-tone-picker');
        const tone  = picker?.value || '';
        if (!tone) return;
        await fetch(`/api/device/${encodeURIComponent(station)}/inject`, {
          method: 'POST', credentials: 'same-origin',
          headers: {'Content-Type': 'application/json'},
          body: JSON.stringify({tone}),
        });
      } else if (act === 'clear-one') {
        const tone = el.dataset.tone;
        await fetch(`/api/device/${encodeURIComponent(station)}/clear`, {
          method: 'POST', credentials: 'same-origin',
          headers: {'Content-Type': 'application/json'},
          body: JSON.stringify({tone}),
        });
      } else if (act === 'clear-all') {
        await fetch(`/api/device/${encodeURIComponent(station)}/clear`, {
          method: 'POST', credentials: 'same-origin',
          headers: {'Content-Type': 'application/json'},
          body: JSON.stringify({all: true}),
        });
      } else if (act === 'advance') {
        const minutes = parseInt(el.dataset.minutes || '0', 10);
        if (!minutes) return;
        await fetch(`/api/device/${encodeURIComponent(station)}/advance_time`, {
          method: 'POST', credentials: 'same-origin',
          headers: {'Content-Type': 'application/json'},
          body: JSON.stringify({minutes}),
        });
      } else if (act === 'pia') {
        // M51 — Instructor mirror of a Patient Integrated Alarm
        // button press. Same route the bedside tablet uses; server
        // hook routes to the same code path. data-pia-action carries
        // the four actions (call_bell / bed_alarm / code_blue /
        // intercom_request).
        const piaAction = el.dataset.piaAction || '';
        if (!piaAction) return;
        if (piaAction === 'code_blue' &&
            !window.confirm('Fire Code Blue at this bed? Cascades to nurses station + all PIAs.')) {
          return;
        }
        await fetch(`/api/device/${encodeURIComponent(station)}/event`, {
          method: 'POST', credentials: 'same-origin',
          headers: {'Content-Type': 'application/json'},
          body: JSON.stringify({
            type: 'pia.button',
            payload: {action: piaAction, by: 'instructor'},
          }),
        });
      }
      // Refresh device cards so the new state shows up immediately.
      pollDevices();
    } catch (err) {
      console.warn('device action failed', err);
    } finally {
      el.disabled = false;
    }
  }

  async function onDeviceAssign(sel) {
    const station = sel.dataset.station;
    const character_id = sel.value || null;
    sel.disabled = true;
    try {
      await fetch(`/api/device/${encodeURIComponent(station)}/assign`, {
        method: 'POST', credentials: 'same-origin',
        headers: {'Content-Type': 'application/json'},
        body: JSON.stringify({character_id}),
      });
      pollDevices();
    } catch (err) {
      console.warn('assign failed', err);
    } finally {
      sel.disabled = false;
    }
  }

  // ── Scene injector (M22 + carried forward) ─────────────────────
  $('scene-form-console')?.addEventListener('submit', async (ev) => {
    ev.preventDefault();
    const kind = $('scene-kind-console').value;
    let params = {};
    const raw = $('scene-params-console').value.trim();
    if (raw) {
      try { params = JSON.parse(raw); }
      catch { $('scene-status-console').textContent = 'Params is not valid JSON.'; return; }
    }
    const status = $('scene-status-console');
    status.textContent = 'Injecting…';
    try {
      const r = await fetch(`/api/encounter/${encodeURIComponent(cfg.encounterId)}/scene`, {
        method: 'POST', credentials: 'same-origin',
        headers: {'Content-Type': 'application/json'},
        body: JSON.stringify({scene: {kind, params}}),
      });
      if (!r.ok) {
        const detail = await r.text();
        status.textContent = `Inject failed (${r.status}). ${detail}`;
      } else {
        status.textContent = `Injected ${kind} at ${new Date().toLocaleTimeString()}`;
        pollTelemetry();
      }
    } catch (err) {
      status.textContent = 'Network error: ' + err;
    }
  });

  // ── Populate device-kinds summary (M1.5) ────────────────────────
  async function bootDeviceKinds() {
    const span = $('device-kinds-summary');
    if (span) span.textContent = 'pump_iv, pump_enteral, cabinet, call_bell, bed_alarm, code_blue_button, fire_alarm';
  }

  // ── M30 — Pop-out button ────────────────────────────────────────
  $('btn-popout')?.addEventListener('click', () => {
    const w = window.open(window.location.pathname + '?popout=1',
                           `encounter_${cfg.encounterId}`,
                           'width=620,height=900,resizable=yes,scrollbars=yes');
    if (w) w.focus();
  });

  // ── M35 — per-encounter Start / Pause / End ─────────────────────
  // These mirror the master header buttons on /portal/room but
  // affect only THIS encounter. End here does NOT fire the cohort
  // debrief — that only happens when the master End fires.
  async function postEncounterAction(action, opts = {}) {
    const r = await fetch(
      `/api/encounter/${encodeURIComponent(cfg.encounterId)}/${action}`,
      {method: 'POST', credentials: 'same-origin'},
    );
    if (!r.ok) {
      alert(`${action} failed (${r.status}).`);
      return null;
    }
    return r.json().catch(() => ({}));
  }
  $('btn-enc-start')?.addEventListener('click', async () => {
    const body = await postEncounterAction('start');
    if (!body) return;
    const stateBadge = $('enc-state');
    if (stateBadge && body.state) stateBadge.textContent = body.state.toUpperCase();
  });
  $('btn-enc-pause')?.addEventListener('click', async () => {
    const body = await postEncounterAction('pause');
    if (!body) return;
    const stateBadge = $('enc-state');
    if (stateBadge && body.state) stateBadge.textContent = body.state.toUpperCase();
  });
  $('btn-enc-end')?.addEventListener('click', async (ev) => {
    const confirm = ev.currentTarget.getAttribute('data-confirm');
    if (confirm && !window.confirm(confirm)) return;
    const body = await postEncounterAction('end');
    if (!body) return;
    const stateBadge = $('enc-state');
    if (stateBadge && body.state) stateBadge.textContent = body.state.toUpperCase();
  });

  // ── Lead student — picker removed (operator: "remove the other
  // parts in the leads area since they add no value"). The M30
  // roster picker + status line + "Lead (roster)" label are gone.
  // The M53 free-text label set on Multi-Patient Control is the
  // single source of truth.
  //
  // bootLeadStudent is kept as an empty stub so the existing
  // DOMContentLoaded `await bootLeadStudent()` call still resolves
  // without 404 noise (the GET endpoint is still wired for the
  // cohort-debrief module path).
  async function bootLeadStudent() { /* no-op since lead picker removed */ }

  // ── M30 — Live transcript poll ──────────────────────────────────
  async function pollTranscript() {
    try {
      const r = await fetch(
        `/api/encounter/${encodeURIComponent(cfg.encounterId)}/transcript?limit=40`,
        {credentials: 'same-origin'},
      );
      if (!r.ok) return;
      const body = await r.json();
      const pane = $('transcript-pane');
      const meta = $('transcript-meta');
      if (!pane) return;
      const rows = body.transcript || [];
      if (rows.length === 0) {
        pane.innerHTML = '<p class="muted small">No turns yet.</p>';
        if (meta) meta.textContent = '0 turns recorded';
        return;
      }
      pane.innerHTML = rows.map(t => {
        const cls = t.direction === 'student' ? 'tr-student' : 'tr-character';
        const time = new Date((t.ts || 0) * 1000).toLocaleTimeString();
        return `<div class="transcript-row ${cls}">
          <div class="tr-meta">
            <span class="tr-time">${escapeHTML(time)}</span>
            <span class="tr-persona muted small">${escapeHTML(t.persona_name || t.persona_id || '')}</span>
            <span class="tr-direction muted small">${escapeHTML(t.direction)}</span>
          </div>
          <div class="tr-text">${escapeHTML(t.text)}</div>
        </div>`;
      }).join('');
      pane.scrollTop = pane.scrollHeight;
      if (meta) meta.textContent =
        `Showing ${rows.length} of ${body.total_entries} turn(s).`;
    } catch (err) { console.warn('transcript poll failed', err); }
  }

  // ── M30 + M33 — Characters · voices · engage ─────────────────────
  //
  // M33 — The voice card was renamed from "Character voices" to
  // "Characters · voices · engage" because it now serves as the
  // single source-of-truth for the persona roster on this encounter:
  //   - row label is the persona display name (not the raw ID)
  //   - "▶ Test" button previews the selected voice via /api/tts
  //   - "💬 Engage" button opens the join chat URL in a popup so the
  //     instructor can play the character themselves.
  let voiceCatalog = [];
  let encVoiceBody = {};
  async function bootVoices() {
    const grid = $('voice-grid');
    if (!grid) return;
    try {
      const [catRes, encRes] = await Promise.all([
        fetch('/api/voices', {credentials: 'same-origin'}),
        fetch(`/api/encounter/${encodeURIComponent(cfg.encounterId)}/voices`,
              {credentials: 'same-origin'}),
      ]);
      const cat = catRes.ok ? await catRes.json() : {voices: []};
      encVoiceBody = encRes.ok ? await encRes.json() : {};
      voiceCatalog = cat.voices || [];
      // M33 — Prefer the new `personas` array (with name + role) if
      // present; fall back to bare `selected_personas` (ids) when the
      // server is older or the encounter is empty.
      const personas = (encVoiceBody.personas && encVoiceBody.personas.length)
                         ? encVoiceBody.personas
                         : (encVoiceBody.selected_personas || []).map(pid => ({
                             id: pid, name: pid, role: '',
                           }));
      const assignments     = encVoiceBody.voice_assignments || {};
      const patientId       = encVoiceBody.patient_persona_id;
      const joinCode        = encVoiceBody.join_code || cfg.joinCode || '';
      if (personas.length === 0) {
        grid.innerHTML = '<p class="muted small">No personas configured for this encounter.</p>';
        return;
      }
      grid.innerHTML = personas.map(p => {
        const pid     = p.id;
        const name    = p.name || pid;
        const role    = p.role || '';
        const current = assignments[pid] || '';
        const isPatient = (pid === patientId);
        const roleTag = isPatient
          ? '<span class="char-role-tag patient">patient</span>'
          : (role ? `<span class="char-role-tag">${escapeHTML(role)}</span>` : '');
        const opts = ['<option value="">— browser TTS —</option>']
          .concat(voiceCatalog.map(v =>
            `<option value="${escapeHTML(v.voice_id)}" ${v.voice_id === current ? 'selected' : ''}>` +
            `${escapeHTML(v.name)} (${escapeHTML(v.source || '')})` +
            `</option>`)).join('');
        // M35 — Engage skips the public /join landing entirely. Master
        // Start auto-registers an `INST-<pid>` chat station for every
        // persona; the engage redirect resolves directly to that
        // station and the instructor lands on the chat. If Start
        // hasn't fired yet, the route lazy-creates the station so
        // Engage works pre-start too.
        //
        // M39 — Engage now opens in a modal dialog inside the encounter
        // console (iframe pointed at /portal/engage/...) instead of a
        // new tab.  The instructor stays in the console for the whole
        // conversation.  The href is still constructed because the
        // dialog's "↗ Pop out" affordance uses it.
        const engageHref = `/portal/engage/`
          + `${encodeURIComponent(cfg.encounterId)}/`
          + `${encodeURIComponent(pid)}`;
        return `<div class="voice-row">
          <div class="char-label">
            <span class="char-name">${escapeHTML(name)}</span>
            ${roleTag}
            <span class="char-pid">${escapeHTML(pid)}</span>
          </div>
          <select data-persona="${escapeHTML(pid)}"
                  data-persona-name="${escapeHTML(name)}">${opts}</select>
          <div class="char-actions">
            <button type="button" class="char-test"
                    data-persona="${escapeHTML(pid)}"
                    data-persona-name="${escapeHTML(name)}"
                    title="Preview the selected voice with a sample phrase">▶ Test</button>
            <button type="button" class="char-engage"
               data-persona="${escapeHTML(pid)}"
               data-persona-name="${escapeHTML(name)}"
               data-engage-href="${engageHref}"
               title="Open an in-encounter chat with this character — stays in the encounter console, no new tab.">💬 Engage</button>
          </div>
        </div>`;
      }).join('');
      grid.querySelectorAll('select[data-persona]').forEach(sel => {
        sel.addEventListener('change', async () => {
          const pid = sel.dataset.persona;
          const voiceId = sel.value || null;
          const r = await fetch(
            `/api/encounter/${encodeURIComponent(cfg.encounterId)}/voices`,
            {method: 'POST', credentials: 'same-origin',
             headers: {'Content-Type': 'application/json'},
             body: JSON.stringify({[pid]: voiceId})},
          );
          if (r.ok) $('voice-status').textContent =
            `Saved ${new Date().toLocaleTimeString()}`;
          else      $('voice-status').textContent = `Save failed (${r.status}).`;
        });
      });
      grid.querySelectorAll('button.char-test').forEach(btn => {
        btn.addEventListener('click', () => testVoiceForRow(btn));
      });
      // M39 — Engage opens the chat in a modal dialog instead of a new
      // tab.  Wire each row's button to the shared dialog opener.
      grid.querySelectorAll('button.char-engage').forEach(btn => {
        btn.addEventListener('click', () => openEngageDialog(btn));
      });
    } catch (err) {
      console.warn('voices boot failed', err);
      grid.innerHTML = '<p class="muted small">Voice catalog unavailable.</p>';
    }
  }

  // M39 — Open the engage dialog for the persona this button represents.
  // We point an iframe at /portal/engage/{eid}/{pid} which 303-redirects
  // to the bound INST- station chat (same UI the new-tab path used).
  // Closing the dialog blanks the iframe src to stop any in-flight TTS
  // playback inside it.
  function openEngageDialog(btn) {
    const dlg   = $('engage-dialog');
    const frame = $('engage-dialog-frame');
    const title = $('engage-dialog-title');
    const popout= $('engage-dialog-popout');
    if (!dlg || !frame) {
      // Dialog markup is missing — fall back to a popup so engage
      // still works.
      window.open(btn.dataset.engageHref || '#', '_blank', 'noopener');
      return;
    }
    const name = btn.dataset.personaName || btn.dataset.persona || 'character';
    if (title) title.textContent = `💬 Engage · ${name}`;
    if (popout) popout.href = btn.dataset.engageHref || '#';
    frame.src = btn.dataset.engageHref || 'about:blank';
    // Native <dialog> showModal() if supported, else fallback.
    if (typeof dlg.showModal === 'function') {
      try { dlg.showModal(); } catch (e) { dlg.setAttribute('open', ''); }
    } else {
      dlg.setAttribute('open', '');
    }
  }
  // Close handler — blanks the iframe so audio inside it stops.
  document.addEventListener('DOMContentLoaded', () => {
    const dlg     = $('engage-dialog');
    const closeBtn= $('engage-dialog-close');
    const frame   = $('engage-dialog-frame');
    if (!dlg || !closeBtn) return;
    closeBtn.addEventListener('click', () => {
      if (frame) frame.src = 'about:blank';
      if (typeof dlg.close === 'function') {
        try { dlg.close(); } catch (e) { dlg.removeAttribute('open'); }
      } else {
        dlg.removeAttribute('open');
      }
    });
    // ESC key on a native <dialog> auto-closes — also blank the frame.
    dlg.addEventListener('close', () => {
      if (frame) frame.src = 'about:blank';
    });
  });

  // ── M42 — Devices modal (inline device manager) ──────────────────
  // Replaces the v6 ops-view link-out. The iframe loads the ops view
  // scoped to this encounter's join code, with the add-device patient
  // pre-populated to this bed's primary persona and the ops-view
  // header hidden via ?embed=1 (no double headers).
  document.addEventListener('DOMContentLoaded', () => {
    const btn      = $('btn-manage-devices');
    const dlg      = $('devices-dialog');
    const frame    = $('devices-dialog-frame');
    const closeBtn = $('devices-dialog-close');
    const popout   = $('devices-dialog-popout');
    if (!btn || !dlg || !frame) return;
    btn.addEventListener('click', () => {
      // Build the scoped ops-view URL. The popout link's href is
      // already the unembed-mode URL for second-monitor workflows.
      const joinCode = cfg.joinCode || '';
      const params = new URLSearchParams({
        join: joinCode,
        embed: '1',
      });
      // Pop out anchor href is the non-embedded version.
      if (popout && joinCode) {
        const popParams = new URLSearchParams({ join: joinCode });
        popout.href = '/portal/control/ops?' + popParams.toString();
      }
      frame.src = '/portal/control/ops?' + params.toString();
      if (typeof dlg.showModal === 'function') {
        try { dlg.showModal(); } catch (e) { dlg.setAttribute('open', ''); }
      } else {
        dlg.setAttribute('open', '');
      }
    });
    if (closeBtn) {
      closeBtn.addEventListener('click', () => {
        if (frame) frame.src = 'about:blank';
        if (typeof dlg.close === 'function') {
          try { dlg.close(); } catch (e) { dlg.removeAttribute('open'); }
        } else {
          dlg.removeAttribute('open');
        }
      });
    }
    dlg.addEventListener('close', () => {
      if (frame) frame.src = 'about:blank';
    });
  });

  // M33 — Play a short preview through the row's selected voice. If
  // the row has no voice (browser TTS), use SpeechSynthesis. Otherwise
  // POST to /api/tts with the voice_id + sample text and play the
  // returned audio stream.
  async function testVoiceForRow(btn) {
    const pid     = btn.dataset.persona;
    const name    = btn.dataset.personaName || pid;
    const row     = btn.closest('.voice-row');
    const sel     = row ? row.querySelector(`select[data-persona="${pid}"]`) : null;
    const voiceId = sel ? sel.value : '';
    const sample  = `Hello, I'm ${name}. This is what my voice sounds like in the simulation.`;
    const status  = $('voice-status');
    btn.disabled = true;
    const oldText = btn.textContent;
    btn.textContent = '⏳ …';
    try {
      if (!voiceId) {
        // No ElevenLabs voice picked → preview via browser TTS so
        // the instructor at least hears the SpeechSynthesis fallback.
        if (window.speechSynthesis) {
          const u = new SpeechSynthesisUtterance(sample);
          window.speechSynthesis.cancel();
          window.speechSynthesis.speak(u);
          if (status) status.textContent =
            `Browser TTS preview (no ElevenLabs voice picked for ${name}).`;
        } else if (status) {
          status.textContent = 'Browser speech synthesis unavailable.';
        }
        return;
      }
      const r = await fetch('/api/tts', {
        method: 'POST',
        credentials: 'same-origin',
        headers: {'Content-Type': 'application/json'},
        body: JSON.stringify({text: sample, voice_id: voiceId}),
      });
      if (!r.ok) {
        if (status) status.textContent =
          `Preview failed (${r.status}) — check the ElevenLabs key in Credentials.`;
        return;
      }
      const blob = await r.blob();
      const url = URL.createObjectURL(blob);
      const audio = new Audio(url);
      audio.addEventListener('ended', () => URL.revokeObjectURL(url));
      await audio.play();
      if (status) status.textContent =
        `Played preview for ${name} at ${new Date().toLocaleTimeString()}.`;
    } catch (err) {
      console.warn('voice test failed', err);
      if (status) status.textContent = `Preview error: ${err.message || err}.`;
    } finally {
      btn.disabled = false;
      btn.textContent = oldText;
    }
  }

  // ── Polling lifecycle ──────────────────────────────────────────
  let devicesTimer = null;
  const DEVICES_POLL_MS = 3000;   // M45 — device roster poll cadence

  function startPolling() {
    if (telemetryTimer || stateTimer || devicesTimer) return;
    const t = async () => {
      await pollTelemetry();
      telemetryTimer = setTimeout(t, TELEMETRY_POLL_MS);
    };
    const s = async () => {
      await pollState();
      // M30 — transcript shares the state-poll cadence (2s). Cheap
      // call — just lists the encounter's in-memory transcript list.
      await pollTranscript();
      stateTimer = setTimeout(s, STATE_POLL_MS);
    };
    // M45 — device roster on its own 3s cadence (each station does a
    // fold + alarm scan, slightly heavier than the state/transcript
    // polls; bump the cadence to spread cost).
    const d = async () => {
      await pollDevices();
      devicesTimer = setTimeout(d, DEVICES_POLL_MS);
    };
    t();
    s();
    d();
  }
  function stopPolling() {
    if (telemetryTimer) { clearTimeout(telemetryTimer); telemetryTimer = null; }
    if (stateTimer)     { clearTimeout(stateTimer);     stateTimer = null; }
    if (devicesTimer)   { clearTimeout(devicesTimer);   devicesTimer = null; }
  }
  document.addEventListener('visibilitychange', () => {
    if (document.hidden) stopPolling(); else startPolling();
  });

  document.addEventListener('DOMContentLoaded', async () => {
    enhanceCards();           // per-card collapse + pop-out (card strategy)
    await bootECG();
    await bootVentState();    // FR-012 — ventilator clinical-state picker
    await bootDeviceKinds();
    await bootLeadStudent();
    await bootVoices();
    bootPtt();                // operator push-to-talk (parity with classic ops)
    bootHandoff();            // shift handoff (FR-009), scoped to this bed
    bootStations();           // live student-station roster for this bed
    // M55 — medications card.
    wireMedsToggle();
    await bootMedications();
    startPolling();
  });

  // ── M55 — Medications card ─────────────────────────────────────────
  //
  // Collapsible (matches the M54 nurse-station threshold panel
  // pattern). Click the H2 header to expand/collapse. Inside, one
  // section per persona on the encounter; each med is a checkbox.
  // Default state: every checkbox ON (= every med shows on the med
  // cart). Operator unchecks the meds NOT in use at scenario start.
  //
  // Per-row clicks POST the persona's full active list to
  // `/api/encounter/{eid}/medications/active`. The M47 cart bootstrap
  // reads `enc.active_medications` and filters per patient on its
  // next refresh.

  function wireMedsToggle() {
    const card   = $('card-medications');
    const toggle = $('meds-toggle');
    if (!card || !toggle) return;
    const setState = (expanded) => {
      if (expanded) {
        card.classList.remove('meds-collapsed');
        toggle.setAttribute('aria-expanded', 'true');
      } else {
        card.classList.add('meds-collapsed');
        toggle.setAttribute('aria-expanded', 'false');
      }
    };
    toggle.addEventListener('click', () => {
      const expanded = !card.classList.contains('meds-collapsed');
      setState(!expanded);
    });
    toggle.addEventListener('keydown', (ev) => {
      if (ev.key === 'Enter' || ev.key === ' ') {
        ev.preventDefault();
        const expanded = !card.classList.contains('meds-collapsed');
        setState(!expanded);
      }
    });
  }

  // Cache the latest response so per-row toggles know the full per-
  // persona list when they POST. The endpoint expects the WHOLE
  // active list, not a delta.
  let _medsData = null;

  async function bootMedications() {
    const host = $('meds-personas');
    if (!host) return;
    try {
      const r = await fetch(
        `/api/encounter/${encodeURIComponent(cfg.encounterId)}/medications`,
        {credentials: 'same-origin'});
      if (!r.ok) {
        host.innerHTML = '<p class="muted small">Failed to load medications.</p>';
        return;
      }
      _medsData = await r.json();
      renderMedications(_medsData);
    } catch (err) {
      host.innerHTML = '<p class="muted small">Failed to load medications.</p>';
    }
  }

  function renderMedications(data) {
    const host = $('meds-personas');
    if (!host) return;
    const personas = (data && data.personas) || [];
    if (!personas.length) {
      host.innerHTML =
        '<p class="muted small">No personas on this encounter yet.</p>';
      return;
    }
    host.innerHTML = personas.map(p => {
      const explicit = !!p.explicit_active_list;
      const explicitNote = explicit
        ? '<span class="meds-status muted small">explicit list</span>'
        : '<span class="meds-status muted small">default — all active</span>';
      const meds = (p.medications || []);
      if (!meds.length) {
        return `
          <section class="meds-persona" data-persona-id="${escapeHTML(p.character_id)}">
            <header class="meds-persona-header">
              <strong>${escapeHTML(p.name)}</strong>
              <span class="muted small">${escapeHTML(p.character_id)}</span>
              ${explicitNote}
            </header>
            <p class="muted small">No medications in this persona's MAR seed.</p>
          </section>`;
      }
      const rows = meds.map(m => {
        const id = `med-${escapeHTML(p.character_id)}-${escapeHTML(
          (m.name || '').toLowerCase().replace(/[^a-z0-9]+/g, '_'))}`;
        const checked = m.active ? 'checked' : '';
        const highAlertBadge = m.high_alert
          ? ' <span class="meds-high-alert" title="High-alert medication">⚠ high-alert</span>' : '';
        return `
          <label class="meds-row" for="${id}">
            <input type="checkbox" id="${id}" class="meds-cb"
                   data-persona-id="${escapeHTML(p.character_id)}"
                   data-med-name="${escapeHTML(m.name)}" ${checked}>
            <span class="meds-name">${escapeHTML(m.name)}</span>${highAlertBadge}
            <span class="muted small meds-dose">${escapeHTML(m.dose || '')} ${escapeHTML(m.route || '')} ${escapeHTML(m.frequency || '')}</span>
          </label>`;
      }).join('');
      return `
        <section class="meds-persona" data-persona-id="${escapeHTML(p.character_id)}">
          <header class="meds-persona-header">
            <strong>${escapeHTML(p.name)}</strong>
            <span class="muted small">${escapeHTML(p.character_id)}</span>
            ${explicitNote}
            <button type="button" class="meds-reset link"
                    data-persona-id="${escapeHTML(p.character_id)}"
                    title="Reset to default — every med shown on the cart">↺ Reset</button>
          </header>
          <div class="meds-rows">${rows}</div>
        </section>`;
    }).join('');
    // Wire checkbox clicks.
    host.querySelectorAll('input.meds-cb').forEach(cb => {
      cb.addEventListener('change', () => onMedToggle(cb));
    });
    host.querySelectorAll('button.meds-reset').forEach(btn => {
      btn.addEventListener('click', () => onMedReset(btn.dataset.personaId));
    });
  }

  async function onMedToggle(cb) {
    const pid = cb.dataset.personaId;
    if (!pid || !_medsData) return;
    // Collect the FULL active list for this persona from the current
    // DOM, then POST it.
    const persona = _medsData.personas.find(p => p.character_id === pid);
    if (!persona) return;
    const host = $('meds-personas');
    const activeNames = Array.from(
      host.querySelectorAll(
        `input.meds-cb[data-persona-id="${cssEscape(pid)}"]:checked`))
      .map(c => c.dataset.medName);
    try {
      const r = await fetch(
        `/api/encounter/${encodeURIComponent(cfg.encounterId)}/medications/active`,
        {
          method: 'POST', credentials: 'same-origin',
          headers: {'Content-Type': 'application/json'},
          body: JSON.stringify({persona_id: pid,
                                  active_med_names: activeNames}),
        });
      if (!r.ok) {
        cb.checked = !cb.checked;   // revert
        return;
      }
      // Update the persona's explicit flag locally so the "default"
      // hint flips to "explicit" without a re-fetch.
      persona.explicit_active_list = true;
      const section = host.querySelector(
        `section.meds-persona[data-persona-id="${cssEscape(pid)}"] .meds-status`);
      if (section) section.textContent = 'explicit list';
    } catch (err) {
      cb.checked = !cb.checked;   // revert
    }
  }

  async function onMedReset(pid) {
    if (!pid) return;
    try {
      const r = await fetch(
        `/api/encounter/${encodeURIComponent(cfg.encounterId)}/medications/active/${encodeURIComponent(pid)}`,
        {method: 'DELETE', credentials: 'same-origin'});
      if (!r.ok) return;
      // Re-fetch to refresh the "default — all active" state.
      await bootMedications();
    } catch (err) { /* ignore */ }
  }

  // Tiny CSS.escape polyfill for query selectors. Persona ids are
  // safe ASCII so this is just defensive.
  function cssEscape(s) {
    if (window.CSS && window.CSS.escape) return window.CSS.escape(s);
    return String(s).replace(/[^a-zA-Z0-9_-]/g, ch =>
      '\\' + ch.charCodeAt(0).toString(16) + ' ');
  }

  // ── Operator push-to-talk — parity with the classic control room ──────────
  // Reuses the personas + ElevenLabs voice assignments bootVoices() already
  // loaded (encVoiceBody). Hold-to-talk uses the browser SpeechRecognition; the
  // transcribed line POSTs to the per-encounter operator-turn endpoint and the
  // reply is spoken in the character's assigned voice (same /api/tts path as the
  // voice "Test" button). A type box covers browsers without STT (e.g. Safari).
  var pttActive = null, pttBusy = false, pttRecog = null, pttListening = false;

  function pttPersonas() {
    var ps = (encVoiceBody && encVoiceBody.personas) || [];
    if (ps.length) return ps;
    return ((encVoiceBody && encVoiceBody.selected_personas) || [])
      .map(function (pid) { return { id: pid, name: pid, role: '' }; });
  }
  function pttVoiceFor(pid) {
    var a = (encVoiceBody && encVoiceBody.voice_assignments) || {};
    return a[pid] || '';
  }
  function pttStatus(msg) { var s = $('op-ptt-status'); if (s) s.textContent = msg || ''; }

  function speakLine(voiceId, text) {
    if (!text) return Promise.resolve();
    if (!voiceId) {
      if (window.speechSynthesis) {
        var u = new SpeechSynthesisUtterance(text);
        window.speechSynthesis.cancel(); window.speechSynthesis.speak(u);
      }
      return Promise.resolve();
    }
    return fetch('/api/tts', {
      method: 'POST', credentials: 'same-origin',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ text: text, voice_id: voiceId }),
    }).then(function (r) { return r.ok ? r.blob() : null; })
      .then(function (blob) {
        if (!blob) return;
        var url = URL.createObjectURL(blob);
        var audio = new Audio(url);
        audio.addEventListener('ended', function () { URL.revokeObjectURL(url); });
        return audio.play();
      });
  }

  function sendPttTurn(message) {
    if (!message || !message.trim() || pttBusy || !pttActive) return;
    pttBusy = true;
    var st = $('op-talk-status'); if (st) st.textContent = 'Sending…';
    var fd = new FormData();
    fd.append('persona_id', pttActive.id);
    fd.append('message', message);
    fetch('/api/room/encounter/' + encodeURIComponent(cfg.encounterId) + '/operator/turn',
          { method: 'POST', credentials: 'same-origin', body: fd })
      .then(function (r) {
        return r.ok ? r.json()
          : r.json().then(function (j) { throw new Error((j && j.error) || r.status); });
      })
      .then(function (data) {
        if (data && data.ok) {
          if (st) st.textContent = 'Speaking…';
          pttStatus(pttActive.name + ': ' + (data.reply || ''));
          return speakLine(pttVoiceFor(pttActive.id), data.reply);
        }
        pttStatus('Error: ' + ((data && data.error) || 'unknown'));
      })
      .catch(function (e) { pttStatus('Error: ' + (e.message || e)); })
      .then(function () {
        pttBusy = false;
        if (st) setTimeout(function () { if (!pttListening) st.textContent = 'Idle'; }, 600);
      });
  }

  function bootPtt() {
    var chips = $('op-chips'), talk = $('op-talk-btn'), typeBox = $('op-type');
    if (!chips || !talk) return;
    var ps = pttPersonas();
    if (!ps.length) { chips.innerHTML = '<p class="muted small">No characters on this bed.</p>'; return; }
    chips.textContent = '';
    ps.forEach(function (p, i) {
      var b = document.createElement('button');
      b.type = 'button'; b.className = 'op-chip' + (i === 0 ? ' active' : '');
      b.textContent = p.name || p.id;
      b.addEventListener('click', function () {
        var all = chips.querySelectorAll('.op-chip');
        for (var k = 0; k < all.length; k++) all[k].classList.remove('active');
        b.classList.add('active');
        pttActive = { id: p.id, name: p.name || p.id };
      });
      chips.appendChild(b);
    });
    pttActive = { id: ps[0].id, name: ps[0].name || ps[0].id };

    if (typeBox) {
      typeBox.addEventListener('keydown', function (e) {
        if (e.key === 'Enter' && typeBox.value.trim()) {
          sendPttTurn(typeBox.value.trim()); typeBox.value = '';
        }
      });
    }

    var SR = window.SpeechRecognition || window.webkitSpeechRecognition;
    if (!SR) {
      var ban = $('op-ptt-banner'); if (ban) ban.hidden = false;
      talk.disabled = true; talk.style.opacity = '0.55';
      return;
    }
    var interim = $('op-interim'), finalText = '';
    function startListen() {
      if (pttListening || pttBusy) return;
      pttRecog = new SR();
      pttRecog.lang = 'en-US'; pttRecog.interimResults = true; pttRecog.continuous = true;
      finalText = '';
      pttRecog.onresult = function (ev) {
        var intr = '';
        for (var i = ev.resultIndex; i < ev.results.length; i++) {
          var tr = ev.results[i][0].transcript;
          if (ev.results[i].isFinal) finalText += tr; else intr += tr;
        }
        if (interim) interim.textContent = intr || finalText;
      };
      pttRecog.onerror = function () { stopListen(true); };
      try {
        pttRecog.start(); pttListening = true; talk.classList.add('listening');
        var s = $('op-talk-status'); if (s) s.textContent = 'Listening…';
      } catch (e) { /* already started */ }
    }
    function stopListen(abort) {
      if (!pttListening) return;
      pttListening = false; talk.classList.remove('listening');
      try { pttRecog && pttRecog.stop(); } catch (e) {}
      var s = $('op-talk-status'); if (s) s.textContent = 'Idle';
      var said = finalText.trim();
      if (interim) interim.textContent = '';
      if (!abort && said) sendPttTurn(said);
    }
    talk.addEventListener('mousedown', startListen);
    talk.addEventListener('touchstart', function (e) { e.preventDefault(); startListen(); }, { passive: false });
    talk.addEventListener('mouseup', function () { stopListen(false); });
    talk.addEventListener('mouseleave', function () { if (pttListening) stopListen(false); });
    talk.addEventListener('touchend', function (e) { e.preventDefault(); stopListen(false); });
  }

  // ── Card strategy — collapse + pop-out every console card ──────────────────
  // Mirrors the Operate cockpit: each card can collapse (save space) and pop out
  // (window.open ?card=<id>) onto another monitor. The popped window is the SAME
  // console in "solo" mode (one card, no page chrome) so it stays fully live off
  // the existing telemetry/voice/state polls — no separate per-card route needed.
  function toggleCard(card, caret) {
    var collapsed = card.classList.toggle('cc-collapsed');
    if (caret) {
      caret.textContent = collapsed ? '▸' : '▾';
      caret.setAttribute('aria-expanded', collapsed ? 'false' : 'true');
    }
  }

  function enhanceCards() {
    var solo = new URLSearchParams(location.search).get('card');
    var cards = document.querySelectorAll('.console-card');
    if (solo) {
      document.body.classList.add('enc-solo');
      cards.forEach(function (c) { if (c.id !== solo) c.style.display = 'none'; });
      var t = document.getElementById(solo);
      if (t) t.classList.remove('cc-collapsed', 'meds-collapsed');  // expanded in its window
      return;     // popped window: just the live card, no collapse/pop controls
    }
    cards.forEach(function (c) {
      var h = c.querySelector('h2');
      if (!h || h.querySelector('.cc-tools')) return;
      var tools = document.createElement('span');
      tools.className = 'cc-tools';
      var pop = document.createElement('button');
      pop.type = 'button'; pop.className = 'cc-pop'; pop.textContent = '⧉';
      pop.title = 'Pop out to its own window (another monitor)';
      pop.addEventListener('click', function (e) {
        e.stopPropagation();
        window.open(location.pathname + '?card=' + encodeURIComponent(c.id),
          'enc_' + c.id, 'width=560,height=760,menubar=no,toolbar=no,location=no');
      });
      tools.appendChild(pop);
      // card-medications manages its own collapse (wireMedsToggle) — give it
      // pop-out only, so the two collapse mechanisms never fight.
      if (c.id !== 'card-medications') {
        var caret = document.createElement('button');
        caret.type = 'button'; caret.className = 'cc-caret'; caret.textContent = '▾';
        caret.title = 'Collapse / expand'; caret.setAttribute('aria-expanded', 'true');
        caret.addEventListener('click', function (e) { e.stopPropagation(); toggleCard(c, caret); });
        tools.appendChild(caret);
        h.addEventListener('click', function (e) {
          if (e.target.closest && e.target.closest('.cc-tools')) return;
          toggleCard(c, caret);
        });
        h.classList.add('cc-clickable');
      }
      h.appendChild(tools);
    });
  }

  // ── Shift handoff (FR-009) — per-bed via ?bed=<encounterId> ───────────────
  function hoApi(path, opts) {
    var url = '/api/control/handoff' + (path || '');
    url += (url.indexOf('?') >= 0 ? '&' : '?') + 'bed=' + encodeURIComponent(cfg.encounterId);
    return fetch(url, opts).then(function (r) { return r.json(); });
  }
  function hoRenderActive(st) {
    var cfgEl = $('ho-config'), a = $('ho-active'), evb = $('ho-eval');
    if (!st || !st.active) {
      if (cfgEl) cfgEl.hidden = false;
      if (a) a.hidden = true;
      if (evb) evb.hidden = true;
      return;
    }
    if (cfgEl) cfgEl.hidden = true;
    if (a) a.hidden = false;
    var h = '<div class="muted small">Mode: ' + escapeHTML(st.mode)
          + (st.dial ? ' · ' + escapeHTML(st.dial) : '') + ' · phase: ' + escapeHTML(st.phase) + '</div>';
    if (st.n_patients > 1 && st.current_patient)
      h += '<div class="small">Current patient: ' + escapeHTML(st.current_patient)
         + ' (' + (st.cursor + 1) + '/' + st.n_patients + ')</div>';
    h += '<div class="ho-actions">';
    if (st.phase === 'handoff' && st.n_patients > 1) h += '<button type="button" data-act="advance">Next patient →</button>';
    if (st.phase === 'handoff' || st.phase === 'prioritization') h += '<button type="button" data-act="evaluate">🧮 Score the handoff</button>';
    h += '<button type="button" data-act="end">End handoff</button></div>';
    a.innerHTML = h;
    a.querySelectorAll('button[data-act]').forEach(function (btn) {
      btn.addEventListener('click', function () {
        var act = btn.getAttribute('data-act');
        if (act === 'advance') hoApi('/advance', { method: 'POST' }).then(hoRefresh);
        else if (act === 'evaluate') hoApi('/evaluate', { method: 'POST' })
          .then(function (j) { hoRenderEval(j.evaluations || {}); });
        else if (act === 'end') { if (confirm('End the handoff?')) hoApi('/end', { method: 'POST' }).then(hoRefresh); }
      });
    });
  }
  function hoRenderEval(evals) {
    var box = $('ho-eval'); if (!box) return; box.hidden = false;
    var html = '';
    Object.keys(evals).forEach(function (pid) {
      var ev = evals[pid]; if (!ev) return;
      var d = ev.perception_delta || {};
      html += '<div class="ho-evhead"><strong>' + escapeHTML((ev.patient && ev.patient.name) || pid)
            + '</strong> — measured ' + (d.measured_pct != null ? d.measured_pct : '–') + '%</div>';
      var comp = (d.rows || []).filter(function (r) { return r.q === 'completeness'; })[0];
      if (comp) html += '<div class="small">Self ' + comp.self_pct + '% vs measured ' + comp.measured_pct
            + '% → <strong>' + escapeHTML(comp.verdict) + '</strong></div>';
      html += '<div class="muted small" style="margin-top:3px;">Tick to confirm (✗ = high-risk miss):</div>';
      Object.keys(ev.coverage || {}).forEach(function (eid) {
        var c = ev.coverage[eid];
        var mark = c.said ? '✓' : (c.high_risk ? '✗' : '·');
        html += '<label class="small ho-cov' + (c.high_risk && !c.said ? ' ho-miss' : '') + '">'
              + '<input type="checkbox" data-confirm="' + escapeHTML(pid) + ':' + escapeHTML(eid) + '"'
              + (c.confirmed ? ' checked' : '') + '> ' + mark + ' ' + escapeHTML(c.display) + '</label>';
      });
      if ((ev.auto_prompts || []).length) {
        html += '<div class="small muted" style="margin-top:4px;">Debrief prompts:</div><ul class="small ho-prompts">';
        ev.auto_prompts.forEach(function (p) { html += '<li>' + escapeHTML(p) + '</li>'; });
        html += '</ul>';
      }
    });
    html += '<div style="margin-top:8px;"><a href="/portal/debrief/current" target="_blank" rel="noopener">Open debrief ↗</a></div>';
    box.innerHTML = html;
    box.querySelectorAll('input[data-confirm]').forEach(function (cb) {
      cb.addEventListener('change', function () {
        var parts = cb.getAttribute('data-confirm').split(':');
        hoApi('/confirm', { method: 'POST', headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify({ persona_id: parts[0], element_id: parts[1], confirmed: cb.checked }) });
      });
    });
  }
  function hoRefresh() {
    return hoApi('').then(function (st) {
      var sum = $('ho-summary');
      if (sum) sum.textContent = st && st.active ? ('· ' + st.mode + ' · ' + st.phase) : '· not started';
      hoRenderActive(st);
      if (st && st.active) hoApi('/evaluation').then(function (j) {
        if (j && j.evaluations && Object.keys(j.evaluations).length) hoRenderEval(j.evaluations);
      });
    }).catch(function () {});
  }
  function bootHandoff() {
    var sel = $('ho-counterpart'); if (!sel) return;
    var ps = pttPersonas();
    sel.innerHTML = ps.map(function (p) {
      return '<option value="' + escapeHTML(p.id) + '">'
        + escapeHTML((p.name || p.id) + (p.role ? ' — ' + p.role : '')) + '</option>';
    }).join('');
    var mode = $('ho-mode'), dialWrap = $('ho-dial-wrap');
    if (mode && dialWrap) mode.addEventListener('change', function () {
      dialWrap.hidden = mode.value !== 'oncoming';
    });
    var start = $('ho-start');
    if (start) start.addEventListener('click', function () {
      var b = { mode: mode ? mode.value : 'offgoing', counterpart_id: sel.value };
      if (b.mode === 'oncoming') b.dial = ($('ho-dial') || {}).value;
      hoApi('/start', { method: 'POST', headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify(b) }).then(function (j) {
        if (!j.ok) { var s = $('ho-status'); if (s) s.textContent = j.error || 'failed'; return; }
        hoRefresh();
      });
    });
    hoRefresh();
    setInterval(hoRefresh, 6000);
  }

  // ── Connected student stations on this bed (FR-011 #54) ───────────────────
  function renderEncStations(stations) {
    var grid = $('enc-station-grid'), count = $('enc-station-count'), oc = $('enc-online-count');
    if (!grid) return;
    if (count) count.textContent = '(' + stations.length + ')';
    var online = stations.filter(function (s) { return s.online; }).length;
    if (oc) oc.textContent = stations.length ? ('· ' + online + '/' + stations.length + ' online') : '';
    if (!stations.length) {
      grid.innerHTML = '<p class="muted small">No stations connected yet — share the QR.</p>';
      return;
    }
    grid.innerHTML = stations.map(function (s) {
      var pill = s.online ? '<span class="pill good">🟢 online</span>'
                          : '<span class="pill dim">⚪ ' + s.seconds_since_seen + 's ago</span>';
      var plat = s.platform ? '<span class="tag">' + escapeHTML(s.platform) + '</span>' : '';
      return '<article class="station-card"><header><strong>'
        + escapeHTML(s.persona_name || '— unassigned —') + '</strong>' + pill + '</header>'
        + '<p class="role">' + escapeHTML(s.persona_role || '') + '</p>'
        + '<div class="station-meta">' + plat + '<span class="muted small">' + s.turns
        + ' turn' + (s.turns === 1 ? '' : 's') + '</span></div>'
        + '<code class="muted small">' + escapeHTML(s.station_id) + '</code></article>';
    }).join('');
  }
  function pollEncStations() {
    fetch('/api/encounter/' + encodeURIComponent(cfg.encounterId) + '/stations',
          { credentials: 'same-origin' })
      .then(function (r) { return r.ok ? r.json() : null; })
      .then(function (d) { if (d) renderEncStations(d.stations || []); })
      .catch(function () {});
  }
  function bootStations() {
    pollEncStations();
    setInterval(pollEncStations, 3000);
  }
})();
