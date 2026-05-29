/* MEDSIM V5 — functional EHR engine.
 *
 * One React app, themed into Helix / Cyrus / Meridian by themes.js.
 * Unlike the V2-V4 mockups this is a working medical record: it loads
 * the scenario-seeded patient, renders the live chart projection from
 * the V3 chart-event database, and every Save / Sign / Record / Place
 * writes a real chart_event and re-renders from the projection.
 *
 * Bootstrap (window.MEDSIM_V3): EHR_ID, MODE, JOIN, STATION, BASE_URL,
 * PATIENTS, SEED, LOCKED.
 */
const { useState, useEffect, useCallback, useMemo } = React;

const V3 = window.MEDSIM_V3 || {};
const THEMES = window.MEDSIM_THEMES || {};
const THEME = THEMES[V3.EHR_ID] || THEMES.helix;
const LIVE = V3.MODE === "live";
// API calls are SAME-ORIGIN relative — never V3.BASE_URL. BASE_URL is the
// QR/LAN-facing host (e.g. the Wi-Fi IP for phones); using it here would
// make every fetch cross-origin and CORS-blocked when the EHR is opened
// from localhost. The EHR always talks to whatever server served it.
const API = "";

// Apply the theme palette to CSS variables.
(function applyTheme() {
  const c = THEME.colors;
  const r = document.documentElement.style;
  r.setProperty("--brand", c.brand); r.setProperty("--brand-ink", c.brandInk);
  r.setProperty("--accent", c.accent); r.setProperty("--bg", c.bg);
  r.setProperty("--panel", c.panel); r.setProperty("--ink", c.ink);
  r.setProperty("--ink2", c.ink2); r.setProperty("--ink3", c.ink3);
  r.setProperty("--line", c.line); r.setProperty("--ok", c.ok);
  r.setProperty("--warn", c.warn); r.setProperty("--danger", c.danger);
  document.body.style.fontFamily = THEME.font;
})();

// ── Demo data — used when MODE === "demo" (wizard preview, no session) ──
const DEMO_PATIENT = {
  mrn: "DEMO-0001", name: "Eleanor Hightower", dob: "1948-02-09", age: 78,
  sex: "F", pronouns: "she/her", room: "Med-Surg · 214A",
  status: "Inpatient · Day 3", allergies: ["Codeine (nausea)"],
  code: "Full Code", isolation: "Standard",
  chief_complaint: "CHF exacerbation", persona_label: "(demo)",
  problems: ["CHF exacerbation", "Atrial fibrillation", "Osteoarthritis"],
  meds: ["Furosemide 40 mg PO BID", "Metoprolol 25 mg PO BID"],
  pcp: "Dr. M. Chen", attending: "Dr. P. Adeyemi",
};
const DEMO_SEED = {
  chief_complaint: "CHF exacerbation",
  problem_list: [
    { name: "CHF exacerbation", onset: "active" },
    { name: "Atrial fibrillation", onset: "chronic" },
  ],
  medications: [
    { name: "Furosemide", dose: "40 mg", frequency: "PO BID" },
    { name: "Metoprolol", dose: "25 mg", frequency: "PO BID" },
  ],
  allergies: [{ substance: "Codeine", reaction: "nausea" }],
  vitals_baseline: [
    { time: "T-8h", t: "36.9", hr: "88", rr: "20", bp: "138/84", spo2: "94", pain: "2" },
    { time: "T-4h", t: "37.0", hr: "92", rr: "22", bp: "142/86", spo2: "93", pain: "3" },
  ],
  labs_recent: [
    { panel: "BMP", time: "T-6h", values: [
      { name: "Na", v: "138", ref: "135-145", flag: "" },
      { name: "K", v: "3.3", ref: "3.5-5.1", flag: "L" },
      { name: "Cr", v: "1.4", ref: "0.6-1.1", flag: "H" },
    ]},
    { panel: "BNP", time: "T-6h", values: [
      { name: "BNP", v: "1240", ref: "<100", flag: "H" },
    ]},
  ],
  notes_recent: [
    { note_id: "n_demo", note_type: "Admission H&P", author: "Admitting provider",
      ts: "T-12h", signed: true,
      body: "CHIEF COMPLAINT: CHF exacerbation\n\nHISTORY OF PRESENT ILLNESS:\nDemonstration patient. Open a real scenario to load live data." },
  ],
  encounter: { location: "Med-Surg · 214A", type: "Inpatient", los: "Day 3",
               isolation: "Standard", reason: "CHF exacerbation" },
  care_team: [{ role: "Attending", name: "Dr. P. Adeyemi" }],
};

