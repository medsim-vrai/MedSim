/* global React */
const { useState, useEffect, useRef, useMemo } = React;

const I = {
  squares: (s=14)=> <svg width={s} height={s} viewBox="0 0 16 16" fill="none"><rect x="2" y="2" width="5" height="5" stroke="currentColor"/><rect x="9" y="2" width="5" height="5" stroke="currentColor"/><rect x="2" y="9" width="5" height="5" stroke="currentColor"/><rect x="9" y="9" width="5" height="5" stroke="currentColor"/></svg>,
  list: (s=14)=> <svg width={s} height={s} viewBox="0 0 16 16" fill="none"><path d="M3 4h10M3 8h10M3 12h10" stroke="currentColor" strokeLinecap="round"/></svg>,
  pen: (s=14)=> <svg width={s} height={s} viewBox="0 0 16 16" fill="none"><path d="M3 13l2-.5L12.5 5l-1.5-1.5L3.5 11 3 13z" stroke="currentColor" strokeLinejoin="round"/></svg>,
  mic: (s=14)=> <svg width={s} height={s} viewBox="0 0 16 16" fill="none"><rect x="6" y="2" width="4" height="8" rx="2" stroke="currentColor"/><path d="M4 8a4 4 0 008 0M8 12v2" stroke="currentColor" strokeLinecap="round"/></svg>,
  flask: (s=14)=> <svg width={s} height={s} viewBox="0 0 16 16" fill="none"><path d="M6 2v4L3 12.5A1.5 1.5 0 004.3 14.5h7.4A1.5 1.5 0 0013 12.5L10 6V2M5 2h6" stroke="currentColor" strokeLinejoin="round"/></svg>,
  pulse: (s=14)=> <svg width={s} height={s} viewBox="0 0 16 16" fill="none"><path d="M1 8h3l1.5-4 2 8L10 6l1 2h4" stroke="currentColor" strokeLinejoin="round" strokeLinecap="round"/></svg>,
  user: (s=14)=> <svg width={s} height={s} viewBox="0 0 16 16" fill="none"><circle cx="8" cy="6" r="2.5" stroke="currentColor"/><path d="M3 13.5c.5-2.5 2.5-4 5-4s4.5 1.5 5 4" stroke="currentColor" strokeLinecap="round"/></svg>,
  shield: (s=14)=> <svg width={s} height={s} viewBox="0 0 16 16" fill="none"><path d="M8 2l5 1.5v4.5c0 3-2 5.5-5 6-3-.5-5-3-5-6V3.5L8 2z" stroke="currentColor" strokeLinejoin="round"/></svg>,
  building: (s=14)=> <svg width={s} height={s} viewBox="0 0 16 16" fill="none"><rect x="3" y="2" width="10" height="12" stroke="currentColor"/><path d="M6 5h1M9 5h1M6 8h1M9 8h1M7 14v-3h2v3" stroke="currentColor" strokeLinecap="round"/></svg>,
  tablet: (s=14)=> <svg width={s} height={s} viewBox="0 0 16 16" fill="none"><rect x="3" y="2" width="10" height="12" rx="1.5" stroke="currentColor"/><circle cx="8" cy="12" r=".7" fill="currentColor"/></svg>,
  desktop: (s=14)=> <svg width={s} height={s} viewBox="0 0 16 16" fill="none"><rect x="2" y="3" width="12" height="8" rx="1" stroke="currentColor"/><path d="M6 14h4M8 11v3" stroke="currentColor" strokeLinecap="round"/></svg>,
  phone: (s=14)=> <svg width={s} height={s} viewBox="0 0 16 16" fill="none"><rect x="5" y="2" width="6" height="12" rx="1" stroke="currentColor"/><circle cx="8" cy="12" r=".5" fill="currentColor"/></svg>,
  search: (s=14)=> <svg width={s} height={s} viewBox="0 0 16 16" fill="none"><circle cx="7" cy="7" r="4" stroke="currentColor"/><path d="M10 10l3 3" stroke="currentColor" strokeLinecap="round"/></svg>,
  check: (s=14)=> <svg width={s} height={s} viewBox="0 0 16 16" fill="none"><path d="M3 8l3 3 7-7" stroke="currentColor" strokeWidth="1.6" strokeLinecap="round" strokeLinejoin="round"/></svg>,
  warn: (s=14)=> <svg width={s} height={s} viewBox="0 0 16 16" fill="none"><path d="M8 2l6.5 11h-13L8 2zM8 6v3.5M8 11.5v.01" stroke="currentColor" strokeLinejoin="round"/></svg>,
  plus: (s=14)=> <svg width={s} height={s} viewBox="0 0 16 16" fill="none"><path d="M8 3v10M3 8h10" stroke="currentColor" strokeLinecap="round"/></svg>,
  x: (s=14)=> <svg width={s} height={s} viewBox="0 0 16 16" fill="none"><path d="M4 4l8 8M12 4l-8 8" stroke="currentColor" strokeLinecap="round"/></svg>,
  send: (s=14)=> <svg width={s} height={s} viewBox="0 0 16 16" fill="none"><path d="M2 8l12-5-3 12-3-5-6-2z" stroke="currentColor" strokeLinejoin="round"/></svg>,
  caret: (s=14)=> <svg width={s} height={s} viewBox="0 0 16 16" fill="none"><path d="M5 6l3 3 3-3" stroke="currentColor" strokeLinecap="round"/></svg>,
  bell: (s=14)=> <svg width={s} height={s} viewBox="0 0 16 16" fill="none"><path d="M3.5 11h9l-1-1.5V7a3.5 3.5 0 10-7 0v2.5L3.5 11zM7 13a1 1 0 002 0" stroke="currentColor" strokeLinejoin="round"/></svg>,
  bolt:(s=14)=> <svg width={s} height={s} viewBox="0 0 16 16" fill="none"><path d="M9 2L4 9h3l-1 5 5-7H8l1-5z" stroke="currentColor" strokeLinejoin="round"/></svg>,
  spark:(s=14)=> <svg width={s} height={s} viewBox="0 0 16 16" fill="none"><path d="M8 2v3M8 11v3M2 8h3M11 8h3M4.5 4.5l2 2M9.5 9.5l2 2M11.5 4.5l-2 2M6.5 9.5l-2 2" stroke="currentColor" strokeLinecap="round"/></svg>
};
window.I = I;

