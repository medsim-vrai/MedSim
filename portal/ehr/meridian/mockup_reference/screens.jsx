/* global React, I, Pill, PatientHeader, Anno, Card, MerLogo, ghostBtn, primaryBtn, slateBtn, inputStyle, selStyle */
const { useState, useEffect, useRef, useMemo } = React;

// CLINICIAN
const ClinicianWorkspace = ({patient, setPatient, anno})=>{
  const NAV = [
    { k:"today", label:"My Day", ic:I.home },
    { k:"chart", label:"Chart", ic:I.list },
    { k:"vitals", label:"Vitals", ic:I.pulse },
    { k:"note", label:"Document", ic:I.pen },
    { k:"voice", label:"Voice + Scribe", ic:I.mic },
    { k:"orders", label:"Orders", ic:I.flask },
    { k:"results", label:"Results", ic:I.spark }
  ];
  const [tab, setTab] = useState("today");
  return (
    <div style={{display:"flex",flexDirection:"column",flex:1,minHeight:0}}>
      {tab!=="today" && <PatientHeader p={patient}/>}
      <div style={{display:"flex",borderBottom:"1px solid var(--line)",background:"#fff",padding:"0 16px",gap:4}}>
        {NAV.map(n=>(
          <button key={n.k} onClick={()=>setTab(n.k)} style={{
            display:"flex",alignItems:"center",gap:6,padding:"12px 14px",
            color: tab===n.k?"var(--sage-2)":"var(--ink-2)",
            borderBottom: tab===n.k?"2px solid var(--sage)":"2px solid transparent",
            fontWeight:600,fontSize:12,marginBottom:-1
          }}>{n.ic(13)}{n.label}</button>
        ))}
      </div>
      <div style={{flex:1,overflow:"auto",background:"var(--bg)",padding:18,position:"relative"}}>
        {tab==="today" && <MyDay setPatient={setPatient} setTab={setTab} anno={anno}/>}
        {tab==="chart" && <ChartTab p={patient} anno={anno}/>}
        {tab==="vitals" && <VitalsTab anno={anno}/>}
        {tab==="note" && <DocumentTab p={patient} anno={anno}/>}
        {tab==="voice" && <VoiceTab p={patient} anno={anno}/>}
        {tab==="orders" && <OrdersTab anno={anno}/>}
        {tab==="results" && <ResultsTab anno={anno}/>}
      </div>
    </div>
  );
};

const MyDay = ({setPatient, setTab, anno})=>(
  <div style={{position:"relative"}}>
    <Anno show={anno} side="right">"My Day" lands clinicians on a calm overview — schedule + inbox + tasks. Less density than enterprise EHRs; tuned for community-hospital workflow.</Anno>
    <div style={{display:"grid",gridTemplateColumns:"1.4fr 1fr 1fr",gap:14,marginBottom:14}}>
      <Card title="Today's Schedule" sub="Tuesday · April 25, 2026" actions={<button style={ghostBtn}>+ Walk-in</button>}>
        <table style={{width:"100%"}}>
          <thead><tr><th style={{width:60}}>Time</th><th>Patient</th><th>Reason</th><th style={{width:60}}>Rm</th><th style={{width:90}}>Status</th></tr></thead>
          <tbody>
            {window.MER_SCHEDULE.map((s,i)=>(
              <tr key={i} onClick={()=>{
                const p=window.MER_PATIENTS.find(p=>s.patient.startsWith(p.name.split(" ")[0])) || window.MER_PATIENTS[1];
                setPatient(p); setTab("chart");
              }} style={{cursor:"pointer"}}>
                <td style={{fontFamily:"'JetBrains Mono',monospace",fontWeight:600,color:"var(--sage-2)"}}>{s.time}</td>
                <td style={{fontWeight:600}}>{s.patient}</td>
                <td style={{color:"var(--ink-2)"}}>{s.reason}</td>
                <td style={{fontFamily:"'JetBrains Mono',monospace",fontSize:11}}>{s.room}</td>
                <td><Pill tone={s.status==="Roomed"?"sage":s.status==="Inpatient"?"slate":s.status==="Waiting"?"gold":"neutral"} size="sm">{s.status}</Pill></td>
              </tr>
            ))}
          </tbody>
        </table>
      </Card>
      <Card title="Inbox" sub="12 items">
        {[
          {t:"Lab",msg:"BNP elevated · Hightower, E.",tone:"terracotta"},
          {t:"Result",msg:"CXR final · Hightower, E.",tone:"sage"},
          {t:"Refill",msg:"Lisinopril · Whitford-Bayle, C.",tone:"slate"},
          {t:"Msg",msg:"Mother re: fever · Acheampong, P.",tone:"gold"},
          {t:"Cosign",msg:"Resident note · Yarbrough, T.",tone:"slate"}
        ].map((it,i)=>(
          <div key={i} style={{display:"flex",alignItems:"center",gap:10,padding:"8px 0",borderBottom:i<4?"1px dotted var(--line-2)":"none"}}>
            <Pill tone={it.tone} size="sm">{it.t}</Pill>
            <span style={{flex:1,fontSize:12}}>{it.msg}</span>
            <button style={{color:"var(--ink-3)",fontSize:11}}>Open</button>
          </div>
        ))}
      </Card>
      <Card title="Tasks" sub="5 due today">
        {[
          {t:"Sign 3 progress notes from yesterday",done:false},
          {t:"Cosign resident H&P · Yarbrough",done:false},
          {t:"Discharge summary · Hightower (target tomorrow)",done:false},
          {t:"Refill request × 2",done:true},
          {t:"Review BNP result · Hightower",done:true}
        ].map((it,i)=>(
          <div key={i} style={{display:"flex",alignItems:"center",gap:10,padding:"8px 0",borderBottom:i<4?"1px dotted var(--line-2)":"none"}}>
            <input type="checkbox" defaultChecked={it.done}/>
            <span style={{flex:1,fontSize:12,textDecoration: it.done?"line-through":"none",color:it.done?"var(--ink-3)":"var(--ink)"}}>{it.t}</span>
          </div>
        ))}
      </Card>
    </div>
    <div style={{display:"grid",gridTemplateColumns:"repeat(4,1fr)",gap:10}}>
      <Kpi label="Notes due" v="3" tone="terracotta"/>
      <Kpi label="Avg note time" v="3:42" tone="sage"/>
      <Kpi label="Patients seen" v="2 / 7"/>
      <Kpi label="Inbox" v="12"/>
    </div>
  </div>
);