// ── API layer ──────────────────────────────────────────────────────────
async function getJson(path) {
  try {
    const r = await fetch(API + path, { credentials: "same-origin" });
    if (!r.ok) return null;
    return await r.json();
  } catch (e) { return null; }
}
async function postJson(path, body) {
  try {
    const r = await fetch(API + path, {
      method: "POST", headers: { "Content-Type": "application/json" },
      credentials: "same-origin", body: JSON.stringify(body),
    });
    const data = await r.json().catch(() => ({}));
    return { ok: r.ok, status: r.status, data };
  } catch (e) { return { ok: false, status: 0, data: {} }; }
}
function fetchChart(patientId) {
  if (!LIVE) return Promise.resolve(null);
  return getJson(`/api/ehr/${V3.JOIN}/chart/${encodeURIComponent(patientId)}`);
}
function fetchCatalog() {
  if (!LIVE) return Promise.resolve({ items: [] });
  return getJson(`/api/ehr/${V3.JOIN}/orders/catalog`).then(d => d || { items: [] });
}
function emitEvent(type, surface, patientId, payload) {
  if (!LIVE) return Promise.resolve({ ok: true, demo: true });
  return postJson(`/api/ehr/${V3.JOIN}/${V3.STATION}/event`, {
    type, surface, patient_id: patientId, ehr_station_id: V3.STATION,
    ts_client: Date.now(), payload: payload || {},
  });
}
function placeOrder(patientId, order) {
  if (!LIVE) return Promise.resolve({ ok: true, demo: true });
  return postJson(`/api/ehr/${V3.JOIN}/orders`, {
    patient_id: patientId, ehr_station_id: V3.STATION, order,
  });
}
function postCatalogItem(category, code, label) {
  if (!LIVE) return Promise.resolve({ ok: true, demo: true, data: {} });
  return postJson(`/api/ehr/${V3.JOIN}/orders/catalog`, {
    ehr_station_id: V3.STATION, category, code, label,
  });
}

// ── UI primitives ──────────────────────────────────────────────────────
const card = { background: "var(--panel)", border: "1px solid var(--line)",
               borderRadius: 8, padding: 14, marginBottom: 12 };
const h2 = { margin: "0 0 10px", fontSize: 14, color: "var(--brand-ink)" };
const btn = { background: "var(--brand)", color: "#fff", border: 0,
              borderRadius: 6, padding: "7px 14px", fontWeight: 600, fontSize: 12 };
const btnGhost = { background: "#fff", color: "var(--ink2)",
                   border: "1px solid var(--line)", borderRadius: 6,
                   padding: "6px 12px", fontWeight: 600, fontSize: 12 };
const inputS = { width: "100%", boxSizing: "border-box", padding: "7px 9px",
                 border: "1px solid var(--line)", borderRadius: 5, fontSize: 13 };

function Pill({ children, tone }) {
  const map = {
    ok: ["var(--ok)", "#e3f1e6"], warn: ["var(--warn)", "#fdf3dc"],
    danger: ["var(--danger)", "#f7e1e4"], brand: ["var(--brand)", "#e6ecf8"],
    flat: ["var(--ink2)", "#eef0f5"],
  };
  const [fg, bg] = map[tone] || map.flat;
  return <span style={{ background: bg, color: fg, padding: "2px 8px",
    borderRadius: 99, fontSize: 11, fontWeight: 600, whiteSpace: "nowrap" }}>{children}</span>;
}
function Card({ title, actions, children }) {
  return <section style={card}>
    {title && <div style={{ display: "flex", alignItems: "center", marginBottom: 8 }}>
      <h2 style={{ ...h2, margin: 0, flex: 1 }}>{title}</h2>{actions}</div>}
    {children}
  </section>;
}
function Empty({ children }) {
  return <p style={{ color: "var(--ink3)", fontSize: 12, margin: "6px 0" }}>{children}</p>;
}

// ── Patient banner ─────────────────────────────────────────────────────
function PatientBanner({ p }) {
  const allergies = (p.allergies && p.allergies.length) ? p.allergies.join(", ") : "NKDA";
  return <div style={{
    background: `linear-gradient(95deg, ${THEME.colors.bandFrom}, ${THEME.colors.bandTo})`,
    color: "#fff", padding: "10px 16px", display: "flex", flexWrap: "wrap",
    gap: "4px 22px", alignItems: "baseline" }}>
    <strong style={{ fontSize: 16 }}>{p.name}</strong>
    <span style={{ opacity: .9 }}>{p.sex} · {p.age || "—"}y · {p.dob}</span>
    <span style={{ opacity: .9 }}>MRN {p.mrn}{p.fin ? ` · FIN ${p.fin}` : ""}</span>
    <span style={{ opacity: .9 }}>{p.room || p.location || "—"}</span>
    <span style={{ background: "rgba(255,255,255,.18)", padding: "1px 8px",
      borderRadius: 99, fontSize: 11 }}>Allergies: {allergies}</span>
    <span style={{ background: "rgba(255,255,255,.18)", padding: "1px 8px",
      borderRadius: 99, fontSize: 11 }}>{p.code || "Full Code"}</span>
    {p.isolation && p.isolation !== "Standard" &&
      <span style={{ background: "var(--accent)", padding: "1px 8px",
        borderRadius: 99, fontSize: 11 }}>{p.isolation}</span>}
    {p.chief_complaint &&
      <span style={{ opacity: .92 }}>CC: {p.chief_complaint}</span>}
  </div>;
}

