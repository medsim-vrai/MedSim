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
    applyMode(currentMode());
    poll();
    setInterval(poll, POLL_MS);
  });
})();
