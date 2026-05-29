// MEDSIM V3 — ops view EHR panel.
// Polls /api/ehr/state every 3s and renders the EHR station roster.
// Wires the Charting-complete button to /portal/control/charting_complete.

(function () {
  "use strict";
  if (!window.MEDSIM2_OPS || !window.MEDSIM2_OPS.ehr_id) return;

  const grid          = document.getElementById("ehr-station-grid");
  const countEl       = document.getElementById("ehr-station-count");
  const eventCountEl  = document.getElementById("ehr-event-count");
  const btn           = document.getElementById("btn-charting-complete");
  const statusEl      = document.getElementById("charting-complete-status");
  if (!grid || !btn) return;

  let locked = !!(btn.dataset.locked === "1");
  let totalEvents = 0;

  async function refresh() {
    try {
      const r = await fetch("/api/ehr/state", { credentials: "same-origin" });
      if (!r.ok) return;
      const j = await r.json();
      if (!j.active) return;
      locked = !!j.locked;
      totalEvents = j.event_count || 0;
      render(j);
    } catch (e) {
      console.warn("[ehr-ops] poll failed", e);
    }
  }

  function render(state) {
    const list = state.stations || [];
    countEl.textContent = `(${list.length})`;
    eventCountEl.textContent = `${totalEvents} event${totalEvents === 1 ? "" : "s"}`;

    if (!list.length) {
      grid.innerHTML = '<p class="muted">No EHR stations connected yet. Share the EHR QR.</p>';
    } else {
      grid.innerHTML = list.map(s => `
        <div class="station-card ${s.online ? 'online' : 'offline'}" style="border:1px solid #dde2ee;border-radius:6px;padding:10px 12px;background:#fff;">
          <div style="display:flex;justify-content:space-between;align-items:center;">
            <strong>${escapeHtml(s.device_label || '— unnamed device —')}</strong>
            <span class="badge ${s.online ? 'ok' : 'warn'}">${s.online ? 'online' : 'offline'}</span>
          </div>
          <div class="muted small" style="margin-top:4px;">
            <code>${s.ehr_station_id.slice(0, 12)}</code> · ${s.event_count} event${s.event_count === 1 ? '' : 's'} · last seen ${s.seconds_since_seen}s ago
          </div>
        </div>
      `).join("");
    }

    btn.disabled = locked || totalEvents === 0;
    if (locked) {
      btn.textContent = "🔒 Charting locked";
      btn.classList.add("danger");
      btn.classList.remove("primary-action");
      statusEl.textContent = "Comparison report available in the debrief.";
    } else if (totalEvents === 0) {
      statusEl.textContent = "Disabled — no chart events yet.";
    } else {
      statusEl.textContent = `${totalEvents} event${totalEvents === 1 ? '' : 's'} captured.`;
    }
  }

  btn.addEventListener("click", async () => {
    if (locked) return;
    if (!confirm(
      "End charting now and run the comparison engine?\n\n" +
      "• The EHR will become read-only for all students.\n" +
      "• The hybrid comparison (rules + Haiku 4.5 rubric) will run.\n" +
      "• Documentation and Orders cards will appear in the debrief.\n\n" +
      "This cannot be undone — but you can still run the rest of the scenario.")) return;
    btn.disabled = true;
    statusEl.textContent = "Running comparison… (~3-6s)";
    try {
      const r = await fetch("/portal/control/charting_complete", {
        method: "POST", credentials: "same-origin",
      });
      const j = await r.json().catch(() => ({}));
      if (!r.ok) {
        statusEl.textContent = `Error: ${j.detail || r.status}`;
        btn.disabled = false;
        return;
      }
      locked = true;
      statusEl.textContent = `Locked. Composite score: ${(j.composite * 100).toFixed(0)}%`;
      btn.textContent = "🔒 Charting locked";
      btn.classList.add("danger");
      btn.classList.remove("primary-action");
    } catch (e) {
      statusEl.textContent = "Network error — try again.";
      btn.disabled = false;
    }
  });

  function escapeHtml(s) {
    return String(s).replace(/[&<>"']/g, c => ({
      "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;"
    }[c]));
  }

  // The "Launch EHR on this device" control is a plain <a> link
  // (href=/portal/control/launch_ehr, target=medsim_ehr_window) — an
  // ordinary same-origin navigation, so it needs no JS here. The GET
  // route registers the control-room EHR station and 303-redirects the
  // new window into the Medical Records interface.

  refresh();
  setInterval(refresh, 3000);
})();