// ── Summary tab ────────────────────────────────────────────────────────
function SummaryTab({ p, seed, chart, act, locked }) {
  const problems = mergeList(
    (seed.problem_list || []).map(x => typeof x === "string" ? x : x.name),
    chart && chart.problems);
  const allergies = mergeList(
    (seed.allergies || []).map(x => typeof x === "string" ? x : (x.substance || x.name)),
    chart && chart.allergies);
  const meds = (seed.medications || []).map(m =>
    typeof m === "string" ? m : [m.name, m.dose, m.frequency].filter(Boolean).join(" "));
  const enc = seed.encounter || {};
  return <div>
    <Card title="Encounter">
      <Row k="Reason for visit" v={enc.reason || p.chief_complaint || "—"} />
      <Row k="Location" v={enc.location || p.room || "—"} />
      <Row k="Type / LOS" v={`${enc.type || "—"} · ${enc.los || "—"}`} />
      <Row k="Code status" v={p.code || "Full Code"} />
    </Card>
    <Card title="Problem list" actions={
      <AddInline label="Add problem" disabled={locked}
        onAdd={(name) => act.addProblem(name)} />}>
      {problems.length ? <ul style={ulS}>{problems.map((x, i) =>
        <li key={i}>{x}</li>)}</ul> : <Empty>No active problems.</Empty>}
    </Card>
    <Card title="Allergies" actions={
      <AddInline label="Add allergy" disabled={locked}
        onAdd={(name) => act.addAllergy(name)} />}>
      {allergies.length ? <ul style={ulS}>{allergies.map((x, i) =>
        <li key={i}>{x}</li>)}</ul> : <Empty>NKDA.</Empty>}
    </Card>
    <Card title="Home / active medications">
      {meds.length ? <ul style={ulS}>{meds.map((x, i) =>
        <li key={i}>{x}</li>)}</ul> : <Empty>None recorded.</Empty>}
    </Card>
    <Card title="Care team">
      <ul style={ulS}>{(seed.care_team || []).map((c, i) =>
        <li key={i}><strong>{c.role}:</strong> {c.name}</li>)}</ul>
    </Card>
  </div>;
}
const ulS = { margin: "4px 0", paddingLeft: 18, fontSize: 13 };
function Row({ k, v }) {
  return <div style={{ display: "flex", gap: 10, padding: "3px 0",
    borderBottom: "1px dotted var(--line)" }}>
    <span style={{ color: "var(--ink3)", minWidth: 130 }}>{k}</span>
    <span style={{ fontWeight: 500 }}>{v}</span></div>;
}
function AddInline({ label, onAdd, disabled }) {
  const [open, setOpen] = useState(false);
  const [val, setVal] = useState("");
  if (disabled) return null;
  if (!open) return <button style={btnGhost} onClick={() => setOpen(true)}>+ {label}</button>;
  return <span style={{ display: "flex", gap: 6 }}>
    <input style={{ ...inputS, width: 180 }} value={val} autoFocus
      placeholder={label} onChange={e => setVal(e.target.value)} />
    <button style={btn} onClick={() => { if (val.trim()) { onAdd(val.trim()); setVal(""); setOpen(false); } }}>Add</button>
    <button style={btnGhost} onClick={() => { setOpen(false); setVal(""); }}>✕</button>
  </span>;
}
function mergeList(base, delta) {
  const out = base.slice();
  if (delta) {
    (delta.adds || []).forEach(a => { if (a && out.indexOf(a) < 0) out.push(a); });
    (delta.removes || []).forEach(r => {
      const i = out.indexOf(r); if (i >= 0) out.splice(i, 1);
    });
  }
  return out;
}

// ── Vitals tab ─────────────────────────────────────────────────────────
const VITAL_COLS = [
  ["t", "Temp"], ["hr", "HR"], ["rr", "RR"], ["bp", "BP"],
  ["spo2", "SpO₂"], ["pain", "Pain"],
];
function VitalsTab({ seed, chart, act, locked }) {
  const [form, setForm] = useState({ t: "", hr: "", rr: "", bp: "", spo2: "", pain: "" });
  const baseline = (seed.vitals_baseline || []).map(v => ({ ...v, _src: "baseline" }));
  const recorded = ((chart && chart.vitals) || []).map(v => ({
    ...v, time: tsLabel(v.ts), _src: "student" }));
  const rows = baseline.concat(recorded);
  function submit() {
    if (Object.values(form).every(x => !x)) return;
    act.recordVitals({ ...form });
    setForm({ t: "", hr: "", rr: "", bp: "", spo2: "", pain: "" });
  }
  return <div>
    <Card title="Flowsheet">
      <table style={tableS}><thead><tr>
        <th style={thS}>Time</th>
        {VITAL_COLS.map(([k, l]) => <th key={k} style={thS}>{l}</th>)}
        <th style={thS}>Source</th>
      </tr></thead><tbody>
        {rows.length === 0 && <tr><td colSpan={8}><Empty>No vitals recorded.</Empty></td></tr>}
        {rows.map((v, i) => <tr key={i}>
          <td style={tdS}>{v.time || "—"}</td>
          {VITAL_COLS.map(([k]) => <td key={k} style={tdS}>{v[k] || "—"}</td>)}
          <td style={tdS}>{v._src === "student"
            ? <Pill tone="ok">charted</Pill> : <Pill tone="flat">baseline</Pill>}</td>
        </tr>)}
      </tbody></table>
    </Card>
    <Card title="Record a vitals set">
      {locked ? <Empty>Charting is locked.</Empty> : <div>
        <div style={{ display: "flex", gap: 8, flexWrap: "wrap" }}>
          {VITAL_COLS.map(([k, l]) => <label key={k} style={{ fontSize: 11, color: "var(--ink3)" }}>
            {l}<input style={{ ...inputS, width: 78 }} value={form[k]}
              onChange={e => setForm({ ...form, [k]: e.target.value })} /></label>)}
        </div>
        <button style={{ ...btn, marginTop: 10 }} onClick={submit}>Record vitals</button>
      </div>}
    </Card>
  </div>;
}

