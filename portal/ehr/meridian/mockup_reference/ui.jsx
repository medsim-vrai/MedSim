/* global React */
const { useState, useEffect, useRef, useMemo } = React;

const I = {
  home:(s=14)=> <svg width={s} height={s} viewBox="0 0 16 16" fill="none"><path d="M2 7l6-5 6 5v7H10v-4H6v4H2V7z" stroke="currentColor" strokeLinejoin="round"/></svg>,
  list:(s=14)=> <svg width={s} height={s} viewBox="0 0 16 16" fill="none"><path d="M3 4h10M3 8h10M3 12h10" stroke="currentColor" strokeLinecap="round"/></svg>,
  pen:(s=14)=> <svg width={s} height={s} viewBox="0 0 16 16" fill="none"><path d="M3 13l2-.5L12.5 5l-1.5-1.5L3.5 11 3 13z" stroke="currentColor" strokeLinejoin="round"/></svg>,
  mic:(s=14)=> <svg width={s} height={s} viewBox="0 0 16 16" fill="none"><rect x="6" y="2" width="4" height="8" rx="2" stroke="currentColor"/><path d="M4 8a4 4 0 008 0M8 12v2" stroke="currentColor" strokeLinecap="round"/></svg>,
  flask:(s=14)=> <svg width={s} height={s} viewBox="0 0 16 16" fill="none"><path d="M6 2v4L3 12.5A1.5 1.5 0 004.3 14.5h7.4A1.5 1.5 0 0013 12.5L10 6V2M5 2h6" stroke="currentColor" strokeLinejoin="round"/></svg>,
  pulse:(s=14)=> <svg width={s} height={s} viewBox="0 0 16 16" fill="none"><path d="M1 8h3l1.5-4 2 8L10 6l1 2h4" stroke="currentColor" strokeLinejoin="round" strokeLinecap="round"/></svg>,
  user:(s=14)=> <svg width={s} height={s} viewBox="0 0 16 16" fill="none"><circle cx="8" cy="6" r="2.5" stroke="currentColor"/><path d="M3 13.5c.5-2.5 2.5-4 5-4s4.5 1.5 5 4" stroke="currentColor" strokeLinecap="round"/></svg>,
  shield:(s=14)=> <svg width={s} height={s} viewBox="0 0 16 16" fill="none"><path d="M8 2l5 1.5v4.5c0 3-2 5.5-5 6-3-.5-5-3-5-6V3.5L8 2z" stroke="currentColor" strokeLinejoin="round"/></svg>,
  building:(s=14)=> <svg width={s} height={s} viewBox="0 0 16 16" fill="none"><rect x="3" y="2" width="10" height="12" stroke="currentColor"/><path d="M6 5h1M9 5h1M6 8h1M9 8h1M7 14v-3h2v3" stroke="currentColor" strokeLinecap="round"/></svg>,
  tablet:(s=14)=> <svg width={s} height={s} viewBox="0 0 16 16" fill="none"><rect x="3" y="2" width="10" height="12" rx="1.5" stroke="currentColor"/><circle cx="8" cy="12" r=".7" fill="currentColor"/></svg>,
  desktop:(s=14)=> <svg width={s} height={s} viewBox="0 0 16 16" fill="none"><rect x="2" y="3" width="12" height="8" rx="1" stroke="currentColor"/><path d="M6 14h4M8 11v3" stroke="currentColor" strokeLinecap="round"/></svg>,
  phone:(s=14)=> <svg width={s} height={s} viewBox="0 0 16 16" fill="none"><rect x="5" y="2" width="6" height="12" rx="1" stroke="currentColor"/><circle cx="8" cy="12" r=".5" fill="currentColor"/></svg>,
  search:(s=14)=> <svg width={s} height={s} viewBox="0 0 16 16" fill="none"><circle cx="7" cy="7" r="4" stroke="currentColor"/><path d="M10 10l3 3" stroke="currentColor" strokeLinecap="round"/></svg>,
  check:(s=14)=> <svg width={s} height={s} viewBox="0 0 16 16" fill="none"><path d="M3 8l3 3 7-7" stroke="currentColor" strokeWidth="1.6" strokeLinecap="round" strokeLinejoin="round"/></svg>,
  warn:(s=14)=> <svg width={s} height={s} viewBox="0 0 16 16" fill="none"><path d="M8 2l6.5 11h-13L8 2zM8 6v3.5M8 11.5v.01" stroke="currentColor" strokeLinejoin="round"/></svg>,
  plus:(s=14)=> <svg width={s} height={s} viewBox="0 0 16 16" fill="none"><path d="M8 3v10M3 8h10" stroke="currentColor" strokeLinecap="round"/></svg>,
  x:(s=14)=> <svg width={s} height={s} viewBox="0 0 16 16" fill="none"><path d="M4 4l8 8M12 4l-8 8" stroke="currentColor" strokeLinecap="round"/></svg>,
  send:(s=14)=> <svg width={s} height={s} viewBox="0 0 16 16" fill="none"><path d="M2 8l12-5-3 12-3-5-6-2z" stroke="currentColor" strokeLinejoin="round"/></svg>,
  bell:(s=14)=> <svg width={s} height={s} viewBox="0 0 16 16" fill="none"><path d="M3.5 11h9l-1-1.5V7a3.5 3.5 0 10-7 0v2.5L3.5 11zM7 13a1 1 0 002 0" stroke="currentColor" strokeLinejoin="round"/></svg>,
  spark:(s=14)=> <svg width={s} height={s} viewBox="0 0 16 16" fill="none"><path d="M8 2v3M8 11v3M2 8h3M11 8h3M4.5 4.5l2 2M9.5 9.5l2 2M11.5 4.5l-2 2M6.5 9.5l-2 2" stroke="currentColor" strokeLinecap="round"/></svg>,
  caret:(s=14)=> <svg width={s} height={s} viewBox="0 0 16 16" fill="none"><path d="M5 6l3 3 3-3" stroke="currentColor" strokeLinecap="round"/></svg>
};
window.I = I;

