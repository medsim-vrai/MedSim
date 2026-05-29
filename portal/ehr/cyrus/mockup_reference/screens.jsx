/* global React, I, Pill, PatientBanner, Anno, Card, CyrusLogo, ghostBtn, primaryBtn, navyBtn, inputStyle, selStyle */
const { useState, useEffect, useRef, useMemo } = React;

// =====================================================================
// CLINICIAN
// =====================================================================
const ClinicianWorkspace = ({patient, setPatient, anno})=>{
  const NAV = [
    { k:"worklist", label:"Worklist", ic:I.list },
    { k:"summary", label:"Patient Summary", ic:I.squares },
    { k:"flowsheet", label:"iView Flowsheet", ic:I.pulse },
    { k:"powernote", label:"PowerNote", ic:I.pen },
    { k:"voice", label:"Ambient Capture", ic:I.mic },
    { k:"orders", label:"PowerOrders", ic:I.flask },
    { k:"results", label:"Results Review", ic:I.spark }
  ];
  const [tab, setTab] = useState("flowsheet");
  return (
    <div style={{display:"flex",flex:1,minHeight:0}}>
      <SideRail nav={NAV} value={tab} onChange={setTab}/>
      <div style={{flex:1,display:"flex",flexDirection:"column",minWidth:0}}>
        {tab!=="worklist" && <PatientBanner p={patient}/>}
        <div style={{flex:1,overflow:"auto",background:"var(--bg)",padding:14,position:"relative"}}>
          {tab==="worklist" && <Worklist setPatient={setPatient} setTab={setTab} anno={anno}/>}
          {tab==="summary" && <PatientSummary p={patient} anno={anno}/>}
          {tab==="flowsheet" && <IViewFlowsheet anno={anno}/>}
          {tab==="powernote" && <PowerNote p={patient} anno={anno}/>}
          {tab==="voice" && <AmbientCapture p={patient} anno={anno}/>}
          {tab==="orders" && <PowerOrders anno={anno}/>}
          {tab==="results" && <ResultsReview anno={anno}/>}
        </div>
      </div>
    </div>
  );
};

const SideRail = ({nav,value,onChange})=>(
  <aside style={{width:64,background:"#08263e",borderRight:"1px solid #06182a",display:"flex",flexDirection:"column",alignItems:"center",padding:"10px 0",gap:4}}>
    {nav.map(n=>(
      <button key={n.k} onClick={()=>onChange(n.k)} title={n.label} style={{
        width:48,padding:"10px 0",borderRadius:3,
        display:"flex",flexDirection:"column",alignItems:"center",gap:4,
        background: value===n.k?"#1c5b8a":"transparent",
        color: value===n.k?"#fff":"#9bb0c1",
        borderLeft: value===n.k?"3px solid #1e9c95":"3px solid transparent",
        marginLeft: value===n.k?-3:0
      }}>
        {n.ic(16)}
        <span style={{fontSize:9,fontWeight:600,letterSpacing:".02em",textAlign:"center",lineHeight:1.1}}>{n.label.split(" ")[0]}</span>
      </button>
    ))}
  </aside>
);

// ── Worklist (multi-patient unit dashboard) ───────────────────────────
const Worklist = ({setPatient, setTab, anno})=>{
  const [filter, setFilter] = useState("all");
  const items = window.CYRUS_WORKLIST;
  return (
    <div style={{position:"relative"}}>
      <Anno show={anno} side="right">Multi-patient worklist groups by unit. Acuity column drives sort; flag column highlights interventions due in the next 60 min.</Anno>
      <div style={{display:"grid",gridTemplateColumns:"repeat(4,1fr)",gap:10,marginBottom:14}}>
        <Kpi label="Census" value="148" delta="+6"/>
        <Kpi label="Acuity ≥ 4" value="32" delta="+3" tone="orange"/>
        <Kpi label="Tasks due 60m" value="91" delta="" tone="teal"/>
        <Kpi label="Pending cosign" value="14" delta="-2" tone="navy"/>
      </div>
      <Card title="Unit Worklist · ICU-3 · MS-6 · L&D-2" actions={
        <>
          {["all","high","med"].map(f=>(
            <button key={f} onClick={()=>setFilter(f)} style={{...ghostBtn,padding:"3px 8px",background:filter===f?"var(--navy-tint)":"#fff",color:filter===f?"var(--navy)":"var(--ink-2)"}}>{f}</button>
          ))}
        </>
      } pad={false}>
        <table style={{width:"100%"}}>
          <thead><tr><th>Acuity</th><th>Unit / Bed</th><th>Patient</th><th>LOS</th><th>Status</th><th>Next task</th><th>Action</th></tr></thead>
          <tbody>
            {items.filter(it=>filter==="all"||it.flag===filter).map((it,i)=>(
              <tr key={i} style={{cursor:"pointer"}} onClick={()=>{
                const p = window.CYRUS_PATIENTS.find(p=>it.patient.startsWith(p.name.split(" ")[0])) || window.CYRUS_PATIENTS[0];
                setPatient(p); setTab("summary");
              }}>
                <td><AcuityChip n={it.acuity}/></td>
                <td style={{fontFamily:"'JetBrains Mono',monospace",fontWeight:600}}>{it.unit} · {it.bed}</td>
                <td style={{fontWeight:600}}>{it.patient}</td>
                <td>{it.los}</td>
                <td>{it.flag==="high"&&<Pill tone="red" size="sm">{it.status}</Pill>}{it.flag==="med"&&<Pill tone="orange" size="sm">{it.status}</Pill>}{!it.flag&&<Pill tone="neutral" size="sm">{it.status}</Pill>}</td>
                <td style={{color:"var(--ink-2)"}}>{it.task}</td>
                <td><button style={{...ghostBtn,padding:"3px 9px"}}>Open chart →</button></td>
              </tr>
            ))}
          </tbody>
        </table>
      </Card>
    </div>
  );
};

const AcuityChip = ({n})=>{
  const colors = ["#dde","#cdd9e2","#cfe5e3","#fbe6d3","#f0c8b0","#f5dbdd"];
  return <div style={{
    width:24,height:24,borderRadius:3,background:colors[n]||"#eee",
    color: n>=4?"var(--red)":"var(--navy)",
    fontWeight:700,display:"grid",placeItems:"center",fontSize:12,
    fontFamily:"'JetBrains Mono',monospace",border:"1px solid rgba(0,0,0,.05)"
  }}>{n}</div>;
};

const Kpi = ({label,value,delta,tone="navy"})=>(
  <div style={{background:"#fff",border:"1px solid var(--line)",borderLeft:`3px solid var(--${tone==="navy"?"navy":tone==="orange"?"orange":"teal"})`,borderRadius:3,padding:"12px 14px"}}>
    <div style={{fontSize:11,color:"var(--ink-3)",fontWeight:600,letterSpacing:".05em",textTransform:"uppercase"}}>{label}</div>
    <div style={{fontSize:24,fontWeight:700,marginTop:4,fontFamily:"'JetBrains Mono',monospace"}}>{value}</div>
    {delta && <Pill tone={tone}>{delta}</Pill>}
  </div>
);

