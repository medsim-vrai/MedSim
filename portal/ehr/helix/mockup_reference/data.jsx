// Synthetic patient data — Helix Health
const HELIX_PATIENTS = [
  {
    mrn: "HLX-4471203",
    name: "Marisol Fontaine-Reyes",
    dob: "1962-03-14",
    age: 64,
    sex: "F",
    pronouns: "she/her",
    room: "5C-12",
    status: "Inpatient · POD 2",
    allergies: ["Penicillin (hives)", "Iodine contrast (mild)"],
    code: "Full Code",
    isolation: "Contact",
    problems: ["Type 2 diabetes mellitus", "Stage 2 CKD", "HFpEF", "Post-op cholecystectomy"],
    meds: ["Metformin 500mg BID", "Lisinopril 10mg daily", "Furosemide 20mg daily", "Pantoprazole 40mg daily"],
    pcp: "T. Okafor, MD",
    attending: "S. Park, MD"
  },
  {
    mrn: "HLX-9982041",
    name: "Daniyar Tashkenbayev",
    dob: "1989-11-02",
    age: 36,
    sex: "M",
    pronouns: "he/him",
    room: "ED-7",
    status: "ED · Triaged ESI-3",
    allergies: ["NKDA"],
    code: "Full Code",
    isolation: "Standard",
    problems: ["Acute right flank pain", "h/o nephrolithiasis"],
    meds: ["Ibuprofen 600mg PRN", "Tamsulosin 0.4mg daily"],
    pcp: "Unassigned",
    attending: "R. Ng, MD (ED)"
  },
  {
    mrn: "HLX-3318824",
    name: "Imani Whitcombe",
    dob: "2017-06-28",
    age: 8,
    sex: "F",
    pronouns: "she/her",
    room: "Peds-3",
    status: "Outpt · Well-child visit",
    allergies: ["Amoxicillin (rash)"],
    code: "Full Code",
    isolation: "Standard",
    problems: ["Mild persistent asthma", "Atopic dermatitis"],
    meds: ["Fluticasone HFA 44mcg BID", "Cetirizine 5mg daily PRN"],
    pcp: "L. Sandberg, MD",
    attending: "—"
  }
];

// Encounters / schedule
const HELIX_SCHEDULE = [
  { time:"08:00", patient:"Fontaine-Reyes, M.", reason:"Post-op rounds", status:"Seen", flag:"" },
  { time:"08:20", patient:"Whitcombe, I.", reason:"Well-child 8y", status:"Roomed", flag:"new-results" },
  { time:"08:40", patient:"Tashkenbayev, D.", reason:"Flank pain f/u", status:"In room", flag:"stat-lab" },
  { time:"09:00", patient:"Olamide, B.", reason:"DM mgmt", status:"Scheduled", flag:"" },
  { time:"09:20", patient:"Petrov, K.", reason:"Hypertension", status:"Scheduled", flag:"" },
  { time:"09:40", patient:"Ahmadi-Lutz, R.", reason:"Anxiety f/u", status:"Scheduled", flag:"" },
  { time:"10:00", patient:"Berenger, V.", reason:"Knee pain", status:"Scheduled", flag:"" }
];

// Order catalog (CPOE)
const HELIX_ORDERS = [
  { code:"CBC w/ DIFF", group:"Lab", cost:"$24", turnaround:"45 min", common:true },
  { code:"BMP", group:"Lab", cost:"$22", turnaround:"40 min", common:true },
  { code:"CMP", group:"Lab", cost:"$28", turnaround:"45 min", common:true },
  { code:"TROPONIN-I", group:"Lab", cost:"$42", turnaround:"30 min", common:false },
  { code:"LIPASE", group:"Lab", cost:"$31", turnaround:"55 min", common:false },
  { code:"UA W/ MICRO", group:"Lab", cost:"$18", turnaround:"35 min", common:true },
  { code:"CT ABD/PELV W/CONTRAST", group:"Imaging", cost:"$840", turnaround:"~2 h", common:false },
  { code:"CXR PA/LAT", group:"Imaging", cost:"$90", turnaround:"30 min", common:true },
  { code:"US KIDNEY/BLADDER", group:"Imaging", cost:"$310", turnaround:"~1 h", common:false },
  { code:"KETOROLAC 30 MG IV ×1", group:"Med", cost:"$8", turnaround:"now", common:false },
  { code:"ONDANSETRON 4 MG IV PRN", group:"Med", cost:"$6", turnaround:"now", common:true },
  { code:"NS 1L IV BOLUS", group:"Med", cost:"$12", turnaround:"now", common:true }
];