const Logo = ({size=22})=>(
  <svg width={size} height={size} viewBox="0 0 24 24" fill="none">
    <path d="M2 18l5-11 4 8 3-5 5 8" stroke="#4a7556" strokeWidth="1.8" strokeLinecap="round" strokeLinejoin="round"/>
    <circle cx="12" cy="12" r="10.2" stroke="#4a7556" strokeWidth="1.2"/>
  </svg>
);
window.MerLogo = Logo;

const Pill = ({tone="neutral",children,size="sm"})=>{
  const tones = {
    neutral:{bg:"#ecefe9",fg:"#48564f"},
    sage:{bg:"var(--sage-tint)",fg:"var(--sage-2)"},
    slate:{bg:"var(--slate-tint)",fg:"var(--slate)"},
    terracotta:{bg:"var(--terracotta-tint)",fg:"var(--terracotta)"},
    gold:{bg:"var(--gold-tint)",fg:"var(--gold)"},
    crimson:{bg:"var(--crimson-tint)",fg:"var(--crimson)"}
  }[tone] || {bg:"#ecefe9",fg:"#48564f"};
  return <span style={{
    display:"inline-flex",alignItems:"center",gap:4,
    background:tones.bg,color:tones.fg,
    padding: size==="sm"?"2px 8px":"4px 10px",
    borderRadius:99,fontSize: size==="sm"?11:12,fontWeight:600
  }}>{children}</span>;
};
window.Pill = Pill;

