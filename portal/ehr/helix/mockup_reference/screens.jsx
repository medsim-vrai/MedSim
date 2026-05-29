/* global React, Ico, Pill, PatientBand, Anno */
const { useState, useEffect, useRef, useMemo } = React;

// =====================================================================
// CLINICIAN WORKSPACE
// =====================================================================
const ClinicianWorkspace = ({patient, setPatient, anno, device})=>{
  const TABS = [
    { k:"chart", label:"Chart Review", ic:Ico.chart },
    { k:"vitals", label:"Vitals & Flowsheet", ic:Ico.pulse },
    { k:"notes", label:"Notes (SmartPhrase)", ic:Ico.pen },
    { k:"voice", label:"Ambient Scribe", ic:Ico.mic },
    { k:"orders", label:"Orders / CPOE", ic:Ico.flask },
    { k:"results", label:"Results", ic:Ico.spark },
    { k:"meds", label:"Meds (MAR)", ic:Ico.pill }
  ];
  const [tab, setTab] = useState("notes");

  return (
    <div style={{display:"flex",flexDirection:"column",flex:1,minHeight:0}}>
      <PatientBand p={patient}/>
      {/* Patient list rail + activity tabs */}
      <div style={{display:"flex",flex:1,minHeight:0}}>
        <ScheduleRail current={patient} setPatient={setPatient}/>
        <div style={{flex:1,display:"flex",flexDirection:"column",minWidth:0}}>
          <ActivityTabs tabs={TABS} value={tab} onChange={setTab} anno={anno}/>
          <div style={{flex:1,overflow:"auto",background:"#f4f5f8",padding:14,position:"relative"}}>
            {tab==="chart" && <ChartReview p={patient} anno={anno}/>}
            {tab==="vitals" && <VitalsFlowsheet anno={anno}/>}
            {tab==="notes" && <SmartPhraseNote p={patient} anno={anno}/>}
            {tab==="voice" && <AmbientScribe p={patient} anno={anno}/>}
            {tab==="orders" && <CPOE anno={anno}/>}
            {tab==="results" && <ResultsView anno={anno}/>}
            {tab==="meds" && <MedsMAR p={patient} anno={anno}/>}
          </div>
        </div>
      </div>
    </div>
  );
};

const ScheduleRail = ({current, setPatient})=>{
  const items = window.HELIX_SCHEDULE;
  return (
    <aside style={{width:248,background:"#fff",borderRight:"1px solid var(--line)",display:"flex",flexDirection:"column"}}>
      <div style={{padding:"10px 12px",borderBottom:"1px solid var(--line)",display:"flex",alignItems:"center",gap:6}}>
        <div style={{fontSize:11,fontWeight:700,letterSpacing:".06em",color:"var(--ink-2)"}}>TODAY · 7 PATIENTS</div>
        <div style={{flex:1}}/>
        <button style={{padding:"3px 6px",border:"1px solid var(--line)",borderRadius:4,fontSize:11,fontWeight:600}}>+ Add</button>
      </div>
      {items.map((it,i)=>{
        const active = it.patient.startsWith(current.name.split(" ")[0]);
        return (
          <button key={i} onClick={()=>{
            // map by last name
            const found = window.HELIX_PATIENTS.find(p=>it.patient.startsWith(p.name.split(" ")[0])) || window.HELIX_PATIENTS[0];
            setPatient(found);
          }} style={{
            display:"block",textAlign:"left",
            padding:"9px 12px",borderBottom:"1px solid var(--line-2)",
            background: active?"var(--brand-tint)":"transparent",
            borderLeft: active?"3px solid var(--brand)":"3px solid transparent",
            cursor:"pointer"
          }}>
            <div style={{display:"flex",alignItems:"baseline",gap:8}}>
              <div style={{fontFamily:"'IBM Plex Mono',monospace",fontSize:11,color:"var(--ink-3)"}}>{it.time}</div>
              <div style={{fontWeight:600,fontSize:12}}>{it.patient}</div>
            </div>
            <div style={{fontSize:11,color:"var(--ink-3)",marginTop:2,display:"flex",alignItems:"center",gap:6}}>
              <span>{it.reason}</span>
              {it.flag==="stat-lab" && <Pill tone="rose" size="sm">STAT lab</Pill>}
              {it.flag==="new-results" && <Pill tone="amber" size="sm">new result</Pill>}
            </div>
            <div style={{marginTop:4}}>
              <Pill tone={it.status==="Seen"?"green":it.status==="In room"?"brand":it.status==="Roomed"?"teal":"neutral"} size="sm">{it.status}</Pill>
            </div>
          </button>
        );
      })}
      <div style={{flex:1}}/>
      <div style={{padding:"8px 12px",borderTop:"1px solid var(--line)",fontSize:11,color:"var(--ink-3)",display:"flex",alignItems:"center",gap:6}}>
        {Ico.shield(12)} HIPAA session · auto-lock 5m
      </div>
    </aside>
  );
};

const ActivityTabs = ({tabs,value,onChange,anno})=>(
  <div style={{
    display:"flex",alignItems:"stretch",background:"#fff",
    borderBottom:"1px solid var(--line)",position:"relative"
  }}>
    {tabs.map(t=>(
      <button key={t.k} onClick={()=>onChange(t.k)} style={{
        display:"flex",alignItems:"center",gap:6,
        padding:"9px 14px",fontWeight:600,fontSize:12,
        color: value===t.k?"var(--brand)":"var(--ink-2)",
        borderBottom: value===t.k?"3px solid var(--brand)":"3px solid transparent",
        marginBottom:-1
      }}>
        {t.ic(13)} {t.label}
      </button>
    ))}
    <div style={{flex:1}}/>
    <Anno show={anno} side="right">
      Activity tabs scaffold every clinical task. Power users live in keyboard-shortcuts; the dense rail trades discoverability for speed.
    </Anno>
  </div>
);

// ── Chart Review ──────────────────────────────────────────────────────
const ChartReview = ({p, anno})=>(
  <div style={{display:"grid",gridTemplateColumns:"1.2fr 1fr 1fr",gap:12}}>
    <Card title="Problem List">
      {p.problems.map((x,i)=>(
        <Row key={i} mono="ICD" code={["E11.9","N18.2","I50.32","Z90.49"][i]||"—"} label={x}/>
      ))}
      <button style={addBtn}>{Ico.plus(11)} Add problem</button>
    </Card>
    <Card title="Active Medications">
      {p.meds.map((m,i)=><Row key={i} label={m} tone="brand"/>)}
      <button style={addBtn}>{Ico.plus(11)} Med rec</button>
    </Card>
    <Card title="Allergies & Alerts">
      {p.allergies.map((a,i)=><Row key={i} label={a} tone="amber"/>)}
      <Row label="Fall risk: Moderate" tone="rose"/>
      <Row label="Glucose monitoring Q6h" tone="teal"/>
    </Card>
    <Card title="Recent Encounters" style={{gridColumn:"span 2"}}>
      <table style={tbl}>
        <thead><tr><th>Date</th><th>Type</th><th>Provider</th><th>Diagnosis</th><th>Disposition</th></tr></thead>
        <tbody>
          <tr><td>2026-04-23</td><td>Surg / Cholecystectomy</td><td>S. Park, MD</td><td>K80.20 Cholelithiasis</td><td>Admit POD-0</td></tr>
          <tr><td>2026-02-11</td><td>Office</td><td>T. Okafor, MD</td><td>E11.9 T2DM</td><td>F/u 3 mo</td></tr>
          <tr><td>2025-11-04</td><td>ED</td><td>R. Ng, MD</td><td>R10.9 Abd pain</td><td>Discharge</td></tr>
          <tr><td>2025-08-19</td><td>Office</td><td>T. Okafor, MD</td><td>I50.32 HFpEF</td><td>F/u 6 mo</td></tr>
        </tbody>
      </table>
    </Card>
    <Card title="Care Team">
      <Row label="Attending: S. Park, MD" tone="brand"/>
      <Row label="PCP: T. Okafor, MD"/>
      <Row label="Nurse: J. Olufemi, RN"/>
      <Row label="Pharmacy: M. Vahdat, PharmD"/>
      <Row label="Case mgmt: A. Korsgaard"/>
    </Card>
  </div>
);