// ── Patient Summary (modular MPage) ────────────────────────────────────
const PatientSummary = ({p, anno})=>(
  <div style={{display:"grid",gridTemplateColumns:"repeat(12,1fr)",gap:10,position:"relative"}}>
    <Anno show={anno} side="right">Modular MPage — every component lives in its own card; admins can rearrange per role/specialty.</Anno>
    <Card title="Problems" style={{gridColumn:"span 4"}}>
      {p.problems.map((x,i)=><Pill key={i} tone="navy" size="md" style={{margin:"2px 4px 2px 0"}}>{x}</Pill>).reduce((acc,el,i)=>(acc.concat(el)),[])}
      <div style={{marginTop:8}}><button style={{...ghostBtn,padding:"4px 10px"}}>{I.plus(11)} Add problem</button></div>
    </Card>
    <Card title="Active Medications" style={{gridColumn:"span 4"}}>
      {p.meds.map((m,i)=>(
        <div key={i} style={{padding:"6px 0",borderBottom:"1px dotted var(--line-2)",display:"flex",gap:8}}>
          <Pill tone="teal" size="sm">{i===0?"IV":i===1||i===2?"IV":"PO"}</Pill>
          <span style={{flex:1,fontSize:12}}>{m}</span>
        </div>
      ))}
    </Card>
    <Card title="Allergies" style={{gridColumn:"span 4"}}>
      {p.allergies.map((a,i)=>(
        <div key={i} style={{display:"flex",alignItems:"center",gap:8,padding:"6px 0",borderBottom:"1px dotted var(--line-2)"}}>
          {I.warn(13)} <span style={{fontWeight:500,fontSize:12}}>{a}</span>
        </div>
      ))}
    </Card>
    <Card title="Care Team" style={{gridColumn:"span 4"}}>
      <Row label={`Attending: ${p.attending}`} tone="navy"/>
      {p.care_team.map(c=><Row key={c} label={c}/>)}
    </Card>
    <Card title="Vitals (last 24h)" style={{gridColumn:"span 4"}}>
      <table style={{width:"100%",fontFamily:"'JetBrains Mono',monospace",fontSize:11}}>
        <thead><tr><th>Time</th><th>BP</th><th>HR</th><th>SpO₂</th><th>T</th></tr></thead>
        <tbody>
          {[["02:00","108/62","94","94","36.7"],["06:00","102/58","98","94","37.1"],["10:00","98/56","104","93","37.4"],["14:00","92/52","112","92","37.6"],["18:00","86/48","118","91","38.1"],["Now","82/46","124","90","38.4"]].map((r,i)=>(
            <tr key={i} style={{background:i===5?"var(--red-tint)":"transparent"}}><td>{r[0]}</td><td>{r[1]}</td><td>{r[2]}</td><td>{r[3]}</td><td>{r[4]}</td></tr>
          ))}
        </tbody>
      </table>
    </Card>
    <Card title="Active Issues / Alerts" style={{gridColumn:"span 4"}}>
      <Row label="qSOFA score: 3 — sepsis criteria met" tone="red"/>
      <Row label="Lactate trending up: 3.6" tone="red"/>
      <Row label="MAP &lt; 65 — pressor titration" tone="orange"/>
      <Row label="UOP declining (22 ml/hr)" tone="orange"/>
    </Card>
  </div>
);

const Row = ({label,tone})=>(
  <div style={{display:"flex",alignItems:"center",gap:8,padding:"6px 0",borderBottom:"1px dotted var(--line-2)"}}>
    {tone && <span style={{width:6,height:6,borderRadius:99,background:`var(--${tone==="navy"?"navy":tone})`}}/>}
    <span style={{flex:1,fontSize:12}}>{label}</span>
  </div>
);

// ── iView Flowsheet (Cerner's signature column-based grid) ────────────
const IViewFlowsheet = ({anno})=>{
  const [groups, setGroups] = useState(window.CYRUS_FLOWSHEET_GROUPS);
  const toggle = (i)=>{
    const g = [...groups]; g[i] = {...g[i], expanded: !g[i].expanded}; setGroups(g);
  };
  const times = ["02:00","06:00","10:00","14:00","18:00","Now"];
  return (
    <Card title="iView Flowsheet — ICU q1h documentation" pad={false}>
      <Anno show={anno} side="right">Charting is column-down: nurse picks a time column then tab/enter through every cell. Group headers collapse — power users keep only what's relevant.</Anno>
      <div style={{padding:"6px 12px",borderBottom:"1px solid var(--line)",display:"flex",alignItems:"center",gap:8,background:"#f6f9fc"}}>
        <Pill tone="navy">Adult Critical Care band</Pill>
        <Pill tone="teal">RN: M. Petrosian</Pill>
        <div style={{flex:1}}/>
        <button style={ghostBtn}>Insert column</button>
        <button style={navyBtn}>{I.check(12)} Sign group</button>
      </div>
      <div style={{overflow:"auto"}}>
        <table style={{width:"100%",fontFamily:"'JetBrains Mono',monospace",fontSize:12}}>
          <thead><tr>
            <th style={{width:200}}>Parameter</th>
            {times.map(t=><th key={t} style={{textAlign:"center",minWidth:78}}>{t}</th>)}
            <th style={{textAlign:"center",background:"var(--teal-tint)",color:"var(--teal)",minWidth:88}}>Now ✏︎</th>
            <th style={{width:90}}>Ref</th>
          </tr></thead>
          <tbody>
            {groups.map((g,gi)=>(
              <React.Fragment key={g.name}>
                <tr style={{background:"#0b3454",color:"#fff",cursor:"pointer"}} onClick={()=>toggle(gi)}>
                  <td colSpan={9} style={{fontWeight:700,fontFamily:"'DM Sans',sans-serif",fontSize:11,letterSpacing:".06em",textTransform:"uppercase",color:"#fff",padding:"6px 12px"}}>
                    <span style={{display:"inline-block",transform:g.expanded?"rotate(0)":"rotate(-90deg)",transition:"transform .15s"}}>{I.caret(11)}</span> {g.name}
                  </td>
                </tr>
                {g.expanded && g.rows.map(r=>(
                  <tr key={r.k}>
                    <td style={{fontFamily:"'DM Sans',sans-serif",fontWeight:500}}>{r.k}</td>
                    {r.values.map((v,j)=>{
                      let bg="transparent",fg="";
                      const lastTwo = j>=4;
                      if(r.k==="HR" && +v>110){bg="var(--red-tint)";fg="var(--red)";}
                      if(r.k==="HR" && +v>=100 && +v<=110){bg="var(--orange-tint)";fg="var(--orange)";}
                      if(r.k==="SpO₂" && +v<92){bg="var(--orange-tint)";fg="var(--orange)";}
                      if(r.k==="Lactate" && parseFloat(v)>2){bg="var(--red-tint)";fg="var(--red)";}
                      if(r.k.startsWith("Norepi") && parseFloat(v)>=0.08){bg="var(--orange-tint)";fg="var(--orange)";}
                      if(r.k==="Urine" && +v<30){bg="var(--orange-tint)";fg="var(--orange)";}
                      return <td key={j} style={{textAlign:"center",background:bg,color:fg||"inherit"}}>{v}</td>;
                    })}
                    <td style={{textAlign:"center",background:"#eef9f8",borderLeft:"2px solid var(--teal)",borderRight:"2px solid var(--teal)"}}>
                      <input style={{width:60,border:"1px solid var(--line)",borderRadius:3,padding:"2px 4px",textAlign:"center",fontFamily:"inherit"}} placeholder="—"/>
                    </td>
                    <td style={{color:"var(--ink-3)",fontFamily:"'DM Sans',sans-serif",fontSize:11}}>{r.ref}</td>
                  </tr>
                ))}
              </React.Fragment>
            ))}
          </tbody>
        </table>
      </div>
    </Card>
  );
};

