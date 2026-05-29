/* global React */
const { useState, useEffect, useRef, useMemo } = React;

// ── Icons (inline minimal SVG, no AI-slop hand-drawn imagery) ──────────
const Ico = {
  chart: (s=14)=> <svg width={s} height={s} viewBox="0 0 16 16" fill="none"><rect x="2.5" y="2.5" width="11" height="11" rx="1.5" stroke="currentColor"/><path d="M5 7h6M5 10h4" stroke="currentColor" strokeLinecap="round"/></svg>,
  pen: (s=14)=> <svg width={s} height={s} viewBox="0 0 16 16" fill="none"><path d="M3 13l2-.5L12.5 5l-1.5-1.5L3.5 11 3 13z" stroke="currentColor" strokeLinejoin="round"/></svg>,
  mic: (s=14)=> <svg width={s} height={s} viewBox="0 0 16 16" fill="none"><rect x="6" y="2" width="4" height="8" rx="2" stroke="currentColor"/><path d="M4 8a4 4 0 008 0M8 12v2" stroke="currentColor" strokeLinecap="round"/></svg>,
  flask: (s=14)=> <svg width={s} height={s} viewBox="0 0 16 16" fill="none"><path d="M6 2v4L3 12.5A1.5 1.5 0 004.3 14.5h7.4A1.5 1.5 0 0013 12.5L10 6V2" stroke="currentColor" strokeLinejoin="round"/><path d="M5 2h6" stroke="currentColor" strokeLinecap="round"/></svg>,
  pulse: (s=14)=> <svg width={s} height={s} viewBox="0 0 16 16" fill="none"><path d="M1 8h3l1.5-4 2 8L10 6l1 2h4" stroke="currentColor" strokeLinejoin="round" strokeLinecap="round"/></svg>,
  user: (s=14)=> <svg width={s} height={s} viewBox="0 0 16 16" fill="none"><circle cx="8" cy="6" r="2.5" stroke="currentColor"/><path d="M3 13.5c.5-2.5 2.5-4 5-4s4.5 1.5 5 4" stroke="currentColor" strokeLinecap="round"/></svg>,
  pill: (s=14)=> <svg width={s} height={s} viewBox="0 0 16 16" fill="none"><rect x="2" y="6" width="12" height="4" rx="2" stroke="currentColor"/><path d="M8 6v4" stroke="currentColor"/></svg>,
  tablet: (s=14)=> <svg width={s} height={s} viewBox="0 0 16 16" fill="none"><rect x="3" y="2" width="10" height="12" rx="1.5" stroke="currentColor"/><circle cx="8" cy="12" r=".7" fill="currentColor"/></svg>,
  search: (s=14)=> <svg width={s} height={s} viewBox="0 0 16 16" fill="none"><circle cx="7" cy="7" r="4" stroke="currentColor"/><path d="M10 10l3 3" stroke="currentColor" strokeLinecap="round"/></svg>,
  check: (s=14)=> <svg width={s} height={s} viewBox="0 0 16 16" fill="none"><path d="M3 8l3 3 7-7" stroke="currentColor" strokeWidth="1.6" strokeLinecap="round" strokeLinejoin="round"/></svg>,
  warn: (s=14)=> <svg width={s} height={s} viewBox="0 0 16 16" fill="none"><path d="M8 2l6.5 11h-13L8 2z" stroke="currentColor" strokeLinejoin="round"/><path d="M8 6v3.5M8 11.5v.01" stroke="currentColor" strokeLinecap="round"/></svg>,
  bell: (s=14)=> <svg width={s} height={s} viewBox="0 0 16 16" fill="none"><path d="M3.5 11h9l-1-1.5V7a3.5 3.5 0 10-7 0v2.5L3.5 11zM7 13a1 1 0 002 0" stroke="currentColor" strokeLinejoin="round"/></svg>,
  plus: (s=14)=> <svg width={s} height={s} viewBox="0 0 16 16" fill="none"><path d="M8 3v10M3 8h10" stroke="currentColor" strokeLinecap="round"/></svg>,
  x: (s=14)=> <svg width={s} height={s} viewBox="0 0 16 16" fill="none"><path d="M4 4l8 8M12 4l-8 8" stroke="currentColor" strokeLinecap="round"/></svg>,
  send: (s=14)=> <svg width={s} height={s} viewBox="0 0 16 16" fill="none"><path d="M2 8l12-5-3 12-3-5-6-2z" stroke="currentColor" strokeLinejoin="round"/></svg>,
  bolt: (s=14)=> <svg width={s} height={s} viewBox="0 0 16 16" fill="none"><path d="M9 2L4 9h3l-1 5 5-7H8l1-5z" stroke="currentColor" strokeLinejoin="round"/></svg>,
  shield: (s=14)=> <svg width={s} height={s} viewBox="0 0 16 16" fill="none"><path d="M8 2l5 1.5v4.5c0 3-2 5.5-5 6-3-.5-5-3-5-6V3.5L8 2z" stroke="currentColor" strokeLinejoin="round"/></svg>,
  phone: (s=14)=> <svg width={s} height={s} viewBox="0 0 16 16" fill="none"><rect x="5" y="2" width="6" height="12" rx="1" stroke="currentColor"/><circle cx="8" cy="12" r=".5" fill="currentColor"/></svg>,
  desktop: (s=14)=> <svg width={s} height={s} viewBox="0 0 16 16" fill="none"><rect x="2" y="3" width="12" height="8" rx="1" stroke="currentColor"/><path d="M6 14h4M8 11v3" stroke="currentColor" strokeLinecap="round"/></svg>,
  building: (s=14)=> <svg width={s} height={s} viewBox="0 0 16 16" fill="none"><rect x="3" y="2" width="10" height="12" stroke="currentColor"/><path d="M6 5h1M9 5h1M6 8h1M9 8h1M7 14v-3h2v3" stroke="currentColor" strokeLinecap="round"/></svg>,
  spark: (s=14)=> <svg width={s} height={s} viewBox="0 0 16 16" fill="none"><path d="M8 2v3M8 11v3M2 8h3M11 8h3M4.5 4.5l2 2M9.5 9.5l2 2M11.5 4.5l-2 2M6.5 9.5l-2 2" stroke="currentColor" strokeLinecap="round"/></svg>
};
window.Ico = Ico;