// ── SmartPhrase Note (the workhorse data-entry surface) ───────────────
const SmartPhraseNote = ({p, anno})=>{
  const [text, setText] = useState(
`HPI: ${p.name.split(",")[0]} is a ${p.age}-year-old ${p.sex==="F"?"woman":"man"} POD #2 s/p elective cholecystectomy.
Overnight: tolerating PO, ambulating with PT, pain controlled on PO oxycodone.
No fevers, drain output minimal serosanguinous.

ROS: `);
  const [sug, setSug] = useState(null);
  const [phrasePop, setPhrasePop] = useState(false);
  const ta = useRef(null);
  const [signed, setSigned] = useState(false);

  // Detect smartphrase trigger as user types
  const handleChange = (e)=>{
    const val = e.target.value;
    setText(val);
    const cursor = e.target.selectionStart;
    const before = val.slice(0, cursor);
    const m = before.match(/(\.[a-z0-9-]*)$/i);
    if(m){
      const trigger = m[1].toLowerCase();
      const matches = window.HELIX_SMARTPHRASES.filter(p=>p.trigger.startsWith(trigger));
      if(matches.length){ setSug({ trigger, matches, pos:cursor }); setPhrasePop(true); return; }
    }
    setPhrasePop(false);
  };
  const expand = (sp)=>{
    if(!sug) return;
    const before = text.slice(0, sug.pos - sug.trigger.length);
    const after = text.slice(sug.pos);
    setText(before + sp.expansion + after);
    setPhrasePop(false);
    setTimeout(()=>ta.current?.focus(),0);
  };

  return (
    <div style={{display:"grid",gridTemplateColumns:"1fr 280px",gap:12,position:"relative"}}>
      <Anno show={anno} side="left">SmartPhrase tokens (".ros10", ".pe-normal") expand to multi-paragraph templates. Type a dot in the editor to try.</Anno>
      <div style={{background:"#fff",border:"1px solid var(--line)",borderRadius:6,display:"flex",flexDirection:"column",minHeight:520}}>
        <div style={{padding:"8px 10px",borderBottom:"1px solid var(--line)",display:"flex",gap:6,alignItems:"center"}}>
          <select style={selStyle} defaultValue="prog"><option value="prog">Progress note</option><option>H&amp;P</option><option>Discharge summary</option><option>Op note</option></select>
          <select style={selStyle} defaultValue="surg"><option value="surg">Surgery</option><option>Internal Med</option><option>Family Med</option></select>
          <div style={{width:1,height:20,background:"var(--line)"}}/>
          <button style={tbBtn}><b>B</b></button>
          <button style={tbBtn}><i>I</i></button>
          <button style={tbBtn}>•</button>
          <button style={tbBtn}>1.</button>
          <div style={{flex:1}}/>
          <Pill tone="neutral">Author: J. Lindqvist, MD</Pill>
          <Pill tone="green">Auto-saved 11s ago</Pill>
        </div>
        <textarea ref={ta} value={text} onChange={handleChange} style={{
          flex:1,resize:"none",border:0,outline:"none",padding:"14px 18px",
          fontFamily:"'IBM Plex Mono',monospace",fontSize:13,lineHeight:1.7,color:"var(--ink)"
        }}/>
        {phrasePop && sug && (
          <div style={{
            position:"absolute",bottom:64,left:14,
            background:"#fff",border:"1px solid var(--brand)",borderRadius:6,
            boxShadow:"0 8px 24px rgba(20,59,138,.15)",padding:6,zIndex:10,minWidth:380
          }}>
            <div style={{fontSize:10,fontWeight:700,color:"var(--brand)",letterSpacing:".08em",padding:"3px 6px"}}>SMARTPHRASE — {sug.trigger}</div>
            {sug.matches.map(m=>(
              <button key={m.trigger} onClick={()=>expand(m)} style={{
                display:"block",width:"100%",textAlign:"left",
                padding:"6px 8px",borderRadius:4,fontSize:12
              }} onMouseEnter={e=>e.currentTarget.style.background="var(--brand-tint)"}
                onMouseLeave={e=>e.currentTarget.style.background="transparent"}>
                <span style={{fontFamily:"'IBM Plex Mono',monospace",color:"var(--brand)",fontWeight:600}}>{m.trigger}</span>
                <span style={{color:"var(--ink-3)",marginLeft:8}}>{m.expansion.slice(0,55)}…</span>
              </button>
            ))}
          </div>
        )}
        <div style={{padding:"8px 10px",borderTop:"1px solid var(--line)",display:"flex",alignItems:"center",gap:8}}>
          <Pill tone="brand">{text.length} chars</Pill>
          <Pill tone="neutral">{text.split(/\s+/).filter(Boolean).length} words</Pill>
          <div style={{flex:1}}/>
          <button style={ghostBtn} onClick={()=>{
            window.medsimV3?.event("note.save","notes", p.mrn, {
              note_id:"helix-progress-1", note_type:"Progress note",
              template:"SmartPhrase", body:text, signed:false
            });
          }}>Save draft</button>
          <button onClick={()=>{
            setSigned(true);
            window.medsimV3?.event("note.save","notes", p.mrn, {
              note_id:"helix-progress-1", note_type:"Progress note",
              template:"SmartPhrase", body:text, signed:true
            });
          }} style={{...primaryBtn, background: signed?"var(--green)":"var(--brand)"}}>
            {signed? <>{Ico.check(12)} Signed 11:42</> : <>{Ico.send(12)} Sign &amp; route</>}
          </button>
        </div>
      </div>

      <div style={{display:"flex",flexDirection:"column",gap:10}}>
        <Card title="SmartPhrases">
          <div style={{display:"flex",flexDirection:"column",gap:4}}>
            {window.HELIX_SMARTPHRASES.map(p=>(
              <div key={p.trigger} style={{padding:"6px 8px",border:"1px solid var(--line)",borderRadius:4}}>
                <div style={{display:"flex",alignItems:"center",gap:6}}>
                  <code style={{background:"var(--brand-tint)",color:"var(--brand)",padding:"1px 6px",borderRadius:3,fontWeight:600,fontSize:11}}>{p.trigger}</code>
                  <button style={{marginLeft:"auto",fontSize:11,color:"var(--brand)",fontWeight:600}}>insert</button>
                </div>
                <div style={{fontSize:11,color:"var(--ink-3)",marginTop:3}}>{p.expansion.slice(0,90)}…</div>
              </div>
            ))}
          </div>
        </Card>
        <Card title="Problem-oriented snippets">
          <Row label=".dmplan — DM follow-up plan"/>
          <Row label=".ckd2 — CKD stage 2 plan"/>
          <Row label=".dctomorrow — Discharge plan"/>
        </Card>
        <Card title="Co-sign / Routing">
          <Row label="Cosign: S. Park, MD" tone="brand"/>
          <Row label="Notify PCP T. Okafor"/>
          <Row label="Charge: 99232 inpt subseq" tone="amber"/>
        </Card>
      </div>
    </div>
  );
};

