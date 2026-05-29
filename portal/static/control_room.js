// MEDSIM V7 — charge-nurse dashboard (M5).
//
// Polls /api/room/state every POLL_INTERVAL_MS, paints an Encounter
// grid, and wires the top-bar buttons to the M4 API surface
// (/api/room/freeze_all, /resume_all, /scene_broadcast, /end and
// /api/encounter/{id}/scene).
//
// No frameworks — just DOM. Matches v6's vanilla-JS convention.
// Polling pauses while the tab is hidden so a backgrounded laptop
// doesn't burn cycles. M16's WebSocket transport will replace polling
// with push.

(function () {
  'use strict';

  const POLL_INTERVAL_MS = 2000;
  const POLL_BACKOFF_MS  = 8000;   // when the room ends or 404s

  const $ = (id) => document.getElementById(id);

  let pollTimer = null;
  let lastKnownRoomId = null;

  // ── Render helpers ─────────────────────────────────────────────────

  function formatTimeAgo(ts) {
    if (!ts) return '—';
    const delta = Math.max(0, Date.now() / 1000 - ts);
    if (delta < 5)    return 'just now';
    if (delta < 60)   return `${Math.floor(delta)}s ago`;
    if (delta < 3600) return `${Math.floor(delta / 60)}m ago`;
    return `${Math.floor(delta / 3600)}h ago`;
  }

  function encounterCardHTML(enc) {
    const stateClass = enc.state === 'paused'  ? 'is-paused'
                    : enc.state === 'ended'   ? 'is-ended'
                    : enc.state === 'running' ? 'is-running'
                    : '';
    const alertPills = [];
    if (enc.chart_event_count === 0) {
      alertPills.push('<span class="alert-pill info">no chart yet</span>');
    }
    if (enc.chat_stations === 0 && enc.state === 'running') {
      alertPills.push('<span class="alert-pill warning">no chat station</span>');
    }
    // M30 — lead student badge + per-card pop-out button.
    const leadPill = enc.lead_student_name
      ? `<span class="alert-pill info" title="Lead student for this encounter">🎓 ${escapeHTML(enc.lead_student_name)}</span>`
      : '';
    return `
      <div class="encounter-card ${stateClass}"
           data-encounter-id="${enc.encounter_id}"
           data-join-code="${enc.join_code}"
           data-console-url="${enc.console_url || ('/portal/room/encounter/' + enc.encounter_id)}">
        <div class="encounter-card-header">
          <h3 class="encounter-label">${escapeHTML(enc.label || enc.scenario_name)}</h3>
          <span class="encounter-join">${enc.join_code}</span>
        </div>
        <div class="encounter-meta">
          <span class="badge ${enc.state === 'running' ? 'active'
                              : enc.state === 'paused' ? 'frozen'
                              : enc.state === 'ended'  ? 'ended' : ''}">
            ${enc.state.toUpperCase()}
          </span>
          ${enc.ehr_id ? `<span>${enc.ehr_id}</span>` : ''}
          ${enc.chart_mode === 'private_clone'
              ? '<span class="alert-pill info">private clone</span>' : ''}
          ${leadPill}
          ${alertPills.join('')}
        </div>
        <div class="encounter-meta-row">
          <span>${enc.chat_stations} chat · ${enc.ehr_stations} EHR · ${enc.device_stations} dev</span>
          <span>${enc.chart_event_count} chart events</span>
        </div>
        <div class="encounter-meta-row">
          <span>${enc.assigned_student_ids.length} student${enc.assigned_student_ids.length === 1 ? '' : 's'}</span>
          <span>last: ${formatTimeAgo(enc.last_event_ts)}</span>
        </div>
        <div class="encounter-card-actions">
          <button type="button" class="card-popout" title="Open this encounter console in a new window">↗ Pop out</button>
        </div>
      </div>
    `;
  }

  function escapeHTML(s) {
    return String(s == null ? '' : s)
      .replace(/&/g, '&amp;').replace(/</g, '&lt;')
      .replace(/>/g, '&gt;').replace(/"/g, '&quot;');
  }

  function render(room) {
    lastKnownRoomId = room.room_id;
    $('room-empty').hidden = true;
    $('room-grid-wrap').hidden = false;

    $('room-title').textContent = room.label
      ? `${room.label} — ${room.encounters.length} encounter${room.encounters.length === 1 ? '' : 's'}`
      : `Room of ${room.encounters.length}`;
    $('room-code').textContent = room.room_code || '—';
    const statusBadge = $('room-status');
    statusBadge.textContent = (room.status || 'unknown').toUpperCase();
    statusBadge.className = `badge ${room.status || ''}`;

    $('meta-encounter-count').textContent =
      `${room.encounters.length} encounter${room.encounters.length === 1 ? '' : 's'}`;
    $('meta-student-count').textContent =
      `${room.students.length} student${room.students.length === 1 ? '' : 's'}`;
    $('meta-last-poll').textContent = `last poll ${new Date().toLocaleTimeString()}`;

    $('encounter-grid').innerHTML = room.encounters.map(encounterCardHTML).join('');

    // Drill-in: click an encounter card → /portal/room/encounter/{id}
    // (Phase 7 M22 Per-Patient Console). The v6 legacy ops view is
    // still reachable at /portal/control/ops?join={code} if needed.
    // M30 — the "↗ Pop out" button on each card opens the console
    // in a new window; stopPropagation so the surrounding card-click
    // drill-in doesn't ALSO fire.
    $('encounter-grid').querySelectorAll('.encounter-card').forEach((card) => {
      card.addEventListener('click', (ev) => {
        if (ev.target.closest('.card-popout')) return;   // handled below
        const eid = card.getAttribute('data-encounter-id');
        if (eid) window.location.href = `/portal/room/encounter/${eid}`;
      });
      const popoutBtn = card.querySelector('.card-popout');
      if (popoutBtn) {
        popoutBtn.addEventListener('click', (ev) => {
          ev.stopPropagation();
          const url = card.getAttribute('data-console-url');
          const eid = card.getAttribute('data-encounter-id');
          if (!url) return;
          const w = window.open(url, `encounter_${eid}`,
                                 'width=620,height=900,resizable=yes,scrollbars=yes');
          if (w) w.focus();
        });
      }
    });

    // Refresh scene-injector targets dropdown
    const tgt = $('scene-targets');
    if (tgt) {
      // Preserve "All encounters" first option; rebuild the rest.
      tgt.innerHTML = '<option value="all">All encounters</option>';
      room.encounters.forEach((enc) => {
        const opt = document.createElement('option');
        opt.value = enc.encounter_id;
        opt.textContent = `${enc.label || enc.scenario_name} (${enc.join_code})`;
        tgt.appendChild(opt);
      });
    }

    const ended = room.status === 'ended';
    setButtonEnabled('btn-freeze',  !ended && room.status !== 'frozen');
    setButtonEnabled('btn-resume',  !ended && room.status === 'frozen');
    setButtonEnabled('btn-scene',   !ended);
    setButtonEnabled('btn-end',     !ended);
    setButtonEnabled('btn-debrief', ended);
  }

  function renderEmpty() {
    // Keep lastKnownRoomId — if the operator just ended a room, the
    // Cohort Debrief button below should still navigate to that
    // room's debrief page (M14). It only goes null on a fresh page
    // load where we never saw a room.
    $('room-empty').hidden = false;
    $('room-grid-wrap').hidden = true;
    $('room-code').textContent = '—';
    const sb = $('room-status');
    sb.textContent = lastKnownRoomId ? 'ENDED' : '—';
    sb.className = lastKnownRoomId ? 'badge ended' : 'badge';
    setButtonEnabled('btn-freeze', false);
    setButtonEnabled('btn-resume', false);
    setButtonEnabled('btn-scene', false);
    setButtonEnabled('btn-end', false);
    setButtonEnabled('btn-debrief', !!lastKnownRoomId);
  }

  function setButtonEnabled(id, enabled) {
    const b = $(id);
    if (!b) return;
    b.disabled = !enabled;
  }

  // ── Polling ────────────────────────────────────────────────────────

  async function pollOnce() {
    try {
      const resp = await fetch('/api/room/state', {credentials: 'same-origin'});
      if (resp.status === 404) {
        renderEmpty();
        return POLL_BACKOFF_MS;
      }
      if (!resp.ok) {
        console.warn('room/state', resp.status);
        return POLL_INTERVAL_MS;
      }
      const body = await resp.json();
      render(body);
      // M47 — capture the encounter roster for the cart panel's
      // chip-rendering (encounter labels instead of bare ids).
      // M56-bugfix — `body.encounters` is at the top level of the
      // /api/room/state response (see _room_summary), not nested
      // under `body.room`. The previous `body.room` guard always
      // failed so lastKnownEncounters stayed empty and the cart
      // card showed encounter IDs instead of labels.
      if (body) _captureEncountersForCarts(body);
      return POLL_INTERVAL_MS;
    } catch (exc) {
      console.warn('room/state poll failed', exc);
      return POLL_INTERVAL_MS;
    }
  }

  function startPolling() {
    if (pollTimer) return;
    const tick = async () => {
      const delay = await pollOnce();
      pollTimer = setTimeout(tick, delay);
    };
    tick();
  }

  function stopPolling() {
    if (pollTimer) {
      clearTimeout(pollTimer);
      pollTimer = null;
    }
  }

  document.addEventListener('visibilitychange', () => {
    if (document.hidden) stopPolling();
    else startPolling();
  });

  // ── Button handlers ────────────────────────────────────────────────

  async function postJSON(path, body) {
    const opts = {
      method: 'POST',
      credentials: 'same-origin',
      headers: {'Content-Type': 'application/json'},
    };
    if (body !== undefined) opts.body = JSON.stringify(body);
    return fetch(path, opts);
  }

  function wireButtons() {
    // M35 — master Start launches every encounter into 'running' and
    // auto-registers instructor "Engage" chat stations for every persona.
    $('btn-start-all')?.addEventListener('click', async () => {
      const r = await postJSON('/api/room/start_all');
      if (!r.ok) { alert(`Start failed (${r.status}).`); return; }
      pollOnce();
    });
    $('btn-freeze')?.addEventListener('click', async () => {
      const r = await postJSON('/api/room/freeze_all');
      if (!r.ok) alert(`Pause failed (${r.status}).`);
      pollOnce();
    });
    // btn-resume was removed from the header in M35 (Start handles both
    // first-launch and resume-from-pause) but the handler stays so a
    // stale cached DOM doesn't error on click. Same for the route — it
    // remains available for v6-compat scripts.
    $('btn-resume')?.addEventListener('click', async () => {
      const r = await postJSON('/api/room/resume_all');
      if (!r.ok) alert(`Resume failed (${r.status}).`);
      pollOnce();
    });
    $('btn-end')?.addEventListener('click', async (ev) => {
      const confirm = ev.currentTarget.getAttribute('data-confirm');
      if (confirm && !window.confirm(confirm)) return;
      const r = await postJSON('/api/room/end');
      if (!r.ok) { alert(`End failed (${r.status}).`); return; }
      // M35 — On successful End, the cohort debrief was saved. Send
      // the instructor straight into it.
      const body = await r.json().catch(() => ({}));
      if (body.cohort_debrief_url) {
        window.location.href = body.cohort_debrief_url;
        return;
      }
      pollOnce();
    });
    $('btn-debrief')?.addEventListener('click', () => {
      if (!lastKnownRoomId) {
        alert('No room id known yet. Cohort debrief opens after End room.');
        return;
      }
      window.location.href = `/portal/debrief/cohort/${lastKnownRoomId}`;
    });
    $('btn-quickstart')?.addEventListener('click', async () => {
      const r = await postJSON('/api/room/start', {
        label: 'Quickstart 2-bed demo',
        encounters: [
          {scenario_name: 'Bed 1 — Mr. Diaz',     persona_id: 'P-001', ehr_id: 'helix'},
          {scenario_name: 'Bed 2 — Ms. Kowalski', persona_id: 'P-013', ehr_id: 'cyrus'},
        ],
      });
      if (!r.ok) {
        const detail = await r.text();
        alert(`Quickstart failed (${r.status}). ${detail}`);
        return;
      }
      pollOnce();
    });

    // Scene injector dialog
    $('btn-scene')?.addEventListener('click', () => {
      const dlg = $('scene-dialog');
      if (dlg?.showModal) dlg.showModal();
    });
    $('scene-cancel')?.addEventListener('click', () => {
      $('scene-dialog')?.close();
    });
    $('scene-form')?.addEventListener('submit', async (ev) => {
      // dialog form="dialog" closes the dialog on submit; intercept first
      // to fire the request.
      ev.preventDefault();
      const targets = $('scene-targets').value;
      const kind    = $('scene-kind').value;
      let params = {};
      const raw = $('scene-params').value.trim();
      if (raw) {
        try { params = JSON.parse(raw); }
        catch { alert('Params is not valid JSON.'); return; }
      }
      const scene = {kind, params};

      let r;
      if (targets === 'all' || /^E?-?\w+$/i.test(targets) === false) {
        r = await postJSON('/api/room/scene_broadcast',
                            {scene, targets: 'all'});
      } else if (targets.startsWith('many:')) {
        const eids = targets.slice('many:'.length).split(',').filter(Boolean);
        r = await postJSON('/api/room/scene_broadcast',
                            {scene, targets: eids});
      } else {
        r = await postJSON(`/api/encounter/${encodeURIComponent(targets)}/scene`,
                            {scene});
      }
      if (!r.ok) {
        const detail = await r.text();
        alert(`Inject failed (${r.status}). ${detail}`);
      }
      $('scene-dialog')?.close();
      pollOnce();
    });
  }

  // ── M47 — Med Carts panel ──────────────────────────────────────
  //
  // Operator creates room-level med carts here. Each cart can be
  // linked to one or more encounters. The cabinet bootstrap reads
  // the cart_links list to render a grouped-per-patient MAR.

  async function loadMedCarts() {
    const host = $('med-carts-list');
    if (!host) return;
    try {
      const r = await fetch('/api/room/med_carts',
                            {credentials: 'same-origin'});
      if (!r.ok) {
        host.innerHTML = '<p class="muted small">No active room.</p>';
        return;
      }
      const body = await r.json();
      const carts = body.carts || [];
      renderMedCarts(carts);
    } catch (err) {
      console.warn('med carts poll failed', err);
    }
  }

  function renderMedCarts(carts) {
    const host = $('med-carts-list');
    if (!host) return;
    if (!carts.length) {
      host.innerHTML =
        '<p class="muted small">No med carts yet. Use the form above to add one.</p>';
      return;
    }
    // Build a roster of encounters from the latest known state so the
    // link dropdown lists every bed (excluding ones already linked
    // to the cart in question).
    const allEncs = lastKnownEncounters || [];
    const encById = {};
    allEncs.forEach(e => { encById[e.encounter_id] = e; });
    host.innerHTML = carts.map(cart => {
      const linkedChips = (cart.linked_encounter_ids || []).map(eid => {
        const e = encById[eid];
        const label = e ? (e.label || e.scenario_name || eid) : eid;
        const isPrimary = (eid === cart.primary_encounter_id);
        const removeBtn = isPrimary
          ? '<span class="muted small" title="The cart\'s primary encounter cannot be unlinked. Delete and recreate the cart instead.">★ primary</span>'
          : `<button type="button" class="med-cart-chip-x"
                  data-act="unlink"
                  data-station="${escapeAttr(cart.station_id)}"
                  data-encounter="${escapeAttr(eid)}"
                  title="Unlink ${escapeAttr(label)}">×</button>`;
        return `<span class="med-cart-chip">${escapeText(label)} ${removeBtn}</span>`;
      }).join('');
      // M56 — Build a "link encounter" CHECKLIST (was a single-select
      // dropdown), excluding already-linked encounters. Operator ticks
      // one or more beds + clicks "+ Add selected" to extend the cart's
      // link list AFTER creation. Closes the operator ask: "med cart
      // assignment needs the ability to add encounters to the list
      // after it has been created".
      const linkedSet = new Set(cart.linked_encounter_ids || []);
      const linkableEncs = allEncs.filter(
        e => !linkedSet.has(e.encounter_id));
      const linkCheckboxes = linkableEncs.map(e => `
        <label class="med-cart-add-check">
          <input type="checkbox"
                 class="med-cart-add-enc-cb"
                 data-station="${escapeAttr(cart.station_id)}"
                 value="${escapeAttr(e.encounter_id)}">
          <span>${escapeText(e.label || e.scenario_name || e.encounter_id)}</span>
        </label>`).join('');
      // M59-bugfix — Big visible "Linked to N" count badge so the
      // operator immediately sees what's actually linked. Pre-fix
      // they had to count chips; small chips were easy to miss.
      const linkedCount = (cart.linked_encounter_ids || []).length;
      const countBadgeClass = linkedCount >= 2
        ? 'med-cart-count-badge med-cart-count-multi'
        : 'med-cart-count-badge';
      return `<div class="med-cart-card">
        <div class="med-cart-card-header">
          <strong>${escapeText(cart.label)}</strong>
          <span class="${countBadgeClass}"
                title="Number of encounters linked to this cart">
            🔗 ${linkedCount} bed${linkedCount === 1 ? '' : 's'}
          </span>
          <span class="muted small">${escapeText(cart.station_id)}</span>
          ${cart.device_url ? `
            <a class="med-cart-launch-btn"
               href="${escapeAttr(cart.device_url)}"
               target="_blank" rel="noopener"
               title="Open this cart's tablet UI in a new window on this device — skips the QR-scan join step.">
              🛒 Open cart
            </a>
          ` : ''}
        </div>
        <div class="med-cart-card-encs">
          <span class="small muted">Linked encounters:</span>
          ${linkedChips || '<span class="muted small">none yet</span>'}
        </div>
        ${linkableEncs.length ? `
          <div class="med-cart-add-encs">
            <span class="small muted">Add encounters:</span>
            <div class="med-cart-add-checklist"
                 data-station="${escapeAttr(cart.station_id)}">
              ${linkCheckboxes}
            </div>
            <button type="button" class="dev-btn-sm med-cart-add-btn"
                    data-act="add-multi"
                    data-station="${escapeAttr(cart.station_id)}">+ Add selected</button>
          </div>
        ` : ''}
        ${cart.join_url ? `
          <div class="med-cart-card-qr">
            <img class="med-cart-card-qr-img"
                 src="/api/qr.svg?data=${encodeURIComponent(cart.join_url)}"
                 alt="QR for ${escapeAttr(cart.label)}">
            <code class="med-cart-card-qr-url">${escapeText(cart.join_url)}</code>
          </div>
        ` : ''}
      </div>`;
    }).join('');
    host.querySelectorAll('[data-act]').forEach(el => {
      el.addEventListener('click', () => onMedCartAction(el));
    });
  }

  async function onMedCartAction(el) {
    const act     = el.dataset.act;
    const station = el.dataset.station;
    if (!act || !station) return;
    el.disabled = true;
    try {
      if (act === 'add-multi') {
        // M56 — Add one or more ticked encounters in a single click.
        // The link route only accepts ONE encounter per call, so we
        // fan out — fast enough for typical 1-10 bed rooms.
        const card = el.closest('.med-cart-card');
        const checklist = card?.querySelector(
          `.med-cart-add-checklist[data-station="${cssEscapeAttr(station)}"]`);
        if (!checklist) return;
        const eids = Array.from(
          checklist.querySelectorAll('.med-cart-add-enc-cb:checked'))
          .map(cb => cb.value);
        if (!eids.length) return;
        for (const eid of eids) {
          await fetch(
            `/api/room/med_cart/${encodeURIComponent(station)}/link_encounter`,
            {
              method: 'POST', credentials: 'same-origin',
              headers: {'Content-Type': 'application/json'},
              body: JSON.stringify({encounter_id: eid}),
            });
        }
      } else if (act === 'unlink') {
        const eid = el.dataset.encounter;
        await fetch(`/api/room/med_cart/${encodeURIComponent(station)}/link_encounter/${encodeURIComponent(eid)}`, {
          method: 'DELETE', credentials: 'same-origin',
        });
      }
      loadMedCarts();
    } catch (err) {
      console.warn('med cart action failed', err);
    } finally {
      el.disabled = false;
    }
  }

  // Tiny helper — used by the post-create encounter checklist
  // querySelector since the station id is interpolated into a CSS
  // attribute selector.
  function cssEscapeAttr(s) {
    if (window.CSS && window.CSS.escape) return window.CSS.escape(s);
    return String(s).replace(/[^a-zA-Z0-9_-]/g, ch =>
      '\\' + ch.charCodeAt(0).toString(16) + ' ');
  }

  // Track the latest encounter roster from pollOnce so the cart
  // panel's link-encounter dropdown can list them by label.
  let lastKnownEncounters = [];
  function _captureEncountersForCarts(state) {
    lastKnownEncounters = state?.encounters || [];
  }

  // Escape helpers (the existing wireButtons code already has its
  // own escape — duplicating here keeps M47 isolated and avoids
  // changing the existing helper signature).
  function escapeText(s) {
    return String(s == null ? '' : s)
      .replace(/&/g, '&amp;').replace(/</g, '&lt;')
      .replace(/>/g, '&gt;');
  }
  function escapeAttr(s) {
    return String(s == null ? '' : s)
      .replace(/&/g, '&amp;').replace(/</g, '&lt;')
      .replace(/>/g, '&gt;').replace(/"/g, '&quot;');
  }

  // ── Boot ───────────────────────────────────────────────────────────

  document.addEventListener('DOMContentLoaded', () => {
    wireButtons();
    startPolling();
    // M47 + M56 — Wire the create-cart form + initial cart list load.
    // M56: the form now carries a checkbox per encounter; the operator
    // ticks which beds get the cart at creation time.
    const form = $('med-cart-create-form');
    if (form) {
      // M56-bugfix — live "Will link N encounter(s)" counter so the
      // operator can verify the tick count BEFORE submitting. Helps
      // surface stale-HTML / missed-tick states (operator reported
      // a "ticked 3, only 1 linked" bug that came from a pre-M56
      // cached page with no checkboxes — the JS found zero
      // `.med-cart-create-enc-cb:checked` and the server defaulted
      // to first encounter).
      function _updateTickCount() {
        const counter = $('med-cart-tick-count');
        if (!counter) return;
        const n = form.querySelectorAll(
          '.med-cart-create-enc-cb:checked').length;
        const total = form.querySelectorAll(
          '.med-cart-create-enc-cb').length;
        counter.textContent =
          `Will link ${n} of ${total} encounter${total === 1 ? '' : 's'}`;
        counter.classList.toggle(
          'med-cart-tick-count-zero', n === 0 && total > 0);
      }
      form.querySelectorAll('.med-cart-create-enc-cb').forEach(cb => {
        cb.addEventListener('change', _updateTickCount);
      });
      _updateTickCount();
      // M59-bugfix — "All beds" / "None" quick toggles.
      const allBtn = $('med-cart-create-all');
      if (allBtn) allBtn.addEventListener('click', () => {
        form.querySelectorAll('.med-cart-create-enc-cb')
            .forEach(cb => { cb.checked = true; });
        _updateTickCount();
      });
      const noneBtn = $('med-cart-create-none');
      if (noneBtn) noneBtn.addEventListener('click', () => {
        form.querySelectorAll('.med-cart-create-enc-cb')
            .forEach(cb => { cb.checked = false; });
        _updateTickCount();
      });
      form.addEventListener('submit', async (ev) => {
        ev.preventDefault();
        const label = $('med-cart-label').value.trim();
        const status = $('med-cart-create-status');
        if (!label) return;
        // M56 — collect ticked encounter ids in document order. First
        // ticked becomes the cart's primary on the back-end. Empty list
        // is OK — back-end falls back to first encounter (legacy).
        const checkedEids = Array.from(
          form.querySelectorAll('.med-cart-create-enc-cb:checked'))
          .map(cb => cb.value);
        if (status) status.textContent = 'creating…';
        try {
          const r = await fetch('/api/room/med_cart/register', {
            method: 'POST', credentials: 'same-origin',
            headers: {'Content-Type': 'application/json'},
            body: JSON.stringify({
              label,
              encounter_ids: checkedEids,
            }),
          });
          if (!r.ok) {
            const detail = await r.text();
            if (status) status.textContent =
              `create failed (${r.status}): ${detail}`;
            return;
          }
          const body = await r.json();
          $('med-cart-label').value = '';
          // Uncheck every encounter so the next cart starts clean.
          form.querySelectorAll('.med-cart-create-enc-cb')
              .forEach(cb => { cb.checked = false; });
          _updateTickCount();
          const linkedN = (body.linked_encounter_ids || []).length;
          if (status) status.textContent =
            `Created. Cart linked to ${linkedN} encounter${linkedN === 1 ? '' : 's'}.`;
          loadMedCarts();
        } catch (err) {
          if (status) status.textContent = 'network error';
        }
      });
    }
    loadMedCarts();
    // Refresh cart list on the same cadence as the state poll.
    setInterval(loadMedCarts, 5000);
    // M53 — Lead assignments panel.
    wireLeadAssignments();
  });

  // ── M53 — Lead assignments panel ───────────────────────────────────
  //
  // The template pre-renders one row per encounter (server-side, off
  // `room.encounters`). We wire per-row Apply/Clear buttons + a bulk
  // "apply to all checked" action. Each Apply POSTs the single-bed
  // route; the bulk Apply uses /api/room/lead_assignments so one
  // call writes the same label to N encounters atomically.
  //
  // No re-rendering on the state poll — this panel is operator-typed
  // text, not server-derived data; live-overwriting an in-progress
  // edit would be hostile. We DO refresh after a successful Apply so
  // the input shows the canonical trimmed value the server stored.
  function wireLeadAssignments() {
    const panel = $('lead-assign-panel');
    if (!panel) return;

    // Helper — POST one bed's label and update status / input.
    async function _saveRowLabel(eid, label) {
      const input = panel.querySelector(
        `.lead-assign-input[data-encounter-id="${eid}"]`);
      const status = panel.querySelector(
        `.lead-assign-status[data-encounter-id="${eid}"]`);
      if (status) {
        status.textContent = 'saving…';
        status.classList.remove('ok', 'err');
      }
      try {
        const r = await fetch(
          `/api/encounter/${encodeURIComponent(eid)}/lead_label`,
          {
            method: 'POST', credentials: 'same-origin',
            headers: {'Content-Type': 'application/json'},
            body: JSON.stringify({lead_label: label}),
          });
        if (!r.ok) {
          if (status) {
            status.textContent = `failed (${r.status})`;
            status.classList.add('err');
          }
          return false;
        }
        const body = await r.json();
        if (status) {
          status.textContent = body.lead_label ? 'saved ✓' : 'cleared ✓';
          status.classList.add('ok');
        }
        if (input) input.value = body.lead_label || '';
        return true;
      } catch (err) {
        if (status) {
          status.textContent = 'network error';
          status.classList.add('err');
        }
        return false;
      }
    }

    // M53 bugfix #2 — Per-row Apply button.
    panel.querySelectorAll('.lead-assign-apply').forEach(btn => {
      btn.addEventListener('click', async () => {
        const eid = btn.dataset.encounterId;
        if (!eid) return;
        const input = panel.querySelector(
          `.lead-assign-input[data-encounter-id="${eid}"]`);
        if (!input) return;
        await _saveRowLabel(eid, (input.value || '').trim());
      });
    });

    // M53 bugfix #2 — Per-row inputs auto-save on Enter and on blur
    // (focus loss). The operator's natural workflow is "type, then
    // tab away or hit return", not "type, then hunt for the Apply
    // button". Each input remembers its last-saved value via a
    // `data-saved` attribute so blur doesn't re-POST when nothing
    // has changed.
    panel.querySelectorAll('.lead-assign-input').forEach(input => {
      // Seed the saved-snapshot with the SSR-rendered value so a
      // blur right after page load doesn't generate a no-op POST.
      input.dataset.saved = (input.value || '').trim();
      input.addEventListener('keydown', async (ev) => {
        if (ev.key === 'Enter') {
          ev.preventDefault();
          const eid = input.dataset.encounterId;
          const label = (input.value || '').trim();
          if (eid && label !== input.dataset.saved) {
            input.dataset.saved = label;
            await _saveRowLabel(eid, label);
          }
        }
      });
      input.addEventListener('blur', async () => {
        const eid = input.dataset.encounterId;
        const label = (input.value || '').trim();
        if (eid && label !== input.dataset.saved) {
          input.dataset.saved = label;
          await _saveRowLabel(eid, label);
        }
      });
    });

    panel.querySelectorAll('.lead-assign-clear').forEach(btn => {
      btn.addEventListener('click', async () => {
        const eid = btn.dataset.encounterId;
        if (!eid) return;
        const input = panel.querySelector(
          `.lead-assign-input[data-encounter-id="${eid}"]`);
        if (input) {
          input.value = '';
          input.dataset.saved = '';
        }
        await _saveRowLabel(eid, '');
      });
    });

    // M53 bugfix #2 — Bulk Apply: smart fallback.
    //
    // Pre-fix: the bulk button blindly read the bulk-input value
    // (often empty) and wrote it to every checked row, WIPING any
    // labels the operator had typed into per-row inputs.
    //
    // Now:
    //   * If the bulk input HAS text → behave as before: write that
    //     text to every checked row (the "set all the same label"
    //     workflow).
    //   * If the bulk input is EMPTY → apply each checked row's OWN
    //     typed value individually (the "I typed different labels
    //     per row, apply them all" workflow). Empty per-row inputs
    //     in this mode are SKIPPED so the operator doesn't
    //     accidentally clear other beds they didn't intend to.
    //   * Either way, the bulk input is NOT auto-cleared on success.
    //     Operator can re-apply the same label to more rows without
    //     re-typing.
    const bulkBtn = $('lead-bulk-apply');
    if (bulkBtn) {
      bulkBtn.addEventListener('click', async () => {
        const bulkInput = $('lead-bulk-input');
        const status    = $('lead-bulk-status');
        if (status) {
          status.textContent = '';
          status.classList.remove('ok', 'err');
        }
        const bulkLabel = ((bulkInput && bulkInput.value) || '').trim();
        const checked = Array.from(
          panel.querySelectorAll('.lead-assign-cb'))
          .filter(cb => cb.checked)
          .map(cb => cb.dataset.encounterId);
        if (!checked.length) {
          if (status) {
            status.textContent = 'check at least one encounter first';
            status.classList.add('err');
          }
          return;
        }
        if (status) status.textContent = 'applying…';
        try {
          let assignments;
          if (bulkLabel) {
            // "Set all the same label" workflow.
            assignments = [{encounter_ids: checked,
                              lead_label: bulkLabel}];
          } else {
            // "Apply per-row typed values" workflow. Group by label
            // so the server gets one assignment per distinct label.
            const byLabel = new Map();
            for (const eid of checked) {
              const i = panel.querySelector(
                `.lead-assign-input[data-encounter-id="${eid}"]`);
              const v = (i && (i.value || '').trim()) || '';
              if (!v) continue;   // skip empty per-row inputs
              if (!byLabel.has(v)) byLabel.set(v, []);
              byLabel.get(v).push(eid);
            }
            if (byLabel.size === 0) {
              if (status) {
                status.textContent =
                  'nothing to apply — type a label in the bulk box ' +
                  'or in the per-row inputs';
                status.classList.add('err');
              }
              return;
            }
            assignments = Array.from(byLabel.entries()).map(
              ([lead_label, encounter_ids]) =>
                ({encounter_ids, lead_label}));
          }
          const r = await fetch('/api/room/lead_assignments', {
            method: 'POST', credentials: 'same-origin',
            headers: {'Content-Type': 'application/json'},
            body: JSON.stringify({assignments}),
          });
          if (!r.ok) {
            if (status) {
              status.textContent = `failed (${r.status})`;
              status.classList.add('err');
            }
            return;
          }
          const body = await r.json();
          // Mirror the applied values into per-row inputs so the
          // operator sees what landed.  Update `dataset.saved` too
          // so the auto-save blur handler doesn't re-POST on tab-
          // away after a successful bulk apply.
          for (const a of assignments) {
            for (const eid of a.encounter_ids) {
              const i = panel.querySelector(
                `.lead-assign-input[data-encounter-id="${eid}"]`);
              if (i) {
                i.value = a.lead_label;
                i.dataset.saved = a.lead_label;
              }
            }
          }
          if (status) {
            const n = (body.applied || []).length;
            status.textContent =
              `applied to ${n} encounter${n === 1 ? '' : 's'} ✓`;
            status.classList.add('ok');
          }
          // Intentionally NOT clearing the bulk input — operator may
          // want to re-apply the same label to additional rows.
        } catch (err) {
          if (status) {
            status.textContent = 'network error';
            status.classList.add('err');
          }
        }
      });
    }
    const checkAll = $('lead-bulk-checkall');
    if (checkAll) {
      checkAll.addEventListener('click', () => {
        const cbs = panel.querySelectorAll('.lead-assign-cb');
        const allOn = Array.from(cbs).every(cb => cb.checked);
        cbs.forEach(cb => { cb.checked = !allOn; });
      });
    }
  }
})();
