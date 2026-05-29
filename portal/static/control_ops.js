// MEDSIM 2 — control-room ops view.
//
// Three live regions:
//   1. Station roster — rich cards (device platform, persona, online, turns)
//   2. Live transcript — all turns from all stations + operator, time-ordered
//   3. Operator PTT — instructor engages any selected persona via voice
//
// Polling intervals tuned to match v6 control.js:
//   - /api/control/state    every 3 s (station roster + session state)
//   - /api/control/transcript?since=N every 2 s (incremental delta)

(function () {
  "use strict";

  const ctx = window.MEDSIM2_OPS || {};
  const personas = ctx.personas || [];

  // ---- helpers ---------------------------------------------------------
  function escapeHtml(s) {
    return String(s ?? "").replace(/[&<>"']/g, c => ({
      "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;",
    }[c]));
  }
  function fmtTime(ts) {
    const d = new Date(ts * 1000);
    return d.toLocaleTimeString([], { hour: "2-digit", minute: "2-digit", second: "2-digit" });
  }

  // ---- station roster --------------------------------------------------
  const stationGrid = document.getElementById("station-grid");
  const stationCount = document.getElementById("station-count");
  const onlineCount = document.getElementById("online-count");
  const stateBadge = document.getElementById("state-badge");

  function renderStations(stations) {
    stationCount.textContent = `(${stations.length})`;
    const online = stations.filter(s => s.online).length;
    onlineCount.textContent = stations.length ? `· ${online}/${stations.length} online` : "";
    if (!stations.length) {
      stationGrid.innerHTML = '<p class="muted">No stations connected yet. Share the QR code.</p>';
      return;
    }
    stationGrid.innerHTML = stations.map(s => {
      const safetyClass = s.safety_class || "baseline";
      const alteredTag = s.altered_state
        ? `<span class="tag altered">${escapeHtml(s.altered_state)}</span>`
        : "";
      const platformTag = s.platform
        ? `<span class="tag">${escapeHtml(s.platform)}</span>`
        : "";
      const onlinePill = s.online
        ? `<span class="pill good">🟢 online</span>`
        : `<span class="pill dim">⚪ ${s.seconds_since_seen}s ago</span>`;
      return `
        <article class="station-card safety-${escapeHtml(safetyClass)}">
          <header>
            <strong>${escapeHtml(s.persona_name || "— unassigned —")}</strong>
            ${onlinePill}
          </header>
          <p class="role">${escapeHtml(s.persona_role || "")}</p>
          <div class="station-meta">
            ${platformTag}
            ${alteredTag}
            <span class="muted small">${s.turns} turn${s.turns === 1 ? "" : "s"}</span>
          </div>
          <code class="muted small">${escapeHtml(s.station_id)}</code>
        </article>
      `;
    }).join("");
  }

  async function tickState() {
    try {
      const res = await fetch("/api/control/state");
      const data = await res.json();
      if (!data.active) {
        stationGrid.innerHTML = '<p class="muted">Session ended.</p>';
        return;
      }
      stateBadge.textContent = data.state;
      stateBadge.className = "badge " + (data.state === "paused" ? "warn"
                                          : data.state === "running" ? "ok"
                                          : data.state === "configured" ? "warn" : "ok");
      renderStations(data.stations || []);
      // Old buttons (legacy area)
      const btnPause = document.getElementById("btn-pause");
      const btnResume = document.getElementById("btn-resume");
      if (btnPause && btnResume) {
        btnPause.hidden  = data.state !== "running";
        btnResume.hidden = data.state !== "paused";
      }
      // V6.1 — sticky header buttons, state-aware
      const hdrBadge   = document.getElementById("hdr-state-badge");
      const hdrStart   = document.getElementById("hdr-btn-start");
      const hdrPause   = document.getElementById("hdr-btn-pause");
      const hdrResume  = document.getElementById("hdr-btn-resume");
      if (hdrBadge) {
        hdrBadge.textContent = (data.state || "").toUpperCase();
        const tones = {
          configured: ["#7a5400", "#fff5d6"],   // pending start
          running:    ["#1f7a3a", "#dcefe1"],
          paused:     ["#7a5400", "#fff5d6"],
          ended:      ["#962d22", "#fdecea"],
        };
        const [fg, bg] = tones[data.state] || ["#3a4a6b", "#eef0f5"];
        hdrBadge.style.color = fg; hdrBadge.style.background = bg;
      }
      if (hdrStart)  hdrStart.hidden  = data.state !== "configured";
      if (hdrPause)  hdrPause.hidden  = data.state !== "running";
      if (hdrResume) hdrResume.hidden = data.state !== "paused";
    } catch (e) { /* transient — ignore */ }
  }

  // ---- live transcript -------------------------------------------------
  const transcriptEl = document.getElementById("transcript");
  const tCount = document.getElementById("t-count");
  let nextIndex = 0;

  function renderTranscriptEntry(e) {
    const div = document.createElement("div");
    const cls = e.direction === "character" ? "character" : "student";
    div.className = `turn ${cls} source-${(e.source || "").split(":")[0]}`;
    const time = fmtTime(e.ts);
    const sourceLabel = escapeHtml(e.source === "operator" ? "Operator" : e.source_label || "Station");
    const personaName = escapeHtml(e.persona_name || "—");
    const latency = e.latency_ms ? ` <span class="lat-pill">${e.latency_ms}ms</span>` : "";

    if (e.direction === "student") {
      div.innerHTML = `
        <span class="t">${time}</span>
        <span class="who"><strong>${sourceLabel}</strong> → ${personaName}</span>
        <span class="msg">${escapeHtml(e.text)}</span>
      `;
    } else {
      div.innerHTML = `
        <span class="t">${time}</span>
        <span class="who char-name"><strong>${personaName}</strong>${latency}</span>
        <span class="msg">${escapeHtml(e.text)}</span>
      `;
    }
    return div;
  }

  let deviceSinceTs = 0;

  async function tickTranscript() {
    try {
      const res = await fetch(`/api/control/transcript?since=${nextIndex}&since_ts=${deviceSinceTs}`);
      const data = await res.json();
      if (!data.active) return;
      const turns = data.entries || [];
      const deviceEvents = data.device_events || [];
      if (turns.length || deviceEvents.length) {
        // Clear the "No turns yet" placeholder on first arrival
        if (nextIndex === 0 && deviceSinceTs === 0) transcriptEl.innerHTML = "";
        // Interleave by timestamp so device programming / alarms appear
        // alongside chat turns in the order they actually happened.
        const combined = [
          ...turns.map((e) => ({kind: "turn", ts: e.ts, payload: e})),
          ...deviceEvents.map((e) => ({kind: "device", ts: e.ts, payload: e})),
        ].sort((a, b) => a.ts - b.ts);
        for (const item of combined) {
          if (item.kind === "turn") {
            transcriptEl.appendChild(renderTranscriptEntry(item.payload));
          } else {
            transcriptEl.appendChild(renderDeviceEventEntry(item.payload));
          }
        }
        nextIndex = data.total;
        deviceSinceTs = data.device_since_ts || deviceSinceTs;
        const totalShown = (data.total || 0);
        tCount.textContent = `(${totalShown} turn${totalShown === 1 ? "" : "s"})`;
        transcriptEl.scrollTop = transcriptEl.scrollHeight;
      }
    } catch (e) { /* transient */ }
  }

  // V6 — render a device event (programming, alarms, silence, clear)
  // inline with the chat transcript. Color-coded by event family so the
  // operator can scan quickly.
  function renderDeviceEventEntry(ev) {
    const div = document.createElement("div");
    const t   = ev.type || "";
    let bg = "#f4f7fc", border = "#dde6f3", color = "#3a4a6b", icon = "⚙";
    if (t === "alarm.injected")        { bg = "#fdecea"; border = "#f5c0c1"; color = "#962d22"; icon = "⚠"; }
    else if (t === "alarm.silenced")   { bg = "#fff5d6"; border = "#f0c97a"; color = "#7a5400"; icon = "🔕"; }
    else if (t === "alarm.cleared")    { bg = "#dcefe1"; border = "#9fcfae"; color = "#1f7a3a"; icon = "✓"; }
    else if (t.endsWith(".program"))   { bg = "#e2eaf7"; border = "#aac0e1"; color = "#143b8a"; icon = "⚙"; }
    else if (t.endsWith(".start"))     { bg = "#dcefe1"; border = "#9fcfae"; color = "#1f7a3a"; icon = "▶"; }
    else if (t.endsWith(".pause")
          || t.endsWith(".stop"))      { bg = "#fff5d6"; border = "#f0c97a"; color = "#7a5400"; icon = "■"; }
    else if (t === "device.assigned")  { bg = "#e7d7f0"; border = "#c7a6d8"; color = "#5a2273"; icon = "→"; }
    else if (t === "device.time_advanced") { bg = "#e2eaf7"; border = "#aac0e1"; color = "#143b8a"; icon = "⏩"; }
    else if (t.startsWith("cabinet.")) { bg = "#e2eaf7"; border = "#aac0e1"; color = "#143b8a"; icon = "💊"; }
    const time = new Date(ev.ts * 1000).toLocaleTimeString(undefined, {hour12: false});
    const surface = (ev.surface === "instructor") ? " · INSTRUCTOR" : (ev.surface === "system" ? " · auto" : "");
    div.style.cssText = `background:${bg};border:1px solid ${border};color:${color};`
      + `border-radius:6px;padding:6px 10px;margin:4px 0;font-size:12px;line-height:1.4;`
      + `display:flex;justify-content:space-between;gap:10px;align-items:baseline`;
    div.innerHTML =
      `<span><strong>${icon} ${escapeHtmlSafe(ev.station_label || ev.station_id)}</strong> · ${escapeHtmlSafe(ev.summary || t)}</span>`
      + `<span style="color:${color};opacity:.7;font-size:11px;font-family:ui-monospace,Menlo,monospace">${time}${surface}</span>`;
    return div;
  }

  function escapeHtmlSafe(s) {
    return String(s == null ? "" : s).replace(/[&<>"']/g, ch =>
      ({"&":"&amp;","<":"&lt;",">":"&gt;","\"":"&quot;","'":"&#39;"}[ch]));
  }

  // ---- pause / resume / kill ------------------------------------------
  async function setState(state) {
    const fd = new FormData();
    fd.append("state", state);
    await fetch("/api/control/state", { method: "POST", body: fd });
    tickState();
  }
  const btnPause = document.getElementById("btn-pause");
  const btnResume = document.getElementById("btn-resume");
  const btnKill = document.getElementById("btn-kill");
  if (btnPause) btnPause.addEventListener("click", () => setState("paused"));
  if (btnResume) btnResume.addEventListener("click", () => setState("running"));
  if (btnKill) btnKill.addEventListener("click", () => {
    if (confirm("⛔ Kill switch — pause ALL stations immediately?")) setState("paused");
  });
  // V6.1 — sticky header buttons
  const hdrStart  = document.getElementById("hdr-btn-start");
  const hdrPause  = document.getElementById("hdr-btn-pause");
  const hdrResume = document.getElementById("hdr-btn-resume");
  if (hdrStart)  hdrStart .addEventListener("click", () => setState("running"));
  if (hdrPause)  hdrPause .addEventListener("click", () => setState("paused"));
  if (hdrResume) hdrResume.addEventListener("click", () => setState("running"));

  document.querySelectorAll("form[data-confirm]").forEach(f => {
    f.addEventListener("submit", e => {
      if (!confirm(f.dataset.confirm)) e.preventDefault();
    });
  });

  // ---- operator PTT panel ---------------------------------------------
  const SR = window.SpeechRecognition || window.webkitSpeechRecognition;
  const opTalkBtn = document.getElementById("op-talk-btn");
  const opTalkStatus = document.getElementById("op-talk-status");
  const opInterim = document.getElementById("op-interim");
  const opSttBanner = document.getElementById("op-stt-banner");
  const opChips = document.querySelectorAll(".op-persona-chip");

  let activePersona = personas[0] || null;
  let recognition = null;
  let isListening = false;
  let inFlight = false;

  // V4 — operator PTT speaks through the shared MedSimTTS client: the
  // active persona's assigned ElevenLabs voice, falling back to the
  // browser voice profile when ElevenLabs is unavailable.
  function speak(text, persona) {
    if (!text || !window.MedSimTTS) return Promise.resolve();
    const vp = (persona && persona.voice_profile) || {};
    const va = (window.MEDSIM2_OPS && window.MEDSIM2_OPS.voice_assignments) || {};
    return window.MedSimTTS.speak(text, {
      voiceId:  (persona && va[persona.id]) || "",
      language: ((vp.language) || "en").split("-")[0],
      profile:  vp,
    });
  }

  opChips.forEach(chip => {
    chip.addEventListener("click", () => {
      opChips.forEach(c => c.classList.remove("active"));
      chip.classList.add("active");
      const pid = chip.dataset.personaId;
      activePersona = personas.find(p => p.id === pid) || null;
    });
  });

  // V6 — Chart seed report. Loads once on page load (the seed is built
  // at session start and frozen, so polling is unnecessary). Shows
  // validator warnings + auto-corrections inline above the QR card.
  (async function loadSeedReport() {
    try {
      const r = await fetch("/api/control/seed_report");
      const j = await r.json();
      if (!j.active || !j.report) return;
      const rep = j.report;
      const card = document.getElementById("seed-report-card");
      if (!card) return;
      const cond = document.getElementById("seed-report-condition");
      if (cond) cond.textContent = j.condition ? "condition: " + j.condition : "";
      const wrapW = document.getElementById("seed-report-warnings");
      const wrapC = document.getElementById("seed-report-corrections");
      const warnings    = rep.warnings || [];
      const corrections = rep.auto_corrections || [];
      // Hide the card entirely if there is nothing to surface.
      if (!warnings.length && !corrections.length) { card.hidden = true; return; }
      card.hidden = false;
      if (warnings.length && wrapW) {
        wrapW.innerHTML = '<div style="font-weight:600;color:#962d22;margin-bottom:4px">⚠ Review (' + warnings.length + ')</div>'
          + warnings.map(w => '<div style="background:#fdecea;color:#962d22;border:1px solid #f5c0c1;border-radius:6px;padding:8px 10px;margin:4px 0;font-size:13px">' + escapeHtml(w) + '</div>').join("");
      }
      if (corrections.length && wrapC) {
        wrapC.innerHTML = '<div style="font-weight:600;color:#7a5400;margin:8px 0 4px">Auto-corrected (' + corrections.length + ')</div>'
          + corrections.map(c => '<div style="background:#fff7e3;color:#7a5400;border:1px solid #f0c97a;border-radius:6px;padding:8px 10px;margin:4px 0;font-size:13px">' + escapeHtml(c) + '</div>').join("");
      }
    } catch (e) {
      console.warn("[MEDSIM] seed report failed:", e);
    }
  })();

  // V6.1 — medication checklist. Pulls every seeded MAR med, renders a
  // checkbox per row. Toggling fires /api/control/seed/medications/toggle
  // which flips the `included` flag on the seed; the EHR's MAR filters
  // included:false on its next chart poll so students see the updated list.
  async function loadMedChecklist() {
    try {
      const r = await fetch("/api/control/seed/medications");
      const j = await r.json();
      const card = document.getElementById("med-checklist-card");
      const grid = document.getElementById("med-checklist");
      const summary = document.getElementById("med-checklist-summary");
      if (!card || !grid) return;
      const meds = j.medications || [];
      if (!meds.length) { card.hidden = true; return; }
      card.hidden = false;
      const included = meds.filter(m => m.included).length;
      if (summary) summary.textContent = `${included}/${meds.length} included`;
      grid.innerHTML = meds.map(m => {
        const ha = m.high_alert
          ? '<span style="background:#fdecea;color:#962d22;border:1px solid #f5c0c1;padding:1px 6px;border-radius:3px;font-size:10px;font-weight:600;margin-left:6px">HIGH ALERT</span>'
          : '';
        return `<label style="display:flex;gap:9px;align-items:flex-start;padding:8px 10px;border:1px solid #dde6f3;border-radius:6px;background:#fafbfd;cursor:pointer">
          <input type="checkbox" class="med-toggle" data-med-id="${escapeHtml(m.med_id || '')}" ${m.included ? 'checked' : ''} style="margin-top:3px;width:16px;height:16px;cursor:pointer">
          <div style="flex:1;min-width:0">
            <div style="font-weight:600;color:#0a234f;font-size:13px">${escapeHtml(m.name)} ${ha}</div>
            <div style="color:#3a4a6b;font-size:11px;margin-top:2px">${escapeHtml(m.dose || '')} · ${escapeHtml(m.route || '')} · ${escapeHtml(m.frequency || '')}</div>
            ${m.rationale ? `<div style="color:#6b7896;font-size:11px;font-style:italic;margin-top:2px">${escapeHtml(m.rationale)}</div>` : ''}
          </div>
        </label>`;
      }).join("");
      grid.querySelectorAll(".med-toggle").forEach(cb => {
        cb.addEventListener("change", async e => {
          const medId = cb.dataset.medId;
          const included = cb.checked;
          try {
            await fetch("/api/control/seed/medications/toggle", {
              method: "POST", headers: {"Content-Type":"application/json"},
              body: JSON.stringify({med_id: medId, included}),
            });
            // Refresh summary count
            const all = grid.querySelectorAll(".med-toggle");
            const inc = Array.from(all).filter(x => x.checked).length;
            if (summary) summary.textContent = `${inc}/${all.length} included`;
          } catch (err) {
            console.error("[MEDSIM] toggle failed:", err);
            cb.checked = !included;   // revert
          }
        });
      });
    } catch (e) {
      console.warn("[MEDSIM] med checklist failed:", e);
    }
  }
  loadMedChecklist();

  function escapeHtml(s) {
    return String(s).replace(/[&<>"']/g, ch =>
      ({"&":"&amp;","<":"&lt;",">":"&gt;","\"":"&quot;","'":"&#39;"}[ch]));
  }

  // V6 — error toast surfaces operator-turn failures (Anthropic auth,
  // network) loudly above the talk button. Without it, errors only
  // appeared in the tiny status line and looked like the audio was broken.
  function showOpError(msg) {
    let el = document.getElementById("op-error-toast");
    if (!el) {
      el = document.createElement("div");
      el.id = "op-error-toast";
      el.style.cssText = "background:#fdecea;color:#962d22;border:1px solid #f5c0c1;"
        + "border-radius:6px;padding:10px 12px;margin:0 0 10px;font-size:13px;line-height:1.5;"
        + "display:flex;justify-content:space-between;gap:10px;align-items:flex-start;";
      const parent = opTalkStatus && opTalkStatus.parentElement;
      if (parent) parent.insertBefore(el, parent.firstChild);
    }
    el.innerHTML = '<span></span><button type="button" style="background:none;border:0;'
      + 'color:#962d22;cursor:pointer;font-size:18px;line-height:1;padding:0">×</button>';
    el.firstElementChild.textContent = msg;
    el.lastElementChild.onclick = () => el.remove();
    el.hidden = false;
  }

  async function sendOpTurn(message) {
    if (!message.trim() || inFlight || !activePersona) return;
    inFlight = true;
    opTalkStatus.textContent = "Sending…";
    try {
      const fd = new FormData();
      fd.append("persona_id", activePersona.id);
      fd.append("message", message);
      const res = await fetch("/api/control/operator/turn", { method: "POST", body: fd });
      const data = await res.json();
      if (data.ok) {
        opTalkStatus.textContent = "Speaking…";
        // Clear any prior error toast on a successful turn.
        const prev = document.getElementById("op-error-toast");
        if (prev) prev.remove();
        await speak(data.reply, activePersona);
        // Trigger an immediate transcript refresh so the new turn shows up quickly
        tickTranscript();
      } else {
        const raw = (data.error || "unknown");
        // Always log the raw error to the console so a developer can read it
        // even if the visible toast disappears or a stale cached client is
        // serving the old (silent) error path.
        console.error("[MEDSIM] operator-turn failed:", raw, data);
        // Map common backend errors to actionable operator-friendly messages.
        let pretty = raw;
        if (/invalid x-api-key|AuthenticationError|401/i.test(raw)) {
          pretty = "Anthropic API key is invalid or rotated. Update it at /portal/credentials — the next PTT will pick up the new key without restarting the scenario.";
        } else if (/RateLimitError|429/i.test(raw)) {
          pretty = "Anthropic rate-limited this request. Wait a few seconds and try again.";
        } else if (/credit|billing/i.test(raw)) {
          pretty = "Anthropic account billing issue — check your console.";
        }
        showOpError(pretty);
        opTalkStatus.textContent = "Error";
      }
    } catch (err) {
      console.error("[MEDSIM] operator-turn network error:", err);
      showOpError("Network error talking to the server: " + err.message);
      opTalkStatus.textContent = "Network error";
    } finally {
      inFlight = false;
      setTimeout(() => { if (!isListening) opTalkStatus.textContent = "Idle"; }, 600);
    }
  }

  function setupOpRecognition() {
    if (!SR) {
      opSttBanner.hidden = false;
      opTalkBtn.disabled = true;
      return;
    }
    recognition = new SR();
    recognition.continuous = false;
    recognition.interimResults = true;
    recognition.lang = "en-US";
    recognition.onresult = e => {
      let interim = "", final = "";
      for (let i = e.resultIndex; i < e.results.length; i++) {
        const r = e.results[i];
        if (r.isFinal) final += r[0].transcript;
        else interim += r[0].transcript;
      }
      opInterim.textContent = interim;
      if (final.trim()) {
        opInterim.textContent = "";
        try { recognition.stop(); } catch {}
        isListening = false; opTalkBtn.classList.remove("active");
        sendOpTurn(final);
      }
    };
    recognition.onend = () => { isListening = false; opTalkBtn.classList.remove("active"); if (!inFlight) opTalkStatus.textContent = "Idle"; };
    recognition.onerror = e => { isListening = false; opTalkBtn.classList.remove("active"); opTalkStatus.textContent = "Error: " + e.error; };
  }

  function startOp() {
    if (!recognition || isListening || inFlight || !activePersona) return;
    try {
      // V6 — prime the shared audio element inside this user-gesture so
      // the async TTS reply (which fires long after the gesture expires)
      // can bypass Chrome's autoplay policy.
      if (window.MedSimTTS && window.MedSimTTS.prime) window.MedSimTTS.prime();
      window.speechSynthesis.cancel();
      recognition.start();
      isListening = true;
      opTalkBtn.classList.add("active");
      opTalkStatus.textContent = `Listening → ${activePersona.name}`;
    } catch {}
  }
  function stopOp() { if (isListening && recognition) try { recognition.stop(); } catch {} }

  if (opTalkBtn) {
    opTalkBtn.addEventListener("pointerdown", e => { e.preventDefault(); startOp(); });
    opTalkBtn.addEventListener("pointerup", stopOp);
    opTalkBtn.addEventListener("pointerleave", stopOp);
    opTalkBtn.addEventListener("pointercancel", stopOp);
  }

  setupOpRecognition();
  // ---- start polling ---------------------------------------------------
  tickState();
  tickTranscript();
  setInterval(tickState, 3000);
  setInterval(tickTranscript, 2000);
})();