// ── Notes tab ──────────────────────────────────────────────────────────
const NOTE_TYPES = ["Nursing Progress", "SBAR Handoff", "Assessment",
                    "Education", "Shift Summary", "Discharge"];
function NotesTab({ seed, chart, act, locked }) {
  const seedNotes = (seed.notes_recent || []).map(n => ({ ...n, _src: "baseline" }));
  const studentNotes = ((chart && chart.notes) || []).map(n => ({
    ...n, ts: tsLabel(n.latest_ts), _src: "student" }));
  const notes = seedNotes.concat(studentNotes);
  const [editing, setEditing] = useState(null);  // {note_id, note_type, body}
  function newNote() {
    setEditing({ note_id: "note_" + Date.now(), note_type: NOTE_TYPES[0], body: "" });
  }
  function save(signed) {
    if (!editing.body.trim()) return;
    act.saveNote(editing.note_id, editing.note_type, editing.body, signed);
    setEditing(null);
  }
  return <div>
    <Card title="Notes" actions={!locked &&
      <button style={btn} onClick={newNote}>+ New note</button>}>
      {notes.length === 0 && <Empty>No notes yet.</Empty>}
      {notes.map((n, i) => <div key={i} style={{ borderBottom: "1px solid var(--line)",
        padding: "8px 0" }}>
        <div style={{ display: "flex", gap: 8, alignItems: "baseline" }}>
          <strong>{n.note_type}</strong>
          <span style={{ color: "var(--ink3)", fontSize: 11 }}>{n.author || "Student"} · {n.ts || "—"}</span>
          {n.signed ? <Pill tone="ok">signed</Pill> : <Pill tone="warn">draft</Pill>}
          {n._src === "student" && !n.signed && !locked &&
            <button style={{ ...btnGhost, padding: "2px 8px" }}
              onClick={() => setEditing({ note_id: n.note_id,
                note_type: n.note_type, body: n.body })}>Edit</button>}
        </div>
        <pre style={preS}>{n.body}</pre>
        {(n.addenda || []).map((a, j) => <pre key={j} style={{ ...preS,
          borderLeft: "3px solid var(--accent)", paddingLeft: 8 }}>
          [addendum {tsLabel(a.ts)}] {a.body}</pre>)}
        {n.signed && n._src === "student" && !locked &&
          <AddInline label="Add addendum"
            onAdd={(txt) => act.addendum(n.note_id, txt)} />}
      </div>)}
    </Card>
    {editing && <Card title="Note editor">
      <select style={{ ...inputS, marginBottom: 8 }} value={editing.note_type}
        onChange={e => setEditing({ ...editing, note_type: e.target.value })}>
        {NOTE_TYPES.map(t => <option key={t}>{t}</option>)}
      </select>
      <textarea style={{ ...inputS, minHeight: 200, fontFamily: "'IBM Plex Mono',monospace" }}
        value={editing.body} placeholder="Document your assessment, interventions, and SBAR…"
        onChange={e => setEditing({ ...editing, body: e.target.value })} />
      <div style={{ display: "flex", gap: 8, marginTop: 10 }}>
        <button style={btnGhost} onClick={() => save(false)}>Save draft</button>
        <button style={btn} onClick={() => save(true)}>Sign &amp; file</button>
        <button style={btnGhost} onClick={() => setEditing(null)}>Cancel</button>
      </div>
    </Card>}
  </div>;
}
const preS = { whiteSpace: "pre-wrap", fontFamily: "'IBM Plex Mono',monospace",
               fontSize: 12, margin: "6px 0", color: "var(--ink2)" };