const Kpi = ({label,v,tone="slate"})=>(
  <div style={{background:"#fff",border:"1px solid var(--line)",borderRadius:8,padding:"14px 16px"}}>
    <div style={{fontSize:11,color:"var(--ink-3)",fontWeight:600,letterSpacing:".05em",textTransform:"uppercase"}}>{label}</div>
    <div style={{fontFamily:"'Newsreader',serif",fontSize:28,fontWeight:700,marginTop:4,color:"var(--ink)"}}>{v}</div>
    <Pill tone={tone}>last 24h</Pill>
  </div>
);

// Chart (left = problem-oriented, right = quick context)
const ChartTab = ({p, anno})=>(
  <div style={{display:"grid",gridTemplateColumns:"1fr 1fr 1fr",gap:14,position:"relative"}}>
    <Anno show={anno} side="right">Chart panels arranged by what a small-hospital clinician scans first: problems, meds, allergies; then encounters and labs.</Anno>
    <Card title="Problem List">
      {p.problems.map((x,i)=>(
        <div key={i} style={{display:"flex",alignItems:"center",gap:8,padding:"8px 0",borderBottom:"1px dotted var(--line-2)"}}>
          <span style={{width:6,height:6,borderRadius:99,background:"var(--sage)"}}/>
          <span style={{flex:1,fontSize:12}}>{x}</span>
          <Pill tone="slate" size="sm">{["I50.32","I48.0","M19.90"][i]||"—"}</Pill>
        </div>
      ))}
      <button style={{...ghostBtn,marginTop:8,padding:"5px 12px"}}>{I.plus(11)} Add</button>
    </Card>
    <Card title="Active Medications">
      {p.meds.map((m,i)=>(
        <div key={i} style={{padding:"8px 0",borderBottom:"1px dotted var(--line-2)",display:"flex",gap:8}}>
          <Pill tone="sage" size="sm">PO</Pill>
          <span style={{flex:1,fontSize:12}}>{m}</span>
        </div>
      ))}
    </Card>
    <Card title="Allergies">
      {p.allergies.map((a,i)=>(
        <div key={i} style={{padding:"8px 0",borderBottom:"1px dotted var(--line-2)",display:"flex",alignItems:"center",gap:8}}>
          {a==="NKDA"
            ? <Pill tone="sage">{I.check(11)} NKDA</Pill>
            : <><Pill tone="terracotta">⚠</Pill><span style={{flex:1,fontSize:12,fontWeight:500}}>{a}</span></>}
        </div>
      ))}
    </Card>
    <Card title="Recent Encounters" style={{gridColumn:"span 2"}}>
      <table style={{width:"100%"}}>
        <thead><tr><th>Date</th><th>Type</th><th>Provider</th><th>Diagnosis</th></tr></thead>
        <tbody>
          <tr><td>2026-04-22</td><td>Inpt admit</td><td>P. Adeyemi, MD</td><td>CHF exac</td></tr>
          <tr><td>2026-02-08</td><td>Office</td><td>M. Chen, MD</td><td>HFpEF f/u</td></tr>
          <tr><td>2025-12-12</td><td>Office</td><td>M. Chen, MD</td><td>AFib stable</td></tr>
          <tr><td>2025-09-30</td><td>ED</td><td>F. Kovacs, MD</td><td>Falls (no fx)</td></tr>
        </tbody>
      </table>
    </Card>
    <Card title="Care Team">
      <div style={{padding:"6px 0"}}><b>PCP:</b> Dr. M. Chen</div>
      <div style={{padding:"6px 0"}}><b>Attending:</b> Dr. P. Adeyemi</div>
      <div style={{padding:"6px 0"}}><b>Cardiology:</b> Dr. F. Larsson</div>
      <div style={{padding:"6px 0"}}><b>Case Mgr:</b> J. Whitman, RN</div>
    </Card>
  </div>
);