const Logo = ({size=22})=>(
  <svg width={size} height={size} viewBox="0 0 24 24" fill="none">
    <circle cx="12" cy="12" r="10" stroke="#0b3454" strokeWidth="1.6"/>
    <path d="M7 12a5 5 0 0110 0M9.5 12a2.5 2.5 0 015 0" stroke="#1e9c95" strokeWidth="1.6" strokeLinecap="round"/>
  </svg>
);
window.CyrusLogo = Logo;

// Pill
const Pill = ({tone="neutral",children,size="sm"})=>{
  const tones = {
    neutral:{bg:"#eaeef3",fg:"#3a4d5c"},
    navy:{bg:"var(--navy-tint)",fg:"var(--navy)"},
    teal:{bg:"var(--teal-tint)",fg:"var(--teal)"},
    orange:{bg:"var(--orange-tint)",fg:"var(--orange)"},
    red:{bg:"var(--red-tint)",fg:"var(--red)"},
    green:{bg:"var(--green-tint)",fg:"var(--green)"}
  }[tone] || {bg:"#eaeef3",fg:"#3a4d5c"};
  return <span style={{
    display:"inline-flex",alignItems:"center",gap:4,
    background:tones.bg,color:tones.fg,
    padding: size==="sm"?"2px 8px":"4px 10px",
    borderRadius:3,fontSize: size==="sm"?11:12,fontWeight:600,letterSpacing:".01em"
  }}>{children}</span>;
};
window.Pill = Pill;