// ── PowerNote (structured/discrete documentation) ─────────────────────
const PowerNote = ({p, anno})=>{
  const [section, setSection] = useState("hpi");
  const [hpi, setHpi] = useState({
    onset:"6 hours ago", quality:"sharp / pleuritic", severity:"7/10",
    location:"R lower chest, radiates to back", duration:"intermittent, worsening",
    timing:"continuous past 2h", context:"started at home, no trauma", modifying:"worse with deep breath"
  });
  return (
    <div style={{display:"grid",gridTemplateColumns:"220px 1fr 280px",gap:12,position:"relative"}}>
      <Anno show={anno} side="right" top={40}>PowerNote captures discrete data — every checkbox/dropdown becomes a coded element, not free text. Trades flexibility for queryability.</Anno>
      <div style={{display:"flex",flexDirection:"column",gap:6}}>
        {[
          {k:"hpi",l:"History of Present Illness", done:true},
          {k:"ros",l:"Review of Systems", done:false},
          {k:"pmh",l:"Past Medical History", done:true},
          {k:"meds",l:"Medications", done:true},
          {k:"exam",l:"Physical Exam", done:false},
          {k:"assess",l:"Assessment", done:false},
          {k:"plan",l:"Plan", done:false},
          {k:"billing",l:"Billing & Codes", done:false}
        ].map(s=>(
          <button key={s.k} onClick={()=>setSection(s.k)} style={{
            display:"flex",alignItems:"center",gap:8,padding:"9px 12px",
            background: section===s.k?"#fff":"transparent",
            border: section===s.k?"1px solid var(--navy)":"1px solid var(--line)",
            borderLeft: section===s.k?"3px solid var(--teal)":"3px solid var(--line)",
            borderRadius:3,textAlign:"left",fontWeight:600,fontSize:12
          }}>
            <div style={{
              width:18,height:18,borderRadius:99,
              background: s.done?"var(--green)":"#eaeef3",
              color:s.done?"#fff":"var(--ink-3)",
              display:"grid",placeItems:"center",fontSize:10,fontWeight:700
            }}>{s.done?I.check(10):"·"}</div>
            <span style={{flex:1,color: section===s.k?"var(--navy)":"var(--ink-2)"}}>{s.l}</span>
          </button>
        ))}
      </div>
      <div style={{background:"#fff",border:"1px solid var(--line)",borderRadius:4,padding:14,minHeight:540}}>
        {section==="hpi" && (
          <div>
            <div style={{display:"flex",alignItems:"center",gap:8,marginBottom:14,paddingBottom:10,borderBottom:"1px solid var(--line)"}}>
              <h3 style={{margin:0,fontSize:14,fontWeight:700}}>History of Present Illness — Chest Pain</h3>
              <Pill tone="teal">Template: Chest Pain v3.1</Pill>
              <div style={{flex:1}}/>
              <Pill tone="green">Auto-saved 4s ago</Pill>
            </div>
            <div style={{display:"grid",gridTemplateColumns:"repeat(2,1fr)",gap:14}}>
              {Object.entries({
                onset:"Onset",quality:"Quality",severity:"Severity (0–10)",
                location:"Location",duration:"Duration",timing:"Timing",
                context:"Context",modifying:"Modifying factors"
              }).map(([k,l])=>(
                <label key={k} style={{display:"flex",flexDirection:"column",gap:4}}>
                  <span style={{fontSize:11,fontWeight:600,letterSpacing:".04em",color:"var(--navy)",textTransform:"uppercase"}}>{l}</span>
                  <input value={hpi[k]} onChange={e=>setHpi({...hpi,[k]:e.target.value})} style={inputStyle}/>
                </label>
              ))}
            </div>
            <div style={{marginTop:18}}>
              <div style={{fontSize:11,fontWeight:600,letterSpacing:".04em",color:"var(--navy)",textTransform:"uppercase",marginBottom:6}}>Associated Symptoms (multi-select)</div>
              <div style={{display:"flex",flexWrap:"wrap",gap:6}}>
                {["Dyspnea","Nausea","Diaphoresis","Palpitations","Cough","Hemoptysis","Fever","Syncope","Leg swelling"].map((sx,i)=>(
                  <label key={sx} style={{display:"flex",alignItems:"center",gap:5,padding:"5px 10px",border:"1px solid var(--line)",borderRadius:3,fontSize:12,background:i<3?"var(--navy-tint)":"#fff",color:i<3?"var(--navy)":"var(--ink-2)",fontWeight:500}}>
                    <input type="checkbox" defaultChecked={i<3}/> {sx}
                  </label>
                ))}
              </div>
            </div>
            <div style={{marginTop:18}}>
              <div style={{fontSize:11,fontWeight:600,letterSpacing:".04em",color:"var(--navy)",textTransform:"uppercase",marginBottom:6}}>Free-text addendum</div>
              <textarea defaultValue="Patient reports symptom onset while walking up stairs at home. No prior similar episodes. Took aspirin 325 mg en route." style={{...inputStyle,width:"100%",minHeight:80,resize:"vertical",fontFamily:"inherit"}}/>
            </div>
            <div style={{display:"flex",gap:8,marginTop:18}}>
              <button style={ghostBtn}>← Previous</button>
              <button style={ghostBtn} onClick={()=>{
                const pid = (window.CYRUS_PATIENTS && window.CYRUS_PATIENTS[0]?.mrn) || null;
                const body = `HPI · ${hpi.onset||"—"} onset, ${hpi.quality||"—"} quality, severity ${hpi.severity||"—"}, located ${hpi.location||"—"}, duration ${hpi.duration||"—"}`;
                window.medsimV3?.event("note.save","notes", pid, {
                  note_id:"cyrus-powernote-1", note_type:"PowerNote · HPI",
                  template:"Chest Pain v3.1", body, signed:false
                });
              }}>Save & exit</button>
              <div style={{flex:1}}/>
              <button style={primaryBtn}>Continue: ROS →</button>
            </div>
          </div>
        )}
        {section!=="hpi" && (
          <div style={{padding:"60px 18px",textAlign:"center",color:"var(--ink-3)"}}>
            <div style={{fontSize:12}}>Section: <b>{section.toUpperCase()}</b></div>
            <div style={{marginTop:6,fontSize:11}}>Click a different section in the rail to navigate. The HPI section above demonstrates the discrete-data form pattern.</div>
          </div>
        )}
      </div>
      <div style={{display:"flex",flexDirection:"column",gap:10}}>
        <Card title="Auto-coded">
          <Row label="ICD: R07.9 Chest pain, unspecified" tone="navy"/>
          <Row label="ICD: R06.02 Shortness of breath" tone="navy"/>
          <Row label="CPT: 99223 Initial inpt level 3" tone="teal"/>
        </Card>
        <Card title="Decision support">
          <Row label="HEART score: 5 (moderate risk)" tone="orange"/>
          <Row label="Consider troponin q3h × 2" tone="teal"/>
          <Row label="Order set: Chest Pain Workup" tone="teal"/>
        </Card>
        <Card title="Co-sign chain">
          <Row label="Cosign: Dr. K. Almeida"/>
          <Row label="Notify: PCP via Direct"/>
        </Card>
      </div>
    </div>
  );
};

