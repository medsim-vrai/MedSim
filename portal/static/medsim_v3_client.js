// MEDSIM V3 — EHR-station client helper.
//
// Loaded into every EHR bundle (Helix, Cyrus, Meridian) before the React
// app boots. Provides a small, stable surface that screens.jsx can call
// from Save/Sign/Place-order buttons without each EHR needing its own
// fetch boilerplate.
//
//   medsimV3.event(type, surface, patientId, payload)
//   medsimV3.placeOrder(patientId, order)
//   medsimV3.fetchChart(patientId)
//   medsimV3.fetchCatalog()
//   medsimV3.onLockChange(fn)   // fires when ehr_session is locked by op
//
// Bootstrap globals (set in <head> of index.html before this file loads):
//   window.MEDSIM_V3 = {
//     EHR_ID, JOIN, STATION, BASE_URL, MODE: "live"|"demo",
//     PATIENTS, SEED, LOCKED, NOW
//   }
(function () {
  "use strict";

  const ctx = window.MEDSIM_V3 || {};
  if (!ctx.MODE) ctx.MODE = "demo"; // standalone-page fallback
  if (!ctx.JOIN) ctx.JOIN = "DEMO00";
  if (!ctx.STATION) ctx.STATION = "demo";
  if (!ctx.BASE_URL) ctx.BASE_URL = window.location.origin;

  const LIVE = ctx.MODE === "live";
  const apiBase = `${ctx.BASE_URL}/api/ehr/${ctx.JOIN}/${ctx.STATION}`;

  const listeners = { lockChange: [] };
  let lockedClient = !!ctx.LOCKED;

  // ── HTTP helpers ──────────────────────────────────────────────────
  async function postJson(path, body) {
    if (!LIVE) {
      console.debug("[medsimV3 demo] suppressed POST", path, body);
      return { ok: true, demo: true };
    }
    try {
      const resp = await fetch(path, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify(body),
      });
      const data = await resp.json().catch(() => ({}));
      if (resp.status === 423 || data?.locked) markLocked();
      return data;
    } catch (err) {
      console.warn("[medsimV3] POST failed", path, err);
      return { ok: false, error: String(err) };
    }
  }

  async function getJson(path) {
    if (!LIVE) return { ok: true, demo: true };
    try {
      const resp = await fetch(path);
      return await resp.json().catch(() => ({}));
    } catch (err) {
      console.warn("[medsimV3] GET failed", path, err);
      return { ok: false, error: String(err) };
    }
  }

  function markLocked() {
    if (lockedClient) return;
    lockedClient = true;
    renderBanner();
    listeners.lockChange.forEach((fn) => {
      try { fn(true); } catch (e) { /* never let a listener crash the EHR */ }
    });
  }

  // ── Public surface ────────────────────────────────────────────────
  const api = {
    get ctx() { return ctx; },
    get isLocked() { return lockedClient; },
    get isLive() { return LIVE; },

    event(type, surface, patientId, payload) {
      return postJson(`${apiBase}/event`, {
        type, surface,
        patient_id: patientId || null,
        ehr_station_id: ctx.STATION,
        ts_client: Date.now(),
        payload: payload || {},
      });
    },

    placeOrder(patientId, order) {
      // Emit BOTH a generic event and POST to /orders so the comparison
      // engine can read either path. The /orders route also writes a
      // chart_event so debrief reconstruction is consistent.
      return postJson(`${ctx.BASE_URL}/api/ehr/${ctx.JOIN}/orders`, {
        patient_id: patientId,
        ehr_station_id: ctx.STATION,
        order: order,
      });
    },

    fetchChart(patientId) {
      return getJson(`${ctx.BASE_URL}/api/ehr/${ctx.JOIN}/chart/${encodeURIComponent(patientId)}`);
    },

    fetchCatalog() {
      return getJson(`${ctx.BASE_URL}/api/ehr/${ctx.JOIN}/orders/catalog`);
    },

    heartbeat() { return postJson(`${apiBase}/heartbeat`, {}); },

    onLockChange(fn) {
      listeners.lockChange.push(fn);
      if (lockedClient) try { fn(true); } catch (e) {}
    },
  };

  // ── Banner: shows session state + locks the chart UI ──────────────
  function renderBanner() {
    const mount = document.getElementById("v3-banner-mount");
    if (!mount) return;
    const cls = lockedClient ? "v3-banner locked" : "v3-banner";
    const txt = lockedClient
      ? `🔒 Charting locked by operator — read-only. Session <code>${ctx.JOIN || "—"}</code>`
      : (LIVE
          ? `MEDSIM V3 · ${ctx.EHR_ID || "—"} · join <code>${ctx.JOIN}</code> · station <code>${ctx.STATION}</code>`
          : `MEDSIM V3 · ${ctx.EHR_ID || "—"} · DEMO mode — saves are not persisted`);
    mount.innerHTML = `<div class="${cls}">${txt}</div>`;
    // Pad the body so the banner doesn't overlap content.
    document.body.style.paddingTop = "22px";
  }

  // ── Persistent identity: keep ehr_station_id across accidental refresh
  if (LIVE && ctx.STATION) {
    try { sessionStorage.setItem("medsim_v3_station", ctx.STATION); } catch (e) {}
  }

  // ── Periodic heartbeat
  if (LIVE) {
    setInterval(() => { api.heartbeat(); }, 20000);
  }

  // ── Apply seeded patients as the chart's primary data source ──────
  // If the bootstrap supplied PATIENTS, mirror them into the per-EHR
  // global the original mockup data.jsx exposes (window.HELIX_PATIENTS,
  // window.CYRUS_PATIENTS, window.MER_PATIENTS) so screens.jsx renders
  // the seeded patient instead of the canned mockup. The mockup data.jsx
  // still defines the global first; we overwrite once the EHR_ID is set
  // and the data.jsx file has finished executing.
  function applyBootstrapPatients() {
    if (!Array.isArray(ctx.PATIENTS) || ctx.PATIENTS.length === 0) return;
    const key = ({ helix: "HELIX_PATIENTS", cyrus: "CYRUS_PATIENTS", meridian: "MER_PATIENTS" })[ctx.EHR_ID];
    if (!key) return;
    window[key] = ctx.PATIENTS;
  }

  // data.jsx loads as type=text/babel and is transpiled async — we have
  // to wait until it has assigned its globals before clobbering. The
  // simplest cross-version approach: poll for the global, then patch.
  function waitForDataAndPatch(attempts = 80) {
    const key = ({ helix: "HELIX_PATIENTS", cyrus: "CYRUS_PATIENTS", meridian: "MER_PATIENTS" })[ctx.EHR_ID];
    if (!key) return;
    if (window[key]) { applyBootstrapPatients(); return; }
    if (attempts <= 0) return;
    setTimeout(() => waitForDataAndPatch(attempts - 1), 50);
  }

  window.medsimV3 = api;
  document.addEventListener("DOMContentLoaded", () => {
    renderBanner();
    waitForDataAndPatch();
    setTimeout(mountDocPanel, 300);  // after React mounts so we sit above it
  });

  // ── Doc Panel ──────────────────────────────────────────────────────
  // A small floating widget that lets the student emit chart events
  // directly. Always available so V3 works end-to-end without surgery
  // on each EHR's screens.jsx. The screens.jsx files are 50k+ lines of
  // mockup JSX — wiring every Save button is per-EHR work. This panel
  // covers the most common 4 events (note save, vitals, order, comm log)
  // for any patient currently displayed.
  function mountDocPanel() {
    if (document.getElementById("v3-docpanel")) return;
    const host = document.createElement("div");
    host.id = "v3-docpanel";
    host.innerHTML = `
      <style>
        #v3-docpanel { position: fixed; bottom: 18px; left: 18px; z-index: 100;
                       font-family: Inter, system-ui, sans-serif; font-size: 12px; }
        #v3-docpanel.collapsed .panel { display: none; }
        #v3-docpanel .toggle { background:#0a234f; color:#fff; border:0; padding:8px 14px;
                       border-radius:99px; font-weight:700; box-shadow:0 4px 12px rgba(0,0,0,.18);
                       cursor:pointer; font-size:11px; letter-spacing:.5px; }
        #v3-docpanel .panel { background:#fff; border:1px solid #dde2ee; border-radius:8px;
                       width: 320px; box-shadow:0 12px 30px rgba(0,0,0,.18); margin-bottom:8px;
                       padding:12px; }
        #v3-docpanel .panel h4 { margin:0 0 8px; font-size:13px; color:#0a234f; }
        #v3-docpanel .panel textarea { width:100%; box-sizing:border-box; padding:6px 8px;
                       border:1px solid #dde2ee; border-radius:4px; font-size:12px; margin:4px 0;
                       font-family: inherit; resize:vertical; }
        #v3-docpanel .panel input { width:100%; box-sizing:border-box; padding:6px 8px;
                       border:1px solid #dde2ee; border-radius:4px; font-size:12px; margin:4px 0; }
        #v3-docpanel .panel .row { display:flex; gap:6px; margin-top:6px; }
        #v3-docpanel .panel .row button { flex:1; padding:6px 8px; border-radius:4px; border:0;
                       background:#143b8a; color:#fff; font-weight:600; cursor:pointer; font-size:11px; }
        #v3-docpanel .panel .row button.secondary { background:#eaedf5; color:#3a4a6b; }
        #v3-docpanel .panel select { width:100%; padding:6px 8px; border:1px solid #dde2ee;
                       border-radius:4px; font-size:12px; margin:4px 0; }
        #v3-docpanel .panel .out { color:#1f7a3a; font-size:11px; margin-top:6px; min-height:1em; }
        #v3-docpanel .panel .out.err { color:#a02437; }
        #v3-docpanel .tabs { display:flex; gap:2px; margin-bottom:8px; border-bottom:1px solid #eaedf5; }
        #v3-docpanel .tab { padding:4px 8px; cursor:pointer; font-size:11px; color:#6b7896; border-bottom:2px solid transparent; }
        #v3-docpanel .tab.active { color:#0a234f; border-bottom-color:#0a234f; font-weight:600; }
        #v3-docpanel .body > div { display:none; }
        #v3-docpanel .body > div.active { display:block; }
      </style>
      <div class="panel">
        <h4>V3 Document Panel <span style="float:right;font-weight:400;color:#6b7896;font-size:10px;">${ctx.EHR_ID || "—"}</span></h4>
        <div class="tabs">
          <div class="tab active" data-tab="note">Note</div>
          <div class="tab" data-tab="vitals">Vitals</div>
          <div class="tab" data-tab="order">Order</div>
          <div class="tab" data-tab="comm">Comm</div>
        </div>
        <div class="body">
          <div data-pane="note" class="active">
            <select data-id="note-type">
              <option>Nursing Progress</option><option>SBAR Handoff</option>
              <option>Assessment</option><option>Education</option><option>Discharge</option>
            </select>
            <textarea data-id="note-body" rows="4" placeholder="Note body — use SBAR format for handoffs…"></textarea>
            <div class="row">
              <button data-act="note-save">Save draft</button>
              <button data-act="note-sign">Sign</button>
            </div>
          </div>
          <div data-pane="vitals">
            <div class="row"><input data-id="v-t" placeholder="T °C"><input data-id="v-hr" placeholder="HR"></div>
            <div class="row"><input data-id="v-rr" placeholder="RR"><input data-id="v-bp" placeholder="BP"></div>
            <div class="row"><input data-id="v-spo2" placeholder="SpO₂"><input data-id="v-pain" placeholder="Pain 0-10"></div>
            <div class="row"><button data-act="vitals-save">Record vitals</button></div>
          </div>
          <div data-pane="order">
            <select data-id="o-cat">
              <option value="lab">Lab</option><option value="imaging">Imaging</option>
              <option value="med">Med</option><option value="consult">Consult</option>
              <option value="diet">Diet</option><option value="activity">Activity</option>
            </select>
            <input data-id="o-code" placeholder="Order code (e.g. BMP, NS 1L IV BOLUS)">
            <textarea data-id="o-rationale" rows="2" placeholder="Rationale (required for scoring)"></textarea>
            <div class="row">
              <select data-id="o-priority"><option>routine</option><option>stat</option><option>now</option></select>
              <button data-act="order-place">Sign + send</button>
            </div>
          </div>
          <div data-pane="comm">
            <select data-id="c-with">
              <option>Provider</option><option>Pharmacy</option><option>Family</option>
              <option>RN</option><option>Charge RN</option><option>Social Work</option>
            </select>
            <textarea data-id="c-body" rows="3" placeholder="Communication log entry…"></textarea>
            <div class="row"><button data-act="comm-log">Log communication</button></div>
          </div>
        </div>
        <div class="out" data-id="out"></div>
      </div>
      <button class="toggle">📝 V3 doc panel</button>
    `;
    document.body.appendChild(host);
    host.classList.add("collapsed");

    host.querySelector(".toggle").addEventListener("click", () => {
      host.classList.toggle("collapsed");
    });
    host.querySelectorAll(".tab").forEach(t => {
      t.addEventListener("click", () => {
        host.querySelectorAll(".tab").forEach(x => x.classList.remove("active"));
        host.querySelectorAll(".body > div").forEach(x => x.classList.remove("active"));
        t.classList.add("active");
        host.querySelector(`.body > div[data-pane="${t.dataset.tab}"]`).classList.add("active");
      });
    });

    const $ = (k) => host.querySelector(`[data-id="${k}"]`);
    const out = $("out");
    const showOut = (msg, isErr) => {
      out.textContent = msg;
      out.classList.toggle("err", !!isErr);
      setTimeout(() => { out.textContent = ""; out.classList.remove("err"); }, 4000);
    };

    function patientId() {
      const key = ({ helix: "HELIX_PATIENTS", cyrus: "CYRUS_PATIENTS", meridian: "MER_PATIENTS" })[ctx.EHR_ID];
      const arr = key && window[key];
      return (arr && arr[0] && (arr[0].mrn || arr[0].fin)) || null;
    }

    host.querySelectorAll("[data-act]").forEach(btn => {
      btn.addEventListener("click", async () => {
        const pid = patientId();
        if (!pid) { showOut("No patient loaded.", true); return; }
        const act = btn.dataset.act;
        let res;
        try {
          if (act === "note-save" || act === "note-sign") {
            res = await api.event("note.save", "notes", pid, {
              note_id:   "doc_panel_" + Date.now(),
              note_type: $("note-type").value,
              body:      $("note-body").value,
              signed:    act === "note-sign",
            });
          } else if (act === "vitals-save") {
            res = await api.event("vitals.record", "vitals", pid, {
              t: $("v-t").value, hr: $("v-hr").value, rr: $("v-rr").value,
              bp: $("v-bp").value, spo2: $("v-spo2").value, pain: $("v-pain").value,
            });
          } else if (act === "order-place") {
            res = await api.placeOrder(pid, {
              category:  $("o-cat").value,
              code:      $("o-code").value.trim(),
              label:     $("o-code").value.trim(),
              rationale: $("o-rationale").value.trim(),
              priority:  $("o-priority").value,
              signed_by: ctx.STATION || "—",
            });
          } else if (act === "comm-log") {
            res = await api.event("communication.log", "comms", pid, {
              addressee: $("c-with").value,
              body:      $("c-body").value,
            });
          }
          if (res && res.ok) showOut(`✓ Saved (id ${res.id || "—"}).`);
          else if (res && res.locked) showOut("Charting locked — chart is read-only.", true);
          else showOut(`Error: ${(res && res.error) || "—"}`, true);
        } catch (e) {
          showOut(`Network error: ${e}`, true);
        }
      });
    });
  }
})();
