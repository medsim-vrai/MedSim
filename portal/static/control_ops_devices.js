// V6 — Simulated devices panel on the operator control_ops page.
//
// Responsibilities:
//   1. Roster — list joined DeviceStations, refresh on poll + on instructor WS push.
//   2. Add Device — modal that POSTs /api/device/register and shows the returned QR.
//   3. Device detail — modal with character (re)assignment + alarm injection +
//      recent-event tail.
//   4. Instructor WebSocket — live firehose of every device event so the
//      roster and detail panel stay current without polling.
//
// Reuses the personas and join_code globals exposed by control_ops.html via
// window.MEDSIM2_OPS.

(function () {
  const OPS = window.MEDSIM2_OPS || {};
  const personas = (OPS.personas || []);
  const $ = (id) => document.getElementById(id);

  // ── State ───────────────────────────────────────────────────────────
  let modelsByKind = {};                  // {pump_iv: ['alaris'], ...}
  let alarmCatalogByKind = {               // per-kind tone catalogue
    pump_iv:      null,
    pump_enteral: null,
    cabinet:      null,
  };
  let rosterCache = [];
  let currentDetail = null;               // station_id currently shown in detail modal
  let ws = null;
  let wsReconnectTimer = null;

  // ── Helpers ─────────────────────────────────────────────────────────
  function personaName(charId) {
    if (!charId) return '— unassigned —';
    const p = personas.find((x) => x.id === charId);
    return p ? `${p.name || charId}` : charId;
  }
  function kindLabel(kind) {
    return ({
      pump_iv:      'IV pump',
      pump_enteral: 'Enteral pump',
      cabinet:      'Dispensing cabinet',
      patient_integrated_alarm: 'Patient alarm (PIA)',
      // FR-012 advanced devices
      telemetry_monitor: 'Telemetry monitor',
      vent_monitor:      'Vent monitor',
      ventilator:        'Ventilator (controls)',
    })[kind] || kind;
  }
  function modelLabel(model) {
    return ({
      alaris:        'BD Alaris',
      kangaroo_omni: 'Kangaroo OMNI',
      pyxis:         'BD Pyxis MedStation',
      generic_tele:         'Bedside telemetry monitor',
      generic_vent_display: 'Ventilator display',
      generic_vent:         'Ventilator (controls)',
    })[model] || model.replace(/_/g, ' ');
  }
  // FR-012 — kinds that live under the "Advanced devices" group.
  const ADVANCED_KINDS = new Set(['telemetry_monitor', 'vent_monitor', 'ventilator']);
  function escapeHtml(s) {
    return String(s == null ? '' : s)
      .replace(/&/g, '&amp;').replace(/</g, '&lt;').replace(/>/g, '&gt;')
      .replace(/"/g, '&quot;').replace(/'/g, '&#39;');
  }
  async function fetchJSON(url, opts) {
    const r = await fetch(url, opts);
    if (!r.ok) {
      // Pull the server's error detail when present so the user sees what
      // actually failed (e.g., "No active session." or "Unknown device_model").
      let detail = '';
      try {
        const body = await r.json();
        detail = body.detail || body.message || body.error || '';
      } catch (e) { /* not JSON */ }
      const err = new Error(`${url} → ${r.status}${detail ? ': ' + detail : ''}`);
      err.status = r.status;
      err.detail = detail;
      throw err;
    }
    return r.json();
  }

  // ── Initial config load ─────────────────────────────────────────────
  async function loadModels() {
    modelsByKind = await fetchJSON('/api/device/models');
  }

  // The alarm catalogue is read off the device's bootstrap spec, but we
  // need it before any device is joined to populate the inject dropdown.
  // The shared catalogue is identical per-kind, so we cache it on first
  // use of any station of that kind.
  async function loadAlarmCatalog(kind) {
    if (alarmCatalogByKind[kind]) return alarmCatalogByKind[kind];
    // Build a synthetic catalog from the shared PUMP_ALARMS / CABINET_ALERTS
    // tables — the server already exposes audio URLs in bootstrap, and the
    // tone IDs are stable. Keep a lightweight in-JS mirror so we don't need
    // a separate endpoint just to populate this dropdown.
    const PUMP = [
      'air_in_line', 'occlusion_downstream', 'occlusion_upstream', 'door_open',
      'infusion_complete', 'feed_complete', 'near_end_prealarm',
      'low_battery', 'depleted_battery', 'system_error',
      'callback_reminder', 'excess_flow_flofast', 'dose_done',
      'alarm_high_priority', 'alarm_medium_priority', 'alarm_low_priority',
    ];
    const CABINET = [
      'scan_success', 'scan_mismatch', 'transaction_complete',
      'login_success', 'login_failed', 'discrepancy_alert',
      'witness_required', 'inventory_low', 'ekit_expiration',
      'drawer_open', 'drawer_failure', 'network_offline', 'security_alert',
    ];
    // FR-012 advanced-device alarm catalogues (mirror portal/devices/engine/alarms.py).
    const MONITOR = [
      'asystole', 'vfib', 'vtach', 'brady_severe', 'tachy_severe',
      'spo2_low', 'apnea', 'brady', 'tachy', 'rr_high',
      'nibp_high', 'nibp_low', 'pvc_frequent', 'afib', 'leads_off',
    ];
    const VENT = [
      'high_pressure', 'low_pressure', 'low_minute_volume', 'apnea',
      'o2_supply', 'vent_inop', 'power_fail', 'low_tidal_volume', 'high_rr',
      'high_minute_volume', 'peep_loss', 'auto_peep', 'fio2_deviation',
      'exhalation_valve',
    ];
    if (kind === 'telemetry_monitor') { alarmCatalogByKind[kind] = MONITOR; return MONITOR; }
    if (kind === 'vent_monitor' || kind === 'ventilator') { alarmCatalogByKind[kind] = VENT; return VENT; }
    alarmCatalogByKind[kind] = (kind === 'cabinet') ? CABINET : PUMP;
    return alarmCatalogByKind[kind];
  }

  // ── Roster rendering ────────────────────────────────────────────────
  function renderRoster(stations) {
    rosterCache = stations || [];
    $('device-count').textContent = `(${rosterCache.length})`;
    const onlineN = rosterCache.filter((s) => s.online).length;
    $('device-online-count').textContent = `${onlineN} online`;

    const grid = $('device-grid');
    if (!rosterCache.length) {
      grid.innerHTML = '<p class="muted">No devices yet. Click <strong>Add device</strong> to mint one.</p>';
      return;
    }
    grid.innerHTML = rosterCache.map((s) => {
      const alarms = s.active_alarms || [];
      const anyAudible = alarms.some((a) => !a.silenced);
      const stateClass = (alarms.length && anyAudible) ? 'alarmed'
                       : s.runtime_state === 'paused'  ? 'paused'
                       : (s.online ? 'online' : 'offline');
      // Per-alarm row: tone name + silenced badge + Clear button. Silenced
      // badge shows remaining seconds so the instructor knows when the
      // student's silence window expires.
      const alarmRows = alarms.map((a) => {
        const sil = a.silenced
          ? `<span style="background:#fff5d6;color:#7a5400;border:1px solid #f0c97a;padding:1px 6px;border-radius:3px;font-size:11px;font-weight:600;margin-left:6px">SILENCED · ${a.remaining_s}s</span>`
          : `<span style="background:#fdecea;color:#962d22;border:1px solid #f5c0c1;padding:1px 6px;border-radius:3px;font-size:11px;font-weight:600;margin-left:6px">SOUNDING</span>`;
        return `<div style="display:flex;justify-content:space-between;align-items:center;background:#fafbfd;border:1px solid #e6ebf3;border-radius:4px;padding:5px 8px;margin-top:4px;font-size:12px">
          <span><strong>${escapeHtml(a.tone || '')}</strong>${sil}</span>
          <button type="button" class="secondary small btn-alarm-clear" data-tone="${escapeHtml(a.tone || '')}" style="padding:3px 10px;font-size:11px">Clear</button>
        </div>`;
      }).join('');
      const alarmsBlock = alarms.length ? `
        <div style="margin-top:8px">
          <div style="display:flex;justify-content:space-between;align-items:center">
            <strong style="font-size:12px;color:${anyAudible ? '#962d22' : '#7a5400'}">Active alarms (${alarms.length})</strong>
            <button type="button" class="secondary small btn-alarm-clear-all" style="padding:3px 10px;font-size:11px">Clear all</button>
          </div>
          ${alarmRows}
        </div>` : '';

      return `
        <div class="device-card ${stateClass}" data-station="${escapeHtml(s.station_id)}">
          <div class="device-card-hdr">
            <strong>${escapeHtml(s.label || '(unlabeled)')}</strong>
            <span class="device-state-dot ${s.online ? 'on' : 'off'}" title="${s.online ? 'online' : 'offline'}"></span>
          </div>
          <div class="muted small">${escapeHtml(kindLabel(s.device_kind))} · ${escapeHtml(modelLabel(s.device_model))}</div>
          <div class="muted small">→ ${escapeHtml(personaName(s.character_id))}</div>
          <div class="muted small" style="margin-top:4px">State: <code>${escapeHtml(s.runtime_state || 'idle')}</code></div>
          ${alarmsBlock}
          ${s.device_kind === 'pump_iv' || s.device_kind === 'pump_enteral' ? `
            <div style="margin-top:8px;padding-top:8px;border-top:1px dashed #dde6f3">
              <div style="font-size:11px;color:#6b7896;margin-bottom:4px">
                ⏩ Step time forward
                ${s.runtime_state === 'running'
                    ? `<span style="background:#dff5e3;color:#1d6334;border:1px solid #b1d8bd;padding:1px 6px;border-radius:3px;font-size:10px;font-weight:700;margin-left:6px">RUNNING${(s.running_channels && s.running_channels.length) ? ' · ch ' + s.running_channels.join(',') : ''}</span>`
                    : s.runtime_state === 'programmed'
                      ? `<span style="background:#fff4cf;color:#7a5400;border:1px solid #f0d899;padding:1px 6px;border-radius:3px;font-size:10px;font-weight:700;margin-left:6px" title="Pump is programmed but not started — advance won't change volume/time until student presses Start">PROGRAMMED · press Start</span>`
                      : `<span style="background:#eef0f4;color:#5b6470;border:1px solid #dde1e8;padding:1px 6px;border-radius:3px;font-size:10px;font-weight:700;margin-left:6px">IDLE</span>`}
              </div>
              <div style="display:flex;gap:4px;flex-wrap:wrap">
                <button type="button" class="secondary small btn-advance-time" data-mins="5"  style="padding:3px 8px;font-size:11px">+5 min</button>
                <button type="button" class="secondary small btn-advance-time" data-mins="15" style="padding:3px 8px;font-size:11px">+15 min</button>
                <button type="button" class="secondary small btn-advance-time" data-mins="30" style="padding:3px 8px;font-size:11px">+30 min</button>
                <button type="button" class="secondary small btn-advance-time" data-mins="60" style="padding:3px 8px;font-size:11px">+1 hr</button>
              </div>
            </div>` : ''}
          <div style="margin-top:10px;display:flex;gap:6px;flex-wrap:wrap">
            <button type="button" class="secondary small btn-device-detail">Detail / inject</button>
            <button type="button" class="secondary small btn-device-qr">QR</button>
          </div>
        </div>
      `;
    }).join('');
    grid.querySelectorAll('.btn-device-detail').forEach((btn) => {
      btn.addEventListener('click', (e) => {
        const card = e.target.closest('.device-card');
        openDetail(card.dataset.station);
      });
    });
    grid.querySelectorAll('.btn-device-qr').forEach((btn) => {
      btn.addEventListener('click', (e) => {
        const card = e.target.closest('.device-card');
        showQrFor(card.dataset.station);
      });
    });
    grid.querySelectorAll('.btn-alarm-clear').forEach((btn) => {
      btn.addEventListener('click', async (e) => {
        const card = e.target.closest('.device-card');
        const tone = btn.dataset.tone;
        btn.disabled = true; btn.textContent = '…';
        try {
          await fetchJSON(`/api/device/${card.dataset.station}/clear`, {
            method: 'POST', headers: {'Content-Type':'application/json'},
            body: JSON.stringify({tone}),
          });
          await refreshRoster();
        } catch (err) {
          btn.disabled = false; btn.textContent = 'Clear';
        }
      });
    });
    grid.querySelectorAll('.btn-alarm-clear-all').forEach((btn) => {
      btn.addEventListener('click', async (e) => {
        const card = e.target.closest('.device-card');
        btn.disabled = true; btn.textContent = '…';
        try {
          await fetchJSON(`/api/device/${card.dataset.station}/clear`, {
            method: 'POST', headers: {'Content-Type':'application/json'},
            body: JSON.stringify({all: true}),
          });
          await refreshRoster();
        } catch (err) {
          btn.disabled = false; btn.textContent = 'Clear all';
        }
      });
    });
    // V6.1 — time-advance buttons fire engine.run_tick(now+N*60) on the
    // server, then refresh the roster so VI / alarms / battery state
    // reflect the elapsed time.
    grid.querySelectorAll('.btn-advance-time').forEach((btn) => {
      btn.addEventListener('click', async (e) => {
        const card = e.target.closest('.device-card');
        const mins = parseInt(btn.dataset.mins, 10);
        const label = btn.textContent;
        btn.disabled = true; btn.textContent = '⏩…';
        try {
          await fetchJSON(`/api/device/${card.dataset.station}/advance_time`, {
            method: 'POST', headers: {'Content-Type':'application/json'},
            body: JSON.stringify({minutes: mins}),
          });
          await refreshRoster();
        } catch (err) {
          console.error('[MEDSIM] advance_time failed:', err);
        } finally {
          btn.disabled = false; btn.textContent = label;
        }
      });
    });
  }

  // M43 — When the ops view is opened scoped to a specific encounter
  // (?join=<code>), append the same join code to operator-side device
  // API calls so the backend can resolve the right ControlSession.
  // Without this every device action 409s with "No active session" in
  // v7 multi-patient mode because control_session.get_active() returns
  // None.  In single-patient mode `window.MEDSIM2_OPS.join_code` is
  // still set but the backend's get_active() fallback finds the same
  // session — so this is a no-op for the v6 path.
  function _joinQuery() {
    const jc = (window.MEDSIM2_OPS && window.MEDSIM2_OPS.join_code) || '';
    return jc ? ('?join=' + encodeURIComponent(jc)) : '';
  }

  async function refreshRoster() {
    try {
      const r = await fetchJSON('/api/device/roster' + _joinQuery());
      renderRoster(r.stations || []);
    } catch (e) {
      // Probably 401 redirected to /login — leave roster alone.
    }
  }

  // ── Add-device modal ────────────────────────────────────────────────
  function fillCharacterSelect(sel, current) {
    sel.innerHTML = '<option value="">— unassigned —</option>'
      + personas.map((p) => `<option value="${escapeHtml(p.id)}"${p.id === current ? ' selected' : ''}>${escapeHtml(p.name || p.id)}</option>`).join('');
  }
  function fillKindSelect(sel) {
    // M44 — when the ops view is embedded inside an encounter
    // console's "Managed devices" modal, exclude the `cabinet`
    // (med-cart) kind from the dropdown. Med carts are a room-level
    // resource — they're created on the Multi-Patient Control
    // dashboard and linked to encounters, not minted per-bed. The
    // v6 single-patient path (no embed_mode) keeps the full list.
    const embed = !!(window.MEDSIM2_OPS && window.MEDSIM2_OPS.embed_mode);
    const allKinds = Object.keys(modelsByKind);
    const kinds = embed
      ? allKinds.filter(k => k !== 'cabinet')
      : allKinds;
    // FR-012 — split the picker into Basic / Advanced groups. Unknown future
    // kinds default to Basic; the advanced clinical devices get their own group.
    const basic = kinds.filter(k => !ADVANCED_KINDS.has(k));
    const advanced = kinds.filter(k => ADVANCED_KINDS.has(k));
    const opt = (k) =>
      `<option value="${escapeHtml(k)}">${escapeHtml(kindLabel(k))}</option>`;
    let html = '';
    if (basic.length)
      html += `<optgroup label="Basic devices">${basic.map(opt).join('')}</optgroup>`;
    if (advanced.length)
      html += `<optgroup label="Advanced devices">${advanced.map(opt).join('')}</optgroup>`;
    sel.innerHTML = html;
    // Refresh the help text under the Add button so the operator
    // sees why the cabinet option isn't there.
    const note = document.getElementById('devices-card-kinds-note');
    if (note && embed) {
      note.textContent =
        'Bed-level devices only (pumps + future-device buttons). '
        + 'Med carts are managed at the room level — '
        + 'add them on the Multi-Patient Control page.';
    }
  }
  function fillModelSelect(sel, kind) {
    const list = modelsByKind[kind] || [];
    sel.innerHTML = list.map((m) =>
      `<option value="${escapeHtml(m)}">${escapeHtml(modelLabel(m))}</option>`).join('');
  }
  function openAddDevice() {
    fillKindSelect($('ad-kind'));
    fillModelSelect($('ad-model'), $('ad-kind').value);
    // M42 — default to the encounter's primary patient persona when
    // the ops view was opened scoped to a specific bed. Falls back
    // to "— unassigned —" when no default was provided (v6 behavior).
    const defaultPatient = (window.MEDSIM2_OPS
                             && window.MEDSIM2_OPS.default_device_patient_id) || '';
    fillCharacterSelect($('ad-char'), defaultPatient);
    $('ad-label').value = '';
    $('ad-qr-result').hidden = true;
    $('add-device-form').hidden = false;
    $('add-device-modal').hidden = false;
    // V6 — re-enable a previously-disabled submit button and clear any
    // stale error from the prior attempt. Without this the second device
    // attempt would either be silently impossible to submit, or carry
    // over a confusing error message from the first attempt.
    const submitBtn = $('add-device-form').querySelector('button[type="submit"]');
    if (submitBtn) { submitBtn.disabled = false; submitBtn.textContent = 'Mint QR'; }
    _addDeviceError('');
    // Make sure the form is the topmost element of the modal (re-attach
    // it if a prior render put #ad-qr-result above it).
    try { $('ad-label').focus(); } catch (e) {}
  }
  function closeAddDevice() { $('add-device-modal').hidden = true; }

  function _addDeviceError(msg) {
    let err = $('ad-error');
    if (!err) {
      err = document.createElement('div');
      err.id = 'ad-error';
      err.style.cssText = 'background:#fdecea;color:#962d22;border:1px solid #f5c0c1;'
        + 'border-radius:6px;padding:9px 12px;margin:0 0 10px;font-size:13px;line-height:1.4;'
        + 'display:flex;justify-content:space-between;gap:10px;align-items:flex-start';
      const form = $('add-device-form');
      if (form) form.insertBefore(err, form.firstChild);
    }
    if (!msg) { err.hidden = true; return; }
    err.innerHTML = '<span></span><button type="button" style="background:none;border:0;color:#962d22;cursor:pointer;font-size:18px;line-height:1;padding:0">×</button>';
    err.firstElementChild.textContent = msg;
    err.lastElementChild.onclick = () => err.hidden = true;
    err.hidden = false;
  }

  async function submitAddDevice(e) {
    e.preventDefault();
    _addDeviceError('');   // clear any prior error
    const kind  = $('ad-kind').value;
    const model = $('ad-model').value;
    const label = $('ad-label').value.trim();
    const char  = $('ad-char').value || null;
    if (!label) {
      _addDeviceError('Enter a label for the device (e.g., "Bed 3 IV").');
      return;
    }
    if (!kind)  { _addDeviceError('Pick a device kind.');  return; }
    if (!model) { _addDeviceError('Pick a device model.'); return; }
    const submitBtn = e.target.querySelector('button[type="submit"]');
    if (submitBtn) { submitBtn.disabled = true; submitBtn.textContent = 'Minting…'; }
    let resp;
    try {
      // M43 — pass ?join so multi-patient mode resolves the right session.
      resp = await fetchJSON('/api/device/register' + _joinQuery(), {
        method: 'POST', headers: {'Content-Type': 'application/json'},
        body: JSON.stringify({device_kind: kind, device_model: model, label}),
      });
    } catch (err) {
      console.error('[MEDSIM] register failed:', err);
      _addDeviceError('Mint failed — ' + (err.detail || err.message || 'unknown error') + '. Check the server log; the form is ready to retry.');
      if (submitBtn) { submitBtn.disabled = false; submitBtn.textContent = 'Mint QR'; }
      return;
    }
    if (char) {
      try {
        await fetchJSON(`/api/device/${resp.station_id}/assign`, {
          method: 'POST', headers: {'Content-Type': 'application/json'},
          body: JSON.stringify({character_id: char}),
        });
      } catch (err) {
        console.warn('[MEDSIM] assign failed (device minted OK):', err);
        // Don't block QR display — the assignment can be redone from the roster card.
      }
    }
    // Show QR
    $('add-device-form').hidden = true;
    $('ad-qr-result').hidden = false;
    $('ad-qr-svg').innerHTML = resp.qr_svg || '<div style="color:#962d22">No QR returned</div>';
    $('ad-qr-caption').textContent =
      `${modelLabel(model)} · "${label}"${char ? ` · → ${personaName(char)}` : ''}`;
    $('ad-qr-url').textContent = resp.join_url;
    // Render LAN warning if the server is loopback-only (QR will fail
    // from any other device on the wifi).
    let warnEl = $('ad-qr-warning');
    if (!warnEl) {
      warnEl = document.createElement('div');
      warnEl.id = 'ad-qr-warning';
      warnEl.style.cssText = 'background:#fdecea;color:#962d22;border:1px solid #f5c0c1;'
        + 'border-radius:6px;padding:10px 12px;margin:10px 0;font-size:13px;line-height:1.5;';
      $('ad-qr-result').insertBefore(warnEl, $('ad-qr-svg'));
    }
    if (resp.warning) {
      warnEl.textContent = '⚠ ' + resp.warning;
      warnEl.hidden = false;
    } else {
      warnEl.hidden = true;
    }
    await refreshRoster();
  }

  function showQrFor(stationId) {
    // Re-mint the join URL for an existing station without creating a new one
    // — we don't need a separate endpoint; the device-join page accepts an
    // existing station id and renders the same landing.
    const s = rosterCache.find((x) => x.station_id === stationId);
    if (!s) return;
    fetch(`/api/device/${stationId}/bootstrap`).then((r) => r.json()).then((b) => {
      const base = window.location.origin;
      const url = `${base}/device/${OPS.join_code}/${stationId}`;
      // Synthesize a QR via the server's qrgen by calling the registry mint
      // would create a new station — instead reuse the existing /api/ehr/qr.svg
      // template path. Quickest path: open the join URL plain text in the modal.
      openAddDevice();
      $('add-device-form').hidden = true;
      $('ad-qr-result').hidden = false;
      $('ad-qr-svg').innerHTML = '<a href="' + url + '" target="_blank" style="font-family:ui-monospace,Menlo,monospace;font-size:13px">' + url + '</a>';
      $('ad-qr-caption').textContent = `${modelLabel(s.device_model)} · "${s.label}" · scan this URL`;
      $('ad-qr-url').textContent = url;
    });
  }

  // ── Detail modal ────────────────────────────────────────────────────
  function openDetail(stationId) {
    const s = rosterCache.find((x) => x.station_id === stationId);
    if (!s) return;
    currentDetail = stationId;
    $('dd-title').textContent = `${modelLabel(s.device_model)} — ${s.label || '(unlabeled)'}`;
    $('dd-meta').innerHTML =
      `${escapeHtml(kindLabel(s.device_kind))} · station <code>${escapeHtml(stationId)}</code> · `
      + `<span class="device-state-dot ${s.online ? 'on' : 'off'}"></span> ${s.online ? 'online' : 'offline'}`;
    fillCharacterSelect($('dd-char'), s.character_id || '');
    loadAlarmCatalog(s.device_kind).then((tones) => {
      $('dd-tone').innerHTML = tones.map((t) =>
        `<option value="${escapeHtml(t)}">${escapeHtml(t.replace(/_/g, ' '))}</option>`).join('');
    });
    $('dd-events').innerHTML = '<span class="muted">Loading…</span>';
    fetchTail(stationId);
    $('device-detail-modal').hidden = false;
  }
  function closeDetail() { $('device-detail-modal').hidden = true; currentDetail = null; }

  async function fetchTail(stationId) {
    try {
      const r = await fetchJSON(`/api/device/${stationId}/state`);
      const state = r.state || {};
      const lines = [];
      if (state.active_alarms && state.active_alarms.length) {
        lines.push(`<span style="color:#a02437">⚠ alarms: ${state.active_alarms.map((a) => a.tone || a).join(', ')}</span>`);
      }
      if (state.screen)        lines.push(`screen: ${escapeHtml(state.screen)}`);
      if (state.session_user)  lines.push(`user: ${escapeHtml(state.session_user)}`);
      if (state.patient)       lines.push(`patient: ${escapeHtml(state.patient.name || state.patient.id)}`);
      if (state.channels) {
        Object.entries(state.channels).forEach(([k, c]) => {
          if (c.drug_label || c.rate_ml_hr) {
            lines.push(`ch ${k}: ${escapeHtml(c.drug_label || '')} ${c.rate_ml_hr} mL/hr ${c.running ? '▶' : c.paused ? '⏸' : '◼'}`);
          }
        });
      }
      $('dd-events').innerHTML = lines.length ? lines.join('<br>') :
        '<span class="muted">(no activity yet)</span>';
    } catch (e) {
      $('dd-events').innerHTML = '<span class="muted">(state unavailable)</span>';
    }
  }

  async function submitAssign(e) {
    e.preventDefault();
    if (!currentDetail) return;
    const char = $('dd-char').value || null;
    await fetchJSON(`/api/device/${currentDetail}/assign`, {
      method: 'POST', headers: {'Content-Type': 'application/json'},
      body: JSON.stringify({character_id: char}),
    });
    await refreshRoster();
  }
  async function submitInject(e) {
    e.preventDefault();
    if (!currentDetail) return;
    const tone = $('dd-tone').value;
    await fetchJSON(`/api/device/${currentDetail}/inject`, {
      method: 'POST', headers: {'Content-Type': 'application/json'},
      body: JSON.stringify({tone}),
    });
    await fetchTail(currentDetail);
    await refreshRoster();
  }

  // ── Instructor WebSocket — live firehose ────────────────────────────
  function connectWS() {
    if (ws && ws.readyState <= 1) return;
    const proto = window.location.protocol === 'https:' ? 'wss:' : 'ws:';
    ws = new WebSocket(`${proto}//${window.location.host}/ws/instructor`);
    ws.onmessage = (ev) => {
      try {
        const msg = JSON.parse(ev.data);
        if (msg.type === 'roster' && Array.isArray(msg.stations)) {
          // Server sent its initial snapshot — keep our cache in sync.
          renderRoster(msg.stations.map((s) => ({...s, online: true})));
        } else if (msg.type === 'device_event' || msg.type === 'device_assignment') {
          // Refresh roster — cheap, single request.
          refreshRoster();
          if (currentDetail && msg.station_id === currentDetail) {
            fetchTail(currentDetail);
          }
        }
      } catch (e) { /* ignore */ }
    };
    ws.onclose = () => {
      if (wsReconnectTimer) clearTimeout(wsReconnectTimer);
      wsReconnectTimer = setTimeout(connectWS, 3000);
    };
    ws.onerror = () => { try { ws.close(); } catch (e) {} };
  }

  // ── Wire everything up on load ──────────────────────────────────────
  document.addEventListener('DOMContentLoaded', async () => {
    if (!$('device-grid')) return;            // Devices section not on this page
    try { await loadModels(); } catch (e) { /* operator probably not authed */ }

    $('btn-add-device').addEventListener('click', openAddDevice);
    $('ad-cancel').addEventListener('click', closeAddDevice);
    $('ad-done').addEventListener('click', closeAddDevice);
    $('add-device-form').addEventListener('submit', submitAddDevice);
    $('ad-kind').addEventListener('change', () => fillModelSelect($('ad-model'), $('ad-kind').value));

    $('dd-close').addEventListener('click', closeDetail);
    $('dd-assign-form').addEventListener('submit', submitAssign);
    $('dd-inject-form').addEventListener('submit', submitInject);

    // Close modals by clicking the dark backdrop.
    ['add-device-modal', 'device-detail-modal'].forEach((id) => {
      $(id).addEventListener('click', (e) => {
        if (e.target.id === id) e.target.hidden = true;
      });
    });

    await refreshRoster();
    // V6 — 2s cadence so SILENCED-badge countdown + Clear button state
    // stay close to live without needing WS subscription for the
    // instructor side. (Cheap: roster fold is a few ms per station.)
    setInterval(refreshRoster, 2000);
    connectWS();
  });
})();