// Vitals
const VitalsTab = ({anno})=>(
  <Card title="Flowsheet · last 24 h" sub="q4h vitals · CHF protocol" pad={false}>
    <Anno show={anno} side="right">Lighter flowsheet: timestamps as columns, parameters as rows. Free-edit "Now" cell for ad-hoc measurement entry.</Anno>
    <div style={{padding:"8px 16px",borderBottom:"1px solid var(--line-2)",display:"flex",gap:8,alignItems:"center"}}>
      <Pill tone="sage">RN: J. Whitman</Pill>
      <Pill tone="slate">CHF protocol</Pill>
      <div style={{flex:1}}/>
      <button style={ghostBtn}>Add column</button>
      <button style={primaryBtn}>{I.plus(12)} New entry</button>
    </div>
    <table style={{width:"100%",fontFamily:"'JetBrains Mono',monospace",fontSize:12}}>
      <thead><tr><th style={{width:140}}>Parameter</th>
        {window.MER_VITALS.map(v=><th key={v.time} style={{textAlign:"center"}}>{v.time}</th>)}
        <th style={{textAlign:"center",background:"var(--sage-tint)",color:"var(--sage-2)"}}>Now ✏︎</th>
      </tr></thead>
      <tbody>
        {[
          {k:"Temp °C",f:"t"},{k:"HR",f:"hr"},{k:"RR",f:"rr"},
          {k:"BP",f:"bp"},{k:"SpO₂",f:"spo2"},{k:"Daily wt kg",f:"weight"}
        ].map(r=>(
          <tr key={r.k}>
            <td style={{fontFamily:"'Public Sans',sans-serif",fontWeight:600}}>{r.k}</td>
            {window.MER_VITALS.map((v,i)=>(
              <td key={i} style={{textAlign:"center",color:v[r.f]?"inherit":"var(--ink-3)"}}>{v[r.f]||"—"}</td>
            ))}
            <td style={{textAlign:"center",background:"#f4f8f4",borderLeft:"2px solid var(--sage)",borderRight:"2px solid var(--sage)"}}>
              <input style={{width:60,border:"1px solid var(--line)",borderRadius:4,padding:"3px 5px",textAlign:"center"}} placeholder="—"/>
            </td>
          </tr>
        ))}
      </tbody>
    </table>
  </Card>
);

// Document
const DocumentTab = ({p, anno})=>{
  const [tpl, setTpl] = useState("GEN-FU");
  const [text, setText] = useState(`Subjective:
${p.name.split(" ")[0]} returns for follow-up. Reports feeling better since admission. No chest pain, no orthopnea, less leg swelling.

Objective:
Vitals stable. Lungs clearer at bases. JVD improved. Trace pretibial edema.

Assessment:
1. CHF exacerbation — improving. Continue diuresis.
2. AFib — rate-controlled, anticoagulated.

Plan:
- Continue IV furosemide × 1 day, transition to PO.
- Daily weight, strict I&Os.
- Cardiology following.
- Anticipate discharge tomorrow with home health.
`);
  return (
    <div style={{display:"grid",gridTemplateColumns:"260px 1fr 280px",gap:14,position:"relative"}}>
      <Anno show={anno} side="right" top={50}>Template-led documentation. Pick a template (left), edit free text (center), see auto-coding + cosign (right). Lighter than enterprise smart-phrase systems but covers most community workflows.</Anno>
      <Card title="Templates" pad={false}>
        {window.MER_TEMPLATES.map(t=>(
          <button key={t.code} onClick={()=>setTpl(t.code)} style={{
            display:"block",width:"100%",textAlign:"left",padding:"10px 14px",
            background: tpl===t.code?"var(--sage-tint)":"transparent",
            borderLeft: tpl===t.code?"3px solid var(--sage)":"3px solid transparent",
            borderBottom:"1px solid var(--line-2)"
          }}>
            <div style={{fontFamily:"'JetBrains Mono',monospace",fontSize:10,color:"var(--sage-2)",fontWeight:700}}>{t.code}</div>
            <div style={{fontWeight:600,fontSize:12,marginTop:1}}>{t.name}</div>
            <div style={{fontSize:11,color:"var(--ink-3)"}}>{t.lines} lines</div>
          </button>
        ))}
      </Card>
      <Card title="Progress Note · SOAP" sub="Auto-saving every 15s" actions={<Pill tone="sage">Saved 4s ago</Pill>} pad={false}>
        <div style={{padding:"8px 14px",borderBottom:"1px solid var(--line-2)",display:"flex",gap:6,alignItems:"center"}}>
          <select style={selStyle} defaultValue="prog"><option value="prog">Progress note</option><option>H&amp;P</option><option>Discharge summary</option></select>
          <select style={selStyle} defaultValue="im"><option value="im">Internal Med</option><option>Family Med</option><option>Cards</option></select>
          <div style={{flex:1}}/>
          <Pill tone="slate">Author: Dr. P. Adeyemi</Pill>
        </div>
        <textarea value={text} onChange={e=>setText(e.target.value)} style={{
          width:"100%",border:0,outline:"none",padding:"16px 18px",
          fontFamily:"'JetBrains Mono',monospace",fontSize:13,lineHeight:1.7,
          minHeight:430,resize:"vertical"
        }}/>
        <div style={{padding:"10px 14px",borderTop:"1px solid var(--line-2)",display:"flex",gap:8,alignItems:"center"}}>
          <Pill tone="slate">{text.length} chars</Pill>
          <Pill tone="slate">{text.split(/\s+/).filter(Boolean).length} words</Pill>
          <div style={{flex:1}}/>
          <button style={ghostBtn} onClick={()=>{
            window.medsimV3?.event("note.save","notes", p.mrn, {
              note_id:"meridian-soap-1", note_type:"Progress note · SOAP",
              template:tpl, body:text, signed:false
            });
          }}>Save draft</button>
          <button style={primaryBtn} onClick={()=>{
            window.medsimV3?.event("note.save","notes", p.mrn, {
              note_id:"meridian-soap-1", note_type:"Progress note · SOAP",
              template:tpl, body:text, signed:true
            });
          }}>{I.send(12)} Sign &amp; route</button>
        </div>
      </Card>
      <div style={{display:"flex",flexDirection:"column",gap:12}}>
        <Card title="Auto-coding">
          <div style={{padding:"6px 0",borderBottom:"1px dotted var(--line-2)"}}><Pill tone="sage" size="sm">ICD</Pill> <b>I50.32</b> Chronic diastolic CHF</div>
          <div style={{padding:"6px 0",borderBottom:"1px dotted var(--line-2)"}}><Pill tone="sage" size="sm">ICD</Pill> <b>I48.0</b> Paroxysmal AFib</div>
          <div style={{padding:"6px 0"}}><Pill tone="slate" size="sm">CPT</Pill> <b>99232</b> Subseq inpt level 2</div>
        </Card>
        <Card title="Co-sign / Routing">
          <div style={{padding:"4px 0"}}>Cosign: not required (attending)</div>
          <div style={{padding:"4px 0"}}>Notify PCP: Dr. M. Chen via Direct</div>
          <div style={{padding:"4px 0"}}>Charge capture: queued</div>
        </Card>
        <Card title="Quick text">
          {["Discussed dietary restrictions","Patient agrees with plan","Pending labs reviewed"].map(q=>(
            <div key={q} style={{padding:"5px 0",fontSize:12,color:"var(--sage-2)",cursor:"pointer"}}>+ {q}</div>
          ))}
        </Card>
      </div>
    </div>
  );
};