// ── Ambient Capture ────────────────────────────────────────────────────
const AmbientCapture = ({p, anno})=>{
  const [recording, setRecording] = useState(false);
  const [elapsed, setElapsed] = useState(0);
  const [draft, setDraft] = useState(null);
  useEffect(()=>{ if(!recording) return; const id=setInterval(()=>setElapsed(e=>e+1),1000); return ()=>clearInterval(id); },[recording]);
  return (
    <div style={{display:"grid",gridTemplateColumns:"1fr 1fr",gap:12,position:"relative"}}>
      <Anno show={anno} side="right">Capture is encrypted on-device, transcribed cloud-side, then mapped to discrete PowerNote fields — preserving Cerner's structured-data philosophy.</Anno>
      <Card title="Mobile bedside companion" pad={false}>
        <div style={{padding:"22px 18px",background:"linear-gradient(180deg,#f6f9fc,#fff)",display:"flex",flexDirection:"column",alignItems:"center",borderBottom:"1px solid var(--line)"}}>
          <button onClick={()=>{ if(recording){setRecording(false); setDraft({hpi:`70-year-old woman in septic shock from pulmonary source. ICU day 4. Worsening hemodynamics with rising lactate (3.6) and pressor escalation.`,exam:"Toxic-appearing. Bibasilar crackles. Mottled extremities.",ap:"Septic shock, escalating norepi. Repeat lactate, broaden coverage to vanco/pip-tazo, consider stress-dose steroids.",fields:[["Onset","3 days ago"],["Source","Pulmonary"],["qSOFA","3"],["MAP","58 mmHg"]]});} else setRecording(true); }} style={{
            width:84,height:84,borderRadius:99,background:recording?"var(--red)":"var(--teal)",color:"#fff",
            display:"grid",placeItems:"center",
            boxShadow:recording?"0 0 0 6px rgba(177,48,58,.2),0 0 0 14px rgba(177,48,58,.08)":"0 8px 18px rgba(30,156,149,.3)"
          }}>
            {recording? I.x(28) : I.mic(34)}
          </button>
          <div style={{marginTop:14,fontFamily:"'JetBrains Mono',monospace",fontSize:22,fontWeight:600}}>
            {String(Math.floor(elapsed/60)).padStart(2,"0")}:{String(elapsed%60).padStart(2,"0")}
          </div>
          <div style={{display:"flex",gap:6,marginTop:6}}>
            <Pill tone={recording?"red":"neutral"}>{recording?"● RECORDING":"Idle"}</Pill>
            <Pill tone="teal">3 speakers · room mic</Pill>
            <Pill tone="navy">HIPAA E2E</Pill>
          </div>
        </div>
        <div style={{padding:14,fontSize:12}}>
          <div style={{display:"flex",gap:8,alignItems:"center",marginBottom:8}}>
            <Pill tone="navy">Live transcript</Pill>
            <span style={{color:"var(--ink-3)",fontSize:11}}>diarized · 96% confidence</span>
          </div>
          <div style={{display:"flex",flexDirection:"column",gap:8,maxHeight:240,overflow:"auto"}}>
            {[
              ["Attending","Mrs. Wojciechowska, how are you feeling this morning?"],
              ["Patient","Tired… can't catch my breath."],
              ["Attending","Lactate's still going up. Let's bump norepi to 0.10 and restart vanco trough."],
              ["RN","Want me to recheck a CBC with the next lactate?"],
              ["Attending","Yes please, q4h until trending down."]
            ].map((t,i)=>(
              <div key={i} style={{display:"flex",gap:10}}>
                <Pill tone={t[0]==="Attending"?"navy":t[0]==="RN"?"teal":"orange"} size="sm">{t[0]}</Pill>
                <div style={{flex:1}}>{t[1]}</div>
              </div>
            ))}
          </div>
        </div>
      </Card>
      <Card title={draft?"AI draft → PowerNote field mapping":"AI draft will appear after stop"}>
        {!draft && <div style={{padding:"60px 16px",textAlign:"center",color:"var(--ink-3)",fontSize:12}}>{I.spark(28)}<div style={{marginTop:10}}>Press the mic to record. After stopping, every spoken value is mapped to a coded PowerNote field.</div></div>}
        {draft && (
          <div style={{display:"flex",flexDirection:"column",gap:12}}>
            <div>
              <div style={{fontSize:10,fontWeight:700,letterSpacing:".08em",color:"var(--navy)",textTransform:"uppercase",marginBottom:4}}>HPI</div>
              <div style={{fontSize:13,lineHeight:1.5}}>{draft.hpi}</div>
            </div>
            <div>
              <div style={{fontSize:10,fontWeight:700,letterSpacing:".08em",color:"var(--navy)",textTransform:"uppercase",marginBottom:6}}>Mapped to discrete fields</div>
              <table style={{width:"100%"}}>
                <tbody>
                  {draft.fields.map(([k,v])=>(
                    <tr key={k}><td style={{color:"var(--ink-3)",width:120}}>{k}</td><td style={{fontWeight:600}}>{v}</td><td style={{textAlign:"right"}}><Pill tone="teal" size="sm">match 96%</Pill></td></tr>
                  ))}
                </tbody>
              </table>
            </div>
            <div>
              <div style={{fontSize:10,fontWeight:700,letterSpacing:".08em",color:"var(--navy)",textTransform:"uppercase",marginBottom:6}}>Exam</div>
              <div style={{fontSize:13,lineHeight:1.5}}>{draft.exam}</div>
            </div>
            <div>
              <div style={{fontSize:10,fontWeight:700,letterSpacing:".08em",color:"var(--navy)",textTransform:"uppercase",marginBottom:6}}>A/P</div>
              <div style={{fontSize:13,lineHeight:1.5}}>{draft.ap}</div>
            </div>
            <div style={{display:"flex",gap:6}}>
              <button style={ghostBtn}>Edit</button>
              <div style={{flex:1}}/>
              <button style={primaryBtn}>{I.check(12)} Push to PowerNote &amp; sign</button>
            </div>
          </div>
        )}
      </Card>
    </div>
  );
};