// ── Ambient AI scribe ─────────────────────────────────────────────────
const AmbientScribe = ({p, anno})=>{
  const [recording, setRecording] = useState(false);
  const [elapsed, setElapsed] = useState(0);
  const [transcript, setTranscript] = useState([
    { speaker:"Clinician", t:"All right, what brings you in today?" },
    { speaker:"Patient", t:"I've had this pain in my right side for two days. It comes in waves." },
    { speaker:"Clinician", t:"Any nausea or fever? Any blood in your urine?" },
    { speaker:"Patient", t:"A little nauseous, no fever. Pee looked pink this morning." }
  ]);
  const [draft, setDraft] = useState(null);
  useEffect(()=>{
    if(!recording) return;
    const id = setInterval(()=>setElapsed(e=>e+1),1000);
    return ()=>clearInterval(id);
  },[recording]);
  const stop = ()=>{
    setRecording(false);
    setDraft({
      hpi:`${p.age}-year-old ${p.sex==="M"?"man":"woman"} presents with 2 days of intermittent right flank pain, colicky in nature, associated with mild nausea and one episode of pink-tinged urine. Denies fever, dysuria. History of nephrolithiasis.`,
      exam:"Tender to palpation R CVA. Abdomen soft, non-distended. No peritoneal signs.",
      assessment:"Recurrent nephrolithiasis suspected — obtain UA and non-contrast CT abd/pelv. Pain control with IV ketorolac.",
      orders:["UA W/ MICRO","CT ABD/PELV W/CONTRAST","KETOROLAC 30 MG IV ×1"],
      icd:["N20.0 Calculus of kidney"],
      cpt:["99284 ED level 4"]
    });
  };
  return (
    <div style={{display:"grid",gridTemplateColumns:"1fr 1fr",gap:12,position:"relative"}}>
      <Anno show={anno} side="right">Ambient capture mics in pocket. AI drafts SOAP + suggests ICD/CPT — clinician edits, signs. Time-to-note drops from 7 min → ~90 s.</Anno>
      <Card title="Live capture" pad={false}>
        <div style={{padding:"24px 18px",display:"flex",flexDirection:"column",alignItems:"center",borderBottom:"1px solid var(--line)",background:"linear-gradient(180deg,#f7f9ff,#fff)"}}>
          <button onClick={()=>recording?stop():setRecording(true)} style={{
            width:84,height:84,borderRadius:99,
            background: recording?"var(--rose)":"var(--brand)",color:"#fff",
            display:"grid",placeItems:"center",
            boxShadow: recording?"0 0 0 6px rgba(160,36,55,.2),0 0 0 14px rgba(160,36,55,.08)":"0 8px 18px rgba(20,59,138,.3)",
            transition:"all .25s"
          }}>
            {recording? Ico.x(28) : Ico.mic(36)}
          </button>
          <div style={{marginTop:14,fontFamily:"'IBM Plex Mono',monospace",fontSize:22,fontWeight:600,letterSpacing:".05em"}}>
            {String(Math.floor(elapsed/60)).padStart(2,"0")}:{String(elapsed%60).padStart(2,"0")}
          </div>
          <div style={{display:"flex",gap:6,marginTop:6}}>
            <Pill tone={recording?"rose":"neutral"}>{recording?"● RECORDING":"Idle"}</Pill>
            <Pill tone="brand">2 speakers</Pill>
            <Pill tone="teal">Encryption: end-to-end</Pill>
          </div>
        </div>
        <div style={{padding:14,maxHeight:330,overflow:"auto",display:"flex",flexDirection:"column",gap:8}}>
          {transcript.map((t,i)=>(
            <div key={i} style={{display:"flex",gap:10}}>
              <Pill tone={t.speaker==="Clinician"?"brand":"teal"}>{t.speaker}</Pill>
              <div style={{flex:1,fontSize:13}}>{t.t}</div>
            </div>
          ))}
          {recording && <div style={{display:"flex",gap:6,alignItems:"center",color:"var(--ink-3)",fontSize:11,fontStyle:"italic"}}>
            <span style={{display:"inline-block",width:6,height:6,borderRadius:99,background:"var(--rose)",animation:"pulse 1s infinite"}}/>
            transcribing…</div>}
        </div>
      </Card>
      <Card title={draft?"AI-drafted note (review & sign)":"AI-drafted note will appear after stop"}>
        {!draft && <div style={{padding:"60px 16px",textAlign:"center",color:"var(--ink-3)",fontSize:12}}>
          {Ico.spark(28)}<div style={{marginTop:10}}>Press the mic to record. Stop when done. The scribe drafts H&amp;P, problem list, orders, billing codes.</div>
        </div>}
        {draft && (
          <div style={{display:"flex",flexDirection:"column",gap:10}}>
            <Section label="HPI">{draft.hpi}</Section>
            <Section label="Exam">{draft.exam}</Section>
            <Section label="Assessment / Plan">{draft.assessment}</Section>
            <Section label="Suggested orders">
              <div style={{display:"flex",flexWrap:"wrap",gap:5}}>
                {draft.orders.map(o=><Pill key={o} tone="brand">+ {o}</Pill>)}
              </div>
            </Section>
            <Section label="Suggested coding">
              <div style={{display:"flex",flexWrap:"wrap",gap:5}}>
                {draft.icd.map(o=><Pill key={o} tone="amber">{o}</Pill>)}
                {draft.cpt.map(o=><Pill key={o} tone="teal">{o}</Pill>)}
              </div>
            </Section>
            <div style={{display:"flex",gap:6,marginTop:6}}>
              <button style={ghostBtn}>Edit</button>
              <button style={ghostBtn}>Discard draft</button>
              <div style={{flex:1}}/>
              <button style={primaryBtn}>{Ico.check(12)} Accept & sign</button>
            </div>
          </div>
        )}
      </Card>
    </div>
  );
};