// Voice
const VoiceTab = ({p, anno})=>{
  const [recording, setRecording] = useState(false);
  const [elapsed, setElapsed] = useState(0);
  const [draft, setDraft] = useState(null);
  useEffect(()=>{ if(!recording) return; const id=setInterval(()=>setElapsed(e=>e+1),1000); return ()=>clearInterval(id); },[recording]);
  return (
    <div style={{display:"grid",gridTemplateColumns:"1fr 1fr",gap:14,position:"relative"}}>
      <Anno show={anno} side="right">Two modes: classic dictation (foot pedal compatible) or ambient AI scribe. Community providers value the choice — many still prefer dictation.</Anno>
      <Card title="Voice capture" pad={false}>
        <div style={{padding:"6px 14px",borderBottom:"1px solid var(--line-2)",display:"flex",gap:6}}>
          <Pill tone="sage">Mode: Ambient scribe</Pill>
          <Pill tone="slate">Switch → Dictation</Pill>
        </div>
        <div style={{padding:"30px 18px",textAlign:"center",background:"linear-gradient(180deg,#fafbf8,#fff)"}}>
          <button onClick={()=>{
            if(recording){
              setRecording(false);
              setDraft({
                hpi:`${p.age}-year-old ${p.sex==="F"?"woman":"man"} POD #3 with CHF exacerbation, improving on diuresis. Reports feeling significantly better; no orthopnea, less edema.`,
                exam:"Lungs clearer at bases. Trace pretibial edema. JVD improved.",
                ap:"CHF exacerbation — continue current diuresis, target euvolemia. AFib rate-controlled. Plan discharge tomorrow w/ VNA.",
                meds:["Furosemide 40 mg PO BID","Metoprolol 25 mg PO BID","Apixaban 5 mg PO BID"]
              });
            } else setRecording(true);
          }} style={{
            width:90,height:90,borderRadius:99,background:recording?"var(--terracotta)":"var(--sage)",color:"#fff",
            display:"grid",placeItems:"center",
            boxShadow:recording?"0 0 0 7px rgba(184,92,60,.2),0 0 0 16px rgba(184,92,60,.08)":"0 8px 20px rgba(74,117,86,.3)"
          }}>{recording? I.x(30) : I.mic(36)}</button>
          <div style={{marginTop:14,fontFamily:"'JetBrains Mono',monospace",fontSize:24,fontWeight:600}}>
            {String(Math.floor(elapsed/60)).padStart(2,"0")}:{String(elapsed%60).padStart(2,"0")}
          </div>
          <div style={{display:"flex",justifyContent:"center",gap:6,marginTop:8}}>
            <Pill tone={recording?"terracotta":"neutral"}>{recording?"● recording":"Idle"}</Pill>
            <Pill tone="sage">2 speakers detected</Pill>
          </div>
        </div>
        <div style={{padding:14,fontSize:12,maxHeight:240,overflow:"auto"}}>
          {[
            ["Provider","How are you feeling today, Mrs. Hightower?"],
            ["Patient","Much better. The swelling's gone down."],
            ["Provider","Any shortness of breath at night?"],
            ["Patient","No, slept flat for the first time."],
            ["Provider","Great. We'll plan to get you home tomorrow."]
          ].map((t,i)=>(
            <div key={i} style={{display:"flex",gap:10,padding:"4px 0"}}>
              <Pill tone={t[0]==="Provider"?"sage":"slate"} size="sm">{t[0]}</Pill>
              <span style={{flex:1}}>{t[1]}</span>
            </div>
          ))}
        </div>
      </Card>
      <Card title={draft?"Draft note (review)":"Draft will appear after stop"}>
        {!draft && <div style={{padding:"50px 16px",textAlign:"center",color:"var(--ink-3)",fontSize:12}}>{I.spark(28)}<div style={{marginTop:10}}>Press the mic. The scribe drafts SOAP + reconciles meds.</div></div>}
        {draft && (
          <div style={{display:"flex",flexDirection:"column",gap:14}}>
            {[["Subjective",draft.hpi],["Objective",draft.exam],["Assessment & Plan",draft.ap]].map(([k,v])=>(
              <div key={k}>
                <div style={{fontFamily:"'Newsreader',serif",fontSize:13,fontWeight:700,color:"var(--sage-2)",marginBottom:4}}>{k}</div>
                <div style={{fontSize:13,lineHeight:1.55}}>{v}</div>
              </div>
            ))}
            <div>
              <div style={{fontFamily:"'Newsreader',serif",fontSize:13,fontWeight:700,color:"var(--sage-2)",marginBottom:4}}>Reconciled medications</div>
              {draft.meds.map(m=><Pill key={m} tone="slate" style={{margin:"2px 4px 2px 0"}}>{m}</Pill>)}
            </div>
            <div style={{display:"flex",gap:8,marginTop:6}}>
              <button style={ghostBtn}>Edit</button>
              <div style={{flex:1}}/>
              <button style={primaryBtn}>{I.check(12)} Push to note &amp; sign</button>
            </div>
          </div>
        )}
      </Card>
    </div>
  );
};