// ── PowerOrders (CPOE) ─────────────────────────────────────────────────
const PowerOrders = ({anno})=>{
  const [active, setActive] = useState(0);
  const set = window.CYRUS_ORDERSETS[active];
  const [selected, setSelected] = useState(new Set([0,1,2,4,5,6,7,8]));
  const items = [
    "Lactate q2h × 4", "CBC w/ diff STAT", "BMP STAT",
    "Blood culture × 2 (different sites) — before abx",
    "Vancomycin 25 mg/kg IV ×1 then weight-based maintenance",
    "Piperacillin-tazo 4.5 g IV q8h",
    "30 ml/kg LR bolus over 1h",
    "Vasopressor: Norepinephrine — start 0.05 mcg/kg/min, titrate to MAP > 65",
    "Procalcitonin baseline"
  ];
  const toggle = (i)=>{ const n=new Set(selected); n.has(i)?n.delete(i):n.add(i); setSelected(n); };
  return (
    <div style={{display:"grid",gridTemplateColumns:"260px 1fr",gap:12,position:"relative"}}>
      <Anno show={anno} side="right">PowerPlans bundle the entire workflow — orders + nursing tasks + documentation triggers — into one signature, enforcing protocol adherence.</Anno>
      <Card title="PowerPlans (Order Sets)" pad={false}>
        {window.CYRUS_ORDERSETS.map((s,i)=>(
          <button key={s.name} onClick={()=>setActive(i)} style={{
            display:"block",width:"100%",textAlign:"left",padding:"10px 12px",
            background: active===i?"var(--navy-tint)":"transparent",
            borderLeft: active===i?"3px solid var(--teal)":"3px solid transparent",
            borderBottom:"1px solid var(--line-2)"
          }}>
            <div style={{fontWeight:600,fontSize:12,color: active===i?"var(--navy)":"var(--ink)"}}>{s.name}</div>
            <div style={{fontSize:11,color:"var(--ink-3)",marginTop:2}}>{s.count} items · {s.pop}</div>
            <div style={{fontSize:10,fontFamily:"'JetBrains Mono',monospace",color:"var(--teal)",marginTop:2}}>{s.evidence}</div>
          </button>
        ))}
      </Card>
      <Card title={`PowerPlan · ${set.name}`} actions={<>
        <Pill tone="teal">Evidence: {set.evidence}</Pill>
        <Pill tone="orange">{selected.size} of {items.length} selected</Pill>
      </>} pad={false}>
        <div style={{padding:"6px 14px",borderBottom:"1px solid var(--line)",background:"#f6f9fc",fontSize:11,color:"var(--ink-3)",display:"flex",alignItems:"center",gap:8}}>
          {I.warn(12)} <b style={{color:"var(--orange)"}}>Initiating in:</b> Wojciechowska, H · ICU-3 / 04 · MAP 58 · Lactate 3.6
        </div>
        <table style={{width:"100%"}}>
          <thead><tr><th style={{width:36}}></th><th>Order</th><th style={{width:120}}>Type</th><th style={{width:100}}>Priority</th><th style={{width:80}}>Status</th></tr></thead>
          <tbody>
            {items.map((o,i)=>(
              <tr key={i} style={{background:selected.has(i)?"transparent":"#fafbfd"}}>
                <td><input type="checkbox" checked={selected.has(i)} onChange={()=>toggle(i)}/></td>
                <td style={{fontWeight:500}}>{o}</td>
                <td><Pill tone={i<3||i===8?"teal":i<6?"orange":"navy"} size="sm">{i<3||i===8?"Lab":i<6?"Med":"Fluid"}</Pill></td>
                <td><select defaultValue={i<3?"STAT":"ASAP"} style={selStyle}><option>STAT</option><option>ASAP</option><option>Routine</option></select></td>
                <td>{selected.has(i)?<Pill tone="green" size="sm">Ready</Pill>:<Pill tone="neutral" size="sm">Skip</Pill>}</td>
              </tr>
            ))}
          </tbody>
        </table>
        <div style={{padding:"12px 14px",borderTop:"1px solid var(--line)",background:"#fafbfd",display:"flex",alignItems:"center",gap:8}}>
          <Pill tone="orange">⚠ Vancomycin: dose adjusted for CrCl 32 → 15 mg/kg q24h</Pill>
          <Pill tone="green">No allergy interactions</Pill>
          <div style={{flex:1}}/>
          <button style={ghostBtn}>Save draft</button>
          <button style={navyBtn} onClick={()=>{
            const pid = (window.CYRUS_PATIENTS && window.CYRUS_PATIENTS[0]?.mrn) || null;
            const picked = items.filter((_,i)=>selected.has(i));
            picked.forEach(label => window.medsimV3?.placeOrder(pid, {
              category: /vanco|pip-tazo|norepi|insulin|hydrocort|lr |ringer|propofol|fent/i.test(label) ? "med"
                      : /lactate|cbc|bmp|cmp|culture|procal|chem|abg|vbg/i.test(label) ? "lab"
                      : /cxr|ct |echo|imaging/i.test(label) ? "imaging"
                      : "lab",
              code:     label,
              label:    label,
              rationale:`PowerPlan: ${set.name} · ${set.evidence}`,
              priority: /STAT/i.test(label) ? "stat" : "routine",
              signed_by:"Cyrus PowerOrders"
            }));
          }}>{I.check(12)} Sign &amp; initiate ({selected.size})</button>
        </div>
      </Card>
    </div>
  );
};