// ── Orders tab ─────────────────────────────────────────────────────────
const ORDER_CATS = ["lab", "imaging", "med", "supply", "diet", "activity", "consult"];
function OrdersTab({ catalog, chart, act, locked }) {
  const [q, setQ] = useState("");
  const [cat, setCat] = useState("all");
  const [cart, setCart] = useState([]);  // {code,label,category,rationale,priority}
  const [custom, setCustom] = useState({ category: "supply", code: "", label: "" });
  const items = (catalog.items || []).filter(o =>
    (cat === "all" || o.category === cat) &&
    (!q || (o.code + " " + (o.label || "")).toLowerCase().includes(q.toLowerCase())));
  const placed = (chart && chart.orders) || [];
  function add(o) {
    setCart(c => c.concat([{ code: o.code, label: o.label || o.code,
      category: o.category, rationale: "", priority: "routine" }]));
  }
  function signAll() {
    cart.forEach(o => act.placeOrder(o));
    setCart([]);
  }
  return <div>
    <Card title="Placed orders">
      {placed.length === 0 && <Empty>No orders placed yet.</Empty>}
      {placed.map((o, i) => <div key={i} style={{ display: "flex", gap: 8,
        padding: "5px 0", borderBottom: "1px dotted var(--line)", alignItems: "baseline" }}>
        <Pill tone={o.status === "discontinued" ? "danger" : "ok"}>{o.status}</Pill>
        <strong style={{ fontFamily: "'IBM Plex Mono',monospace", fontSize: 12 }}>
          {(o.order || {}).code}</strong>
        <span style={{ color: "var(--ink3)", fontSize: 11 }}>
          {(o.order || {}).category} · {(o.order || {}).priority || "routine"}</span>
        <span style={{ flex: 1, color: "var(--ink2)", fontSize: 11 }}>
          {(o.order || {}).rationale}</span>
      </div>)}
    </Card>
    {!locked && <Card title="Order catalog">
      <div style={{ display: "flex", gap: 8, marginBottom: 8 }}>
        <input style={inputS} placeholder="Search orders…" value={q}
          onChange={e => setQ(e.target.value)} />
        <select style={{ ...inputS, width: 130 }} value={cat}
          onChange={e => setCat(e.target.value)}>
          <option value="all">All</option>
          {ORDER_CATS.map(c => <option key={c} value={c}>{c}</option>)}
        </select>
      </div>
      <div style={{ maxHeight: 230, overflow: "auto" }}>
        {items.map((o, i) => <div key={i} style={{ display: "flex", gap: 8,
          padding: "5px 0", borderBottom: "1px dotted var(--line)", alignItems: "center" }}>
          <Pill tone="flat">{o.category}</Pill>
          <span style={{ flex: 1, fontSize: 12 }}>{o.label || o.code}</span>
          {o.common && <Pill tone="brand">common</Pill>}
          {o.added && <Pill tone="ok">custom</Pill>}
          <button style={btnGhost} onClick={() => add(o)}>Add</button>
        </div>)}
        {items.length === 0 && <Empty>No catalog matches.</Empty>}
      </div>
    </Card>}
    {!locked && <Card title="Add a custom supply / service / medication">
      <p style={{ color: "var(--ink3)", fontSize: 12, margin: "0 0 8px" }}>
        Not in the catalog? Add it here — it joins the persistent master
        list and stays orderable in every records system.</p>
      <div style={{ display: "flex", gap: 8, flexWrap: "wrap", alignItems: "flex-end" }}>
        <label style={{ fontSize: 11, color: "var(--ink3)" }}>Category
          <select style={{ ...inputS, width: 130 }} value={custom.category}
            onChange={e => setCustom({ ...custom, category: e.target.value })}>
            {["supply", "service", "med", "lab", "imaging", "diet",
              "activity", "consult"].map(c => <option key={c} value={c}>{c}</option>)}
          </select></label>
        <label style={{ fontSize: 11, color: "var(--ink3)", flex: 1, minWidth: 140 }}>Code
          <input style={inputS} value={custom.code} placeholder="e.g. WOUND VAC KIT"
            onChange={e => setCustom({ ...custom, code: e.target.value })} /></label>
        <label style={{ fontSize: 11, color: "var(--ink3)", flex: 2, minWidth: 160 }}>Label
          <input style={inputS} value={custom.label} placeholder="Human-readable description"
            onChange={e => setCustom({ ...custom, label: e.target.value })} /></label>
        <button style={btn} onClick={() => {
          if (!custom.code.trim()) return;
          act.addCatalogItem(custom.category, custom.code.trim(),
                             custom.label.trim() || custom.code.trim());
          setCustom({ category: custom.category, code: "", label: "" });
        }}>Add to catalog</button>
      </div>
    </Card>}
    {cart.length > 0 && <Card title={`Cart — ${cart.length} order(s) to sign`}>
      {cart.map((o, i) => <div key={i} style={{ borderBottom: "1px solid var(--line)",
        padding: "8px 0" }}>
        <div style={{ display: "flex", gap: 8, alignItems: "center" }}>
          <strong style={{ flex: 1 }}>{o.label}</strong>
          <select style={{ ...inputS, width: 110 }} value={o.priority}
            onChange={e => setCart(c => c.map((x, j) =>
              j === i ? { ...x, priority: e.target.value } : x))}>
            <option>routine</option><option>stat</option><option>now</option>
          </select>
          <button style={btnGhost} onClick={() =>
            setCart(c => c.filter((_, j) => j !== i))}>✕</button>
        </div>
        <input style={{ ...inputS, marginTop: 6 }} value={o.rationale}
          placeholder="Rationale (required for scoring)"
          onChange={e => setCart(c => c.map((x, j) =>
            j === i ? { ...x, rationale: e.target.value } : x))} />
      </div>)}
      <button style={{ ...btn, marginTop: 10 }} onClick={signAll}>
        Sign &amp; send ({cart.length})</button>
    </Card>}
  </div>;
}