// Orders
const OrdersTab = ({anno})=>{
  const [cart, setCart] = useState([{...window.MER_ORDERS[0],pri:"Routine"},{...window.MER_ORDERS[1],pri:"Routine"}]);
  return (
    <div style={{display:"grid",gridTemplateColumns:"1fr 1fr",gap:14,position:"relative"}}>
      <Anno show={anno} side="right">Lightweight order entry. Bottom alerts surface drug-allergy + cost-of-care info. Order-set library on right.</Anno>
      <Card title="Order Entry" pad={false}>
        <div style={{padding:"10px 14px",borderBottom:"1px solid var(--line-2)",display:"flex",alignItems:"center",gap:8}}>
          <div style={{flex:1,display:"flex",alignItems:"center",gap:6,padding:"6px 10px",border:"1px solid var(--line)",borderRadius:99,background:"#fff"}}>{I.search(13)}<input placeholder="Search orders…" style={{flex:1,border:0,outline:"none"}}/></div>
        </div>
        {window.MER_ORDERS.map(o=>(
          <div key={o.code} style={{display:"flex",alignItems:"center",padding:"10px 14px",borderBottom:"1px solid var(--line-2)",gap:10}}>
            <Pill tone={o.group==="Lab"?"sage":o.group==="Imaging"?"slate":o.group==="Med"?"terracotta":"gold"} size="sm">{o.group}</Pill>
            <div style={{flex:1,fontWeight:500,fontSize:12}}>{o.code}</div>
            {o.common && <Pill tone="sage" size="sm">★</Pill>}
            <button onClick={()=>setCart([...cart,{...o,pri:"Routine"}])} style={{...ghostBtn,padding:"4px 10px"}}>{I.plus(11)} Add</button>
          </div>
        ))}
      </Card>
      <div style={{display:"flex",flexDirection:"column",gap:14}}>
        <Card title={`Cart (${cart.length}) — review & sign`} pad={false}>
          {cart.map((o,i)=>(
            <div key={i} style={{display:"flex",alignItems:"center",padding:"10px 14px",borderBottom:"1px solid var(--line-2)",gap:10}}>
              <Pill tone="sage" size="sm">{o.group}</Pill>
              <div style={{flex:1,fontWeight:500,fontSize:12}}>{o.code}</div>
              <select value={o.pri} onChange={e=>{const c=[...cart]; c[i]={...o,pri:e.target.value}; setCart(c);}} style={selStyle}><option>Routine</option><option>STAT</option></select>
              <button onClick={()=>setCart(cart.filter((_,j)=>j!==i))} style={{color:"var(--ink-3)"}}>{I.x(13)}</button>
            </div>
          ))}
          <div style={{padding:"12px 14px",borderTop:"1px solid var(--line-2)",display:"flex",alignItems:"center",gap:8,background:"#fafbf8"}}>
            <Pill tone="sage">No allergy interactions</Pill>
            <Pill tone="gold">Est. visit cost: $148</Pill>
            <div style={{flex:1}}/>
            <button style={primaryBtn} onClick={()=>{
              const pid = (window.MER_PATIENTS && window.MER_PATIENTS[0]?.mrn) || null;
              cart.forEach(o => window.medsimV3?.placeOrder(pid, {
                category: (o.group || "lab").toLowerCase(),
                code:     o.code,
                label:    o.code,
                rationale:`Signed via Meridian Order Entry, priority=${o.pri||"Routine"}`,
                priority: (o.pri || "routine").toLowerCase(),
                signed_by:"Meridian Orders"
              }));
            }}>{I.check(12)} Sign all</button>
          </div>
        </Card>
        <Card title="Order Sets">
          {[
            ["CHF Admission",10,"sage"],
            ["AFib RVR Bundle",7,"slate"],
            ["URI / Strep workup (Peds)",4,"terracotta"],
            ["Discharge Med Rec",6,"gold"]
          ].map(([n,c,t])=>(
            <div key={n} style={{display:"flex",alignItems:"center",padding:"7px 0",borderBottom:"1px dotted var(--line-2)",gap:8}}>
              <Pill tone={t} size="sm">{c}</Pill>
              <span style={{flex:1,fontWeight:500,fontSize:12}}>{n}</span>
              <button style={{...ghostBtn,padding:"4px 10px"}}>Open</button>
            </div>
          ))}
        </Card>
      </div>
    </div>
  );
};

// Results
const ResultsTab = ({anno})=>(
  <Card title="Results · Inbox" pad={false}>
    <Anno show={anno} side="right">Single results inbox per provider. Acknowledge with one click; auto-route abnormal to message thread.</Anno>
    <table style={{width:"100%"}}>
      <thead><tr><th>Time</th><th>Patient</th><th>Result</th><th>Value</th><th>Flag</th><th></th></tr></thead>
      <tbody>
        <tr style={{background:"var(--terracotta-tint)"}}><td>09:14</td><td>Hightower, E.</td><td>BNP</td><td><b>842 pg/mL</b></td><td><Pill tone="terracotta" size="sm">High</Pill></td><td><button style={primaryBtn}>{I.check(12)} Ack</button></td></tr>
        <tr><td>09:02</td><td>Hightower, E.</td><td>BMP — K</td><td>3.8</td><td><Pill tone="sage" size="sm">Normal</Pill></td><td><button style={ghostBtn}>Ack</button></td></tr>
        <tr><td>08:48</td><td>Whitford-Bayle, C.</td><td>Lipid panel</td><td>LDL 142</td><td><Pill tone="gold" size="sm">Borderline</Pill></td><td><button style={ghostBtn}>Ack</button></td></tr>
        <tr><td>08:30</td><td>Acheampong, P.</td><td>Rapid Strep</td><td>Negative</td><td><Pill tone="sage" size="sm">Normal</Pill></td><td><button style={ghostBtn}>Ack</button></td></tr>
        <tr><td>08:22</td><td>Hightower, E.</td><td>CXR PA/LAT</td><td>Mild pulm congestion, improved</td><td><Pill tone="sage" size="sm">Stable</Pill></td><td><button style={ghostBtn}>Ack</button></td></tr>
      </tbody>
    </table>
  </Card>
);

