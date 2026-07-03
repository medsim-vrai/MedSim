/* FR-019 — Network & device-status topology renderer.
   A pure render of the latest NetworkSnapshot (GET /api/network/snapshot).
   Truth lives in MedSim; this file never invents status. Color = class,
   line style = state, dashed/dotted = relationship (see
   docs/FR-019-network-status/README.md — the encoding IS the product). */
(function () {
  "use strict";
  var NS = "http://www.w3.org/2000/svg";
  var POLL_MS = 2800;
  // Real font stacks — SVG presentation attributes don't resolve CSS var().
  var MONO = '"IBM Plex Mono",ui-monospace,Menlo,Consolas,monospace';
  var SANS = '"IBM Plex Sans",ui-sans-serif,system-ui,-apple-system,"Segoe UI",Roboto,sans-serif';

  // Class → color (the encoding — do not alter). Unknown degrades to neutral gray.
  var CLS = {
    control: "#3a3f47", operational: "#2f6db0", character: "#8a4f9e",
    physio: "#1f8f7a", vrai: "#c2862c", supporting: "#7b7f88", student: "#b0567f"
  };
  var NEUTRAL = "#999690", AVAIL = "#b9b6ae", FAULT = "#c0473f", INK = "#22211d",
      PAPER = "#fffefb", BORDER = "#cfccc4", FAINT = "#8a8780";
  function clsColor(c) { return CLS[c] || NEUTRAL; }

  // Link line style: color from class, dash/width/opacity/animation from state.
  // Relationship links (assign/student/role) override per the spec table.
  function linkStyle(kind, cls, state) {
    var color = clsColor(cls);
    if (kind === "student") return { stroke: CLS.student, w: 1.2, dash: "4 3", op: 0.65 };
    if (kind === "role")    return { stroke: CLS.student, w: 1.2, dash: "1 4", op: 0.7 };
    if (kind === "assign")  return { stroke: color, w: 1.2, dash: "4 3", op: 0.65 };
    switch (state) {
      case "active":    return { stroke: color, w: 1.7, dash: "7 5", op: 1, anim: "flow" };
      case "idle":      return { stroke: color, w: 1.2, dash: null, op: 0.5 };
      case "available": return { stroke: AVAIL, w: 1.0, dash: "1.5 5", op: 0.85 };
      case "fault":     return { stroke: FAULT, w: 1.4, dash: "5 4", op: 0.9, anim: "blink" };
      default:          return { stroke: NEUTRAL, w: 1.2, dash: null, op: 0.5 };
    }
  }

  // ── minimal SVG dsl ──────────────────────────────────────────────────────
  function E(name, attrs, kids) {
    var e = document.createElementNS(NS, name);
    if (attrs) for (var k in attrs) if (attrs[k] != null) e.setAttribute(k, attrs[k]);
    if (kids) kids.forEach(function (c) { if (c) e.appendChild(c); });
    return e;
  }
  function txt(s, attrs) { var e = E("text", attrs); e.textContent = s == null ? "" : String(s); return e; }

  // ── snapshot helpers ─────────────────────────────────────────────────────
  function rooms(s) { var r = []; (s.units || []).forEach(function (u) { (u.rooms || []).forEach(function (x) { r.push(x); }); }); return r; }
  function patients(s) { var p = []; rooms(s).forEach(function (r) { (r.patients || []).forEach(function (x) { p.push(x); }); }); return p; }
  function allDevices(s) {
    var out = (s.commonDevices || []).slice();
    patients(s).forEach(function (p) {
      if (p.manikin) out.push(p.manikin);
      if (p.tablet) out.push(p.tablet);
      (p.supporting || []).forEach(function (d) { out.push(d); });
    });
    return out;
  }
  function counts(s) {
    var c = { active: 0, idle: 0, available: 0, fault: 0 };
    allDevices(s).forEach(function (d) { if (c[d.state] != null) c[d.state]++; });
    return c;
  }
  function deriveLinks(s) {
    var L = [], ctrl = s.control && s.control.id;
    (s.commonDevices || []).forEach(function (d) {
      if (d.assignedToPatientId) {
        // assigned to a bed → clustered with that patient (local link), not shared
        L.push({ from: d.assignedToPatientId, to: d.id, kind: "local", cls: d.cls, state: d.state });
      } else {
        L.push({ from: ctrl, to: d.id, kind: "control", cls: d.cls, state: d.state });
      }
    });
    patients(s).forEach(function (p) {
      [p.manikin, p.tablet].forEach(function (d) {
        if (!d) return;
        L.push({ from: ctrl, to: d.id, kind: "control", cls: d.cls, state: d.state });
        L.push({ from: p.id, to: d.id, kind: "local", cls: d.cls, state: d.state });
      });
      (p.supporting || []).forEach(function (d) {
        L.push({ from: p.id, to: d.id, kind: "local", cls: d.cls, state: d.state });
      });
    });
    (s.students || []).forEach(function (st) {
      (st.patientIds || []).forEach(function (pid) { L.push({ from: st.id, to: pid, kind: "student", cls: "student" }); });
      if (st.role) {
        // Link to the seat THIS student fills (server sets studentId), so with two
        // same-role seats each student's link lands on their own seat — not both on
        // the first. Fall back to the first matching role seat for older snapshots.
        var seats = (s.commonDevices || []).filter(function (d) { return d.cls === "character" && d.role === st.role; });
        var rd = seats.filter(function (d) { return d.studentId === st.id; })[0] || seats[0];
        if (rd) L.push({ from: st.id, to: rd.id, kind: "role", cls: "student" });
      }
    });
    return L;
  }

  // ── node geometry record ─────────────────────────────────────────────────
  function node(id, cx, cy, w, h, r) {
    return { id: id, cx: cx, cy: cy, w: w, h: h, r: r || 0,
             top: r ? cy - r : cy - h / 2, bot: r ? cy + r : cy + h / 2 };
  }

  // ── node renderers ───────────────────────────────────────────────────────
  function statusPip(x, y, cls, state) {
    var col = clsColor(cls);
    if (state === "active") return E("circle", { cx: x, cy: y, r: 3.2, fill: col });
    if (state === "idle") return E("circle", { cx: x, cy: y, r: 3, fill: "none", stroke: col, "stroke-width": 1.3 });
    if (state === "available") return E("circle", { cx: x, cy: y, r: 3, fill: "none", stroke: AVAIL, "stroke-width": 1.2, "stroke-dasharray": "1 1.6" });
    // fault — filled red + blinking halo
    return E("g", null, [
      E("circle", { cx: x, cy: y, r: 5.5, fill: FAULT, opacity: 0.28, "class": "blink" }),
      E("circle", { cx: x, cy: y, r: 3.2, fill: FAULT })
    ]);
  }
  function deviceBlock(d, n) {
    var w = n.w, h = n.h, x = n.cx - w / 2, y = n.cy - h / 2, col = clsColor(d.cls);
    var kids = [
      E("rect", { x: 0, y: 0, width: w, height: h, rx: 5, fill: PAPER, stroke: BORDER, "stroke-width": 1 }),
      E("rect", { x: 0, y: 2, width: 3.5, height: h - 4, rx: 1.5, fill: col }),
      txt(d.tag, { x: 8, y: 10, "font-family": MONO, "font-size": 8, fill: FAINT, "letter-spacing": ".02em" }),
      txt((d.name || "").slice(0, 15), { x: 8, y: h - 8, "font-family": SANS, "font-size": 10, "font-weight": 500, fill: INK }),
      statusPip(w - 8, 9, d.cls, d.state)
    ];
    if (d.filledBy) {
      // N0 — a student fills this character seat: student-colored dashed frame
      // + who, so the view reads "the student replaced the AI" at a glance.
      kids.push(E("rect", { x: -1.5, y: -1.5, width: w + 3, height: h + 3, rx: 6, fill: "none", stroke: CLS.student, "stroke-width": 1.2, "stroke-dasharray": "3 2.4" }));
      kids.push(txt(String(d.filledBy).slice(0, 12).toUpperCase(), { x: w - 8, y: 10, "text-anchor": "end", "font-family": MONO, "font-size": 6.5, fill: CLS.student, "letter-spacing": ".04em" }));
    }
    if (d.managed) {
      // instructor override active — small amber pip INSIDE the block (a label
      // below the box was overpainted by the next stacked block's rect).
      kids.push(E("circle", { cx: 6, cy: h - 6, r: 2.6, fill: "#c98a1a" }));
    }
    return E("g", { transform: "translate(" + x + "," + y + ")", "data-node-id": d.id || null,
                    "data-node-state": (d.managed ? "managed:" : "") + (d.state || "") }, kids);
  }
  function controlNode(c, n) {
    var w = n.w, h = n.h, x = n.cx - w / 2, y = n.cy - h / 2;
    var g = E("g", { transform: "translate(" + x + "," + y + ")" }, [
      E("circle", { cx: w / 2, cy: h / 2, r: h / 2, fill: "none", stroke: CLS.control, "stroke-width": 1, opacity: 0.5, "class": "scan" }),
      E("rect", { x: 0, y: 0, width: w, height: h, rx: 7, fill: CLS.control }),
      E("circle", { cx: 13, cy: h / 2, r: 4, fill: c.state === "fault" ? FAULT : "#5fd39e" }),
      txt(c.tag, { x: 24, y: h / 2 - 3, "font-family": MONO, "font-size": 8.5, fill: "#c7cad0" }),
      txt(c.name, { x: 24, y: h / 2 + 11, "font-family": SANS, "font-size": 11, "font-weight": 600, fill: "#fff" })
    ]);
    return g;
  }
  function patientCircle(p, n) {
    return E("g", null, [
      txt("BED " + p.bed, { x: n.cx, y: n.cy - n.r - 7, "text-anchor": "middle", "font-family": MONO, "font-size": 8, fill: FAINT, "letter-spacing": ".1em" }),
      E("circle", { cx: n.cx, cy: n.cy, r: n.r, fill: PAPER, stroke: INK, "stroke-width": 1.4 }),
      txt(p.tag, { x: n.cx, y: n.cy + 3.5, "text-anchor": "middle", "font-family": MONO, "font-size": 9.5, "font-weight": 600, fill: INK })
    ]);
  }
  function studentPill(st, n) {
    var w = n.w, h = n.h, x = n.cx - w / 2, y = n.cy - h / 2;
    var sum = (st.patientIds || []).length + " PT" + ((st.patientIds || []).length === 1 ? "" : "S");
    if (st.role) sum += " · " + String(st.role).replace(/_/g, " ").toUpperCase();
    return E("g", { transform: "translate(" + x + "," + y + ")" }, [
      E("rect", { x: 0, y: 0, width: w, height: h, rx: h / 2, fill: "#fbeef3", stroke: CLS.student, "stroke-width": 1 }),
      E("circle", { cx: 12, cy: h / 2, r: 5, fill: "none", stroke: CLS.student, "stroke-width": 1.3 }),
      E("circle", { cx: 12, cy: h / 2 - 1.5, r: 1.8, fill: CLS.student }),
      txt(st.tag, { x: 23, y: h / 2 - 2, "font-family": MONO, "font-size": 8.5, "font-weight": 600, fill: CLS.student }),
      txt(sum, { x: 23, y: h / 2 + 8, "font-family": SANS, "font-size": 8.5, fill: "#7a4361" })
    ]);
  }
  function chip(x, y, letter, cls, state, id, managed) {
    var col = state === "fault" ? FAULT : state === "available" ? AVAIL : clsColor(cls);
    var fill = (state === "active" || state === "fault") ? col : PAPER;
    var ink = (state === "active" || state === "fault") ? "#fff" : col;
    var kids = [
      E("circle", { cx: x, cy: y, r: 6, fill: fill, stroke: col, "stroke-width": 1, "stroke-dasharray": state === "available" ? "1.4 1.6" : null }),
      txt(letter, { x: x, y: y + 3, "text-anchor": "middle", "font-family": MONO, "font-size": 7, "font-weight": 600, fill: ink })
    ];
    if (managed) kids.push(E("circle", { cx: x + 5, cy: y - 5, r: 2, fill: "#c98a1a" }));
    return E("g", { "class": state === "fault" ? "blink" : null,
                    "data-node-id": id || null,
                    "data-node-state": (managed ? "managed:" : "") + (state || "") }, kids);
  }
  function supLetter(d) {
    var k = (d.tag || d.name || "").toUpperCase();
    if (/IV|PUMP/.test(k)) return "I";
    if (/ALM|ALARM|PIA/.test(k)) return "A";
    if (/VENT/.test(k)) return "V";
    return (d.tag || "S").replace(/[^A-Z]/gi, "").charAt(0) || "S";
  }

  // ── link path routing ────────────────────────────────────────────────────
  function vbez(p0, p1) {
    var ym = (p0[1] + p1[1]) / 2;
    return "M" + p0[0] + " " + p0[1] + " C" + p0[0] + " " + ym + " " + p1[0] + " " + ym + " " + p1[0] + " " + p1[1];
  }
  function line(p0, p1) { return "M" + p0[0] + " " + p0[1] + " L" + p1[0] + " " + p1[1]; }
  function dist(a, b) { return Math.hypot(a.cx - b.cx, a.cy - b.cy); }

  function drawLinks(layer, links, pos, view) {
    links.forEach(function (lk) {
      var a = pos[lk.from], b = pos[lk.to];
      if (!a || !b) return;
      if (view === "C" && lk.kind === "local") return;            // radial: parts are chips
      if (view === "C" && dist(a, b) < 4) return;
      var s = linkStyle(lk.kind, lk.cls, lk.state), d;
      if (view === "A") {
        if (lk.kind === "control") d = vbez([a.cx, a.bot], [b.cx, b.top]);
        else if (lk.kind === "local") d = vbez([a.cx, a.bot], [b.cx, b.top]);
        else if (lk.kind === "student" || lk.kind === "role") d = vbez([a.cx, a.top], [b.cx, b.bot]);
        else d = vbez([a.cx, a.cy], [b.cx, b.cy]);               // assign
      } else {
        d = line([a.cx, a.cy], [b.cx, b.cy]);
      }
      layer.appendChild(E("path", {
        d: d, fill: "none", stroke: s.stroke, "stroke-width": s.w,
        "stroke-dasharray": s.dash, "stroke-linecap": "round", opacity: s.op,
        "class": s.anim || null
      }));
    });
  }

  // ── Option A — tiered layout ─────────────────────────────────────────────
  function layoutTiered(s, pos) {
    // N4 — width scales with the data (beds / shared rows / students) so an
    // 8-bed or device-heavy room spreads out instead of cramming into 600px.
    var _ps0 = patients(s), _c0 = s.commonDevices || [];
    var _free = function (d) { return !d.assignedToPatientId; };
    var _nOps = _c0.filter(function (d) { return _free(d) && d.cls !== "character"; }).length;
    var _nCh = _c0.filter(function (d) { return _free(d) && d.cls === "character"; }).length;
    var W = Math.max(600, _ps0.length * 140, _nOps * 112, _nCh * 112,
                     (s.students || []).length * 120);
    var M = 24, IW = W - 2 * M, nodes = [], y = 0;
    var c = s.control || { id: "ctrl", tag: "CTRL-01", name: "Control", state: "active" };
    // Tier 1 — control
    var ctrlN = node(c.id, W / 2, 44, 132, 42); pos[c.id] = ctrlN;
    nodes.push(controlNode(c, ctrlN));
    nodes.push(divider(M, W - M, 86, "CONTROL"));
    // Tier 2 — common: operational + ONLY truly-shared characters (no bed
    // assignment). Bed-assigned characters cluster with their patient (below).
    var _common = s.commonDevices || [];
    var charsByPatient = {};
    _common.forEach(function (d) {
      if (d.assignedToPatientId) (charsByPatient[d.assignedToPatientId] = charsByPatient[d.assignedToPatientId] || []).push(d);
    });
    var ops = _common.filter(function (d) { return !d.assignedToPatientId && d.cls !== "character"; });
    var chars = _common.filter(function (d) { return !d.assignedToPatientId && d.cls === "character"; });
    var bw = 100, bh = 32;
    function row(list, cy) {
      var n = list.length || 1;
      list.forEach(function (d, i) {
        var cx = M + IW * (i + 0.5) / n;
        var nn = node(d.id, cx, cy, Math.min(bw, IW / n - 8), bh); pos[d.id] = nn;
        nodes.push(deviceBlock(d, nn));
      });
    }
    if (ops.length) row(ops, 122);
    if (chars.length) row(chars, 168);
    nodes.push(divider(M, W - M, 200, "COMMON · SHARED"));
    // Tier 3 — patient room
    var r0 = rooms(s)[0], ps = patients(s), rTop = 214;
    var maxParts = 1;
    ps.forEach(function (p) {
      maxParts = Math.max(maxParts, (charsByPatient[p.id] || []).length
        + (p.manikin ? 1 : 0) + (p.tablet ? 1 : 0) + (p.supporting || []).length);
    });
    var cyOff = 50, firstOff = 32, SUBH = 30, STEP = 36;     // circle offset · gap · block h · pitch
    var rH = cyOff + firstOff + (maxParts - 1) * STEP + SUBH / 2 + 12;
    nodes.push(E("rect", { x: M, y: rTop, width: IW, height: rH, rx: 6, fill: "none", stroke: BORDER, "stroke-width": 1.2, "stroke-dasharray": "5 4" }));
    var cap = r0 ? r0.capacity : 8;
    var n = ps.length || 1, slotW = IW / Math.max(n, 1);
    ps.forEach(function (p, i) {
      var cx = M + slotW * (i + 0.5), cy = rTop + cyOff, pr = 21;
      var pn = node(p.id, cx, cy, 0, 0, pr); pos[p.id] = pn;
      nodes.push(patientCircle(p, pn));
      var sy = cy + firstOff, parts = [];
      (charsByPatient[p.id] || []).forEach(function (d) { parts.push(d); });   // care team first
      if (p.manikin) parts.push(p.manikin);
      if (p.tablet) parts.push(p.tablet);
      (p.supporting || []).forEach(function (d) { parts.push(d); });
      parts.forEach(function (d, j) {
        var dn = node(d.id, cx, sy + j * STEP, Math.min(74, slotW - 8), SUBH); pos[d.id] = dn;
        nodes.push(deviceBlock(d, dn));
      });
    });
    var occupied = ps.length;
    if (cap > occupied) {
      nodes.push(txt("BEDS " + (occupied + 1) + "–" + cap + " · OPEN CAPACITY",
        { x: W / 2, y: rTop + rH - 8, "text-anchor": "middle", "font-family": MONO, "font-size": 8, fill: "#bdb9b0", "letter-spacing": ".1em" }));
    }
    var afterRoom = rTop + rH;
    nodes.push(divider(M, W - M, afterRoom + 18, "STUDENTS · PARTICIPANTS"));
    // Tier 4 — students
    var sts = s.students || [], sy = afterRoom + 52;
    var sn2 = sts.length || 1, sw = Math.min(150, IW / sn2 - 8);
    sts.forEach(function (st, i) {
      var cx = M + IW * (i + 0.5) / sn2;
      var stn = node(st.id, cx, sy, Math.max(96, sw), 28); pos[st.id] = stn;
      nodes.push(studentPill(st, stn));
    });
    y = sy + 40;
    return { w: W, h: y, nodes: nodes };
  }

  // ── Option C — radial layout ─────────────────────────────────────────────
  function layoutRadial(s, pos) {
    // N4 — hub geometry scales with load; the busy arc staggers on 3 radii.
    var _c1 = (s.commonDevices || []).filter(function (d) { return !d.assignedToPatientId; });
    var W = Math.max(600, _c1.length * 58, patients(s).length * 150);
    var cx = W / 2, hubY = 250, nodes = [];
    var c = s.control || { id: "ctrl", tag: "CTRL-01", name: "Control", state: "active" };
    var ctrlN = node(c.id, cx, hubY, 124, 40); pos[c.id] = ctrlN;
    // Upper arc — common devices. Stagger alternating devices in/out so labels
    // don't collide when the arc is busy (8+ shared devices).
    var _all = s.commonDevices || [];
    var charsByPatient = {};
    _all.forEach(function (d) {
      if (d.assignedToPatientId) (charsByPatient[d.assignedToPatientId] = charsByPatient[d.assignedToPatientId] || []).push(d);
    });
    var common = _all.filter(function (d) { return !d.assignedToPatientId; }), n = common.length || 1;
    common.forEach(function (d, i) {
      var t = (i + 0.5) / n, ang = (-165 + t * 150) * Math.PI / 180;
      var R = 168 + (n > 10 ? (i % 3) : (i % 2)) * 28;   // N4: 3-deep stagger; capped so R<=224 stays in viewBox
      var dx = cx + R * Math.cos(ang), dy = hubY + R * Math.sin(ang);
      var dn = node(d.id, dx, dy, 92, 28); pos[d.id] = dn;
      nodes.push(deviceBlock(d, dn));
    });
    // Lower — patient room
    var ps = patients(s), r0 = rooms(s)[0], rTop = hubY + 96, rH = 150;
    nodes.push(E("rect", { x: 40, y: rTop, width: W - 80, height: rH, rx: 6, fill: "none", stroke: BORDER, "stroke-width": 1.2, "stroke-dasharray": "5 4" }));
    var np = ps.length || 1, slotW = (W - 80) / np;
    ps.forEach(function (p, i) {
      var px = 40 + slotW * (i + 0.5), py = rTop + 64, pr = 22;
      var pn = node(p.id, px, py, 0, 0, pr); pos[p.id] = pn;
      // parts placed AT the circle so hub→part links land here; chips ring it
      if (p.manikin) pos[p.manikin.id] = node(p.manikin.id, px - 7, py + 2, 0, 0, 1);
      if (p.tablet) pos[p.tablet.id] = node(p.tablet.id, px + 7, py + 2, 0, 0, 1);
      (p.supporting || []).forEach(function (d) { pos[d.id] = pn; });
      nodes.push(patientCircle(p, pn));
      // chips around the circle
      var chips = [];
      if (p.manikin) chips.push(["M", p.manikin]);
      if (p.tablet) chips.push(["T", p.tablet]);
      (p.supporting || []).forEach(function (d) { chips.push([supLetter(d), d]); });
      var cn = chips.length;
      chips.forEach(function (cc, j) {
        var t = cn === 1 ? 0 : (j / (cn - 1) - 0.5);
        var ang = (-90 + t * 150) * Math.PI / 180;
        nodes.push(chip(px + (pr + 8) * Math.cos(ang), py + (pr + 8) * Math.sin(ang), cc[0], cc[1].cls, cc[1].state, cc[1].id, cc[1].managed));
      });
      // assigned characters → chips in the lower arc (purple); pos set for role links
      var team = charsByPatient[p.id] || [];
      team.forEach(function (d, j) {
        var t = team.length === 1 ? 0 : (j / (team.length - 1) - 0.5);
        var ang = (90 + t * 120) * Math.PI / 180;
        var hx = px + (pr + 9) * Math.cos(ang), hy = py + (pr + 9) * Math.sin(ang);
        pos[d.id] = node(d.id, hx, hy, 0, 0, 1);
        nodes.push(chip(hx, hy, (d.name || "?").charAt(0).toUpperCase(), "character", d.state, d.id, d.managed));
      });
    });
    if (r0 && r0.capacity > ps.length) {
      nodes.push(txt("BEDS " + (ps.length + 1) + "–" + r0.capacity + " · OPEN",
        { x: cx, y: rTop + rH - 9, "text-anchor": "middle", "font-family": MONO, "font-size": 8, fill: "#bdb9b0", "letter-spacing": ".1em" }));
    }
    // Students — bottom
    var sts = s.students || [], sy = rTop + rH + 40, ns = sts.length || 1;
    sts.forEach(function (st, i) {
      var sx = 40 + (W - 80) * (i + 0.5) / ns;
      var stn = node(st.id, sx, sy, Math.max(96, Math.min(150, (W - 80) / ns - 8)), 28); pos[st.id] = stn;
      nodes.push(studentPill(st, stn));
    });
    // control on top of its links
    nodes.push(controlNode(c, ctrlN));
    return { w: W, h: sy + 40, nodes: nodes };
  }

  function divider(x1, x2, y, label) {
    return E("g", null, [
      E("line", { x1: x1, y1: y, x2: x2, y2: y, stroke: "#e6e3dc", "stroke-width": 1, "stroke-dasharray": "2 4" }),
      txt(label, { x: x1, y: y - 5, "font-family": MONO, "font-size": 7.5, fill: "#bdb9b0", "letter-spacing": ".14em" })
    ]);
  }

  // ── render ───────────────────────────────────────────────────────────────
  var view = (localStorage.getItem("medsim_view") === "C") ? "C" : "A";
  var last = null;

  function render(s) {
    last = s;
    var host = document.getElementById("diagram"), empty = document.getElementById("empty");
    var has = s && (patients(s).length || (s.commonDevices || []).length || s.sessionId);
    document.getElementById("diagram-title").textContent = view === "C" ? "Option C · Radial hub" : "Option A · Tiered";
    var r0 = s && rooms(s)[0], u0 = s && (s.units || [])[0];
    document.getElementById("diagram-meta").textContent = r0
      ? (r0.label + " · " + (u0 ? u0.name : "Unit") + " · CAP " + r0.capacity).toUpperCase() : "—";
    var c = counts(s || {});
    setText("n-active", c.active); setText("n-idle", c.idle);
    setText("n-available", c.available); setText("n-fault", c.fault);
    if (!has) { host.innerHTML = ""; empty.style.display = "block"; return; }
    empty.style.display = "none";

    var pos = {}, lay = (view === "C") ? layoutRadial(s, pos) : layoutTiered(s, pos);
    var svg = E("svg", { viewBox: "0 0 " + lay.w + " " + lay.h, role: "img",
                         "aria-label": "Network topology" });
    var linkLayer = E("g", null), nodeLayer = E("g", null);
    svg.appendChild(linkLayer); svg.appendChild(nodeLayer);
    drawLinks(linkLayer, deriveLinks(s), pos, view);
    lay.nodes.forEach(function (nd) { nodeLayer.appendChild(nd); });
    // N4 — smooth transition: fade the canvas only when the GEOMETRY changed
    // (assignment/layout shifts), not on every poll repaint.
    var sig = view + "|" + Object.keys(pos).sort().map(function (k) {
      return k + ":" + Math.round(pos[k].cx) + "," + Math.round(pos[k].cy);
    }).join(";");
    if (_lastSig && sig !== _lastSig) svg.style.animation = "netfade .3s ease";
    _lastSig = sig;
    host.innerHTML = ""; host.appendChild(svg);
  }
  var _lastSig = null;

  // N4 (decision 2) — manage mode: click a device to cycle auto → available →
  // fault → auto (server-side, instructor-gated). ONE delegated listener on the
  // persistent host (survives the per-poll innerHTML swap — no listener leak),
  // with an in-flight guard so rapid clicks on the same node can't double-fire
  // off the same stale attribute before the next poll repaints.
  var _managePending = {};
  (function bindManage() {
    var host = document.getElementById("diagram");
    if (!host) return;
    host.addEventListener("click", function (ev) {
      var mm = document.getElementById("manage-mode");
      if (!mm || !mm.checked) return;
      var g = ev.target && ev.target.closest ? ev.target.closest("g[data-node-id]") : null;
      if (!g) return;
      var id = g.getAttribute("data-node-id");
      if (!id || _managePending[id]) return;
      var st = g.getAttribute("data-node-state") || "";
      var next = st.indexOf("managed:") !== 0 ? "available"
               : st === "managed:available" ? "fault" : "auto";
      _managePending[id] = true;
      fetch("/api/network/device_state", {
        method: "POST", credentials: "same-origin",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ id: id, state: next })
      }).then(function () { return poll(); })
        .catch(function () {})
        .then(function () { delete _managePending[id]; });
    });
  })();
  function setText(id, v) { var e = document.getElementById(id); if (e) e.textContent = v; }

  function selectView(v) {
    view = v; localStorage.setItem("medsim_view", v);
    document.getElementById("seg-A").setAttribute("aria-selected", v === "A" ? "true" : "false");
    document.getElementById("seg-C").setAttribute("aria-selected", v === "C" ? "true" : "false");
    if (last) render(last);
  }

  function stamp() {
    try {
      return new Date().toLocaleTimeString([], { hour: "2-digit", minute: "2-digit", second: "2-digit" });
    } catch (e) { return ""; }
  }

  function poll() {
    return fetch("/api/network/snapshot", { credentials: "same-origin" })
      .then(function (r) { if (r.status === 401) { location.href = "/portal"; return null; } return r.ok ? r.json() : null; })
      .then(function (s) {
        var p = document.getElementById("poll");
        if (s) {
          p.classList.remove("stale");
          document.getElementById("poll-label").textContent = "Polling";
          setText("updated", "updated " + stamp());
          render(s);
        } else {
          p.classList.add("stale");
          document.getElementById("poll-label").textContent = "Offline";
        }
      })
      .catch(function () {
        var p = document.getElementById("poll");
        p.classList.add("stale"); document.getElementById("poll-label").textContent = "Offline";
      });
  }

  // Manual force-refresh — re-checks every link immediately (decoupled from the
  // ~2.8s auto-poll), with button feedback so the instructor sees it fire.
  function refreshNow() {
    var b = document.getElementById("refresh");
    if (b) b.classList.add("busy");
    poll().catch(function () {}).then(function () {
      if (b) setTimeout(function () { b.classList.remove("busy"); }, 300);
    });
  }

  document.getElementById("seg-A").addEventListener("click", function () { selectView("A"); });
  document.getElementById("seg-C").addEventListener("click", function () { selectView("C"); });
  var _rb = document.getElementById("refresh");
  if (_rb) _rb.addEventListener("click", refreshNow);
  selectView(view);
  poll();
  setInterval(poll, POLL_MS);
})();
