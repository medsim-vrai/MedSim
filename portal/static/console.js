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
    renderResumedNote(snap);
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

  // G7 — confirm an auto-restored session ("Resumed 'X' (saved HH:MM)").
  function renderResumedNote(snap) {
    var note = $("#resumed-note");
    if (!note) return;
    var s = sessionCheck(snap);
    if (s && s.resumed) {
      var txt = $("#resumed-text");
      if (txt) txt.textContent = s.detail || "Session resumed.";
      note.hidden = false;
    } else {
      note.hidden = true;
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
  var WIZ = { step: 1, max: 5, boot: null, overall: "loading" };

  function readBootstrap() {
    var el = document.getElementById("console-bootstrap");
    if (!el) return null;
    try { return JSON.parse(el.textContent || "{}"); } catch (e) { return null; }
  }

  function initWizard() {
    var boot = readBootstrap();
    if (!boot || !document.getElementById("launch-wizard")) return;
    WIZ.boot = boot;
    fillSharedChars(boot.personas || []);   // shared/universal picker (built once)
    var ehrSel = $("#wiz-ehr");
    if (ehrSel) ehrSel.addEventListener("change", function () { syncCommonUI(); refreshReview(); });
    ["wiz-med-cart", "wiz-med-cart-mars", "wiz-ehr-terminal"].forEach(function (id) {
      var el = document.getElementById(id);
      if (el) el.addEventListener("change", function () { syncCommonUI(); refreshReview(); });
    });
    var back = $("#wiz-back"), next = $("#wiz-next"), launch = $("#wiz-launch");
    if (back) back.addEventListener("click", function () { wizGoto(WIZ.step - 1); });
    if (next) next.addEventListener("click", function () { wizGoto(WIZ.step + 1); });
    if (launch) launch.addEventListener("click", launchScenario);
    var bedCountEl = $("#wiz-bed-count");
    if (bedCountEl) {
      bedCountEl.addEventListener("change", rebuildBedScenarios);
      bedCountEl.addEventListener("input", rebuildBedScenarios);
    }
    var ns = $("#wiz-nurse-station");
    if (ns) ns.addEventListener("change", refreshReview);
    var viewBtns = document.querySelectorAll(".setup-view-btn");
    for (var b = 0; b < viewBtns.length; b++) {
      viewBtns[b].addEventListener("click", function () { setView(this.getAttribute("data-view")); });
    }
    var boardLaunch = $("#board-launch-btn");
    if (boardLaunch) boardLaunch.addEventListener("click", launchScenario);
    rebuildBedScenarios();               // default: one bed (also builds device rows)
    wizGoto(1);
  }

  function characterRow(p, selClass, avClass, checked, disabled, suffix) {
    var row = document.createElement("label");
    row.className = "wiz-persona";
    var sel = document.createElement("input");
    sel.type = "checkbox"; sel.className = selClass; sel.value = p.id;
    if (checked) sel.checked = true;
    if (disabled) sel.disabled = true;
    sel.addEventListener("change", refreshReview);
    var lab = document.createElement("span");
    lab.className = "wp-label";
    lab.textContent = (p.name || p.id) + (suffix != null ? suffix : (p.role ? " — " + p.role : ""));
    var av = document.createElement("span");
    av.className = "wp-avatar";
    var avcb = document.createElement("input");
    avcb.type = "checkbox"; avcb.className = avClass; avcb.value = p.id;
    avcb.addEventListener("change", refreshReview);
    var avt = document.createElement("span"); avt.textContent = "avatar";
    av.appendChild(avcb); av.appendChild(avt);
    row.appendChild(sel); row.appendChild(lab); row.appendChild(av);
    return row;
  }

  // Shared/universal characters — built once; the picker excludes patients.
  function fillSharedChars(personas) {
    var box = $("#wiz-shared-chars");
    if (!box) return;
    box.textContent = "";
    personas.forEach(function (p) {
      if (p.roleGroup === "Patient") return;
      box.appendChild(characterRow(p, "sh-sel", "sh-av", false, false));
    });
  }

  // Every scenario-character occurrence across all beds, with a V1…Vn designation
  // when the SAME name recurs (e.g. a "concerned wife" in two patients' scenarios
  // is two different people — never shared, each unique to its patient).
  function scenarioCharList() {
    var beds = bedScenarios(), nameCount = {}, nameSeen = {}, out = [];
    beds.forEach(function (b) {
      if (!b.sample) return;
      var s = sampleById(b.sample); if (!s) return;
      (s.personas || []).forEach(function (pid) {
        var p = personaById(pid); var nm = (p && p.name) || pid;
        nameCount[nm] = (nameCount[nm] || 0) + 1;
      });
    });
    beds.forEach(function (b, i) {
      if (!b.sample) return;
      var s = sampleById(b.sample); if (!s) return;
      (s.personas || []).forEach(function (pid) {
        var p = personaById(pid) || { id: pid, name: pid };
        var nm = p.name || pid, variant = "";
        if (nameCount[nm] > 1) { nameSeen[nm] = (nameSeen[nm] || 0) + 1; variant = "V" + nameSeen[nm]; }
        out.push({ bed: i, id: pid, name: nm, role: p.role || "",
                   patient: isPatientPersona(pid), variant: variant });
      });
    });
    return out;
  }

  // Scenario characters — per bed, from each scenario's roster (patient locked in).
  function rebuildScenarioChars() {
    var box = $("#wiz-scenario-chars");
    if (!box) return;
    box.textContent = "";
    var list = scenarioCharList();
    var beds = bedScenarios();
    var firstNotes = "", any = false;
    beds.forEach(function (b, i) {
      if (!b.sample) return;
      var s = sampleById(b.sample); if (!s) return;
      any = true;
      if (!firstNotes) firstNotes = s.notes || "";
      var group = document.createElement("div");
      group.className = "sc-group"; group.setAttribute("data-bed", String(i));
      var h = document.createElement("div");
      h.className = "sc-group-h"; h.textContent = "Bed " + (i + 1) + " · " + (s.name || b.sample);
      group.appendChild(h);
      list.filter(function (c) { return c.bed === i; }).forEach(function (c) {
        var p = personaById(c.id) || { id: c.id, name: c.name };
        var suffix = (c.variant ? " · " + c.variant : "") +
                     (c.patient ? " — Patient" : (c.role ? " — " + c.role : ""));
        group.appendChild(characterRow(p, "sc-sel", "sc-av", true, c.patient, suffix));
      });
      box.appendChild(group);
    });
    if (!any) {
      var empty = document.createElement("p");
      empty.className = "muted"; empty.textContent = "Pick a scenario for each bed first.";
      box.appendChild(empty);
    }
    var notesEl = $("#wiz-notes");
    if (notesEl && !notesEl.value && firstNotes) notesEl.value = firstNotes;
    refreshReview();
  }

  // Beds drive everything: 1 bed = single patient (rich roster), >1 = a room.
  function isMulti() { return bedCount() > 1; }

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
      sel.addEventListener("change", rebuildScenarioChars);
      row.appendChild(lab); row.appendChild(sel);
      box.appendChild(row);
    }
    rebuildDevices();
    rebuildScenarioChars();
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

  function personaById(id) {
    var ps = (WIZ.boot && WIZ.boot.personas) || [];
    for (var i = 0; i < ps.length; i++) { if (ps[i].id === id) return ps[i]; }
    return null;
  }
  function isPatientPersona(id) {
    var p = personaById(id);
    return !!(p && p.roleGroup === "Patient");
  }
  // Scenario cast for one bed = its scenario's checked roster (patient locked in).
  function scenarioCastFor(bedIdx) {
    var g = document.querySelector('#wiz-scenario-chars .sc-group[data-bed="' + bedIdx + '"]');
    if (!g) return [];
    return Array.prototype.slice.call(g.querySelectorAll(".sc-sel:checked"))
      .map(function (cb) { return cb.value; });
  }
  function scenarioAvatarsFor(bedIdx) {
    var g = document.querySelector('#wiz-scenario-chars .sc-group[data-bed="' + bedIdx + '"]');
    if (!g) return [];
    return Array.prototype.slice.call(g.querySelectorAll(".sc-av:checked"))
      .map(function (cb) { return cb.value; });
  }
  // Shared/universal cast = the explicit picker, added to every bed.
  function sharedCast() {
    return Array.prototype.slice.call(document.querySelectorAll("#wiz-shared-chars .sh-sel:checked"))
      .map(function (cb) { return cb.value; });
  }
  function sharedAvatars() {
    return Array.prototype.slice.call(document.querySelectorAll("#wiz-shared-chars .sh-av:checked"))
      .map(function (cb) { return cb.value; });
  }
  function uniq(arr) {
    return arr.filter(function (x, i, a) { return x && a.indexOf(x) === i; });
  }

  // ── devices ───────────────────────────────────────────────────────────────
  // One device picker (basic + advanced) per bed; nursing station is a group
  // resource (rooms only). Plans are minted into QR stations at launch.
  function rebuildDevices() {
    var box = $("#wiz-devices");
    if (!box) return;
    var prev = bedDevices();                  // preserve per-bed selections by index
    box.textContent = "";
    var cat = ((WIZ.boot && WIZ.boot.devices) || [])
      .filter(function (d) { return !d.common; });   // med cart is common, not per-bed
    var n = bedCount();
    for (var i = 0; i < n; i++) {
      var block = document.createElement("div");
      block.className = "wiz-dev-bed";
      block.setAttribute("data-bed", String(i));
      var head = document.createElement("div");
      head.className = "wdb-head"; head.textContent = "Bed " + (i + 1);
      block.appendChild(head);
      var grid = document.createElement("div");
      grid.className = "wdb-grid";
      cat.forEach(function (d) {
        var lab = document.createElement("label");
        lab.className = "dev-opt";
        var cb = document.createElement("input");
        cb.type = "checkbox"; cb.className = "dev-cb"; cb.value = d.kind;
        if (prev[i] && prev[i].indexOf(d.kind) >= 0) cb.checked = true;
        cb.addEventListener("change", refreshReview);
        var t = document.createElement("span");
        t.textContent = d.name;
        if (d.group === "Advanced") {
          var badge = document.createElement("span");
          badge.className = "dev-adv"; badge.textContent = "adv";
          t.appendChild(badge);
        }
        lab.appendChild(cb); lab.appendChild(t);
        grid.appendChild(lab);
      });
      block.appendChild(grid);
      box.appendChild(block);
    }
    syncCommonUI();
    refreshReview();
  }

  function syncCommonUI() {
    var nurseRow = $("#wiz-nurse-row");
    if (nurseRow) nurseRow.hidden = !isMulti();   // nursing station = a room (multi) resource
    var cart = $("#wiz-med-cart");
    var marsRow = $("#wiz-med-cart-mars-row");
    if (marsRow) marsRow.hidden = !(cart && cart.checked);
    var ehrName = $("#wiz-ehr-confirm-name");
    var ehrSel = $("#wiz-ehr");
    if (ehrName && ehrSel && ehrSel.selectedIndex >= 0) {
      ehrName.textContent = ehrSel.options[ehrSel.selectedIndex].textContent;
    }
  }

  function bedDevices() {
    return Array.prototype.slice.call(document.querySelectorAll("#wiz-devices .wiz-dev-bed"))
      .map(function (block) {
        return Array.prototype.slice.call(block.querySelectorAll(".dev-cb:checked"))
          .map(function (cb) { return cb.value; });
      });
  }

  // Mint a bed's planned devices (QR stations) once it has a join code at launch.
  function registerDevices(join, kinds) {
    var cat = (WIZ.boot && WIZ.boot.devices) || [];
    var byKind = {};
    cat.forEach(function (d) { byKind[d.kind] = d; });
    var chain = Promise.resolve();
    (kinds || []).forEach(function (k) {
      var d = byKind[k];
      if (!d) return;
      chain = chain.then(function () {
        return fetch("/api/device/register?join=" + encodeURIComponent(join), {
          method: "POST", credentials: "same-origin",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify({ device_kind: d.kind, device_model: d.model, label: d.name })
        }).catch(function () { /* best-effort — still addable in the cockpit */ });
      });
    });
    return chain;
  }

  // ── common devices (shared across the session): med cart, records terminal,
  //    nursing station — minted at launch via existing endpoints. ────────────
  function commonPlan() {
    function on(id) { var e = document.getElementById(id); return !!(e && e.checked); }
    return { medCart: on("wiz-med-cart"), mars: on("wiz-med-cart-mars"),
             ehrTerminal: on("wiz-ehr-terminal"), nurse: on("wiz-nurse-station") };
  }

  function launchRoomCommon(encs) {
    var p = commonPlan();
    var chain = Promise.resolve();
    if (p.medCart) {
      chain = chain.then(function () {
        if (p.mars) {                                  // one cart linked to every bed -> per-patient MARs
          return fetch("/api/room/med_cart/register", {
            method: "POST", credentials: "same-origin",
            headers: { "Content-Type": "application/json" },
            body: JSON.stringify({ label: "Med cart",
              encounter_ids: encs.map(function (e) { return e.encounter_id; }) })
          }).catch(function () {});
        }
        var j = encs[0] && encs[0].join_code;          // plain cart on bed 1
        return j ? registerDevices(j, ["cabinet"]) : null;
      });
    }
    if (p.ehrTerminal) {
      encs.forEach(function (e) {                       // registers each patient + an EHR station
        chain = chain.then(function () {
          return fetch("/portal/room/encounter/" + encodeURIComponent(e.encounter_id) + "/launch_ehr",
            { method: "POST", credentials: "same-origin" }).catch(function () {});
        });
      });
    }
    if (p.nurse) {
      chain = chain.then(function () {
        return fetch("/portal/control/launch_nurse_station",
          { credentials: "same-origin" }).catch(function () {});
      });
    }
    return chain;
  }

  function launchSingleCommon(joinCode) {
    var p = commonPlan();
    var chain = Promise.resolve();
    if (p.medCart && joinCode) {
      chain = chain.then(function () { return registerDevices(joinCode, ["cabinet"]); });
    }
    if (p.ehrTerminal) {
      chain = chain.then(function () {                  // registers the patient + an EHR station
        return fetch("/portal/control/launch_ehr",
          { method: "POST", credentials: "same-origin" }).catch(function () {});
      });
    }
    return chain;                                       // nursing station = rooms only
  }

  function modeValid() {
    return validBeds().length >= 1;   // a scenario per used bed → patient + cast in the roster
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
      var ehrEl = $("#wiz-ehr");
      rev.appendChild(reviewRow("EHR", (ehrEl ? ehrEl.value : "") || "—"));
      var beds = validBeds();
      if (!beds.length) {
        rev.appendChild(reviewRow("Beds", "pick a scenario for at least one bed"));
      } else if (isMulti()) {
        rev.appendChild(reviewRow("Mode", beds.length + "-bed room"));
        beds.forEach(function (b, i) {
          var bs = sampleById(b.sample) || {};
          rev.appendChild(reviewRow("Bed " + (i + 1),
            (bs.name || b.sample) + " · patient " + (bs.patient_id || "?")));
        });
        var sc = sharedCast();
        if (sc.length) rev.appendChild(reviewRow("Shared cast", sc.length + " at every bed"));
      } else {
        var bs0 = sampleById(beds[0].sample) || {};
        rev.appendChild(reviewRow("Mode", "Single patient"));
        rev.appendChild(reviewRow("Scenario", bs0.name || beds[0].sample));
        rev.appendChild(reviewRow("Characters",
          scenarioCastFor(0).length + " scenario + " + sharedCast().length + " shared"));
        var avs = uniq(scenarioAvatarsFor(0).concat(sharedAvatars())).length;
        if (avs) rev.appendChild(reviewRow("Avatars", avs + " with a face"));
      }
      var devs = bedDevices();
      var totalDev = devs.reduce(function (a, b) { return a + b.length; }, 0);
      if (totalDev) {
        rev.appendChild(reviewRow("Devices", totalDev + " across " + devs.length + " bed(s)"));
      }
      var cp = commonPlan();
      var common = [];
      if (cp.medCart) common.push("med cart" + (cp.mars ? " + MARs" : ""));
      if (cp.ehrTerminal) common.push("records terminal");
      if (cp.nurse && isMulti()) common.push("nursing station");
      if (common.length) rev.appendChild(reviewRow("Common", common.join(", ")));
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
        msg.textContent = (validBeds().length < 1)
          ? "Pick a scenario for at least one bed."
          : "Select at least one character.";
      } else if (WIZ.overall === "red") {
        msg.textContent = "Readiness is red — resolve the blocking check before launching.";
      } else if (WIZ.overall === "amber") {
        msg.textContent = "Readiness amber — you can launch; review the warnings in the cockpit.";
      } else {
        msg.textContent = "Ready to launch.";
      }
    }
    var bv = $("#setup-board-view");          // keep the board in sync when it's showing
    if (bv && !bv.hidden) renderBoard();
  }

  function wizSetReadiness(overall) {
    WIZ.overall = overall || "amber";
    if (document.getElementById("launch-wizard")) refreshReview();
  }

  // ── G6 ecosystem board — an alternate VIEW of the same wizard state ───────
  // opts: a number (jump to that wizard step) OR {gotoStep, popover: fn(card)->node}.
  // With a popover, clicking opens an inline editor; "Open in Set up →" still jumps.
  function boardCard(title, sub, status, opts) {
    if (typeof opts === "number") opts = { gotoStep: opts };
    opts = opts || {};
    var card = document.createElement("button");
    card.type = "button";
    card.className = "board-card";
    card.setAttribute("data-status", status || "green");
    var dot = document.createElement("span"); dot.className = "bc-dot";
    var body = document.createElement("span"); body.className = "bc-body";
    var t = document.createElement("span"); t.className = "bc-title"; t.textContent = title;
    body.appendChild(t);
    if (sub) {
      var s = document.createElement("span"); s.className = "bc-sub"; s.textContent = sub;
      body.appendChild(s);
    }
    card.appendChild(dot); card.appendChild(body);
    if (opts.popover || opts.gotoStep) {
      card.addEventListener("click", function () {
        if (opts.popover) {
          var node = opts.popover(card);
          if (node) { openBoardPopover(card, node); return; }
        }
        if (opts.gotoStep) { setView("wizard"); wizGoto(opts.gotoStep); }
      });
    }
    return card;
  }

  // ── board inline-edit popover ──────────────────────────────────────────────
  function closeBoardPopover() {
    var pop = $("#board-popover");
    if (!pop) return;
    pop.hidden = true; pop.textContent = "";
    if (pop._onDoc) { document.removeEventListener("mousedown", pop._onDoc); pop._onDoc = null; }
    if (pop._onKey) { document.removeEventListener("keydown", pop._onKey); pop._onKey = null; }
  }

  function openBoardPopover(anchor, content) {
    var pop = $("#board-popover");
    if (!pop) return;
    closeBoardPopover();
    pop.appendChild(content);
    pop.hidden = false;
    var r = anchor.getBoundingClientRect();
    pop.style.top = (r.bottom + 6) + "px";
    pop.style.left = Math.max(8, Math.min(r.left, window.innerWidth - 280)) + "px";
    setTimeout(function () {
      pop._onDoc = function (e) {
        if (!pop.contains(e.target) && !anchor.contains(e.target)) closeBoardPopover();
      };
      pop._onKey = function (e) { if (e.key === "Escape") closeBoardPopover(); };
      document.addEventListener("mousedown", pop._onDoc);
      document.addEventListener("keydown", pop._onKey);
    }, 0);
  }

  function popoverShell(label, control, gotoStep) {
    var box = document.createElement("div");
    box.className = "bp-inner";
    var h = document.createElement("div"); h.className = "bp-label"; h.textContent = label;
    box.appendChild(h);
    if (control) box.appendChild(control);
    if (gotoStep) {
      var open = document.createElement("button");
      open.type = "button"; open.className = "bp-open"; open.textContent = "Open in Set up →";
      open.addEventListener("click", function () {
        closeBoardPopover(); setView("wizard"); wizGoto(gotoStep);
      });
      box.appendChild(open);
    }
    return box;
  }

  // Edits drive the LIVE wizard control (dispatch change → prefill/review), then
  // re-render the board — no divergent state.
  function bedScenarioPopover(idx) {
    var sel = buildSampleSelect(bedScenarios()[idx] && bedScenarios()[idx].sample);
    sel.addEventListener("change", function () {
      var live = document.querySelectorAll("#wiz-bed-scenarios .bed-scn-sel");
      if (live[idx]) {
        live[idx].value = sel.value;
        live[idx].dispatchEvent(new Event("change", { bubbles: true }));
      }
      renderBoard();
    });
    return popoverShell("Bed " + (idx + 1) + " — scenario", sel, 2);
  }

  function ehrPopover() {
    var live = $("#wiz-ehr");
    var sel = document.createElement("select");
    if (live) Array.prototype.forEach.call(live.options, function (o) {
      var opt = document.createElement("option");
      opt.value = o.value; opt.textContent = o.textContent;
      if (o.value === live.value) opt.selected = true;
      sel.appendChild(opt);
    });
    sel.addEventListener("change", function () {
      if (live) { live.value = sel.value; live.dispatchEvent(new Event("change", { bubbles: true })); }
      renderBoard();
    });
    return popoverShell("EHR for the session", sel, 1);
  }

  function nursePopover() {
    var live = $("#wiz-nurse-station");
    var lab = document.createElement("label"); lab.className = "bp-check";
    var cb = document.createElement("input");
    cb.type = "checkbox"; cb.checked = !!(live && live.checked);
    var sp = document.createElement("span"); sp.textContent = "Nursing station on";
    cb.addEventListener("change", function () {
      if (live) { live.checked = cb.checked; live.dispatchEvent(new Event("change", { bubbles: true })); }
      renderBoard();
    });
    lab.appendChild(cb); lab.appendChild(sp);
    return popoverShell("Group resource", lab, 4);
  }

  function renderBoard() {
    var scen = $("#board-scenario");
    if (scen) {
      scen.textContent = "";
      var cast = scenarioCharList().filter(function (c) { return !c.patient; });  // patients live in Rooms
      if (!cast.length) {
        scen.appendChild(boardCard("No scenario cast", "pick scenarios", "amber", 2));
      } else {
        cast.forEach(function (c) {
          scen.appendChild(boardCard(c.name + (c.variant ? " · " + c.variant : ""),
            "Bed " + (c.bed + 1), "green", 3));
        });
      }
    }
    var sc = $("#board-shared");
    if (sc) {
      sc.textContent = "";
      var shared = sharedCast();
      if (!shared.length) {
        sc.appendChild(boardCard("Add shared characters", "common doctor / allied health", "amber", 3));
      } else {
        shared.forEach(function (id) {
          var p = personaById(id) || {};
          sc.appendChild(boardCard(p.name || id, p.role || "", "green", 3));
        });
      }
    }
    var res = $("#board-resources");
    if (res) {
      res.textContent = "";
      var ehrEl = $("#wiz-ehr");
      res.appendChild(boardCard("EHR", (ehrEl ? ehrEl.value : "") || "—", "green",
        { gotoStep: 1, popover: ehrPopover }));
      var ns = $("#wiz-nurse-station");
      res.appendChild(boardCard("Nursing station", (ns && ns.checked) ? "on" : "off",
        (ns && ns.checked) ? "green" : "amber", { gotoStep: 4, popover: nursePopover }));
    }
    var rooms = $("#board-rooms");
    if (rooms) {
      rooms.textContent = "";
      var n = bedCount(), scn = bedScenarios(), devs = bedDevices();
      for (var i = 0; i < n; i++) {
        (function (idx) {
          var sel = scn[idx] && scn[idx].sample;
          var s = sel ? sampleById(sel) : null;
          var sub = s ? ((s.name || sel) + " · " + ((devs[idx] && devs[idx].length) || 0) + " device(s)")
                      : "no scenario yet";
          rooms.appendChild(boardCard("Bed " + (idx + 1), sub, s ? "green" : "amber",
            { gotoStep: 2, popover: function () { return bedScenarioPopover(idx); } }));
        })(i);
      }
    }
    var pill = $("#board-readiness");
    if (pill) {
      pill.setAttribute("data-status", WIZ.overall);
      pill.textContent = WIZ.overall === "loading" ? "checking…" : WIZ.overall;
    }
    var lb = $("#board-launch-btn");
    if (lb) lb.disabled = !launchAllowed(WIZ.overall);
    var lm = $("#board-launch-msg");
    if (lm) lm.textContent = modeValid() ? "" : "Pick a scenario for at least one bed.";
  }

  function setView(view) {
    var isBoard = view === "board";
    var wiz = $("#setup-wizard-view"), board = $("#setup-board-view");
    if (wiz) wiz.hidden = isBoard;
    if (board) board.hidden = !isBoard;
    document.querySelectorAll(".setup-view-btn").forEach(function (b) {
      b.classList.toggle("active", b.getAttribute("data-view") === view);
    });
    if (isBoard) renderBoard();
  }

  function launchScenario() {
    if (!launchAllowed(WIZ.overall)) return;
    if (isMulti()) { launchRoom(); return; }
    var btn = $("#wiz-launch");
    if (btn) { btn.disabled = true; btn.textContent = "Launching…"; }
    var bed = validBeds()[0];
    var s = bed ? sampleById(bed.sample) : null;
    var fd = new FormData();
    fd.append("scenario_name", (s && s.name) || "Scenario");
    fd.append("scenario_notes", ($("#wiz-notes") && $("#wiz-notes").value || "").trim());
    if (s) {
      fd.append("scenario_text", s.scenario_text || "");
      if (s.program_id) fd.append("program_id", s.program_id);
      if (s.week !== undefined && s.week !== null) fd.append("week", String(s.week));
      (s.modules || []).forEach(function (m) { fd.append("modules", m); });
    }
    var roster = uniq(scenarioCastFor(0).concat(sharedCast()));   // bed-1 scenario cast (incl. patient) + shared
    roster.forEach(function (p) { fd.append("personas", p); });
    var avs = uniq(scenarioAvatarsFor(0).concat(sharedAvatars()));
    avs.forEach(function (p) { if (roster.indexOf(p) >= 0) fd.append("avatar_personas", p); });
    var ehrEl = $("#wiz-ehr");
    if (ehrEl) fd.append("ehr_id", ehrEl.value);
    fetch("/portal/control/start", { method: "POST", credentials: "same-origin", body: fd })
      .then(function (r) { if (handle401(r)) return null; return r.ok ? r.json() : null; })
      .then(function (data) {
        if (data && data.ok && data.redirect_url) {
          var kinds = bedDevices()[0] || [];          // mint bed 1's planned devices
          var go = function () { window.location = "/portal/console?mode=operate"; };
          var chain = Promise.resolve();
          if (data.join_code && kinds.length) {
            chain = chain.then(function () { return registerDevices(data.join_code, kinds); });
          }
          chain.then(function () { return launchSingleCommon(data.join_code); }).then(go);
          return;
        }
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
    var label = "Training room";
    var ehrEl = $("#wiz-ehr");
    var ehr = ehrEl ? ehrEl.value : "";                 // one EHR for the whole session
    var shared = sharedCast();                          // universal cast across every bed
    var sharedAv = sharedAvatars();
    var encounters = [];
    bedScenarios().forEach(function (b, i) {            // original bed index (matches sc-group)
      if (!b.sample) return;
      var s = sampleById(b.sample) || {};
      var patient = s.patient_id || "";
      var roster = uniq(scenarioCastFor(i).concat(shared));   // bed's scenario cast (incl. patient) + shared
      var avatars = uniq(scenarioAvatarsFor(i).concat(sharedAv))
        .filter(function (id) { return roster.indexOf(id) >= 0; });
      var enc = {
        scenario_name: "Bed " + (i + 1) + " · " + (s.name || "Scenario"),
        persona_id: patient,                            // patient derived from the scenario
        personas: roster,                               // roster drives runtime availability
        avatar_personas: avatars,
        ehr_id: ehr,
        scenario_notes: notes,
        scenario_text: s.scenario_text || ""
      };
      if (s.program_id) enc.program_id = s.program_id;
      if (s.week !== undefined && s.week !== null) enc.week = s.week;
      enc.modules = s.modules || [];
      encounters.push(enc);
    });
    fetch("/api/room/start", {
      method: "POST",
      credentials: "same-origin",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ label: label, encounters: encounters, shared_personas: shared })
    })
      .then(function (r) { if (handle401(r)) return null; return r.ok ? r.json() : null; })
      .then(function (data) {
        if (data && data.ok) {
          var encs = data.encounters || [];
          var devs = bedDevices();
          var chain = Promise.resolve();
          encs.forEach(function (e, i) {              // mint each bed's planned devices
            var kinds = devs[i] || [];
            if (e.join_code && kinds.length) {
              chain = chain.then(function () { return registerDevices(e.join_code, kinds); });
            }
          });
          chain = chain.then(function () { return launchRoomCommon(encs); });  // common devices
          chain.then(function () { window.location = "/portal/console?mode=operate"; });
          return;
        }
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