const HELIX_SMARTPHRASES = [
  { trigger:".ros10", expansion:"Constitutional: denies fever, chills, weight loss. HEENT: denies headache, vision changes. Cardiac: denies chest pain, palpitations. Pulm: denies SOB, cough. GI: denies n/v/d, abd pain. GU: denies dysuria, hematuria. MSK: denies joint pain. Skin: denies rash. Neuro: denies focal weakness, paresthesias. Psych: denies SI/HI." },
  { trigger:".pe-normal", expansion:"Gen: NAD, alert, oriented x3. HEENT: NCAT, PERRL, MMM. Neck: supple, no LAD. CV: RRR, no m/r/g. Pulm: CTAB, no w/r/r. Abd: soft, NT, ND, +BS. Ext: no edema, 2+ pulses. Neuro: CN II–XII intact, 5/5 strength, sensation grossly intact. Skin: warm, dry, intact." },
  { trigger:".dmplan", expansion:"Type 2 DM — A1c reviewed, currently {A1C}. Continue metformin. Reinforced dietary counseling, foot exam normal. Will recheck A1c in 3 months. Referral to RD." },
  { trigger:".ckd2", expansion:"CKD stage 2 — eGFR stable. Continue ACE inhibitor at current dose, avoid NSAIDs. Recheck BMP in 6 weeks." },
  { trigger:".dctomorrow", expansion:"Patient meeting discharge criteria. Plan to discharge in AM pending overnight stability. PT cleared. Home with VNA, follow up with PCP within 7 days." }
];

const HELIX_VITALS = [
  { time:"04:00", t:"36.8", hr:"82", rr:"16", bp:"128/76", spo2:"96", pain:"3" },
  { time:"08:00", t:"37.0", hr:"88", rr:"18", bp:"132/80", spo2:"95", pain:"4" },
  { time:"12:00", t:"37.1", hr:"84", rr:"17", bp:"126/74", spo2:"96", pain:"3" },
  { time:"16:00", t:"36.9", hr:"79", rr:"16", bp:"122/72", spo2:"97", pain:"2" },
  { time:"20:00", t:"36.7", hr:"76", rr:"16", bp:"118/70", spo2:"98", pain:"2" },
  { time:"00:00", t:"36.6", hr:"74", rr:"15", bp:"116/68", spo2:"98", pain:"1" }
];

const HELIX_RESULTS = [
  { name:"Sodium", value:"139", unit:"mmol/L", ref:"135–145", flag:"" },
  { name:"Potassium", value:"3.4", unit:"mmol/L", ref:"3.5–5.1", flag:"L" },
  { name:"Chloride", value:"104", unit:"mmol/L", ref:"98–107", flag:"" },
  { name:"CO2", value:"24", unit:"mmol/L", ref:"22–29", flag:"" },
  { name:"BUN", value:"22", unit:"mg/dL", ref:"7–20", flag:"H" },
  { name:"Creatinine", value:"1.34", unit:"mg/dL", ref:"0.6–1.1", flag:"H" },
  { name:"Glucose", value:"168", unit:"mg/dL", ref:"70–110", flag:"H" },
  { name:"Calcium", value:"9.2", unit:"mg/dL", ref:"8.5–10.5", flag:"" }
];

window.HELIX_PATIENTS = HELIX_PATIENTS;
window.HELIX_SCHEDULE = HELIX_SCHEDULE;
window.HELIX_ORDERS = HELIX_ORDERS;
window.HELIX_SMARTPHRASES = HELIX_SMARTPHRASES;
window.HELIX_VITALS = HELIX_VITALS;
window.HELIX_RESULTS = HELIX_RESULTS;