const AppBar = ({user,role,onSwitch,device,setDevice})=>(
  <div style={{
    background:"#0b3454",color:"#fff",borderBottom:"1px solid #08263e",
    display:"flex",alignItems:"stretch",padding:"0 14px",height:54
  }}>
    <div style={{display:"flex",alignItems:"center",gap:8}}>
      <div style={{background:"#fff",borderRadius:4,padding:"3px 5px",display:"flex",alignItems:"center"}}><Logo size={20}/></div>
      <div>
        <div style={{fontWeight:700,fontSize:14,letterSpacing:".02em"}}>Cyrus Care</div>
        <div style={{fontSize:10,opacity:.6,fontFamily:"'JetBrains Mono',monospace"}}>EnterpriseEHR · 26.1.4</div>
      </div>
    </div>
    <div style={{width:1,background:"rgba(255,255,255,.1)",margin:"0 14px"}}/>
    <div style={{display:"flex",alignItems:"center",gap:0}}>
      {[
        {k:"clinician",l:"Clinician",ic:I.user},
        {k:"registration",l:"Registration",ic:I.building},
        {k:"admin",l:"Administrator",ic:I.shield}
      ].map(t=>(
        <button key={t.k} onClick={()=>onSwitch(t.k)} style={{
          display:"flex",alignItems:"center",gap:6,padding:"0 14px",
          background: role===t.k?"#1c5b8a":"transparent",
          color: role===t.k?"#fff":"#cdd9e2",
          borderTop: role===t.k?"3px solid #1e9c95":"3px solid transparent",
          fontWeight:600,fontSize:12,height:54
        }}>{t.ic(13)}{t.l}</button>
      ))}
    </div>
    <div style={{flex:1}}/>
    <div style={{display:"flex",alignItems:"center",gap:6,background:"rgba(255,255,255,.08)",padding:"0 12px",borderRadius:4,margin:"10px 0",fontSize:12,minWidth:280}}>
      {I.search(13)}<input placeholder="Find patient · order · template…" style={{background:"transparent",border:0,outline:"none",color:"#fff",flex:1}}/>
      <span style={{opacity:.5,fontSize:10,fontFamily:"'JetBrains Mono',monospace"}}>ALT+P</span>
    </div>
    <div style={{display:"flex",gap:2,background:"rgba(255,255,255,.08)",padding:2,borderRadius:4,margin:"12px 8px"}}>
      {[["desktop"],["tablet"],["phone"]].map(([k])=>(
        <button key={k} onClick={()=>setDevice(k)} style={{
          padding:"4px 8px",borderRadius:3,
          background:device===k?"#1e9c95":"transparent",
          color:device===k?"#fff":"#cdd9e2",fontWeight:600
        }}>{I[k](13)}</button>
      ))}
    </div>
    <div style={{display:"flex",alignItems:"center",gap:10,marginLeft:6}}>
      <button style={{position:"relative",color:"#cdd9e2"}}>{I.bell(15)}<span style={{position:"absolute",top:0,right:-2,background:"#d56b1f",color:"#fff",borderRadius:99,fontSize:9,padding:"1px 4px",fontWeight:700}}>4</span></button>
      <div style={{display:"flex",alignItems:"center",gap:6,background:"rgba(255,255,255,.1)",padding:"4px 10px 4px 4px",borderRadius:3}}>
        <div style={{width:24,height:24,borderRadius:3,background:"#1e9c95",display:"grid",placeItems:"center",fontWeight:700,fontSize:11}}>{user.initials}</div>
        <div style={{fontSize:11,lineHeight:1.1}}><div style={{fontWeight:600}}>{user.name}</div><div style={{opacity:.65}}>{user.title}</div></div>
      </div>
    </div>
  </div>
);
window.AppBar = AppBar;

