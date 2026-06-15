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

      (c.actions || []).forEach(function (a) {
        var btn = document.createElement("button");
        btn.type = "button";
        btn.className = "rd-action";
        btn.textContent = a.label;
        btn.addEventListener("click", function () { runAction(a.id, btn); });
        row.appendChild(btn);
      });
      box.appendChild(row);
    });
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
    applyMode(currentMode());
    poll();
    setInterval(poll, POLL_MS);
  });
})();
