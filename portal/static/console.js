/* FR-011 G3 — Mission Control shell client.
   (1) mode tabs <-> URL ?mode=  (2) the persistent readiness bar polling the
   G2 API (/api/control/readiness) + its one-tap actions. Vanilla, DOM-light,
   no build step — served straight from /static. */
(function () {
  "use strict";

  var MODES = ["setup", "operate", "debrief"];
  var DEFAULT_MODE = "operate";
  var POLL_MS = 15000;

  // shape-not-colour-only glyphs (a11y, G8)
  var GLYPH = { green: "●", amber: "▲", red: "■", loading: "…" };
  var OVERALL_TEXT = {
    green: "All systems go", amber: "Attention needed",
    red: "Action required", loading: "Checking readiness…"
  };

  function $(sel, root) { return (root || document).querySelector(sel); }

  function makeActionBtn(action, cls) {
    var btn = document.createElement("button");
    btn.type = "button";
    btn.className = cls;
    btn.textContent = action.label;
    btn.addEventListener("click", function () { runAction(action.id, btn); });
    return btn;
  }

  function sessionCheck(snap) {
    var checks = (snap && snap.checks) || [];
    for (var i = 0; i < checks.length; i++) {
      if (checks[i].id === "session") return checks[i];
    }
    return null;
  }
  function isResumable(snap) {
    var s = sessionCheck(snap);
    return !!(s && (s.actions || []).some(function (a) { return a.id === "resume_session"; }));
  }

  // ── modes ───────────────────────────────────────────────────────────────
  function currentMode() {
    var m = new URLSearchParams(location.search).get("mode");
    return MODES.indexOf(m) >= 0 ? m : DEFAULT_MODE;
  }

  function applyMode(mode) {
    var root = $(".console");
    if (root) root.setAttribute("data-mode", mode);   // CSS shows the matching panel + tab
    var tabs = document.querySelectorAll(".ct-tab");
    for (var i = 0; i < tabs.length; i++) {
      tabs[i].setAttribute("aria-selected",
        tabs[i].getAttribute("data-tab") === mode ? "true" : "false");
    }
  }

  function wireTabs() {
    var tabs = document.querySelectorAll(".ct-tab");
    for (var i = 0; i < tabs.length; i++) {
      tabs[i].addEventListener("click", function (e) {
        e.preventDefault();
        var mode = this.getAttribute("data-tab");
        history.replaceState({ mode: mode }, "", "?mode=" + mode);
        applyMode(mode);
      });
    }
    window.addEventListener("popstate", function () { applyMode(currentMode()); });
  }

  // ── readiness bar ────────────────────────────────────────────────────────
  function render(snap) {
    if (!snap) return;
    var overall = snap.overall || "amber";
    var ov = $(".rb-overall");
    if (ov) {
      ov.setAttribute("data-status", overall);
      $(".rb-glyph", ov).textContent = GLYPH[overall] || "";
      $(".rb-overall-text", ov).textContent = OVERALL_TEXT[overall] || overall;
    }
    var checks = snap.checks || [];

    var strip = $("#rb-checks");
    if (strip) {
      strip.textContent = "";
      checks.forEach(function (c) {
        var chip = document.createElement("span");
        chip.className = "rb-chip";
        chip.setAttribute("data-status", c.status);
        chip.title = c.label + " — " + c.detail;
        chip.textContent = (GLYPH[c.status] || "") + " " + c.label;
        strip.appendChild(chip);
      });
    }
    renderDetail(checks);
    renderTiles(checks);
    renderResumeBanner(snap);
    renderMgmt(snap);
    wizSetReadiness(overall);            // keep the wizard's launch gate live
  }

  function renderDetail(checks) {
    var box = $("#readiness-detail");
    if (!box) return;
    box.textContent = "";
    checks.forEach(function (c) {
      var row = document.createElement("div");
      row.className = "rd-row";
      row.setAttribute("data-status", c.status);

      var head = document.createElement("div");
      head.className = "rd-head";
      head.textContent = (GLYPH[c.status] || "") + " " + c.label;
      row.appendChild(head);

      var detail = document.createElement("div");
      detail.className = "rd-detail";
      detail.textContent = c.detail || "";
      row.appendChild(detail);

      (c.actions || []).forEach(function (a) { row.appendChild(makeActionBtn(a, "rd-action")); });
      box.appendChild(row);
    });
  }

  // ── G4 Operate cockpit ────────────────────────────────────────────────────
  function renderTiles(checks) {
    var grid = $("#readiness-tiles");
    if (!grid) return;
    grid.textContent = "";
    checks.forEach(function (c) {
      var tile = document.createElement("div");
      tile.className = "tile";
      tile.setAttribute("data-status", c.status);

      var head = document.createElement("div");
      head.className = "tile-head";
      var g = document.createElement("span");
      g.className = "tile-glyph";
      g.textContent = GLYPH[c.status] || "";
      var lab = document.createElement("span");
      lab.textContent = c.label;
      head.appendChild(g);
      head.appendChild(lab);
      tile.appendChild(head);

      var det = document.createElement("div");
      det.className = "tile-detail";
      det.textContent = c.detail || "";
      tile.appendChild(det);

      if ((c.actions || []).length) {
        var acts = document.createElement("div");
        acts.className = "tile-actions";
        c.actions.forEach(function (a) { acts.appendChild(makeActionBtn(a, "tile-action")); });
        tile.appendChild(acts);
      }
      grid.appendChild(tile);
    });
  }

  function renderResumeBanner(snap) {
    var banner = $("#resume-banner");
    if (!banner) return;
    if (isResumable(snap)) {
      var s = sessionCheck(snap);
      var det = $("#resume-detail");
      if (det) det.textContent = s ? s.detail : "";
      banner.hidden = false;
    } else {
      banner.hidden = true;
    }
  }

  function renderMgmt(snap) {
    var s = sessionCheck(snap);
    var active = !!(s && s.status === "green");
    ["#mc-meds", "#mc-errors", "#mc-handoff"].forEach(function (sel) {
      var el = $(sel);
      if (!el) return;
      el.setAttribute("data-on", active ? "yes" : "no");
      el.textContent = active ? "Active" : "No session";
    });
  }

  function resumeSession(btn) {
    if (btn) btn.disabled = true;
    fetch("/api/control/session/resume", { method: "POST", credentials: "same-origin" })
      .then(function (r) { if (handle401(r)) return null; return r.ok ? r.json() : null; })
      .then(function () { poll(); })
      .catch(function () { poll(); })
      .then(function () { if (btn) btn.disabled = false; });
  }

  // ── G5 Launch Wizard ──────────────────────────────────────────────────────
  var WIZ = { step: 1, max: 4, sample: null, boot: null, overall: "loading" };

  function readBootstrap() {
    var el = document.getElementById("console-bootstrap");
    if (!el) return null;
    try { return JSON.parse(el.textContent || "{}"); } catch (e) { return null; }
  }

  function initWizard() {
    var boot = readBootstrap();
    if (!boot || !document.getElementById("launch-wizard")) return;
    WIZ.boot = boot;
    fillPersonas(boot.personas || []);   // sample + EHR <option>s are server-rendered
    var sampleSel = $("#wiz-sample");
    if (sampleSel) sampleSel.addEventListener("change", function () { applySample(sampleSel.value); });
    var ehrSel = $("#wiz-ehr");
    if (ehrSel) ehrSel.addEventListener("change", refreshReview);
    var nameEl = $("#wiz-name");
    if (nameEl) nameEl.addEventListener("input", refreshReview);
    var back = $("#wiz-back"), next = $("#wiz-next"), launch = $("#wiz-launch");
    if (back) back.addEventListener("click", function () { wizGoto(WIZ.step - 1); });
    if (next) next.addEventListener("click", function () { wizGoto(WIZ.step + 1); });
    if (launch) launch.addEventListener("click", launchScenario);
    var radios = document.querySelectorAll('input[name="wiz-mode"]');
    for (var i = 0; i < radios.length; i++) {
      radios[i].addEventListener("change", function () { setMode(this.value); });
    }
    var bedCountEl = $("#wiz-bed-count");
    if (bedCountEl) {
      bedCountEl.addEventListener("change", rebuildBedScenarios);
      bedCountEl.addEventListener("input", rebuildBedScenarios);
    }
    setMode("single");
    wizGoto(1);
  }

  function fillPersonas(personas) {
    var box = $("#wiz-personas");
    if (!box) return;
    box.textContent = "";
    personas.forEach(function (p) {
      var row = document.createElement("label");
      row.className = "wiz-persona";
      var sel = document.createElement("input");
      sel.type = "checkbox"; sel.value = p.id; sel.className = "wp-sel";
      sel.addEventListener("change", refreshReview);
      var lab = document.createElement("span");
      lab.className = "wp-label";
      lab.textContent = p.name + (p.role ? " — " + p.role : "");
      var av = document.createElement("span");
      av.className = "wp-avatar";
      var avcb = document.createElement("input");
      avcb.type = "checkbox"; avcb.value = p.id; avcb.className = "wp-avatar-cb";
      var avtxt = document.createElement("span"); avtxt.textContent = "avatar";
      av.appendChild(avcb); av.appendChild(avtxt);
      row.appendChild(sel); row.appendChild(lab); row.appendChild(av);
      box.appendChild(row);
    });
  }

  // ── single ↔ multi-patient mode ───────────────────────────────────────────
  function toggleHidden(sel, hidden) {
    var el = $(sel);
    if (el) el.hidden = !!hidden;
  }

  function setMode(mode) {
    WIZ.mode = (mode === "multi") ? "multi" : "single";
    var multi = WIZ.mode === "multi";
    toggleHidden("#wiz-single", multi);
    toggleHidden("#wiz-multi", !multi);
    toggleHidden("#wiz-scenario-single", multi);
    toggleHidden("#wiz-scenario-multi", !multi);
    toggleHidden("#wiz-personas", multi);
    toggleHidden("#wiz-chars-single-note", multi);
    toggleHidden("#wiz-chars-multi-note", !multi);
    var radios = document.querySelectorAll('input[name="wiz-mode"]');
    for (var i = 0; i < radios.length; i++) radios[i].checked = (radios[i].value === WIZ.mode);
    if (multi) rebuildBedScenarios();
    refreshReview();
  }

  function bedCount() {
    var el = $("#wiz-bed-count");
    var n = el ? parseInt(el.value, 10) : 1;
    if (!(n >= 1)) n = 1;
    if (n > 12) n = 12;
    return n;
  }

  function buildSampleSelect(selectedId) {
    var boot = WIZ.boot || {};
    var sel = document.createElement("select");
    sel.className = "bed-scn-sel";
    var blank = document.createElement("option");
    blank.value = ""; blank.textContent = "— pick a patient scenario —";
    sel.appendChild(blank);
    (boot.samples || []).forEach(function (s) {
      var o = document.createElement("option");
      o.value = s.id; o.textContent = s.name;
      if (selectedId && s.id === selectedId) o.selected = true;
      sel.appendChild(o);
    });
    return sel;
  }

  // One scenario picker per bed; the bed's patient is derived from the sample.
  function rebuildBedScenarios() {
    var box = $("#wiz-bed-scenarios");
    if (!box) return;
    var prev = bedScenarios();                 // preserve selections by bed index
    box.textContent = "";
    var n = bedCount();
    for (var i = 0; i < n; i++) {
      var row = document.createElement("div");
      row.className = "wiz-bed-scn";
      var lab = document.createElement("span");
      lab.className = "wbs-label"; lab.textContent = "Bed " + (i + 1);
      var sel = buildSampleSelect(prev[i] && prev[i].sample);
      sel.addEventListener("change", refreshReview);
      row.appendChild(lab); row.appendChild(sel);
      box.appendChild(row);
    }
    refreshReview();
  }

  function bedScenarios() {
    return Array.prototype.slice.call(document.querySelectorAll("#wiz-bed-scenarios .bed-scn-sel"))
      .map(function (sel) { return { sample: sel.value }; });
  }
  function validBeds() {
    return bedScenarios().filter(function (b) { return b.sample; });
  }
  function sampleById(id) {
    var boot = WIZ.boot || {};
    var f = (boot.samples || []).filter(function (s) { return s.id === id; });
    return f.length ? f[0] : null;
  }

  function applySample(id) {                     // single-patient sample auto-fill
    var s = sampleById(id);
    WIZ.sample = s;
    var notesEl = $("#wiz-notes");
    if (notesEl) notesEl.value = s ? (s.notes || "") : "";
    var nameEl = $("#wiz-name");
    if (nameEl) nameEl.value = s ? (s.name || "") : "";
    var ids = s ? (s.personas || []) : [];        // FULL roster from the sample
    document.querySelectorAll(".wp-sel").forEach(function (cb) {
      cb.checked = ids.indexOf(cb.value) >= 0;
    });
    refreshReview();
  }

  function selectedPersonas() {
    return Array.prototype.slice.call(document.querySelectorAll(".wp-sel:checked"))
      .map(function (cb) { return cb.value; });
  }
  function selectedAvatars() {
    var chosen = selectedPersonas();
    return Array.prototype.slice.call(document.querySelectorAll(".wp-avatar-cb:checked"))
      .map(function (cb) { return cb.value; })
      .filter(function (id) { return chosen.indexOf(id) >= 0; });
  }

  function wizardValid() {                              // single-patient validity
    var nameEl = $("#wiz-name");
    var name = (nameEl && nameEl.value || "").trim();
    return !!name && selectedPersonas().length > 0;
  }
  function modeValid() {
    return WIZ.mode === "multi" ? validBeds().length > 0 : wizardValid();
  }

  // Launch gate (unit-checkable rule): a red readiness check blocks launch; a
  // complete form + non-red readiness allows it (amber = caution, not a blocker —
  // e.g. a cert-SAN drift must not permanently bar a local sim from starting).
  function launchAllowed(overall) {
    return overall !== "red" && modeValid();
  }

  function reviewRow(k, v) {
    var row = document.createElement("div"); row.className = "wr-row";
    var kk = document.createElement("span"); kk.className = "wr-k"; kk.textContent = k;
    var vv = document.createElement("span"); vv.className = "wr-v"; vv.textContent = v;
    row.appendChild(kk); row.appendChild(vv);
    return row;
  }

  function refreshReview() {
    var rev = $("#wiz-review");
    if (rev) {
      rev.textContent = "";
      if (WIZ.mode === "multi") {
        var labelEl = $("#wiz-room-label");
        var mEhr = $("#wiz-ehr");
        rev.appendChild(reviewRow("Mode", "Multi-patient room"));
        rev.appendChild(reviewRow("EHR", (mEhr ? mEhr.value : "") || "—"));
        rev.appendChild(reviewRow("Room", (labelEl && labelEl.value || "").trim() || "Room"));
        var beds = validBeds();
        if (!beds.length) rev.appendChild(reviewRow("Beds", "pick a scenario for at least one bed"));
        beds.forEach(function (b, i) {
          var bs = sampleById(b.sample) || {};
          rev.appendChild(reviewRow("Bed " + (i + 1),
            (bs.name || b.sample) + " · patient " + (bs.patient_id || "?")));
        });
      } else {
        var nameEl = $("#wiz-name");
        var name = (nameEl && nameEl.value || "").trim() || "—";
        var ehrEl = $("#wiz-ehr");
        var n = selectedPersonas().length;
        rev.appendChild(reviewRow("Mode", "Single patient"));
        rev.appendChild(reviewRow("Scenario", name));
        rev.appendChild(reviewRow("EHR", (ehrEl ? ehrEl.value : "") || "—"));
        rev.appendChild(reviewRow("Characters", n ? (n + " selected") : "none — pick at least one"));
        var avs = selectedAvatars().length;
        if (avs) rev.appendChild(reviewRow("Avatars", avs + " with a face"));
      }
    }
    var pill = $("#wiz-readiness-pill");
    if (pill) {
      pill.setAttribute("data-status", WIZ.overall);
      pill.textContent = WIZ.overall === "loading" ? "checking…" : WIZ.overall;
    }
    var btn = $("#wiz-launch");
    if (btn) btn.disabled = !launchAllowed(WIZ.overall);
    var msg = $("#wiz-launch-msg");
    if (msg) {
      if (!modeValid()) {
        msg.textContent = WIZ.mode === "multi"
          ? "Pick a patient scenario for at least one bed."
          : "Add a scenario name and select at least one character.";
      } else if (WIZ.overall === "red") {
        msg.textContent = "Readiness is red — resolve the blocking check before launching.";
      } else if (WIZ.overall === "amber") {
        msg.textContent = "Readiness amber — you can launch; review the warnings in the cockpit.";
      } else {
        msg.textContent = "Ready to launch.";
      }
    }
  }

  function wizSetReadiness(overall) {
    WIZ.overall = overall || "amber";
    if (document.getElementById("launch-wizard")) refreshReview();
  }

  function launchScenario() {
    if (!launchAllowed(WIZ.overall)) return;
    if (WIZ.mode === "multi") { launchRoom(); return; }
    var btn = $("#wiz-launch");
    if (btn) { btn.disabled = true; btn.textContent = "Launching…"; }
    var s = WIZ.sample;
    var fd = new FormData();
    fd.append("scenario_name", ($("#wiz-name").value || "").trim());
    fd.append("scenario_notes", ($("#wiz-notes") && $("#wiz-notes").value || "").trim());
    if (s) {
      fd.append("scenario_text", s.scenario_text || "");
      if (s.program_id) fd.append("program_id", s.program_id);
      if (s.week !== undefined && s.week !== null) fd.append("week", String(s.week));
      (s.modules || []).forEach(function (m) { fd.append("modules", m); });
    }
    selectedPersonas().forEach(function (p) { fd.append("personas", p); });
    selectedAvatars().forEach(function (p) { fd.append("avatar_personas", p); });
    var ehrEl = $("#wiz-ehr");
    if (ehrEl) fd.append("ehr_id", ehrEl.value);
    fetch("/portal/control/start", { method: "POST", credentials: "same-origin", body: fd })
      .then(function (r) { if (handle401(r)) return null; return r.ok ? r.json() : null; })
      .then(function (data) {
        if (data && data.ok && data.redirect_url) { window.location = data.redirect_url; return; }
        var msg = $("#wiz-launch-msg");
        if (msg) msg.textContent = (data && data.message) || "Launch failed.";
        if (btn) { btn.disabled = false; btn.textContent = "Launch scenario"; }
      })
      .catch(function () {
        var msg = $("#wiz-launch-msg");
        if (msg) msg.textContent = "Launch failed (network).";
        if (btn) { btn.disabled = false; btn.textContent = "Launch scenario"; }
      });
  }

  function launchRoom() {
    var btn = $("#wiz-launch");
    if (btn) { btn.disabled = true; btn.textContent = "Launching…"; }
    var notes = ($("#wiz-notes") && $("#wiz-notes").value || "").trim();
    var label = ($("#wiz-room-label") && $("#wiz-room-label").value || "").trim() || "Room";
    var ehrEl = $("#wiz-ehr");
    var ehr = ehrEl ? ehrEl.value : "";                 // one EHR for the whole session
    var encounters = validBeds().map(function (b, i) {
      var s = sampleById(b.sample) || {};
      var enc = {
        scenario_name: "Bed " + (i + 1) + " · " + (s.name || "Scenario"),
        persona_id: s.patient_id || "",                 // patient derived from the scenario
        ehr_id: ehr,
        scenario_notes: notes,
        scenario_text: s.scenario_text || ""
      };
      if (s.program_id) enc.program_id = s.program_id;
      if (s.week !== undefined && s.week !== null) enc.week = s.week;
      enc.modules = s.modules || [];
      return enc;
    });
    fetch("/api/room/start", {
      method: "POST",
      credentials: "same-origin",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ label: label, encounters: encounters })
    })
      .then(function (r) { if (handle401(r)) return null; return r.ok ? r.json() : null; })
      .then(function (data) {
        if (data && data.ok) { window.location = "/portal/room"; return; }
        var msg = $("#wiz-launch-msg");
        if (msg) msg.textContent = (data && data.message) || "Room launch failed.";
        if (btn) { btn.disabled = false; btn.textContent = "Launch scenario"; }
      })
      .catch(function () {
        var msg = $("#wiz-launch-msg");
        if (msg) msg.textContent = "Room launch failed (network).";
        if (btn) { btn.disabled = false; btn.textContent = "Launch scenario"; }
      });
  }

  function wizGoto(n) {
    if (n < 1 || n > WIZ.max) return;
    WIZ.step = n;
    document.querySelectorAll(".wiz-step").forEach(function (st) {
      st.hidden = parseInt(st.getAttribute("data-step"), 10) !== n;
    });
    document.querySelectorAll(".wiz-pill").forEach(function (p) {
      var pn = parseInt(p.getAttribute("data-pill"), 10);
      p.classList.toggle("active", pn === n);
      p.classList.toggle("done", pn < n);
    });
    var back = $("#wiz-back"), next = $("#wiz-next");
    if (back) back.hidden = n === 1;
    if (next) next.hidden = n === WIZ.max;
    if (n === WIZ.max) refreshReview();
  }

  function handle401(r) {
    if (r && r.status === 401) { location.href = "/login"; return true; }
    return false;
  }

  function poll() {
    return fetch("/api/control/readiness", { credentials: "same-origin" })
      .then(function (r) {
        if (handle401(r)) return null;
        return r.ok ? r.json() : null;
      })
      .then(function (snap) { if (snap) render(snap); })
      .catch(function () { /* transient — keep the last rendered state */ });
  }

  function runAction(id, btn) {
    var label = btn ? btn.textContent : "";
    if (btn) { btn.disabled = true; btn.textContent = "…"; }
    fetch("/api/control/readiness/action", {
      method: "POST",
      credentials: "same-origin",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ id: id })
    })
      .then(function (r) {
        if (handle401(r)) return null;
        return r.ok ? r.json() : null;
      })
      .then(function (res) {
        if (res && res.readiness) render(res.readiness);
        else poll();
        if (res && res.hint) window.alert(res.hint);   // restart_hint → show the command
      })
      .catch(function () { poll(); })
      .then(function () { if (btn) { btn.disabled = false; btn.textContent = label; } });
  }

  function wireDetailToggle() {
    var bar = $("#readiness-bar");
    var box = $("#readiness-detail");
    if (!bar || !box) return;
    bar.addEventListener("click", function () {
      var open = box.hidden;
      box.hidden = !open;
      bar.setAttribute("aria-expanded", open ? "true" : "false");
    });
  }

  document.addEventListener("DOMContentLoaded", function () {
    wireTabs();
    wireDetailToggle();
    var testAllBtn = $("#test-all-btn");
    if (testAllBtn) {
      testAllBtn.addEventListener("click", function () { runAction("test_all", testAllBtn); });
    }
    var resumeBtn = $("#resume-btn");
    if (resumeBtn) {
      resumeBtn.addEventListener("click", function () { resumeSession(resumeBtn); });
    }
    initWizard();
    applyMode(currentMode());
    poll();
    setInterval(poll, POLL_MS);
  });
})();