// REGISTRATION
const Registration = ({anno})=>{
  const [tab, setTab] = useState("checkin");
  return (
    <div style={{flex:1,display:"flex",flexDirection:"column",minHeight:0}}>
      <div style={{background:"#fff",borderBottom:"1px solid var(--line)",padding:"0 18px",display:"flex",gap:4}}>
        {[["checkin","Front Desk Check-In"],["new","New Patient"],["intake","Patient Self-Intake"]].map(([k,l])=>(
          <button key={k} onClick={()=>setTab(k)} style={{
            padding:"14px 16px",fontWeight:600,fontSize:12,
            color: tab===k?"var(--sage-2)":"var(--ink-2)",
            borderBottom: tab===k?"2px solid var(--sage)":"2px solid transparent",
            marginBottom:-1
          }}>{l}</button>
        ))}
      </div>
      <div style={{flex:1,overflow:"auto",background:"var(--bg)",padding:18,position:"relative"}}>
        {tab==="checkin" && <CheckIn anno={anno}/>}
        {tab==="new" && <NewPatient anno={anno}/>}
        {tab==="intake" && <SelfIntake anno={anno}/>}
      </div>
    </div>
  );
};

const CheckIn = ({anno})=>(
  <div style={{position:"relative"}}>
    <Anno show={anno} side="right">Front-desk view: today's roster + one-click check-in + copay collection. Most fields pre-fill from prior visit.</Anno>
    <div style={{display:"grid",gridTemplateColumns:"repeat(4,1fr)",gap:10,marginBottom:14}}>
      <Kpi label="Scheduled" v="42"/>
      <Kpi label="Checked-in" v="18" tone="sage"/>
      <Kpi label="Waiting" v="4" tone="gold"/>
      <Kpi label="No-show" v="1" tone="terracotta"/>
    </div>
    <Card title="Today's roster · Office 1" actions={<button style={primaryBtn}>{I.plus(12)} Walk-in</button>} pad={false}>
      <table style={{width:"100%"}}>
        <thead><tr><th>Time</th><th>Patient</th><th>DOB</th><th>Visit</th><th>Insurance</th><th>Copay</th><th>Status</th><th></th></tr></thead>
        <tbody>
          {[
            ["08:00","Whitford-Bayle, C.","1985-07-22","HTN follow-up","BlueCross PPO","$30","Roomed","sage"],
            ["08:30","Acheampong, P.","2019-10-14","Fever / cough","Medicaid MCO","—","Waiting","gold"],
            ["09:30","Yarbrough, T.","1962-05-11","Annual physical","Medicare","—","Scheduled","slate"],
            ["10:00","Borisov, K.","1971-09-14","DM 3-mo check","Aetna HMO","$40","Scheduled","slate"],
            ["10:30","O'Sullivan, F.","1990-03-05","Sinus pain","Self-pay","TBD","Scheduled","slate"],
            ["11:00","Lefebvre, A.","1955-12-21","Med refill","Medicare","—","Scheduled","slate"]
          ].map((r,i)=>(
            <tr key={i}>
              <td style={{fontFamily:"'JetBrains Mono',monospace",fontWeight:600,color:"var(--sage-2)"}}>{r[0]}</td>
              <td style={{fontWeight:600}}>{r[1]}</td>
              <td>{r[2]}</td>
              <td>{r[3]}</td>
              <td style={{color:"var(--ink-2)"}}>{r[4]}</td>
              <td>{r[5]}</td>
              <td><Pill tone={r[7]} size="sm">{r[6]}</Pill></td>
              <td>{r[6]==="Scheduled"
                ? <button style={primaryBtn}>{I.check(12)} Check in</button>
                : <button style={ghostBtn}>Open</button>}</td>
            </tr>
          ))}
        </tbody>
      </table>
    </Card>
  </div>
);