// Patient banner — Cyrus uses a flatter, data-strip approach
const PatientBanner = ({p})=>(
  <div style={{background:"#fff",borderBottom:"3px solid var(--navy)",padding:"10px 16px"}}>
    <div style={{display:"flex",alignItems:"center",gap:12}}>
      <div style={{
        width:44,height:44,borderRadius:3,background:"var(--navy)",color:"#fff",
        display:"grid",placeItems:"center",fontWeight:700,fontSize:14
      }}>{p.name.split(" ").map(s=>s[0]).slice(0,2).join("")}</div>
      <div style={{flex:1}}>
        <div style={{display:"flex",alignItems:"baseline",gap:10}}>
          <div style={{fontSize:17,fontWeight:700}}>{p.name}</div>
          <span style={{fontSize:12,color:"var(--ink-3)"}}>· {p.sex} · {p.age}y · {p.pronouns}</span>
        </div>
        <div style={{display:"flex",gap:18,marginTop:2,fontSize:11,color:"var(--ink-2)",fontFamily:"'JetBrains Mono',monospace"}}>
          <span>FIN <b>{p.fin}</b></span>
          <span>MRN <b>{p.mrn}</b></span>
          <span>DOB <b>{p.dob}</b></span>
          <span>{p.location}</span>
          <span>{p.los}</span>
        </div>
      </div>
      <div style={{display:"flex",gap:6}}>
        <Pill tone="red">⚠ {p.allergies.length} allergies</Pill>
        {p.code!=="Full Code" && <Pill tone="orange">{p.code}</Pill>}
        {p.isolation!=="Standard" && <Pill tone="orange">{p.isolation}</Pill>}
        <Pill tone="navy">{p.status}</Pill>
      </div>
    </div>
    <div style={{display:"flex",gap:6,marginTop:8,flexWrap:"wrap"}}>
      {p.allergies.map(a=><Pill key={a} tone="red" size="sm">⚠ {a}</Pill>)}
      <span style={{flex:1}}/>
      <span style={{fontSize:11,color:"var(--ink-3)"}}>Wt {p.weight} · Ht {p.height} · BSA {p.bsa}</span>
    </div>
  </div>
);
window.PatientBanner = PatientBanner;

const Anno = ({children, side="right", show, top=8})=>{
  if(!show) return null;
  return (
    <div style={{
      position:"absolute",top,[side]:8,zIndex:5,
      background:"#fbe6d3",border:"1px solid var(--orange)",color:"#5a3208",
      padding:"6px 9px",borderRadius:3,fontSize:11,maxWidth:260,
      boxShadow:"0 4px 10px rgba(213,107,31,.18)",fontFamily:"'JetBrains Mono',monospace",lineHeight:1.4
    }}>
      <div style={{fontWeight:700,fontSize:9,letterSpacing:".1em",marginBottom:2}}>NOTE</div>
      {children}
    </div>
  );
};
window.Anno = Anno;

// Card primitive
const Card = ({title,children,style,pad=true,actions,collapsed,onCollapse})=>(
  <section style={{background:"#fff",border:"1px solid var(--line)",borderRadius:4,boxShadow:"var(--shadow)",overflow:"hidden",...style}}>
    <header style={{
      padding:"8px 12px",borderBottom:"1px solid var(--line)",
      display:"flex",alignItems:"center",gap:8,background:"#f6f9fc",
      borderLeft:"3px solid var(--teal)"
    }}>
      <div style={{fontSize:11,fontWeight:700,letterSpacing:".06em",color:"var(--navy)",textTransform:"uppercase"}}>{title}</div>
      <div style={{flex:1}}/>
      {actions}
    </header>
    {!collapsed && <div style={{padding: pad? "12px 14px" : 0}}>{children}</div>}
  </section>
);
window.Card = Card;

const ghostBtn = { padding:"6px 12px",border:"1px solid var(--line)",borderRadius:3,background:"#fff",fontWeight:600,fontSize:12,display:"inline-flex",alignItems:"center",gap:5,color:"var(--ink-2)" };
const primaryBtn = { padding:"7px 14px",border:0,borderRadius:3,background:"var(--teal)",color:"#fff",fontWeight:700,fontSize:12,display:"inline-flex",alignItems:"center",gap:5 };
const navyBtn = { padding:"7px 14px",border:0,borderRadius:3,background:"var(--navy)",color:"#fff",fontWeight:700,fontSize:12,display:"inline-flex",alignItems:"center",gap:5 };
const inputStyle = { padding:"7px 10px",border:"1px solid var(--line)",borderRadius:3,background:"#fff",fontSize:13 };
const selStyle = { ...inputStyle, padding:"5px 8px",fontSize:12 };
window.ghostBtn = ghostBtn;
window.primaryBtn = primaryBtn;
window.navyBtn = navyBtn;
window.inputStyle = inputStyle;
window.selStyle = selStyle;