const AppBar = ({user,role,onSwitch,device,setDevice})=>(
  <div style={{
    background:"#fff",color:"var(--ink)",borderBottom:"1px solid var(--line)",
    display:"flex",alignItems:"center",padding:"0 18px",height:60,gap:18
  }}>
    <div style={{display:"flex",alignItems:"center",gap:10}}>
      <Logo size={26}/>
      <div>
        <div style={{fontFamily:"'Newsreader',serif",fontWeight:700,fontSize:17,letterSpacing:".01em",color:"var(--sage-2)"}}>Meridian EHR</div>
        <div style={{fontSize:10,color:"var(--ink-3)",fontFamily:"'JetBrains Mono',monospace"}}>Community Edition · 2026.1</div>
      </div>
    </div>
    <div style={{width:1,height:32,background:"var(--line)"}}/>
    <div style={{display:"flex",alignItems:"center",gap:4}}>
      {[
        {k:"clinician",l:"Clinician",ic:I.user},
        {k:"registration",l:"Registration",ic:I.building},
        {k:"admin",l:"Administrator",ic:I.shield}
      ].map(t=>(
        <button key={t.k} onClick={()=>onSwitch(t.k)} style={{
          display:"flex",alignItems:"center",gap:6,padding:"7px 14px",borderRadius:99,
          background: role===t.k?"var(--sage-tint)":"transparent",
          color: role===t.k?"var(--sage-2)":"var(--ink-2)",
          fontWeight:600,fontSize:12
        }}>{t.ic(13)}{t.l}</button>
      ))}
    </div>
    <div style={{flex:1}}/>
    <div style={{display:"flex",alignItems:"center",gap:6,background:"var(--bg)",padding:"6px 12px",borderRadius:99,fontSize:12,minWidth:280,border:"1px solid var(--line)"}}>
      {I.search(13)}<input placeholder="Find patient or function…" style={{background:"transparent",border:0,outline:"none",flex:1}}/>
      <span style={{color:"var(--ink-3)",fontSize:10,fontFamily:"'JetBrains Mono',monospace"}}>F2</span>
    </div>
    <div style={{display:"flex",gap:2,background:"var(--bg)",padding:2,borderRadius:99,border:"1px solid var(--line)"}}>
      {[["desktop"],["tablet"],["phone"]].map(([k])=>(
        <button key={k} onClick={()=>setDevice(k)} style={{
          padding:"5px 9px",borderRadius:99,
          background: device===k?"var(--sage)":"transparent",
          color: device===k?"#fff":"var(--ink-2)",fontWeight:600
        }}>{I[k](13)}</button>
      ))}
    </div>
    <div style={{display:"flex",alignItems:"center",gap:10}}>
      <button style={{position:"relative",color:"var(--ink-2)"}}>{I.bell(16)}<span style={{position:"absolute",top:-2,right:-3,background:"var(--terracotta)",color:"#fff",borderRadius:99,fontSize:9,padding:"1px 4px",fontWeight:700}}>3</span></button>
      <div style={{display:"flex",alignItems:"center",gap:8,padding:"4px 10px 4px 4px",border:"1px solid var(--line)",borderRadius:99}}>
        <div style={{width:26,height:26,borderRadius:99,background:"var(--sage)",color:"#fff",display:"grid",placeItems:"center",fontWeight:700,fontSize:11}}>{user.initials}</div>
        <div style={{fontSize:11,lineHeight:1.1}}><div style={{fontWeight:700}}>{user.name}</div><div style={{color:"var(--ink-3)"}}>{user.title}</div></div>
      </div>
    </div>
  </div>
);
window.AppBar = AppBar;