// ── Vitals Flowsheet ──────────────────────────────────────────────────
const VitalsFlowsheet = ({anno})=>{
  const rows = [
    { k:"Temp °C", key:"t", ref:"36.5–37.5" },
    { k:"HR bpm", key:"hr", ref:"60–100" },
    { k:"RR", key:"rr", ref:"12–20" },
    { k:"BP mmHg", key:"bp", ref:"<140/90" },
    { k:"SpO₂ %", key:"spo2", ref:">94" },
    { k:"Pain (0–10)", key:"pain", ref:"≤3" }
  ];
  return (
    <Card title="Vitals & Flowsheet — last 24 h" pad={false}>
      <Anno show={anno} side="right">Grid layout matches paper flowsheet so nurses can scan a column at a glance. Out-of-range cells flag amber automatically.</Anno>
      <div style={{padding:"6px 12px",borderBottom:"1px solid var(--line)",display:"flex",alignItems:"center",gap:8}}>
        <Pill tone="brand">Q4H schedule</Pill>
        <Pill tone="teal">RN: J. Olufemi</Pill>
        <div style={{flex:1}}/>
        <button style={ghostBtn}>Add column</button>
        <button style={primaryBtn}>{Ico.plus(12)} New entry</button>
      </div>
      <div style={{overflow:"auto"}}>
        <table style={{...tbl, width:"100%",fontFamily:"'IBM Plex Mono',monospace",fontSize:12}}>
          <thead><tr>
            <th style={{width:140}}>Vital</th>
            {window.HELIX_VITALS.map(v=><th key={v.time} style={{textAlign:"center",minWidth:78}}>{v.time}</th>)}
            <th style={{textAlign:"center",background:"var(--brand-tint)",color:"var(--brand)"}}>Now ✏︎</th>
            <th style={{width:80}}>Ref</th>
          </tr></thead>
          <tbody>
            {rows.map(r=>(
              <tr key={r.k}>
                <td style={{fontWeight:600,fontFamily:"Inter"}}>{r.k}</td>
                {window.HELIX_VITALS.map((v,i)=>{
                  const val = v[r.key];
                  let bg="transparent", fg="";
                  if(r.key==="hr" && +val>85){ bg="var(--amber-tint)"; fg="var(--amber)"; }
                  if(r.key==="bp" && val.startsWith("13")){ bg="var(--amber-tint)"; fg="var(--amber)"; }
                  if(r.key==="pain" && +val>=4){ bg="var(--rose-tint)"; fg="var(--rose)"; }
                  return <td key={i} style={{textAlign:"center",background:bg,color:fg||"inherit"}}>{val}</td>;
                })}
                <td style={{textAlign:"center",background:"#fffaf0",borderLeft:"2px solid var(--gold)",borderRight:"2px solid var(--gold)"}}>
                  <input style={{width:50,border:"1px solid var(--line)",borderRadius:3,padding:"2px 4px",textAlign:"center",fontFamily:"inherit"}} placeholder="—"/>
                </td>
                <td style={{color:"var(--ink-3)",fontFamily:"Inter",fontSize:11}}>{r.ref}</td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    </Card>
  );
};

// ── CPOE (Order Entry) ───────────────────────────────────────────────
const CPOE = ({anno})=>{
  const [q, setQ] = useState("");
  const [cart, setCart] = useState([
    { ...window.HELIX_ORDERS[0], priority:"Routine" },
    { ...window.HELIX_ORDERS[7], priority:"STAT" }
  ]);
  const filtered = useMemo(()=>{
    const ql = q.toLowerCase();
    return window.HELIX_ORDERS.filter(o=>!ql || o.code.toLowerCase().includes(ql));
  },[q]);
  return (
    <div style={{display:"grid",gridTemplateColumns:"1fr 1fr",gap:12,position:"relative"}}>
      <Anno show={anno} side="right">Decision support fires before signing: cost, formulary, drug-drug interactions, and indication checks. Order set library on right.</Anno>
      <Card title="Order search & catalog" pad={false}>
        <div style={{padding:"10px 12px",borderBottom:"1px solid var(--line)",display:"flex",gap:8}}>
          <div style={{flex:1,display:"flex",alignItems:"center",gap:6,padding:"6px 8px",border:"1px solid var(--line)",borderRadius:6,background:"#fff"}}>
            {Ico.search(12)} <input value={q} onChange={e=>setQ(e.target.value)} placeholder="Search orders, sets, panels…" style={{flex:1,border:0,outline:"none"}}/>
          </div>
          <select style={selStyle} defaultValue="all"><option value="all">All</option><option>Lab</option><option>Imaging</option><option>Med</option></select>
        </div>
        <div style={{maxHeight:520,overflow:"auto"}}>
          {filtered.map(o=>(
            <div key={o.code} style={{display:"flex",alignItems:"center",padding:"9px 12px",borderBottom:"1px solid var(--line-2)",gap:10}}>
              <Pill tone={o.group==="Lab"?"teal":o.group==="Imaging"?"brand":"amber"}>{o.group}</Pill>
              <div style={{flex:1}}>
                <div style={{fontWeight:600,fontFamily:"'IBM Plex Mono',monospace",fontSize:12}}>{o.code}</div>
                <div style={{fontSize:11,color:"var(--ink-3)"}}>TAT {o.turnaround} · {o.cost}</div>
              </div>
              {o.common && <Pill tone="green">★ Frequent</Pill>}
              <button onClick={()=>setCart([...cart, {...o,priority:"Routine"}])} style={{...ghostBtn,padding:"5px 10px"}}>{Ico.plus(11)} Add</button>
            </div>
          ))}
        </div>
      </Card>
      <div style={{display:"flex",flexDirection:"column",gap:12}}>
        <Card title={`Cart (${cart.length}) — pre-sign review`} pad={false}>
          {cart.length===0 && <div style={{padding:18,color:"var(--ink-3)",fontSize:12}}>Cart empty.</div>}
          {cart.map((o,i)=>(
            <div key={i} style={{display:"flex",alignItems:"center",padding:"10px 12px",borderBottom:"1px solid var(--line-2)",gap:10}}>
              <div style={{flex:1}}>
                <div style={{fontWeight:600,fontFamily:"'IBM Plex Mono',monospace",fontSize:12}}>{o.code}</div>
                <div style={{fontSize:11,color:"var(--ink-3)"}}>{o.group} · {o.cost}</div>
              </div>
              <select value={o.priority} onChange={e=>{
                const nc=[...cart]; nc[i]={...o,priority:e.target.value}; setCart(nc);
              }} style={selStyle}>
                <option>Routine</option><option>ASAP</option><option>STAT</option>
              </select>
              <button onClick={()=>setCart(cart.filter((_,j)=>j!==i))} style={{color:"var(--ink-3)"}}>{Ico.x(13)}</button>
            </div>
          ))}
          <div style={{padding:"10px 12px",display:"flex",gap:8,alignItems:"center",borderTop:"1px solid var(--line)",background:"#fafbff"}}>
            <Pill tone="amber">⚠ Drug-allergy: ketorolac safe (no NSAID allergy)</Pill>
            <div style={{flex:1}}/>
            <button style={ghostBtn}>Save as set</button>
            <button style={primaryBtn} onClick={()=>{
              const pid = (window.HELIX_PATIENTS && window.HELIX_PATIENTS[0]?.mrn) || null;
              cart.forEach(o => window.medsimV3?.placeOrder(pid, {
                category: (o.group || "lab").toLowerCase(),
                code:     o.code,
                label:    o.code,
                rationale:`Signed via CPOE cart (Helix), priority=${o.priority||"Routine"}`,
                priority: (o.priority || "routine").toLowerCase(),
                signed_by:"Helix workspace"
              }));
            }}>{Ico.check(12)} Sign all ({cart.length})</button>
          </div>
        </Card>
        <Card title="Order Sets">
          {[
            { name:"ED Flank Pain Workup", n:5, t:"teal" },
            { name:"DKA Admission Bundle", n:11, t:"brand" },
            { name:"Post-op Day 1 Routine", n:7, t:"green" },
            { name:"Sepsis 1-Hour Bundle", n:9, t:"rose" }
          ].map(s=>(
            <div key={s.name} style={{display:"flex",alignItems:"center",padding:"7px 0",borderBottom:"1px solid var(--line-2)",gap:8}}>
              <Pill tone={s.t}>{s.n}</Pill>
              <div style={{flex:1,fontWeight:500}}>{s.name}</div>
              <button style={{...ghostBtn,padding:"4px 9px"}}>Open</button>
            </div>
          ))}
        </Card>
      </div>
    </div>
  );
};

// ── Results ───────────────────────────────────────────────────────────
const ResultsView = ({anno})=>(
  <Card title="In Basket — Lab Results · BMP" pad={false}>
    <Anno show={anno} side="right">In-basket aggregates abnormal results. Click any row to acknowledge with one keystroke.</Anno>
    <div style={{padding:"8px 12px",borderBottom:"1px solid var(--line)",display:"flex",gap:8,alignItems:"center"}}>
      <Pill tone="brand">Collected 06:42</Pill>
      <Pill tone="teal">Resulted 07:18</Pill>
      <Pill tone="amber">2 abnormal</Pill>
      <div style={{flex:1}}/>
      <button style={ghostBtn}>Trend graph</button>
      <button style={primaryBtn}>{Ico.check(12)} Acknowledge & route</button>
    </div>
    <table style={{...tbl,width:"100%",fontFamily:"'IBM Plex Mono',monospace",fontSize:12}}>
      <thead><tr><th>Analyte</th><th>Value</th><th>Unit</th><th>Reference</th><th>Flag</th><th>Trend (5)</th></tr></thead>
      <tbody>
        {window.HELIX_RESULTS.map(r=>(
          <tr key={r.name} style={{background: r.flag?(r.flag==="L"?"var(--brand-tint)":"var(--amber-tint)"):"transparent"}}>
            <td style={{fontFamily:"Inter",fontWeight:500}}>{r.name}</td>
            <td style={{fontWeight:700}}>{r.value}</td>
            <td>{r.unit}</td>
            <td style={{color:"var(--ink-3)"}}>{r.ref}</td>
            <td>{r.flag && <Pill tone={r.flag==="L"?"brand":"amber"}>{r.flag}</Pill>}</td>
            <td><Spark/></td>
          </tr>
        ))}
      </tbody>
    </table>
  </Card>
);

const Spark = ()=>{
  const pts = [4,6,5,7,8].map((v,i)=>`${i*10},${20-v}`).join(" ");
  return <svg width="60" height="20" viewBox="0 0 50 20"><polyline points={pts} fill="none" stroke="var(--brand)" strokeWidth="1.4"/></svg>;
};

// ── MAR / meds ────────────────────────────────────────────────────────
const MedsMAR = ({p, anno})=>(
  <Card title="MAR — Medication Administration Record" pad={false}>
    <Anno show={anno} side="right">Bedside scan workflow: nurse scans patient wristband + med barcode; this grid stamps administration time + initials.</Anno>
    <table style={{...tbl,width:"100%"}}>
      <thead><tr>
        <th>Medication</th><th>Dose</th><th>Route</th><th>06:00</th><th>10:00</th><th>14:00</th><th>18:00</th><th>22:00</th>
      </tr></thead>
      <tbody>
        {p.meds.map((m,i)=>(
          <tr key={i}>
            <td style={{fontWeight:500}}>{m}</td>
            <td>—</td>
            <td>PO</td>
            {[0,1,2,3,4].map(j=>{
              const given = (i+j)%3===0;
              const due = j===2 && i===1;
              return <td key={j} style={{textAlign:"center",fontFamily:"'IBM Plex Mono',monospace",fontSize:11}}>
                {given && <Pill tone="green" size="sm">✓ JO</Pill>}
                {due && <Pill tone="amber" size="sm">DUE</Pill>}
                {!given && !due && <span style={{color:"var(--ink-3)"}}>—</span>}
              </td>;
            })}
          </tr>
        ))}
      </tbody>
    </table>
    <div style={{padding:"10px 12px",borderTop:"1px solid var(--line)",display:"flex",alignItems:"center",gap:8}}>
      <Pill tone="brand">Bedside scan workflow</Pill>
      <Pill tone="teal">Last scan: 09:58 · Wristband ✓ · Med ✓</Pill>
      <div style={{flex:1}}/>
      <button style={primaryBtn}>{Ico.plus(12)} Document admin</button>
    </div>
  </Card>
);

// =====================================================================
// REGISTRATION (Front desk)
// =====================================================================
const RegistrationDesk = ({anno})=>{
  const [step, setStep] = useState(1);
  const [form, setForm] = useState({
    last:"Tashkenbayev", first:"Daniyar", dob:"1989-11-02", sex:"M",
    addr:"4218 Linden Pkwy, Apt 3B", city:"Worcester", state:"MA", zip:"01609",
    phone:"(508) 555-0142", email:"daniyar.t@example.com",
    payor:"BlueCross PPO", member:"BC-9921-44871-02", group:"GRP-882110",
    relationship:"Self", reason:"Right flank pain — possible kidney stone"
  });
  const set = (k,v)=>setForm({...form,[k]:v});
  return (
    <div style={{flex:1,display:"flex",flexDirection:"column",minHeight:0}}>
      <div style={{background:"#fff",borderBottom:"1px solid var(--line)",padding:"10px 16px",display:"flex",alignItems:"center",gap:14}}>
        <div style={{fontWeight:700,fontSize:14}}>New Encounter — Walk-in Registration</div>
        <Pill tone="amber">Door 4 · 09:11</Pill>
        <div style={{flex:1}}/>
        <button style={ghostBtn}>Save & defer</button>
        <button style={primaryBtn}>{Ico.check(12)} Complete check-in</button>
      </div>
      <div style={{display:"flex",flex:1,minHeight:0}}>
        <Stepper step={step} setStep={setStep}/>
        <div style={{flex:1,overflow:"auto",padding:18,background:"#f4f5f8",position:"relative"}}>
          <Anno show={anno} side="right">3-pane form: stepper rail keeps registrars oriented. Search-by-MRN-or-SSN auto-resolves to existing chart to prevent duplicates.</Anno>
          {step===1 && <RegStepDemo form={form} set={set}/>}
          {step===2 && <RegStepInsurance form={form} set={set}/>}
          {step===3 && <RegStepIntake/>}
          {step===4 && <RegStepConsents/>}
          <div style={{display:"flex",justifyContent:"flex-end",gap:6,marginTop:16}}>
            {step>1 && <button style={ghostBtn} onClick={()=>setStep(step-1)}>← Back</button>}
            {step<4 && <button style={primaryBtn} onClick={()=>setStep(step+1)}>Continue →</button>}
            {step===4 && <button style={primaryBtn}>{Ico.check(12)} Finalize</button>}
          </div>
        </div>
      </div>
    </div>
  );
};

const Stepper = ({step,setStep})=>{
  const items = [
    {n:1,k:"Demographics",ic:Ico.user},
    {n:2,k:"Insurance & guarantor",ic:Ico.shield},
    {n:3,k:"Patient-reported intake",ic:Ico.tablet},
    {n:4,k:"Consents & signatures",ic:Ico.pen}
  ];
  return (
    <aside style={{width:240,background:"#fff",borderRight:"1px solid var(--line)",padding:"14px 0"}}>
      {items.map(i=>{
        const done = step>i.n, active = step===i.n;
        return (
          <button key={i.n} onClick={()=>setStep(i.n)} style={{
            display:"flex",alignItems:"center",gap:10,
            width:"100%",padding:"10px 16px",textAlign:"left",
            background:active?"var(--brand-tint)":"transparent",
            borderLeft:active?"3px solid var(--brand)":"3px solid transparent"
          }}>
            <div style={{
              width:22,height:22,borderRadius:99,
              background: done?"var(--green)":active?"var(--brand)":"#eef1f8",
              color: done||active?"#fff":"var(--ink-2)",
              display:"grid",placeItems:"center",fontSize:11,fontWeight:700
            }}>{done?Ico.check(11):i.n}</div>
            <div>
              <div style={{fontWeight:600,fontSize:12,color:active?"var(--brand)":"var(--ink)"}}>{i.k}</div>
              <div style={{fontSize:11,color:"var(--ink-3)"}}>Step {i.n} of 4</div>
            </div>
          </button>
        );
      })}
      <div style={{marginTop:18,padding:"0 16px"}}>
        <Card title="Live alerts" mini>
          <Row label="No duplicates found in MPI" tone="green"/>
          <Row label="Eligibility check pending" tone="amber"/>
        </Card>
      </div>
    </aside>
  );
};

const Field = ({label,value,onChange,type="text",options,wide,placeholder})=>(
  <label style={{display:"flex",flexDirection:"column",gap:4,gridColumn:wide?"span 2":"span 1"}}>
    <span style={{fontSize:11,fontWeight:600,letterSpacing:".04em",color:"var(--ink-2)"}}>{label}</span>
    {type==="select"
      ? <select value={value} onChange={e=>onChange(e.target.value)} style={inputStyle}>{options.map(o=><option key={o}>{o}</option>)}</select>
      : <input type={type} value={value} onChange={e=>onChange(e.target.value)} placeholder={placeholder} style={inputStyle}/>}
  </label>
);

const RegStepDemo = ({form,set})=>(
  <Card title="Demographics">
    <div style={{display:"grid",gridTemplateColumns:"repeat(3,1fr)",gap:10}}>
      <Field label="Last name" value={form.last} onChange={v=>set("last",v)}/>
      <Field label="First name" value={form.first} onChange={v=>set("first",v)}/>
      <Field label="Middle / suffix" value="" onChange={()=>{}}/>
      <Field label="Date of birth" type="date" value={form.dob} onChange={v=>set("dob",v)}/>
      <Field label="Sex assigned at birth" type="select" options={["M","F","X / Unknown"]} value={form.sex} onChange={v=>set("sex",v)}/>
      <Field label="Gender identity" type="select" options={["Man","Woman","Non-binary","Prefer not to say"]} value="Man" onChange={()=>{}}/>
      <Field label="Address line 1" wide value={form.addr} onChange={v=>set("addr",v)}/>
      <Field label="City" value={form.city} onChange={v=>set("city",v)}/>
      <Field label="State" value={form.state} onChange={v=>set("state",v)}/>
      <Field label="ZIP" value={form.zip} onChange={v=>set("zip",v)}/>
      <Field label="Phone" value={form.phone} onChange={v=>set("phone",v)}/>
      <Field label="Email" value={form.email} onChange={v=>set("email",v)}/>
      <Field label="Preferred language" type="select" options={["English","Spanish","Russian","Mandarin"]} value="Russian" onChange={()=>{}}/>
      <Field label="Race" type="select" options={["Asian","Black/African American","White","Other","Decline"]} value="Asian" onChange={()=>{}}/>
      <Field label="Ethnicity" type="select" options={["Not Hispanic/Latino","Hispanic/Latino","Decline"]} value="Not Hispanic/Latino" onChange={()=>{}}/>
    </div>
    <div style={{marginTop:12,padding:10,background:"var(--brand-tint)",borderRadius:6,fontSize:12,display:"flex",alignItems:"center",gap:8}}>
      {Ico.check(13)} <b>MPI match found:</b> existing chart MRN HLX-9982041 — last visit 2024-08-14. <button style={{marginLeft:"auto",fontWeight:700,color:"var(--brand)"}}>Use existing</button>
    </div>
  </Card>
);

const RegStepInsurance = ({form,set})=>(
  <div style={{display:"grid",gridTemplateColumns:"1fr 1fr",gap:12}}>
    <Card title="Primary insurance">
      <Field label="Payor" value={form.payor} onChange={v=>set("payor",v)} wide/>
      <div style={{display:"grid",gridTemplateColumns:"repeat(2,1fr)",gap:10,marginTop:10}}>
        <Field label="Member ID" value={form.member} onChange={v=>set("member",v)}/>
        <Field label="Group #" value={form.group} onChange={v=>set("group",v)}/>
        <Field label="Subscriber relationship" type="select" options={["Self","Spouse","Parent","Other"]} value={form.relationship} onChange={v=>set("relationship",v)}/>
        <Field label="Effective date" type="date" value="2026-01-01" onChange={()=>{}}/>
      </div>
      <div style={{marginTop:12,padding:10,background:"#fdf3dc",borderRadius:6,fontSize:12,display:"flex",alignItems:"center",gap:8,color:"var(--amber)"}}>
        {Ico.warn(13)} Eligibility check returned: <b style={{color:"#5a3a02"}}>Active</b> · Copay $40 · Deductible met $1,200 / $2,500
      </div>
    </Card>
    <Card title="Guarantor & emergency contact">
      <Field label="Guarantor (responsible party)" value="Self — Tashkenbayev, Daniyar" onChange={()=>{}} wide/>
      <div style={{display:"grid",gridTemplateColumns:"1fr 1fr",gap:10,marginTop:10}}>
        <Field label="Emergency contact" value="Aigerim Tashkenbayeva (sister)" onChange={()=>{}}/>
        <Field label="Phone" value="(508) 555-0177" onChange={()=>{}}/>
      </div>
      <Field label="Reason for visit (chief complaint)" wide value={form.reason} onChange={v=>set("reason",v)}/>
      <div style={{marginTop:8,display:"flex",gap:6,flexWrap:"wrap"}}>
        <Pill tone="brand">Walk-in</Pill>
        <Pill tone="amber">No referral</Pill>
        <Pill tone="teal">First visit since 2024</Pill>
      </div>
    </Card>
  </div>
);

const RegStepIntake = ()=>(
  <Card title="Patient-reported intake (tablet)">
    <div style={{display:"grid",gridTemplateColumns:"320px 1fr",gap:18}}>
      <div style={{
        border:"8px solid #1c1d24",borderRadius:24,background:"#0a234f",
        padding:14,color:"#fff",aspectRatio:"3 / 4.4",position:"relative"
      }}>
        <div style={{display:"flex",alignItems:"center",gap:6,fontSize:11,marginBottom:14}}>
          <HelixLogo size={16}/><b>Helix Patient</b>
        </div>
        <div style={{fontFamily:"'Source Serif 4',serif",fontSize:18,lineHeight:1.3,fontWeight:700}}>
          On a scale of 0–10, how would you rate your pain right now?
        </div>
        <div style={{display:"flex",justifyContent:"space-between",marginTop:14,gap:4}}>
          {[0,1,2,3,4,5,6,7,8,9,10].map(n=>(
            <div key={n} style={{
              flex:1,padding:"8px 0",textAlign:"center",borderRadius:6,fontSize:11,fontWeight:700,
              background: n===7?"#f1c948":"rgba(255,255,255,.12)",
              color: n===7?"#0a234f":"#fff"
            }}>{n}</div>
          ))}
        </div>
        <div style={{marginTop:18,fontSize:11,opacity:.8}}>Question 4 of 14</div>
        <div style={{position:"absolute",bottom:14,left:14,right:14,display:"flex",gap:8}}>
          <button style={{flex:1,padding:"10px 12px",background:"rgba(255,255,255,.12)",borderRadius:6,color:"#fff",fontWeight:600}}>← Back</button>
          <button style={{flex:1,padding:"10px 12px",background:"#f1c948",borderRadius:6,color:"#0a234f",fontWeight:700}}>Continue →</button>
        </div>
      </div>
      <div>
        <div style={{fontSize:12,color:"var(--ink-3)",marginBottom:8}}>14 questions · est. 4 min · auto-syncs to chart on submit</div>
        <table style={{...tbl,width:"100%"}}>
          <thead><tr><th>#</th><th>Question</th><th>Type</th><th>Status</th></tr></thead>
          <tbody>
            <tr><td>1</td><td>Confirm name and DOB</td><td>Verify</td><td><Pill tone="green" size="sm">Done</Pill></td></tr>
            <tr><td>2</td><td>Reason for visit (free text)</td><td>Free text</td><td><Pill tone="green" size="sm">Done</Pill></td></tr>
            <tr><td>3</td><td>Current medications</td><td>Med list</td><td><Pill tone="green" size="sm">Done</Pill></td></tr>
            <tr><td>4</td><td>Pain level</td><td>0–10 scale</td><td><Pill tone="amber" size="sm">In progress</Pill></td></tr>
            <tr><td>5</td><td>PHQ-2 depression screen</td><td>2-item</td><td><Pill tone="neutral" size="sm">Pending</Pill></td></tr>
            <tr><td>6</td><td>Smoking / alcohol use</td><td>Multi</td><td><Pill tone="neutral" size="sm">Pending</Pill></td></tr>
            <tr><td>7</td><td>Allergies</td><td>List</td><td><Pill tone="neutral" size="sm">Pending</Pill></td></tr>
            <tr><td>8–14</td><td>Family / surgical / social hx</td><td>Mixed</td><td><Pill tone="neutral" size="sm">Pending</Pill></td></tr>
          </tbody>
        </table>
      </div>
    </div>
  </Card>
);

const RegStepConsents = ()=>(
  <Card title="Consents & signatures">
    {[
      { name:"General Consent for Treatment", state:"signed" },
      { name:"Notice of Privacy Practices (HIPAA)", state:"signed" },
      { name:"Financial Responsibility", state:"signed" },
      { name:"Release of Information — PCP", state:"pending" },
      { name:"Telehealth Consent", state:"declined" },
      { name:"Photo / video for medical record", state:"pending" }
    ].map(c=>(
      <div key={c.name} style={{display:"flex",alignItems:"center",gap:10,padding:"10px 0",borderBottom:"1px solid var(--line-2)"}}>
        <div style={{width:36,height:36,borderRadius:6,background:"var(--brand-tint)",color:"var(--brand)",display:"grid",placeItems:"center"}}>{Ico.pen(15)}</div>
        <div style={{flex:1,fontWeight:500}}>{c.name}</div>
        {c.state==="signed" && <Pill tone="green">{Ico.check(11)} Signed</Pill>}
        {c.state==="pending" && <Pill tone="amber">Awaiting signature</Pill>}
        {c.state==="declined" && <Pill tone="rose">Declined</Pill>}
        <button style={ghostBtn}>{c.state==="signed"?"View":"Capture"}</button>
      </div>
    ))}
  </Card>
);

// =====================================================================
// ADMIN
// =====================================================================
const AdminConsole = ({anno})=>(
  <div style={{flex:1,overflow:"auto",padding:18,background:"#f4f5f8",position:"relative"}}>
    <Anno show={anno} side="right">Admin operates on policy + reporting, not patient charts. KPI strip on top, drill-down panels below.</Anno>
    <div style={{display:"grid",gridTemplateColumns:"repeat(4,1fr)",gap:10,marginBottom:14}}>
      <Kpi label="Notes pending cosign" value="48" delta="-12 vs yest" tone="brand"/>
      <Kpi label="Avg. note time" value="2:14" delta="-38% w/ ambient" tone="green"/>
      <Kpi label="Charge lag (median)" value="1.6 d" delta="+0.2 d" tone="amber"/>
      <Kpi label="Active sessions" value="1,287" delta="peak today" tone="teal"/>
    </div>
    <div style={{display:"grid",gridTemplateColumns:"1.4fr 1fr",gap:14}}>
      <Card title="Documentation throughput by department">
        <BarChart data={[
          {l:"Internal Med", v:312},{l:"Surgery", v:188},{l:"ED",v:240},{l:"Peds",v:144},
          {l:"OB/GYN",v:96},{l:"Cardiology",v:120},{l:"Onc",v:84}
        ]}/>
      </Card>
      <Card title="Audit log — last 24h" pad={false}>
        <table style={{...tbl,width:"100%",fontSize:11}}>
          <thead><tr><th>Time</th><th>User</th><th>Action</th><th>Object</th></tr></thead>
          <tbody>
            {[
              ["09:42","j.lindqvist@helix","SIGN","Progress note · MRN HLX-4471203"],
              ["09:38","r.ng@helix","ORDER","CT abd/pelv · MRN HLX-9982041"],
              ["09:32","admin.audit","BREAK-GLASS","Read ER chart · MRN HLX-3318824"],
              ["09:18","j.olufemi@helix","CHART","Vitals · MRN HLX-4471203"],
              ["09:11","reg.desk-04","REGISTER","New encounter · MRN HLX-9982041"],
              ["08:55","b.steiner@helix","COSIGN","H&P · MRN HLX-4471203"]
            ].map((r,i)=>(
              <tr key={i}>
                <td style={{fontFamily:"'IBM Plex Mono',monospace"}}>{r[0]}</td>
                <td>{r[1]}</td>
                <td><Pill tone={r[2]==="BREAK-GLASS"?"rose":r[2]==="SIGN"?"green":"brand"} size="sm">{r[2]}</Pill></td>
                <td style={{color:"var(--ink-3)"}}>{r[3]}</td>
              </tr>
            ))}
          </tbody>
        </table>
      </Card>
      <Card title="User & role provisioning">
        <table style={{...tbl,width:"100%"}}>
          <thead><tr><th>User</th><th>Role</th><th>Department</th><th>Last sign-in</th><th>Status</th></tr></thead>
          <tbody>
            {[
              ["J. Lindqvist, MD","Attending","Surgery","9 min ago","Active"],
              ["J. Olufemi, RN","Charge nurse","Med-Surg 5C","32 min ago","Active"],
              ["B. Steiner, MD","Hospitalist","Internal Med","2 h ago","Active"],
              ["R. Ng, MD","ED attending","Emergency","just now","Active"],
              ["A. Korsgaard","Case manager","Care Coord","yesterday","Active"],
              ["temp.locum-04","Locum","Internal Med","never","Provisioned"]
            ].map((r,i)=>(
              <tr key={i}>
                <td style={{fontWeight:500}}>{r[0]}</td>
                <td>{r[1]}</td>
                <td>{r[2]}</td>
                <td style={{color:"var(--ink-3)"}}>{r[3]}</td>
                <td><Pill tone={r[4]==="Active"?"green":"amber"} size="sm">{r[4]}</Pill></td>
              </tr>
            ))}
          </tbody>
        </table>
      </Card>
      <Card title="Build & template governance">
        <Row label="SmartPhrase library: 1,284 phrases" tone="brand"/>
        <Row label="Pending phrase approvals: 7" tone="amber"/>
        <Row label="Order sets: 412 active · 12 retired this month"/>
        <Row label="Custom templates: 89 (Surg 22, IM 31, Peds 14)"/>
        <Row label="Decision-support rules firing today: 3,419"/>
      </Card>
    </div>
  </div>
);

const Kpi = ({label,value,delta,tone})=>(
  <div style={{background:"#fff",border:"1px solid var(--line)",borderRadius:6,padding:"12px 14px"}}>
    <div style={{fontSize:11,color:"var(--ink-3)",fontWeight:600,letterSpacing:".05em",textTransform:"uppercase"}}>{label}</div>
    <div style={{fontSize:26,fontFamily:"'Source Serif 4',serif",fontWeight:700,marginTop:4}}>{value}</div>
    <Pill tone={tone}>{delta}</Pill>
  </div>
);

const BarChart = ({data})=>{
  const max = Math.max(...data.map(d=>d.v));
  return (
    <div style={{display:"flex",alignItems:"flex-end",gap:10,height:180,paddingTop:10}}>
      {data.map(d=>(
        <div key={d.l} style={{flex:1,display:"flex",flexDirection:"column",alignItems:"center",gap:6}}>
          <div style={{fontSize:11,fontFamily:"'IBM Plex Mono',monospace",fontWeight:600,color:"var(--brand)"}}>{d.v}</div>
          <div style={{width:"100%",height: (d.v/max)*140,background:"linear-gradient(180deg,var(--brand),#3a5fbf)",borderRadius:"3px 3px 0 0"}}/>
          <div style={{fontSize:11,color:"var(--ink-2)"}}>{d.l}</div>
        </div>
      ))}
    </div>
  );
};

// =====================================================================
// SHARED PIECES
// =====================================================================
const Card = ({title,children,style,pad=true,mini})=>(
  <section style={{background:"#fff",border:"1px solid var(--line)",borderRadius:6,boxShadow:"var(--shadow)",overflow:"hidden",...style}}>
    <header style={{padding: mini?"6px 10px":"9px 14px",borderBottom:"1px solid var(--line)",display:"flex",alignItems:"center",gap:8,background:"#fafbff"}}>
      <div style={{fontSize: mini?11:12,fontWeight:700,letterSpacing:".04em",color:"var(--ink-2)",textTransform:"uppercase"}}>{title}</div>
    </header>
    <div style={{padding: pad? (mini?"8px 10px":"12px 14px") : 0}}>{children}</div>
  </section>
);
const Row = ({label,code,mono,tone="neutral"})=>(
  <div style={{display:"flex",alignItems:"center",gap:8,padding:"6px 0",borderBottom:"1px dotted var(--line-2)"}}>
    {mono && <span style={{fontSize:10,fontFamily:"'IBM Plex Mono',monospace",color:"var(--ink-3)"}}>{mono}</span>}
    {code && <Pill tone={tone}>{code}</Pill>}
    <span style={{flex:1,fontSize:12}}>{label}</span>
  </div>
);
const Section = ({label,children})=>(
  <div>
    <div style={{fontSize:10,fontWeight:700,letterSpacing:".08em",color:"var(--ink-3)",marginBottom:4,textTransform:"uppercase"}}>{label}</div>
    <div style={{fontSize:13,lineHeight:1.55}}>{children}</div>
  </div>
);

const inputStyle = { padding:"7px 9px",border:"1px solid var(--line)",borderRadius:5,background:"#fff",fontSize:13 };
const selStyle = { ...inputStyle, padding:"5px 8px",fontSize:12 };
const tbl = { borderCollapse:"collapse" };
// table cell defaults via global CSS injected
const styleSheet = document.createElement("style");
styleSheet.textContent = `
table { border-collapse: collapse; }
table th, table td { padding: 7px 12px; text-align:left; font-size:12px; border-bottom:1px solid var(--line-2);}
table th { background:#fafbff; font-weight:700; color:var(--ink-2); font-size:11px; letter-spacing:.04em; text-transform:uppercase; }
@keyframes pulse { 0%,100%{opacity:1} 50%{opacity:.3} }
`;
document.head.appendChild(styleSheet);

const tbBtn = { padding:"4px 8px",borderRadius:4,fontSize:12,fontWeight:600,color:"var(--ink-2)" };
const ghostBtn = { padding:"7px 12px",border:"1px solid var(--line)",borderRadius:5,background:"#fff",fontWeight:600,fontSize:12,display:"inline-flex",alignItems:"center",gap:5 };
const primaryBtn = { padding:"7px 14px",border:0,borderRadius:5,background:"var(--brand)",color:"#fff",fontWeight:700,fontSize:12,display:"inline-flex",alignItems:"center",gap:5 };
const addBtn = { marginTop:6,fontSize:11,color:"var(--brand)",fontWeight:600,display:"inline-flex",alignItems:"center",gap:4 };

Object.assign(window,{
  ClinicianWorkspace, RegistrationDesk, AdminConsole
});
