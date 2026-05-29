window.MER_PATIENTS = [
  {
    mrn: "MER-2026-44218",
    name: "Eleanor Hightower",
    dob: "1948-02-09",
    age: 78, sex: "F", pronouns: "she/her",
    location: "Med-Surg · Rm 214A",
    los: "Day 3",
    status: "Inpatient · Stable",
    allergies: ["Codeine (nausea)"],
    code: "Full Code",
    isolation: "Standard",
    problems: ["CHF exacerbation", "AFib (rate-controlled)", "Osteoarthritis"],
    meds: ["Furosemide 40mg PO BID","Metoprolol 25mg PO BID","Apixaban 5mg PO BID","Tylenol 650mg PO q6h PRN"],
    pcp: "Dr. M. Chen",
    attending: "Dr. P. Adeyemi",
    insurance: "Medicare A+B / AARP supp"
  },
  {
    mrn: "MER-2026-09817",
    name: "Caleb Whitford-Bayle",
    dob: "1985-07-22",
    age: 40, sex: "M", pronouns: "he/him",
    location: "Outpt Clinic · Rm 6",
    los: "—",
    status: "Outpatient · F/u visit",
    allergies: ["NKDA"],
    code: "Full Code",
    isolation: "Standard",
    problems: ["Hypertension", "Hyperlipidemia"],
    meds: ["Lisinopril 20mg daily","Atorvastatin 20mg HS"],
    pcp: "Dr. M. Chen",
    attending: "Dr. M. Chen",
    insurance: "BlueCross PPO"
  },
  {
    mrn: "MER-2026-66301",
    name: "Penelope Acheampong",
    dob: "2019-10-14",
    age: 6, sex: "F", pronouns: "she/her",
    location: "Peds · Rm 3",
    los: "—",
    status: "Outpatient · Sick visit",
    allergies: ["Amoxicillin (rash)"],
    code: "Full Code",
    isolation: "Droplet (suspect)",
    problems: ["Fever 101.4F", "URI symptoms"],
    meds: ["Tylenol PRN"],
    pcp: "Dr. R. Singh",
    attending: "Dr. R. Singh",
    insurance: "Medicaid MCO"
  }
];

window.MER_SCHEDULE = [
  { time:"08:00", patient:"Whitford-Bayle, C.", reason:"HTN follow-up", room:"6", status:"Roomed" },
  { time:"08:30", patient:"Acheampong, P.", reason:"Fever 101.4 / cough", room:"3", status:"Waiting" },
  { time:"09:00", patient:"Hightower, E.", reason:"Inpt rounds", room:"214A", status:"Inpatient" },
  { time:"09:30", patient:"Yarbrough, T.", reason:"Annual physical", room:"4", status:"Scheduled" },
  { time:"10:00", patient:"Borisov, K.", reason:"DM 3-mo check", room:"6", status:"Scheduled" },
  { time:"10:30", patient:"O'Sullivan, F.", reason:"Sinus pain", room:"5", status:"Scheduled" },
  { time:"11:00", patient:"Lefebvre, A.", reason:"Med refill", room:"6", status:"Scheduled" }
];

window.MER_TEMPLATES = [
  { code:"GEN-FU", name:"General Follow-Up", lines:8 },
  { code:"HTN-MX", name:"Hypertension Management", lines:14 },
  { code:"DM-FU", name:"Diabetes Follow-Up", lines:18 },
  { code:"WELL-A", name:"Adult Annual Wellness", lines:22 },
  { code:"PEDS-SICK", name:"Pediatric Sick Visit", lines:16 },
  { code:"DC-PLAN", name:"Discharge Planning", lines:11 }
];

window.MER_VITALS = [
  { time:"00:00", t:"36.8", hr:"78", rr:"16", bp:"128/76", spo2:"96", weight:"68.4" },
  { time:"04:00", t:"36.7", hr:"76", rr:"15", bp:"124/72", spo2:"97", weight:"" },
  { time:"08:00", t:"37.0", hr:"82", rr:"17", bp:"132/80", spo2:"96", weight:"68.2" },
  { time:"12:00", t:"36.9", hr:"80", rr:"16", bp:"126/74", spo2:"96", weight:"" },
  { time:"16:00", t:"36.8", hr:"78", rr:"16", bp:"122/72", spo2:"97", weight:"" },
  { time:"20:00", t:"36.7", hr:"74", rr:"15", bp:"118/70", spo2:"97", weight:"68.0" }
];

window.MER_ORDERS = [
  { code:"BMP", group:"Lab", common:true },
  { code:"BNP", group:"Lab", common:true },
  { code:"CBC w/ Diff", group:"Lab", common:true },
  { code:"PT/INR", group:"Lab", common:false },
  { code:"Mg, Phos", group:"Lab", common:false },
  { code:"CXR PA/LAT", group:"Imaging", common:true },
  { code:"Echo TTE", group:"Imaging", common:false },
  { code:"Furosemide 40mg IV ×1", group:"Med", common:true },
  { code:"Potassium chloride 20 mEq PO ×1", group:"Med", common:false },
  { code:"Daily weight", group:"Nursing", common:true }
];