// ── Results Review ────────────────────────────────────────────────────
const ResultsReview = ({anno})=>(
  <div style={{display:"grid",gridTemplateColumns:"1fr 1fr",gap:12,position:"relative"}}>
    <Anno show={anno} side="right">Results review groups by panel and time. Critical values open the acknowledge dialog automatically.</Anno>
    {window.CYRUS_LABS.map(l=>(
      <Card key={l.panel} title={`${l.panel} · resulted ${l.time}`}>
        <table style={{width:"100%",fontFamily:"'JetBrains Mono',monospace",fontSize:12}}>
          <thead><tr><th>Analyte</th><th>Value</th><th>Reference</th><th>Flag</th></tr></thead>
          <tbody>
            {l.values.map(v=>(
              <tr key={v.name} style={{background:v.flag==="HH"?"var(--red-tint)":v.flag==="H"||v.flag==="L"?"var(--orange-tint)":"transparent"}}>
                <td style={{fontFamily:"'DM Sans',sans-serif",fontWeight:500}}>{v.name}</td>
                <td style={{fontWeight:700}}>{v.v}</td>
                <td style={{color:"var(--ink-3)"}}>{v.ref}</td>
                <td>{v.flag && <Pill tone={v.flag==="HH"?"red":"orange"} size="sm">{v.flag}</Pill>}</td>
              </tr>
            ))}
          </tbody>
        </table>
      </Card>
    ))}
    <Card title="Acknowledgement queue" style={{gridColumn:"span 2"}}>
      <table style={{width:"100%"}}>
        <thead><tr><th>Time</th><th>Patient</th><th>Result</th><th>Critical</th><th></th></tr></thead>
        <tbody>
          <tr><td>08:15</td><td>Wojciechowska, H.</td><td>Procalcitonin 4.8</td><td><Pill tone="red" size="sm">CRIT</Pill></td><td><button style={primaryBtn}>{I.check(12)} Ack</button></td></tr>
          <tr><td>07:42</td><td>Wojciechowska, H.</td><td>Lactate 3.6</td><td><Pill tone="red" size="sm">CRIT</Pill></td><td><button style={primaryBtn}>{I.check(12)} Ack</button></td></tr>
          <tr><td>06:30</td><td>Wojciechowska, H.</td><td>K 5.4</td><td><Pill tone="orange" size="sm">High</Pill></td><td><button style={ghostBtn}>Ack</button></td></tr>
        </tbody>
      </table>
    </Card>
  </div>
);

// =====================================================================
// REGISTRATION
// =====================================================================
const Registration = ({anno})=>{
  const [tab, setTab] = useState("schedule");
  return (
    <div style={{flex:1,display:"flex",flexDirection:"column",minHeight:0}}>
      <div style={{background:"#fff",borderBottom:"1px solid var(--line)",padding:"0 16px",display:"flex",gap:0,alignItems:"stretch"}}>
        {[["schedule","Schedule Board"],["registration","Patient Registration"],["intake","Mobile Intake"]].map(([k,l])=>(
          <button key={k} onClick={()=>setTab(k)} style={{
            padding:"12px 16px",fontWeight:600,fontSize:12,
            color: tab===k?"var(--navy)":"var(--ink-2)",
            borderBottom: tab===k?"3px solid var(--teal)":"3px solid transparent",
            marginBottom:-1
          }}>{l}</button>
        ))}
      </div>
      <div style={{flex:1,overflow:"auto",background:"var(--bg)",padding:14,position:"relative"}}>
        {tab==="schedule" && <ScheduleBoard anno={anno}/>}
        {tab==="registration" && <RegFlow anno={anno}/>}
        {tab==="intake" && <MobileIntake anno={anno}/>}
      </div>
    </div>
  );
};

const ScheduleBoard = ({anno})=>{
  const slots = ["08:00","08:20","08:40","09:00","09:20","09:40","10:00","10:20","10:40","11:00"];
  const providers = ["Almeida, K., MD","Bashir, R., MD","Hartwell, N., MD"];
  const fills = {
    "08:00-Almeida, K., MD":{n:"Eklund-Marsh, T.",t:"f/u pancreatitis",s:"checked-in"},
    "08:20-Almeida, K., MD":{n:"Park, A.",t:"new patient",s:"scheduled"},
    "08:40-Almeida, K., MD":{n:"Lim, Y.",t:"DM check",s:"no-show"},
    "09:00-Bashir, R., MD":{n:"Wojciechowska, H.",t:"ICU rounds",s:"in-room"},
    "09:20-Bashir, R., MD":{n:"Vasquez, R.",t:"sepsis f/u",s:"scheduled"},
    "08:00-Hartwell, N., MD":{n:"Robidoux, A.",t:"L&D admit",s:"checked-in"},
    "10:00-Hartwell, N., MD":{n:"Cohen-Patel, M.",t:"36w OB",s:"scheduled"}
  };
  return (
    <div style={{position:"relative"}}>
      <Anno show={anno} side="right">Grid scheduler — providers as columns, time as rows. Drag-to-reschedule; click empty cell to book. Color = check-in status.</Anno>
      <Card title="Today · 2026-04-25" actions={<><button style={ghostBtn}>+ Block</button><button style={navyBtn}>{I.plus(12)} Book</button></>} pad={false}>
        <table style={{width:"100%"}}>
          <thead><tr><th style={{width:80}}>Time</th>{providers.map(p=><th key={p}>{p}</th>)}</tr></thead>
          <tbody>
            {slots.map(slot=>(
              <tr key={slot}>
                <td style={{fontFamily:"'JetBrains Mono',monospace",fontWeight:600,color:"var(--navy)"}}>{slot}</td>
                {providers.map(p=>{
                  const f = fills[`${slot}-${p}`];
                  const colors = { "checked-in":["var(--green-tint)","var(--green)"],"in-room":["var(--teal-tint)","var(--teal)"],"scheduled":["var(--navy-tint)","var(--navy)"],"no-show":["var(--red-tint)","var(--red)"] };
                  if(!f) return <td key={p} style={{color:"var(--ink-3)",fontSize:11,fontStyle:"italic"}}>open</td>;
                  const [bg,fg] = colors[f.s];
                  return <td key={p} style={{padding:6}}>
                    <div style={{padding:"6px 8px",background:bg,borderLeft:`3px solid ${fg}`,borderRadius:3}}>
                      <div style={{fontWeight:600,fontSize:11,color:fg}}>{f.n}</div>
                      <div style={{fontSize:10,color:"var(--ink-2)"}}>{f.t}</div>
                      <div style={{fontSize:10,marginTop:2}}><Pill tone={f.s==="checked-in"?"green":f.s==="in-room"?"teal":f.s==="no-show"?"red":"navy"} size="sm">{f.s}</Pill></div>
                    </div>
                  </td>;
                })}
              </tr>
            ))}
          </tbody>
        </table>
      </Card>
    </div>
  );
};

