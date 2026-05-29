/* global React, ReactDOM, ClinicianWorkspace, RegistrationDesk, AdminConsole, AppBar */
const { useState, useEffect } = React;

const HelixApp = ()=>{
  const [role, setRole] = useState("clinician");
  const [device, setDevice] = useState("desktop");
  const [patient, setPatient] = useState(window.HELIX_PATIENTS[0]);
  const [anno, setAnno] = useState(true);
  const user = { initials:"JL", name:"Dr. J. Lindqvist", title:"Surgery · Attending" };

  // Tweak protocol
  useEffect(()=>{
    const handler = (e)=>{
      if(e.data?.type==="__activate_edit_mode") setShowTweaks(true);
      if(e.data?.type==="__deactivate_edit_mode") setShowTweaks(false);
    };
    window.addEventListener("message", handler);
    window.parent.postMessage({type:"__edit_mode_available"}, "*");
    return ()=> window.removeEventListener("message", handler);
  },[]);
  const [showTweaks, setShowTweaks] = useState(false);

  const widths = { desktop: 1440, tablet: 1024, phone: 420 };
  const w = widths[device];

  return (
    <>
      <AppBar user={user} role={role} onSwitch={setRole} device={device} setDevice={setDevice}/>
      <div style={{flex:1,display:"flex",justifyContent:"center",background:"#dde2ee",padding: device==="desktop"?0:18,minHeight:0}}>
        <div style={{
          width: device==="desktop"? "100%" : w,
          maxWidth: device==="desktop"? "none" : w,
          background:"#fff",
          boxShadow: device==="desktop"? "none":"0 12px 40px rgba(11,23,51,.18)",
          borderRadius: device==="desktop"? 0:8,
          display:"flex",flexDirection:"column",overflow:"hidden",
          minHeight: device==="desktop"? "auto":640
        }}>
          {role==="clinician" && <ClinicianWorkspace patient={patient} setPatient={setPatient} anno={anno} device={device}/>}
          {role==="registration" && <RegistrationDesk anno={anno}/>}
          {role==="admin" && <AdminConsole anno={anno}/>}
        </div>
      </div>

      {/* Floating Tweaks */}
      {showTweaks && (
        <div style={{
          position:"fixed",bottom:18,right:18,zIndex:50,
          width:280,background:"#fff",borderRadius:8,
          boxShadow:"0 18px 40px rgba(11,23,51,.25)",border:"1px solid #143b8a",
          fontSize:12,fontFamily:"Inter"
        }}>
          <div style={{padding:"10px 12px",background:"#143b8a",color:"#fff",borderRadius:"8px 8px 0 0",fontWeight:700,display:"flex",alignItems:"center"}}>
            Tweaks
            <button onClick={()=>{setShowTweaks(false); window.parent.postMessage({type:"__edit_mode_dismissed"},"*");}} style={{marginLeft:"auto",color:"#fff"}}>✕</button>
          </div>
          <div style={{padding:12,display:"flex",flexDirection:"column",gap:10}}>
            <label style={{display:"flex",alignItems:"center",gap:8}}>
              <input type="checkbox" checked={anno} onChange={e=>setAnno(e.target.checked)}/> Show design annotations
            </label>
            <div>
              <div style={{fontWeight:600,marginBottom:4}}>Switch patient</div>
              <select value={patient.mrn} onChange={e=>setPatient(window.HELIX_PATIENTS.find(p=>p.mrn===e.target.value))} style={{width:"100%",padding:"6px 8px",borderRadius:5,border:"1px solid #dde2ee"}}>
                {window.HELIX_PATIENTS.map(p=><option key={p.mrn} value={p.mrn}>{p.name} · {p.status}</option>)}
              </select>
            </div>
            <div>
              <div style={{fontWeight:600,marginBottom:4}}>Device frame</div>
              <div style={{display:"flex",gap:6}}>
                {["desktop","tablet","phone"].map(d=>(
                  <button key={d} onClick={()=>setDevice(d)} style={{
                    flex:1,padding:"6px 0",borderRadius:5,
                    background: device===d?"#143b8a":"#eef1f8",
                    color: device===d?"#fff":"#3a4a6b",fontWeight:600,textTransform:"capitalize"
                  }}>{d}</button>
                ))}
              </div>
            </div>
          </div>
        </div>
      )}

      {!showTweaks && (
        <button onClick={()=>setShowTweaks(true)} style={{
          position:"fixed",bottom:18,right:18,zIndex:50,
          padding:"8px 14px",borderRadius:99,background:"#143b8a",color:"#fff",
          fontWeight:700,fontSize:12,boxShadow:"0 8px 18px rgba(20,59,138,.3)"
        }}>Tweaks</button>
      )}
    </>
  );
};

// ── MEDSIM V3 bootstrap wrapper ─────────────────────────────────────
// `medsim_v3_client.js` has already overwritten window.HELIX_PATIENTS
// with the seeded ChartSeed patient (when running in live mode). The
// wrapper logs `chart.open` once for the initial patient.
const HelixV3Root = ()=>{
  React.useEffect(()=>{
    if (!window.medsimV3) return;
    const p = (window.HELIX_PATIENTS && window.HELIX_PATIENTS[0]) || null;
    if (p) window.medsimV3.event("chart.open", "chart", p.mrn, { name: p.name });
  }, []);
  return <HelixApp/>;
};
ReactDOM.createRoot(document.getElementById("app")).render(<HelixV3Root/>);
