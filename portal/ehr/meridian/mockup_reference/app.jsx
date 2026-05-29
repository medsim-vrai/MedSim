/* global React, ReactDOM, ClinicianWorkspace, Registration, AdminConsole, AppBar */
const { useState, useEffect } = React;

const MerApp = ()=>{
  const [role, setRole] = useState("clinician");
  const [device, setDevice] = useState("desktop");
  const [patient, setPatient] = useState(window.MER_PATIENTS[0]);
  const [anno, setAnno] = useState(true);
  const [showTweaks, setShowTweaks] = useState(false);
  const user = { initials:"PA", name:"Dr. P. Adeyemi", title:"Hospitalist · IM" };

  useEffect(()=>{
    const handler=(e)=>{
      if(e.data?.type==="__activate_edit_mode") setShowTweaks(true);
      if(e.data?.type==="__deactivate_edit_mode") setShowTweaks(false);
    };
    window.addEventListener("message",handler);
    window.parent.postMessage({type:"__edit_mode_available"},"*");
    return ()=>window.removeEventListener("message",handler);
  },[]);

  const widths = { desktop:1440, tablet:1024, phone:420 };
  const w = widths[device];
  return (
    <>
      <AppBar user={user} role={role} onSwitch={setRole} device={device} setDevice={setDevice}/>
      <div style={{flex:1,display:"flex",justifyContent:"center",background:"#e3e8e0",padding:device==="desktop"?0:18,minHeight:0}}>
        <div style={{
          width: device==="desktop"?"100%":w,
          maxWidth: device==="desktop"?"none":w,
          background:"#fff",
          boxShadow: device==="desktop"?"none":"0 12px 40px rgba(31,42,38,.15)",
          borderRadius: device==="desktop"?0:10,
          display:"flex",flexDirection:"column",overflow:"hidden",
          minHeight: device==="desktop"?"auto":640
        }}>
          {role==="clinician" && <ClinicianWorkspace patient={patient} setPatient={setPatient} anno={anno}/>}
          {role==="registration" && <Registration anno={anno}/>}
          {role==="admin" && <AdminConsole anno={anno}/>}
        </div>
      </div>
      {showTweaks && (
        <div style={{position:"fixed",bottom:18,right:18,zIndex:50,width:280,background:"#fff",borderRadius:10,boxShadow:"0 18px 40px rgba(31,42,38,.25)",border:"1px solid var(--sage)",fontSize:12}}>
          <div style={{padding:"10px 14px",background:"var(--sage)",color:"#fff",borderRadius:"10px 10px 0 0",fontWeight:700,display:"flex",alignItems:"center",fontFamily:"'Newsreader',serif",fontSize:14}}>
            Tweaks
            <button onClick={()=>{setShowTweaks(false); window.parent.postMessage({type:"__edit_mode_dismissed"},"*");}} style={{marginLeft:"auto",color:"#fff"}}>✕</button>
          </div>
          <div style={{padding:14,display:"flex",flexDirection:"column",gap:12}}>
            <label style={{display:"flex",alignItems:"center",gap:8}}>
              <input type="checkbox" checked={anno} onChange={e=>setAnno(e.target.checked)}/> Show design annotations
            </label>
            <div>
              <div style={{fontWeight:600,marginBottom:4}}>Switch patient</div>
              <select value={patient.mrn} onChange={e=>setPatient(window.MER_PATIENTS.find(p=>p.mrn===e.target.value))} style={{width:"100%",padding:"7px 10px",borderRadius:6,border:"1px solid var(--line)"}}>
                {window.MER_PATIENTS.map(p=><option key={p.mrn} value={p.mrn}>{p.name} · {p.location}</option>)}
              </select>
            </div>
            <div>
              <div style={{fontWeight:600,marginBottom:4}}>Device frame</div>
              <div style={{display:"flex",gap:6}}>
                {["desktop","tablet","phone"].map(d=>(
                  <button key={d} onClick={()=>setDevice(d)} style={{flex:1,padding:"7px 0",borderRadius:99,background:device===d?"var(--sage)":"var(--bg)",color:device===d?"#fff":"var(--ink-2)",fontWeight:600,textTransform:"capitalize"}}>{d}</button>
                ))}
              </div>
            </div>
          </div>
        </div>
      )}
      {!showTweaks && (
        <button onClick={()=>setShowTweaks(true)} style={{position:"fixed",bottom:18,right:18,zIndex:50,padding:"9px 16px",borderRadius:99,background:"var(--sage)",color:"#fff",fontWeight:700,fontSize:12,boxShadow:"0 8px 18px rgba(74,117,86,.3)"}}>Tweaks</button>
      )}
    </>
  );
};

// ── MEDSIM V3 bootstrap wrapper ─────────────────────────────────────
const MerV3Root = ()=>{
  React.useEffect(()=>{
    if (!window.medsimV3) return;
    const p = (window.MER_PATIENTS && window.MER_PATIENTS[0]) || null;
    if (p) window.medsimV3.event("chart.open", "chart", p.mrn, { name: p.name });
  }, []);
  return <MerApp/>;
};
ReactDOM.createRoot(document.getElementById("app")).render(<MerV3Root/>);