// ── Results tab ────────────────────────────────────────────────────────
function ResultsTab({ seed, chart, act, locked }) {
  const acked = new Set(((chart && chart.results_acknowledged) || []).map(r => r.result_id));
  const panels = seed.labs_recent || [];
  return <div>
    <Card title="Results review">
      {panels.length === 0 && <Empty>No results posted.</Empty>}
      {panels.map((panel, pi) => <div key={pi} style={{ marginBottom: 10 }}>
        <div style={{ display: "flex", gap: 8, alignItems: "baseline" }}>
          <strong>{panel.panel}</strong>
          <span style={{ color: "var(--ink3)", fontSize: 11 }}>{panel.time}</span>
          {acked.has(panel.panel)
            ? <Pill tone="ok">acknowledged</Pill>
            : !locked && <button style={{ ...btnGhost, padding: "2px 8px" }}
                onClick={() => act.acknowledge(panel.panel, panel.panel)}>Acknowledge</button>}
        </div>
        <table style={tableS}><tbody>
          {(panel.values || []).map((v, vi) => <tr key={vi}>
            <td style={tdS}>{v.name}</td>
            <td style={{ ...tdS, fontWeight: 600,
              color: v.flag ? "var(--danger)" : "var(--ink)" }}>{v.v} {v.flag}</td>
            <td style={{ ...tdS, color: "var(--ink3)" }}>{v.ref}</td>
          </tr>)}
        </tbody></table>
      </div>)}
    </Card>
  </div>;
}

// ── MAR tab ────────────────────────────────────────────────────────────
// V6.1 — renders the full MAR v2 record shape produced by ehr_seed:
//   name, dose, route, frequency, interval_h, drug_class, high_alert,
//   rationale, ordered_at, first_dose_at, scheduled_times[],
//   administrations[], current_status, next_due
// Legacy seeds that only had name/dose/frequency still render — every
// extended field is treated as optional.
function MARTab({ seed, chart, act, locked }) {
  // Normalise home meds: string → object, then preserve all v2 fields.
  // V6.1 — filter out meds the instructor unchecked in the operator's
  // medication checklist (included: false).
  const homeMeds = (seed.medications || [])
    .filter(m => typeof m === "string" || m.included !== false)
    .map(m => {
      if (typeof m === "string") return { name: m, source: "home" };
      return { ...m, source: "home" };
    });
  // Meds ordered during the sim live on the chart projection.
  const orderedMeds = ((chart && chart.orders) || [])
    .filter(o => (o.order || {}).category === "med")
    .map(o => {
      const ord = o.order || {};
      return {
        name:  ord.label || ord.code || "Medication",
        dose:  ord.dose, route: ord.route, frequency: ord.frequency,
        source: "ordered", current_status: o.status || "scheduled", ordered_at: o.ts,
      };
    });
  // De-dupe by name+source
  const seen = new Set();
  const meds = homeMeds.concat(orderedMeds).filter(m => {
    const k = (m.source || "") + "|" + (m.name || "").toLowerCase();
    if (seen.has(k)) return false;
    seen.add(k);
    return true;
  });
  const given = (chart && chart.meds_administered) || [];
  return <div>
    <Card title="Medication Administration Record">
      {meds.length === 0 && <Empty>No medications on file.</Empty>}
      {meds.map((m, i) => (
        <MARRow key={i} med={m} given={given} act={act} locked={locked} />
      ))}
    </Card>
  </div>;
}