const NewPatient = ({anno})=>(
  <div style={{display:"grid",gridTemplateColumns:"1fr 1fr",gap:14,position:"relative"}}>
    <Anno show={anno} side="right">Single-page new-patient registration — community hospitals favor a one-screen form over multi-step wizards.</Anno>
    <Card title="Demographics & contact">
      <div style={{display:"grid",gridTemplateColumns:"repeat(2,1fr)",gap:10}}>
        <F label="Last name"/><F label="First name"/>
        <F label="DOB" type="date"/><F label="Sex" v="—"/>
        <F label="Phone"/><F label="Email"/>
        <F label="Address" wide/>
        <F label="City"/><F label="State"/>
        <F label="ZIP"/><F label="Pref. language" v="English"/>
        <F label="Race"/><F label="Ethnicity"/>
      </div>
      <div style={{marginTop:12,padding:10,background:"var(--gold-tint)",borderRadius:6,fontSize:12,display:"flex",alignItems:"center",gap:8,color:"var(--gold)"}}>
        {I.warn(13)} Run MPI duplicate check before saving — community hospital chart consolidation policy.
      </div>
    </Card>
    <Card title="Insurance & guarantor">
      <F label="Primary payor" wide/>
      <div style={{display:"grid",gridTemplateColumns:"repeat(2,1fr)",gap:10,marginTop:10}}>
        <F label="Member ID"/><F label="Group #"/>
        <F label="Subscriber" v="Self"/><F label="Effective date" type="date"/>
        <F label="Guarantor" v="Self" wide/>
        <F label="Emergency contact"/><F label="Emergency phone"/>
      </div>
      <div style={{marginTop:12,padding:10,background:"var(--sage-tint)",borderRadius:6,fontSize:12,display:"flex",alignItems:"center",gap:8,color:"var(--sage-2)"}}>
        {I.check(13)} Eligibility check (270/271): runs automatically on save
      </div>
    </Card>
    <div style={{gridColumn:"span 2",display:"flex",justifyContent:"flex-end",gap:8}}>
      <button style={ghostBtn}>Save draft</button>
      <button style={primaryBtn}>{I.check(12)} Create chart</button>
    </div>
  </div>
);

const F = ({label,v="",type="text",wide})=>(
  <label style={{display:"flex",flexDirection:"column",gap:4,gridColumn:wide?"span 2":"span 1"}}>
    <span style={{fontSize:11,fontWeight:600,letterSpacing:".04em",color:"var(--sage-2)",textTransform:"uppercase"}}>{label}</span>
    <input type={type} defaultValue={v} style={inputStyle}/>
  </label>
);

const SelfIntake = ({anno})=>(
  <div style={{display:"grid",gridTemplateColumns:"320px 1fr",gap:18,position:"relative"}}>
    <Anno show={anno} side="right">Email-link intake. Patient completes from any device pre-visit; data syncs to chart with one registrar review.</Anno>
    <div style={{
      border:"10px solid #1c1d24",borderRadius:32,background:"#fff",
      aspectRatio:"3/6",overflow:"hidden",position:"relative",
      boxShadow:"0 18px 40px rgba(31,42,38,.18)"
    }}>
      <div style={{padding:"14px 16px",background:"var(--sage)",color:"#fff",display:"flex",alignItems:"center",gap:8}}>
        <MerLogo size={18}/><div style={{fontFamily:"'Newsreader',serif",fontWeight:700,fontSize:14}}>Meridian Patient</div>
      </div>
      <div style={{padding:18}}>
        <div style={{fontSize:11,fontWeight:600,color:"var(--sage)",letterSpacing:".06em",textTransform:"uppercase"}}>Step 3 of 6</div>
        <div style={{fontFamily:"'Newsreader',serif",fontWeight:700,fontSize:18,marginTop:6,lineHeight:1.3}}>What's the reason for your visit today?</div>
        <textarea defaultValue="Cough and runny nose for 4 days, low fever last night." style={{width:"100%",marginTop:14,padding:10,border:"1px solid var(--line)",borderRadius:6,fontSize:13,minHeight:90}}/>
        <div style={{marginTop:14,fontSize:11,fontWeight:600,color:"var(--sage)",letterSpacing:".06em",textTransform:"uppercase"}}>Symptoms</div>
        <div style={{display:"flex",flexWrap:"wrap",gap:6,marginTop:6}}>
          {["Cough","Fever","Runny nose","Sore throat","Ear pain","Tiredness"].map((s,i)=>(
            <span key={s} style={{padding:"6px 10px",borderRadius:99,fontSize:11,fontWeight:600,
              background: i<4?"var(--sage-tint)":"var(--bg)",
              color: i<4?"var(--sage-2)":"var(--ink-2)",
              border: i<4?"1px solid var(--sage)":"1px solid var(--line)"
            }}>{s}</span>
          ))}
        </div>
      </div>
      <div style={{position:"absolute",bottom:18,left:18,right:18,display:"flex",gap:8}}>
        <button style={{flex:1,padding:"12px",background:"var(--bg)",borderRadius:99,fontWeight:600,fontSize:13,border:"1px solid var(--line)"}}>Back</button>
        <button style={{flex:1,padding:"12px",background:"var(--sage)",color:"#fff",borderRadius:99,fontWeight:700,fontSize:13}}>Continue</button>
      </div>
    </div>
    <Card title="Self-intake dashboard" sub="Today's pre-visits">
      <div style={{display:"grid",gridTemplateColumns:"repeat(3,1fr)",gap:8,marginBottom:14}}>
        <Kpi label="Sent" v="98"/><Kpi label="Done" v="71" tone="sage"/><Kpi label="Avg time" v="3:48" tone="slate"/>
      </div>
      <table style={{width:"100%"}}>
        <thead><tr><th>Patient</th><th>Sent</th><th>Progress</th><th>Status</th></tr></thead>
        <tbody>
          <tr><td>Acheampong, P. (mom)</td><td>2h ago</td><td><Bar v={50}/></td><td><Pill tone="gold" size="sm">In progress</Pill></td></tr>
          <tr><td>Whitford-Bayle, C.</td><td>1d ago</td><td><Bar v={100}/></td><td><Pill tone="sage" size="sm">Complete</Pill></td></tr>
          <tr><td>Yarbrough, T.</td><td>3d ago</td><td><Bar v={0}/></td><td><Pill tone="terracotta" size="sm">Not started</Pill></td></tr>
          <tr><td>Borisov, K.</td><td>2d ago</td><td><Bar v={80}/></td><td><Pill tone="gold" size="sm">In progress</Pill></td></tr>
        </tbody>
      </table>
    </Card>
  </div>
);