const RegFlow = ({anno})=>{
  const [tab, setTab] = useState(0);
  const TABS = ["Identity","Contact & address","Insurance","Authorizations","Consents"];
  return (
    <div style={{position:"relative"}}>
      <Anno show={anno} side="right">Tabbed registration conversation — registrar can jump between tabs. Each tab self-validates and lights green when complete.</Anno>
      <div style={{background:"#fff",border:"1px solid var(--line)",borderRadius:4}}>
        <div style={{display:"flex",borderBottom:"1px solid var(--line)"}}>
          {TABS.map((t,i)=>(
            <button key={t} onClick={()=>setTab(i)} style={{
              flex:1,padding:"12px 14px",fontWeight:600,fontSize:12,
              color: tab===i?"var(--navy)":"var(--ink-2)",
              borderBottom: tab===i?"3px solid var(--teal)":"3px solid transparent",
              borderRight:"1px solid var(--line-2)",
              background: i<tab?"var(--green-tint)":"transparent"
            }}>
              <span style={{display:"inline-flex",alignItems:"center",gap:6}}>
                {i<tab && <span style={{color:"var(--green)"}}>{I.check(12)}</span>}
                <span>{i+1}. {t}</span>
              </span>
            </button>
          ))}
        </div>
        <div style={{padding:18}}>
          {tab===0 && (
            <div style={{display:"grid",gridTemplateColumns:"repeat(3,1fr)",gap:12}}>
              <F label="Last name" v="Eklund-Marsh"/><F label="First name" v="Tobias"/><F label="Middle/suffix"/>
              <F label="DOB" v="1978-04-17" type="date"/><F label="Sex assigned at birth" v="M"/><F label="Gender identity" v="Man"/>
              <F label="SSN (last 4)" v="••••2241"/><F label="Country of birth" v="Sweden"/><F label="Preferred language" v="English"/>
              <div style={{gridColumn:"span 3",background:"var(--green-tint)",border:"1px solid var(--green)",borderRadius:3,padding:10,fontSize:12,color:"var(--green)",display:"flex",alignItems:"center",gap:8}}>{I.check(13)} <b>MPI match (98%):</b> existing chart MRN CY-77843015 — last visit 2024-11-02. <button style={{marginLeft:"auto",fontWeight:700}}>Use existing</button></div>
            </div>
          )}
          {tab===1 && (
            <div style={{display:"grid",gridTemplateColumns:"repeat(3,1fr)",gap:12}}>
              <F label="Address line 1" v="2218 Ardmore St" wide/>
              <F label="City" v="Springfield"/><F label="State" v="IL"/><F label="ZIP" v="62701"/>
              <F label="Phone (mobile)" v="(217) 555-0184"/><F label="Email" v="t.eklundmarsh@example.com"/>
              <F label="Emergency contact" v="Linnea Eklund (spouse)"/><F label="Emergency phone" v="(217) 555-0177"/>
            </div>
          )}
          {tab===2 && (
            <div>
              <div style={{display:"grid",gridTemplateColumns:"repeat(3,1fr)",gap:12}}>
                <F label="Payor" v="Aetna PPO" wide/><F label="Plan type" v="Commercial"/>
                <F label="Member ID" v="W221440812"/><F label="Group #" v="GRP-77241"/><F label="Effective" v="2025-01-01" type="date"/>
              </div>
              <div style={{marginTop:12,background:"var(--orange-tint)",border:"1px solid var(--orange)",color:"#5a3208",padding:10,borderRadius:3,fontSize:12,display:"flex",alignItems:"center",gap:8}}>
                {I.warn(13)} <b style={{color:"var(--orange)"}}>270/271 eligibility:</b> Active · Copay $50 specialist · Deductible $1,800 / $3,000 met · Preauth required for high-cost imaging
              </div>
            </div>
          )}
          {tab===3 && <div style={{padding:"30px",textAlign:"center",color:"var(--ink-3)",fontSize:12}}>Auth & referral submission UI — abbreviated for this view.</div>}
          {tab===4 && <div style={{padding:"30px",textAlign:"center",color:"var(--ink-3)",fontSize:12}}>Consent capture (signature pad) — abbreviated.</div>}
          <div style={{display:"flex",gap:6,marginTop:16}}>
            {tab>0 && <button style={ghostBtn} onClick={()=>setTab(tab-1)}>← Back</button>}
            <div style={{flex:1}}/>
            {tab<TABS.length-1 && <button style={navyBtn} onClick={()=>setTab(tab+1)}>Continue →</button>}
            {tab===TABS.length-1 && <button style={primaryBtn}>{I.check(12)} Finalize encounter</button>}
          </div>
        </div>
      </div>
    </div>
  );
};

const F = ({label,v="",type="text",wide})=>(
  <label style={{display:"flex",flexDirection:"column",gap:4,gridColumn:wide?"span 2":"span 1"}}>
    <span style={{fontSize:11,fontWeight:600,letterSpacing:".04em",color:"var(--navy)",textTransform:"uppercase"}}>{label}</span>
    <input type={type} defaultValue={v} style={inputStyle}/>
  </label>
);

const MobileIntake = ({anno})=>(
  <div style={{display:"grid",gridTemplateColumns:"320px 1fr",gap:18,position:"relative"}}>
    <Anno show={anno} side="right">Self-service mobile intake. Patient completes from phone before arrival; data flows directly into discrete chart fields, no rekey by registrar.</Anno>
    <div style={{
      border:"10px solid #1c1d24",borderRadius:32,background:"#fff",
      padding:0,aspectRatio:"3 / 6",overflow:"hidden",position:"relative",
      boxShadow:"0 18px 40px rgba(11,52,84,.25)"
    }}>
      <div style={{padding:"14px 16px",background:"var(--navy)",color:"#fff",display:"flex",alignItems:"center",gap:8}}>
        <CyrusLogo size={18}/>
        <div style={{fontWeight:700,fontSize:13}}>Cyrus MyHealth</div>
      </div>
      <div style={{padding:18}}>
        <div style={{fontSize:11,fontWeight:600,color:"var(--teal)",letterSpacing:".06em",textTransform:"uppercase"}}>Step 5 of 8</div>
        <div style={{fontWeight:700,fontSize:18,marginTop:6,lineHeight:1.3}}>Are you currently taking any medications?</div>
        <div style={{fontSize:12,color:"var(--ink-3)",marginTop:4}}>Include prescription, OTC, vitamins, herbal.</div>
        <div style={{marginTop:16,display:"flex",flexDirection:"column",gap:8}}>
          {["Lisinopril 10 mg daily","Atorvastatin 40 mg HS","Aspirin 81 mg daily","Vitamin D 1000 IU"].map((m,i)=>(
            <div key={m} style={{padding:"10px 12px",border:"1px solid var(--line)",borderLeft:`3px solid var(--teal)`,borderRadius:3,background:"#fff",display:"flex",alignItems:"center",gap:8}}>
              <input type="checkbox" defaultChecked/>
              <div style={{flex:1}}>
                <div style={{fontWeight:600,fontSize:12}}>{m}</div>
                <div style={{fontSize:10,color:"var(--ink-3)"}}>Reconciled from prior visit</div>
              </div>
              <button style={{fontSize:11,color:"var(--navy)",fontWeight:600}}>Edit</button>
            </div>
          ))}
          <button style={{padding:"10px 12px",border:"1px dashed var(--navy)",borderRadius:3,color:"var(--navy)",fontWeight:600,fontSize:12}}>+ Add medication</button>
        </div>
      </div>
      <div style={{position:"absolute",bottom:18,left:18,right:18,display:"flex",gap:8}}>
        <button style={{flex:1,padding:"12px",background:"#eaeef3",borderRadius:3,fontWeight:600,fontSize:13}}>Back</button>
        <button style={{flex:1,padding:"12px",background:"var(--teal)",color:"#fff",borderRadius:3,fontWeight:700,fontSize:13}}>Continue</button>
      </div>
    </div>
    <Card title="Intake progress (registrar dashboard view)">
      <div style={{display:"grid",gridTemplateColumns:"repeat(3,1fr)",gap:8,marginBottom:14}}>
        <Kpi label="Sent today" value="142" delta="" tone="navy"/>
        <Kpi label="Completed" value="98" delta="69%" tone="teal"/>
        <Kpi label="Avg time" value="4:12" delta="" tone="orange"/>
      </div>
      <table style={{width:"100%"}}>
        <thead><tr><th>Patient</th><th>Sent</th><th>Progress</th><th>Status</th></tr></thead>
        <tbody>
          <tr><td>Eklund-Marsh, T.</td><td>1d ago</td><td><Bar v={62}/></td><td><Pill tone="orange" size="sm">In progress</Pill></td></tr>
          <tr><td>Park, A.</td><td>2d ago</td><td><Bar v={100}/></td><td><Pill tone="green" size="sm">Complete</Pill></td></tr>
          <tr><td>Lim, Y.</td><td>3d ago</td><td><Bar v={0}/></td><td><Pill tone="red" size="sm">Not started</Pill></td></tr>
          <tr><td>Cohen-Patel, M.</td><td>3h ago</td><td><Bar v={32}/></td><td><Pill tone="orange" size="sm">In progress</Pill></td></tr>
        </tbody>
      </table>
    </Card>
  </div>
);