function MARRow({ med, given, act, locked }) {
  const [showAll, setShowAll] = useState(false);
  const dc        = med.current_status === "discontinued";
  const status    = med.current_status || "scheduled";
  const tone      = statusTone(status);
  const admins    = (med.administrations || []);
  // Also fold in any sim-time administrations from the live chart event log.
  const liveAdmins = given.filter(g =>
    med.name && (g.med || "").toLowerCase().indexOf(med.name.toLowerCase()) >= 0)
    .map(g => ({ ts: tsLabel(g.ts), given_by: g.by || "—",
                 status: "given", site: g.site || "", note: g.note || "" }));
  const allAdmins = liveAdmins.concat(admins);
  const visible   = showAll ? allAdmins : allAdmins.slice(-3);

  return <div style={{
    borderBottom: "1px solid var(--line)", padding: "10px 0",
    opacity: dc ? 0.5 : 1, textDecoration: dc ? "line-through" : "none",
  }}>
    {/* Header line: name + dose + route + freq + HIGH-ALERT + status pill */}
    <div style={{ display: "flex", gap: 8, alignItems: "center", flexWrap: "wrap" }}>
      <strong style={{ color: "var(--ink)" }}>{med.name || "Medication"}</strong>
      {med.dose      && <span style={{ color: "var(--ink2)" }}>· {med.dose}</span>}
      {med.route     && <span style={{ color: "var(--ink2)" }}>· {med.route}</span>}
      {med.frequency && <span style={{ color: "var(--ink2)", fontSize: 12 }}>· {med.frequency}</span>}
      <span style={{ flex: 1 }} />
      {med.high_alert && <Pill tone="danger">⚠ HIGH ALERT</Pill>}
      {med.source === "ordered" ? <Pill tone="brand">ordered</Pill>
                                : <Pill tone="flat">home med</Pill>}
      <Pill tone={tone}>{statusLabel(status)}</Pill>
      {!locked && !dc && <button style={btnGhost}
        onClick={() => act.administer(med.name || med.label || "Medication")}>Administer</button>}
    </div>
    {/* Rationale */}
    {med.rationale && <div style={{ color: "var(--ink3)", fontSize: 12,
                                      fontStyle: "italic", marginTop: 3 }}>
      {med.rationale}
    </div>}
    {/* Timing line: ordered_at · first dose · next due */}
    {(med.ordered_at || med.next_due) && <div style={{ color: "var(--ink2)",
                                                         fontSize: 12, marginTop: 4 }}>
      {med.ordered_at  && <>Ordered <code>{med.ordered_at}</code> · </>}
      {med.first_dose_at && <>1st dose <code>{med.first_dose_at}</code> · </>}
      <strong>Next: <code>{med.next_due || "—"}</code></strong>
    </div>}
    {/* Scheduled times (for non-PRN scheduled meds) */}
    {med.scheduled_times && med.scheduled_times.length > 0 && <div style={{
        color: "var(--ink3)", fontSize: 11, marginTop: 4,
        fontFamily: "ui-monospace, Menlo, monospace" }}>
      Schedule: {med.scheduled_times.slice(0, 6).join(" · ")}
      {med.scheduled_times.length > 6 && ` · +${med.scheduled_times.length - 6} more`}
    </div>}
    {/* Administration history */}
    {allAdmins.length > 0 && <div style={{ marginTop: 6 }}>
      <div style={{ color: "var(--ink3)", fontSize: 11, marginBottom: 3,
                     display: "flex", justifyContent: "space-between" }}>
        <span>Past administrations ({allAdmins.length})</span>
        {allAdmins.length > 3 && <button style={{ background: "none", border: 0,
            color: "var(--brand, #143b8a)", cursor: "pointer", fontSize: 11, padding: 0 }}
            onClick={() => setShowAll(!showAll)}>
          {showAll ? "show recent only" : `show all ${allAdmins.length}`}
        </button>}
      </div>
      {visible.map((a, j) => (
        <div key={j} style={{ fontSize: 11, padding: "2px 0",
                                fontFamily: "ui-monospace, Menlo, monospace",
                                color: "var(--ink2)" }}>
          <code>{a.ts}</code> · <strong>{a.status || "given"}</strong> by {a.given_by || "—"}
          {a.witness  && <> · witness: {a.witness}</>}
          {a.site     && <> · {a.site}</>}
          {a.note     && <> · <em>"{a.note}"</em></>}
        </div>
      ))}
    </div>}
  </div>;
}

function statusTone(s) {
  return s === "overdue"        ? "danger"
       : s === "due_soon"       ? "warn"
       : s === "infusing"       ? "brand"
       : s === "prn_available"  ? "flat"
       : s === "given"          ? "ok"
       : s === "held"           ? "warn"
       : s === "discontinued"   ? "danger"
       : "flat";
}
function statusLabel(s) {
  return s === "overdue"        ? "OVERDUE"
       : s === "due_soon"       ? "DUE SOON"
       : s === "infusing"       ? "INFUSING"
       : s === "prn_available"  ? "PRN"
       : s === "given"          ? "GIVEN"
       : s === "held"           ? "HELD"
       : s === "scheduled"      ? "scheduled"
       : s === "discontinued"   ? "D/C"
       : s || "";
}

// ── shared table styles + helpers ──────────────────────────────────────
const tableS = { width: "100%", borderCollapse: "collapse", fontSize: 12 };
const thS = { textAlign: "left", padding: "4px 6px", borderBottom: "2px solid var(--line)",
              color: "var(--ink3)", fontWeight: 600 };
const tdS = { padding: "4px 6px", borderBottom: "1px solid var(--line)" };
function tsLabel(ts) {
  if (!ts) return "";
  if (typeof ts === "string") return ts;
  try { return new Date(ts * 1000).toLocaleTimeString([], { hour: "2-digit", minute: "2-digit" }); }
  catch (e) { return ""; }
}