// ── Helix Logo (original mark) ────────────────────────────────────────
const HelixLogo = ({size=22})=>{
  return (
    <svg width={size} height={size} viewBox="0 0 24 24" fill="none">
      <path d="M5 3c4 4 10 4 14 0M5 21c4-4 10-4 14 0M5 3v18M19 3v18M7 7c3 3 7 3 10 0M7 17c3-3 7-3 10 0" stroke="#143b8a" strokeWidth="1.4" strokeLinecap="round"/>
    </svg>
  );
};
window.HelixLogo = HelixLogo;

// ── Pill / chip ───────────────────────────────────────────────────────
const Pill = ({tone="neutral",children,size="sm"})=>{
  const tones = {
    neutral: { bg:"#eef1f8", fg:"#3a4a6b" },
    brand:   { bg:"var(--brand-tint)", fg:"var(--brand)" },
    amber:   { bg:"var(--amber-tint)", fg:"var(--amber)" },
    teal:    { bg:"var(--teal-tint)", fg:"var(--teal)" },
    rose:    { bg:"var(--rose-tint)", fg:"var(--rose)" },
    green:   { bg:"var(--green-tint)", fg:"var(--green)" }
  }[tone] || {bg:"#eef1f8",fg:"#3a4a6b"};
  return <span style={{
    display:"inline-flex",alignItems:"center",gap:4,
    background:tones.bg,color:tones.fg,
    padding: size==="sm"?"2px 7px":"4px 10px",
    borderRadius:99, fontSize: size==="sm"?11:12, fontWeight:600,
    letterSpacing:".01em"
  }}>{children}</span>;
};
window.Pill = Pill;