const Bar = ({v})=>(
  <div style={{width:120,background:"#eaeef3",borderRadius:99,height:8,overflow:"hidden"}}>
    <div style={{width:`${v}%`,height:"100%",background: v===100?"var(--green)":v>50?"var(--teal)":"var(--orange)"}}/>
  </div>
);

// =====================================================================
// ADMIN
// =====================================================================
const AdminConsole = ({anno})=>(
  <div style={{flex:1,overflow:"auto",padding:14,background:"var(--bg)",position:"relative"}}>
    <Anno show={anno} side="right">Admin console focused on operations, build governance, and audit. Heavy table density preferred over visualizations.</Anno>
    <div style={{display:"grid",gridTemplateColumns:"repeat(5,1fr)",gap:10,marginBottom:14}}>
      <Kpi label="Active users" value="2,148" delta="peak today" tone="teal"/>
      <Kpi label="Open sessions" value="891"/>
      <Kpi label="Avg note time" value="3:48" delta="-22% w/ ambient" tone="teal"/>
      <Kpi label="Charge lag (med)" value="2.1d" delta="+0.4 d" tone="orange"/>
      <Kpi label="Critical results unack" value="6" delta="↑" tone="orange"/>
    </div>
    <div style={{display:"grid",gridTemplateColumns:"1.4fr 1fr",gap:14}}>
      <Card title="Audit trail · last 30 events" pad={false}>
        <table style={{width:"100%",fontSize:11}}>
          <thead><tr><th>Time</th><th>User</th><th>Type</th><th>Subject</th><th>Outcome</th></tr></thead>
          <tbody>
            {[
              ["09:46","r.bashir@cyrus","SIGN","PowerNote · CY-44210331","success"],
              ["09:42","m.petrosian@cyrus","DOC","iView col 10:00 · CY-44210331","success"],
              ["09:38","admin.compliance","BREAK-GLASS","Read · CY-66019823","logged"],
              ["09:32","reg.desk-12","REGISTER","FIN-2026-008419","success"],
              ["09:18","s.vega@cyrus","ORDER","Vanco PowerPlan","success"],
              ["09:11","login.failure","AUTH","l.silvera@cyrus (3rd)","throttled"],
              ["08:55","k.almeida@cyrus","COSIGN","HPI · CY-77843015","success"],
              ["08:42","integration.bridge","HL7","ADT^A04 → Lab","ack"]
            ].map((r,i)=>(
              <tr key={i}>
                <td style={{fontFamily:"'JetBrains Mono',monospace"}}>{r[0]}</td>
                <td>{r[1]}</td>
                <td><Pill tone={r[2]==="BREAK-GLASS"?"red":r[2]==="AUTH"?"orange":r[2]==="SIGN"||r[2]==="COSIGN"?"green":"navy"} size="sm">{r[2]}</Pill></td>
                <td style={{color:"var(--ink-2)"}}>{r[3]}</td>
                <td style={{color:r[4]==="success"||r[4]==="ack"?"var(--green)":"var(--orange)",fontWeight:600,fontSize:11}}>{r[4]}</td>
              </tr>
            ))}
          </tbody>
        </table>
      </Card>
      <Card title="Build governance">
        <Row label="PowerPlans active: 412" tone="navy"/>
        <Row label="Pending publish (test → prod): 8" tone="orange"/>
        <Row label="iView bands: 56 (ICU, MS, ED, OB)" tone="navy"/>
        <Row label="Custom MPages by role: 18"/>
        <Row label="HL7 interfaces: 23 (22 healthy)" tone="green"/>
        <Row label="DC rules firing today: 4,182"/>
      </Card>
      <Card title="Throughput by service" style={{gridColumn:"span 2"}}>
        <Bars data={[{l:"ICU",v:312},{l:"Med-Surg",v:486},{l:"ED",v:512},{l:"OB",v:188},{l:"Surgery",v:244},{l:"Onc",v:140},{l:"Outpt",v:892}]}/>
      </Card>
    </div>
  </div>
);

const Bars = ({data})=>{
  const max = Math.max(...data.map(d=>d.v));
  return (
    <div style={{display:"flex",alignItems:"flex-end",gap:12,height:160,padding:"6px 0"}}>
      {data.map(d=>(
        <div key={d.l} style={{flex:1,display:"flex",flexDirection:"column",alignItems:"center",gap:4}}>
          <div style={{fontSize:11,fontFamily:"'JetBrains Mono',monospace",fontWeight:600,color:"var(--navy)"}}>{d.v}</div>
          <div style={{width:"100%",height:(d.v/max)*120,background:"linear-gradient(180deg,var(--teal),#0b6e69)",borderRadius:0}}/>
          <div style={{fontSize:11,color:"var(--ink-2)"}}>{d.l}</div>
        </div>
      ))}
    </div>
  );
};

Object.assign(window,{ ClinicianWorkspace, Registration, AdminConsole });