// ── Root ───────────────────────────────────────────────────────────────
function EHRApp() {
  const demo = !LIVE;
  const patient = demo ? DEMO_PATIENT
    : ((V3.PATIENTS && V3.PATIENTS[0]) || DEMO_PATIENT);
  const patientId = patient.mrn;
  const [chart, setChart] = useState(null);
  const [seed, setSeed] = useState(demo ? DEMO_SEED : (V3.SEED || {}));
  const [catalog, setCatalog] = useState({ items: [] });
  const [tab, setTab] = useState("summary");
  const [locked, setLocked] = useState(!!V3.LOCKED);
  const [toast, setToast] = useState("");

  const refresh = useCallback(async () => {
    if (demo) return;
    const c = await fetchChart(patientId);
    if (c) {
      setChart(c);
      if (c.seed && Object.keys(c.seed).length) setSeed(c.seed);
      // Picked up from the poll: if the operator locked charting, or
      // another station's writes arrived, the UI reflects it.
      if (c.locked) setLocked(true);
    }
  }, [demo, patientId]);

  useEffect(() => {
    refresh();
    fetchCatalog().then(setCatalog);
    if (demo) return undefined;
    // Live projection — poll so this station sees other EHR stations'
    // notes/orders/vitals and the operator's lock-in. The note editor is
    // local component state, so a background refresh never disturbs it.
    const iv = setInterval(refresh, 5000);
    return () => clearInterval(iv);
  }, [refresh, demo]);

  function flash(msg) { setToast(msg); setTimeout(() => setToast(""), 2600); }

  // After any write: refetch the projection so the UI reflects the DB.
  async function afterWrite(res, okMsg) {
    if (res && res.status === 423) { setLocked(true); flash("Charting locked by instructor."); return; }
    if (res && (res.ok || res.demo || (res.data && res.data.ok))) {
      flash(demo ? "Demo — not persisted." : okMsg);
      await refresh();
    } else {
      flash("Save failed — check the connection.");
    }
  }

  // Action handlers passed to tabs.
  const act = {
    saveNote: async (id, type, body, signed) =>
      afterWrite(await emitEvent("note.save", "notes", patientId,
        { note_id: id, note_type: type, body, signed,
          author: V3.STATION_LABEL || "Student" }),
        signed ? "Note signed." : "Draft saved."),
    addendum: async (baseId, body) =>
      afterWrite(await emitEvent("note.addendum", "notes", patientId,
        { addendum_to: baseId, body }), "Addendum filed."),
    recordVitals: async (v) =>
      afterWrite(await emitEvent("vitals.record", "vitals", patientId, v),
        "Vitals recorded."),
    placeOrder: async (o) =>
      afterWrite(await placeOrder(patientId, o), "Order placed."),
    acknowledge: async (rid, name) =>
      afterWrite(await emitEvent("result.acknowledge", "results", patientId,
        { result_id: rid, name }), "Result acknowledged."),
    administer: async (med) =>
      afterWrite(await emitEvent("med.administer", "mar", patientId,
        { med, route: "per order" }), "Medication administered."),
    addProblem: async (name) =>
      afterWrite(await emitEvent("problem.add", "problems", patientId, { name }),
        "Problem added."),
    addAllergy: async (name) =>
      afterWrite(await emitEvent("allergy.add", "allergies", patientId,
        { substance: name }), "Allergy added."),
    addCatalogItem: async (category, code, label) => {
      const res = await postCatalogItem(category, code, label);
      if (res && res.data && res.data.items) {
        setCatalog({ items: res.data.items });
      }
      flash(demo ? "Demo — not persisted."
                 : "Added to the master order catalog.");
    },
  };

  const tabs = [
    ["summary", THEME.tabs.summary], ["vitals", THEME.tabs.vitals],
    ["notes", THEME.tabs.notes], ["orders", THEME.tabs.orders],
    ["results", THEME.tabs.results], ["mar", THEME.tabs.mar],
  ];

  return <div>
    {/* status bar */}
    <div style={{ background: locked ? "var(--danger)" : "var(--brand-ink)",
      color: "#fff", fontSize: 11, padding: "3px 12px", display: "flex", gap: 14,
      fontFamily: "'IBM Plex Mono',monospace" }}>
      <span>{THEME.name}</span>
      <span style={{ flex: 1 }}>
        {demo ? "DEMO — preview, nothing is saved"
              : locked ? "🔒 Charting locked — read-only"
                       : `LIVE · session ${V3.JOIN} · station ${V3.STATION}`}</span>
      {!demo && <span>{chart ? `${chart.event_count} chart events` : "loading…"}</span>}
    </div>

    <PatientBanner p={patient} />

    {/* tab bar */}
    <div style={{ display: "flex", background: "var(--panel)",
      borderBottom: "2px solid var(--line)", flexWrap: "wrap" }}>
      {tabs.map(([k, label]) => <button key={k} onClick={() => setTab(k)}
        style={{ background: "none", border: 0, padding: "10px 16px", fontWeight: 600,
          fontSize: 13, color: tab === k ? "var(--brand)" : "var(--ink3)",
          borderBottom: tab === k ? "3px solid var(--brand)" : "3px solid transparent" }}>
        {label}</button>)}
    </div>

    <div style={{ padding: 14, maxWidth: 940, margin: "0 auto" }}>
      {tab === "summary" && <SummaryTab p={patient} seed={seed} chart={chart} act={act} locked={locked} />}
      {tab === "vitals" && <VitalsTab seed={seed} chart={chart} act={act} locked={locked} />}
      {tab === "notes" && <NotesTab seed={seed} chart={chart} act={act} locked={locked} />}
      {tab === "orders" && <OrdersTab catalog={catalog} chart={chart} act={act} locked={locked} />}
      {tab === "results" && <ResultsTab seed={seed} chart={chart} act={act} locked={locked} />}
      {tab === "mar" && <MARTab seed={seed} chart={chart} act={act} locked={locked} />}
    </div>

    {toast && <div style={{ position: "fixed", bottom: 18, left: "50%",
      transform: "translateX(-50%)", background: "var(--brand-ink)", color: "#fff",
      padding: "8px 18px", borderRadius: 99, fontSize: 12, fontWeight: 600,
      boxShadow: "0 6px 20px rgba(0,0,0,.25)" }}>{toast}</div>}
  </div>;
}

ReactDOM.createRoot(document.getElementById("app")).render(<EHRApp />);