// ── App-bar (Helix top chrome) ────────────────────────────────────────
const AppBar = ({user, role, onSwitch, view, setView, device, setDevice})=>{
  return (
    <div style={{
      background:"linear-gradient(180deg,#0a234f,#143b8a)",
      color:"#fff",borderBottom:"3px solid #f1c948",
      display:"flex",alignItems:"center",gap:14,padding:"0 14px",height:46
    }}>
      <div style={{display:"flex",alignItems:"center",gap:8}}>
        <div style={{background:"#fff",borderRadius:6,padding:"3px 5px",display:"flex",alignItems:"center"}}>
          <HelixLogo size={20}/>
        </div>
        <div style={{fontFamily:"'Source Serif 4',serif",fontWeight:700,fontSize:15,letterSpacing:".02em"}}>Helix Health</div>
        <div style={{opacity:.5,fontSize:11,marginLeft:6}}>v 2026.1</div>
      </div>
      <div style={{display:"flex",alignItems:"center",gap:0,marginLeft:10}}>
        {[
          {k:"clinician",label:"Clinician Workspace",ic:Ico.user},
          {k:"registration",label:"Registration",ic:Ico.building},
          {k:"admin",label:"Administrator",ic:Ico.shield}
        ].map(t=>(
          <button key={t.k} onClick={()=>onSwitch(t.k)} style={{
            display:"flex",alignItems:"center",gap:6,
            padding:"6px 12px",borderRadius:6,
            background: role===t.k?"rgba(241,201,72,.18)":"transparent",
            color: role===t.k?"#f1c948":"#dbe2f4",
            fontWeight:600,fontSize:12,
            borderBottom: role===t.k?"2px solid #f1c948":"2px solid transparent"
          }}>
            <span style={{opacity:.85}}>{t.ic(13)}</span>{t.label}
          </button>
        ))}
      </div>
      <div style={{flex:1}}/>
      <div style={{display:"flex",alignItems:"center",gap:6,background:"rgba(255,255,255,.08)",padding:"4px 10px",borderRadius:6,fontSize:12}}>
        {Ico.search(12)} <input placeholder="Find patient, order, or chart…" style={{background:"transparent",border:0,outline:"none",color:"#fff",width:230}}/>
        <span style={{opacity:.5,fontSize:10,fontFamily:"'IBM Plex Mono',monospace"}}>⌘K</span>
      </div>
      <div style={{display:"flex",gap:2,background:"rgba(255,255,255,.08)",padding:2,borderRadius:6}}>
        {[["desktop","Desktop"],["tablet","Tablet"],["phone","Mobile"]].map(([k,l])=>(
          <button key={k} onClick={()=>setDevice(k)} title={l} style={{
            padding:"4px 8px",borderRadius:4,
            background: device===k?"#f1c948":"transparent",
            color: device===k?"#0a234f":"#dbe2f4",fontWeight:600
          }}>{Ico[k](13)}</button>
        ))}
      </div>
      <div style={{display:"flex",alignItems:"center",gap:8,marginLeft:6}}>
        <button style={{position:"relative",color:"#dbe2f4"}}>{Ico.bell(15)}<span style={{position:"absolute",top:-2,right:-2,background:"#c47a04",color:"#fff",borderRadius:99,fontSize:9,padding:"1px 4px",fontWeight:700}}>7</span></button>
        <div style={{display:"flex",alignItems:"center",gap:6,background:"rgba(255,255,255,.1)",padding:"4px 8px 4px 4px",borderRadius:99}}>
          <div style={{width:22,height:22,borderRadius:99,background:"#f1c948",color:"#0a234f",display:"grid",placeItems:"center",fontWeight:700,fontSize:11}}>{user.initials}</div>
          <div style={{fontSize:11,lineHeight:1.1}}>
            <div style={{fontWeight:600}}>{user.name}</div>
            <div style={{opacity:.65}}>{user.title}</div>
          </div>
        </div>
      </div>
    </div>
  );
};
window.AppBar = AppBar;

// ── Patient header band (the "storyboard") ─────────────────────────────
const PatientBand = ({p})=>(
  <div style={{
    background:"#fff",borderBottom:"1px solid var(--line)",padding:"10px 16px",
    display:"flex",alignItems:"center",gap:14
  }}>
    <div style={{
      width:46,height:46,borderRadius:6,background:"var(--brand-tint)",
      color:"var(--brand)",display:"grid",placeItems:"center",fontWeight:700,fontSize:16
    }}>{p.name.split(" ").map(s=>s[0]).slice(0,2).join("")}</div>
    <div>
      <div style={{display:"flex",alignItems:"center",gap:8}}>
        <div style={{fontSize:16,fontWeight:700}}>{p.name}</div>
        <Pill tone="neutral">{p.sex} · {p.age}y · {p.pronouns}</Pill>
        <Pill tone="brand">MRN {p.mrn}</Pill>
        <Pill tone="amber"><span style={{display:"inline-flex"}}>{Ico.warn(11)}</span> {p.allergies.length} allergies</Pill>
        {p.isolation!=="Standard" && <Pill tone="rose">{p.isolation} precautions</Pill>}
        <Pill tone="green">{p.code}</Pill>
      </div>
      <div style={{fontSize:11,color:"var(--ink-3)",marginTop:3,display:"flex",gap:14}}>
        <span>DOB {p.dob}</span><span>Room {p.room}</span><span>{p.status}</span>
        <span>Attending: {p.attending}</span><span>PCP: {p.pcp}</span>
      </div>
    </div>
    <div style={{flex:1}}/>
    <div style={{display:"flex",gap:6}}>
      <button style={{display:"flex",alignItems:"center",gap:6,padding:"7px 11px",border:"1px solid var(--line)",borderRadius:6,fontWeight:600,fontSize:12,background:"#fff"}}>{Ico.bolt(12)} Quick Action</button>
      <button style={{display:"flex",alignItems:"center",gap:6,padding:"7px 11px",border:"1px solid var(--line)",borderRadius:6,fontWeight:600,fontSize:12,background:"#fff"}}>{Ico.send(12)} Sign &amp; Send</button>
    </div>
  </div>
);
window.PatientBand = PatientBand;

// Annotation callout (toggleable)
const Anno = ({children, side="right", show})=>{
  if(!show) return null;
  return (
    <div style={{
      position:"absolute", top:8, [side]:8, zIndex:5,
      background:"#fdf3dc",border:"1px solid #c47a04",color:"#5a3a02",
      padding:"6px 9px",borderRadius:6,fontSize:11,maxWidth:240,
      boxShadow:"0 4px 10px rgba(196,122,4,.18)",fontFamily:"'IBM Plex Mono',monospace",lineHeight:1.4
    }}>
      <div style={{fontWeight:700,fontSize:9,letterSpacing:".1em",marginBottom:2}}>NOTE</div>
      {children}
    </div>
  );
};
window.Anno = Anno;