const Bar = ({v})=>(
  <div style={{width:120,background:"var(--bg)",borderRadius:99,height:8,overflow:"hidden",border:"1px solid var(--line)"}}>
    <div style={{width:`${v}%`,height:"100%",background: v===100?"var(--sage)":v>50?"var(--sage)":"var(--gold)"}}/>
  </div>
);

// ADMIN
const AdminConsole = ({anno})=>(
  <div style={{flex:1,overflow:"auto",padding:18,background:"var(--bg)",position:"relative"}}>
    <Anno show={anno} side="right">Admin console for a community-hospital footprint: simpler scope than enterprise — focuses on operational health and template/template governance.</Anno>
    <div style={{display:"grid",gridTemplateColumns:"repeat(4,1fr)",gap:10,marginBottom:14}}>
      <Kpi label="Active users" v="284" tone="sage"/>
      <Kpi label="Avg note time" v="3:42" tone="sage"/>
      <Kpi label="Charge lag" v="0.9 d" tone="sage"/>
      <Kpi label="Open tickets" v="6" tone="gold"/>
    </div>
    <div style={{display:"grid",gridTemplateColumns:"1.4fr 1fr",gap:14}}>
      <Card title="Audit log · last 24 h" pad={false}>
        <table style={{width:"100%",fontSize:11}}>
          <thead><tr><th>Time</th><th>User</th><th>Action</th><th>Subject</th></tr></thead>
          <tbody>
            {[
              ["09:46","p.adeyemi@meridian","SIGN","Progress note · MER-2026-44218"],
              ["09:42","j.whitman@meridian","DOC","Vitals · MER-2026-44218"],
              ["09:38","admin.compliance","BREAK-GLASS","Read · MER-2026-09817"],
              ["09:32","reg.desk","REGISTER","New patient"],
              ["09:18","m.chen@meridian","SIGN","H&P · MER-2026-09817"],
              ["08:55","r.singh@meridian","ORDER","Rapid Strep"]
            ].map((r,i)=>(
              <tr key={i}>
                <td style={{fontFamily:"'JetBrains Mono',monospace"}}>{r[0]}</td>
                <td>{r[1]}</td>
                <td><Pill tone={r[2]==="BREAK-GLASS"?"crimson":r[2]==="SIGN"?"sage":"slate"} size="sm">{r[2]}</Pill></td>
                <td style={{color:"var(--ink-2)"}}>{r[3]}</td>
              </tr>
            ))}
          </tbody>
        </table>
      </Card>
      <Card title="Build governance">
        <div style={{padding:"6px 0",borderBottom:"1px dotted var(--line-2)"}}>Templates: <b>108</b> active</div>
        <div style={{padding:"6px 0",borderBottom:"1px dotted var(--line-2)"}}>Order sets: <b>62</b></div>
        <div style={{padding:"6px 0",borderBottom:"1px dotted var(--line-2)"}}>Pending approvals: <b>3</b></div>
        <div style={{padding:"6px 0",borderBottom:"1px dotted var(--line-2)"}}>HL7 interfaces: <b>9</b> healthy</div>
        <div style={{padding:"6px 0"}}>Decision rules: <b>184</b></div>
      </Card>
      <Card title="User & role provisioning" style={{gridColumn:"span 2"}}>
        <table style={{width:"100%"}}>
          <thead><tr><th>User</th><th>Role</th><th>Department</th><th>Last login</th><th>Status</th></tr></thead>
          <tbody>
            {[
              ["Dr. P. Adeyemi","Hospitalist","Internal Med","12 min ago","Active"],
              ["Dr. M. Chen","PCP","Family Med","1 h ago","Active"],
              ["Dr. R. Singh","Pediatrician","Peds","just now","Active"],
              ["J. Whitman, RN","Charge nurse","Med-Surg","30 min ago","Active"],
              ["Reg-Desk-01","Front desk","Outpt","just now","Active"],
              ["temp.locum-22","Locum","ED","never","Provisioned"]
            ].map((r,i)=>(
              <tr key={i}>
                <td style={{fontWeight:500}}>{r[0]}</td><td>{r[1]}</td><td>{r[2]}</td><td style={{color:"var(--ink-3)"}}>{r[3]}</td>
                <td><Pill tone={r[4]==="Active"?"sage":"gold"} size="sm">{r[4]}</Pill></td>
              </tr>
            ))}
          </tbody>
        </table>
      </Card>
      <Card title="Throughput by service" style={{gridColumn:"span 2"}}>
        <Bars data={[{l:"Family Med",v:148},{l:"Internal Med",v:96},{l:"Peds",v:72},{l:"ED",v:188},{l:"Med-Surg",v:120},{l:"OB",v:48}]}/>
      </Card>
    </div>
  </div>
);

const Bars = ({data})=>{
  const max = Math.max(...data.map(d=>d.v));
  return (
    <div style={{display:"flex",alignItems:"flex-end",gap:14,height:160}}>
      {data.map(d=>(
        <div key={d.l} style={{flex:1,display:"flex",flexDirection:"column",alignItems:"center",gap:6}}>
          <div style={{fontSize:11,fontFamily:"'JetBrains Mono',monospace",fontWeight:700,color:"var(--sage-2)"}}>{d.v}</div>
          <div style={{width:"100%",height:(d.v/max)*120,background:"linear-gradient(180deg,var(--sage),var(--sage-2))",borderRadius:"6px 6px 0 0"}}/>
          <div style={{fontSize:11,color:"var(--ink-2)"}}>{d.l}</div>
        </div>
      ))}
    </div>
  );
};

Object.assign(window,{ ClinicianWorkspace, Registration, AdminConsole });