const PatientHeader = ({p})=>(
  <div style={{
    background:"linear-gradient(180deg,#fafbf8,#fff)",
    borderBottom:"1px solid var(--line)",padding:"14px 22px",
    display:"flex",alignItems:"center",gap:16
  }}>
    <div style={{
      width:50,height:50,borderRadius:99,background:"var(--sage-tint)",
      color:"var(--sage-2)",fontFamily:"'Newsreader',serif",
      display:"grid",placeItems:"center",fontWeight:700,fontSize:18,
      border:"1px solid var(--sage)"
    }}>{p.name.split(" ").map(s=>s[0]).slice(0,2).join("")}</div>
    <div style={{flex:1}}>
      <div style={{display:"flex",alignItems:"baseline",gap:8}}>
        <div style={{fontFamily:"'Newsreader',serif",fontSize:20,fontWeight:700}}>{p.name}</div>
        <div style={{color:"var(--ink-3)",fontSize:13}}>· {p.sex} · {p.age} · {p.pronouns}</div>
      </div>
      <div style={{display:"flex",gap:16,marginTop:4,fontSize:11,color:"var(--ink-2)"}}>
        <span>MRN <b style={{fontFamily:"'JetBrains Mono',monospace"}}>{p.mrn}</b></span>
        <span>DOB <b>{p.dob}</b></span>
        <span>{p.location}</span>
        {p.los!=="—" && <span>{p.los}</span>}
        <span>PCP: {p.pcp}</span>
      </div>
    </div>
    <div style={{display:"flex",flexDirection:"column",alignItems:"flex-end",gap:4}}>
      <div style={{display:"flex",gap:6}}>
        {p.allergies[0]!=="NKDA" && <Pill tone="terracotta">⚠ {p.allergies.length} allergies</Pill>}
        {p.isolation!=="Standard" && <Pill tone="terracotta">{p.isolation}</Pill>}
        <Pill tone="sage">{p.status}</Pill>
      </div>
      <div style={{fontSize:11,color:"var(--ink-3)"}}>Insurance: {p.insurance}</div>
    </div>
  </div>
);
window.PatientHeader = PatientHeader;

const Anno = ({children, side="right", show, top=12})=>{
  if(!show) return null;
  return (
    <div style={{
      position:"absolute",top,[side]:12,zIndex:5,
      background:"var(--gold-tint)",border:"1px solid var(--gold)",color:"#5a3f0c",
      padding:"7px 10px",borderRadius:6,fontSize:11,maxWidth:260,
      boxShadow:"0 4px 10px rgba(168,124,26,.18)",fontFamily:"'JetBrains Mono',monospace",lineHeight:1.4
    }}>
      <div style={{fontWeight:700,fontSize:9,letterSpacing:".1em",marginBottom:2}}>NOTE</div>
      {children}
    </div>
  );
};
window.Anno = Anno;

const Card = ({title,children,style,pad=true,actions,sub})=>(
  <section style={{background:"#fff",border:"1px solid var(--line)",borderRadius:8,boxShadow:"var(--shadow)",overflow:"hidden",...style}}>
    {title && <header style={{padding:"12px 16px",borderBottom:"1px solid var(--line-2)",display:"flex",alignItems:"center",gap:10}}>
      <div>
        <div style={{fontFamily:"'Newsreader',serif",fontSize:14,fontWeight:700,color:"var(--ink)"}}>{title}</div>
        {sub && <div style={{fontSize:11,color:"var(--ink-3)",marginTop:1}}>{sub}</div>}
      </div>
      <div style={{flex:1}}/>
      {actions}
    </header>}
    <div style={{padding: pad? "14px 16px" : 0}}>{children}</div>
  </section>
);
window.Card = Card;

const ghostBtn = { padding:"7px 14px",border:"1px solid var(--line)",borderRadius:99,background:"#fff",fontWeight:600,fontSize:12,display:"inline-flex",alignItems:"center",gap:5,color:"var(--ink-2)" };
const primaryBtn = { padding:"7px 16px",border:0,borderRadius:99,background:"var(--sage)",color:"#fff",fontWeight:700,fontSize:12,display:"inline-flex",alignItems:"center",gap:5 };
const slateBtn = { padding:"7px 16px",border:0,borderRadius:99,background:"var(--slate)",color:"#fff",fontWeight:700,fontSize:12,display:"inline-flex",alignItems:"center",gap:5 };
const inputStyle = { padding:"8px 11px",border:"1px solid var(--line)",borderRadius:6,background:"#fff",fontSize:13 };
const selStyle = { ...inputStyle, padding:"6px 9px",fontSize:12 };
window.ghostBtn = ghostBtn; window.primaryBtn = primaryBtn; window.slateBtn = slateBtn;
window.inputStyle = inputStyle; window.selStyle = selStyle;
