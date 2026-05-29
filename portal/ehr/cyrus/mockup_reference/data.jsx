// Cyrus Care synthetic data
window.CYRUS_PATIENTS = [
  {
    fin: "FIN-2026-008412",
    mrn: "CY-44210331",
    name: "Helena Wojciechowska",
    dob: "1955-09-21",
    age: 70, sex: "F", pronouns: "she/her",
    location: "ICU-3 / Bed 04",
    los: "ICU day 4 · LOS 6 days",
    status: "Inpatient · Critical",
    allergies: ["Sulfa (rash)", "Latex (anaphylaxis)"],
    code: "DNR / DNI",
    isolation: "Droplet",
    weight: "62.4 kg", height: "164 cm", bsa: "1.69",
    problems: ["Septic shock — pulmonary source", "COPD GOLD III", "Atrial fibrillation", "Chronic kidney disease st 3a"],
    meds: ["Norepinephrine 0.08 mcg/kg/min", "Vancomycin 1 g IV q12h", "Piperacillin-tazo 4.5g IV q8h", "Apixaban 2.5 mg PO BID"],
    attending: "Dr. R. Bashir",
    care_team: ["RN: M. Petrosian", "RT: J. Caldera", "Pharm: S. Vega"]
  },
  {
    fin: "FIN-2026-008419",
    mrn: "CY-77843015",
    name: "Tobias Eklund-Marsh",
    dob: "1978-04-17",
    age: 47, sex: "M", pronouns: "he/him",
    location: "Med-Surg 6 / Bed 12",
    los: "Day 1 · LOS 1 day",
    status: "Inpatient · Stable",
    allergies: ["NKDA"],
    code: "Full Code",
    isolation: "Standard",
    weight: "88.2 kg", height: "182 cm", bsa: "2.10",
    problems: ["Acute pancreatitis", "Hypertriglyceridemia", "Obesity"],
    meds: ["LR 125 ml/h IV", "Hydromorphone PCA", "Ondansetron 4mg IV q6h PRN"],
    attending: "Dr. K. Almeida",
    care_team: ["RN: D. Park", "Pharm: S. Vega"]
  },
  {
    fin: "FIN-2026-008301",
    mrn: "CY-66019823",
    name: "Aaliyah Robidoux",
    dob: "1996-12-03",
    age: 29, sex: "F", pronouns: "she/her",
    location: "L&D-2",
    los: "Active labor",
    status: "OB · Active labor",
    allergies: ["NKDA"],
    code: "Full Code",
    isolation: "Standard",
    weight: "76.0 kg", height: "168 cm", bsa: "1.85",
    problems: ["G2P1 39w3d", "GBS positive"],
    meds: ["Penicillin G 5 MU IV ×1, then 2.5 MU q4h"],
    attending: "Dr. N. Hartwell",
    care_team: ["RN: L. Silvera"]
  }
];

window.CYRUS_WORKLIST = [
  { unit:"ICU-3", bed:"04", patient:"Wojciechowska, H.", acuity:5, los:"6d", status:"Vitals due", task:"q1h vitals", flag:"high" },
  { unit:"ICU-3", bed:"02", patient:"Vasquez, R.", acuity:4, los:"3d", status:"Med due 09:00", task:"Vanco trough", flag:"med" },
  { unit:"MS-6", bed:"12", patient:"Eklund-Marsh, T.", acuity:2, los:"1d", status:"Lipase pending", task:"Pain reassess", flag:"" },
  { unit:"MS-6", bed:"08", patient:"Liang, B.", acuity:2, los:"2d", status:"Stable", task:"Discharge prep", flag:"" },
  { unit:"L&D-2", bed:"—", patient:"Robidoux, A.", acuity:3, los:"4h", status:"Active labor", task:"FHR strip", flag:"high" },
  { unit:"MS-6", bed:"15", patient:"Almasri, F.", acuity:3, los:"5d", status:"NPO post-op", task:"PT eval", flag:"med" }
];

window.CYRUS_ORDERSETS = [
  { name:"Sepsis 1-Hour Bundle", count:9, pop:"Adult ICU", evidence:"SCCM 2024" },
  { name:"DKA Initiation Pathway", count:14, pop:"Adult", evidence:"ADA 2025" },
  { name:"AMI / STEMI Pathway", count:11, pop:"ED → Cath Lab", evidence:"AHA 2024" },
  { name:"Stroke Code (TPA Eligible)", count:13, pop:"ED Adult", evidence:"AHA/ASA 2025" },
  { name:"Post-op Cholecystectomy", count:8, pop:"Surgical", evidence:"ERAS 2025" },
  { name:"Community-Acquired Pneumonia", count:10, pop:"Adult Inpt", evidence:"ATS/IDSA 2024" }
];

window.CYRUS_FLOWSHEET_GROUPS = [
  { name:"Vitals", expanded:true, rows:[
    { k:"Temp °C", values:["36.7","37.1","37.4","37.6","38.1","38.4"], ref:"36.5–37.5" },
    { k:"HR", values:["94","98","104","112","118","124"], ref:"60–100" },
    { k:"BP (MAP)", values:["108/62 (77)","102/58 (73)","98/56 (70)","92/52 (65)","86/48 (61)","82/46 (58)"], ref:"MAP > 65" },
    { k:"SpO₂", values:["94","94","93","92","91","90"], ref:">94" },
    { k:"RR", values:["18","20","22","24","26","28"], ref:"12–20" }
  ]},
  { name:"Hemodynamics", expanded:true, rows:[
    { k:"Norepi mcg/kg/min", values:["0.04","0.04","0.06","0.06","0.08","0.10"], ref:"titrate" },
    { k:"Lactate", values:["1.8","—","2.4","—","3.6","—"], ref:"<2.0" },
    { k:"Urine output ml/hr", values:["55","48","40","32","28","22"], ref:">30" }
  ]},
  { name:"Ventilation", expanded:false, rows:[] },
  { name:"Lines & Drains", expanded:false, rows:[] },
  { name:"I&O", expanded:false, rows:[] }
];

window.CYRUS_LABS = [
  { panel:"BMP", time:"06:30", values:[
    { name:"Na", v:"138", ref:"135–145", flag:""},
    { name:"K", v:"5.4", ref:"3.5–5.1", flag:"H"},
    { name:"Cl", v:"104", ref:"98–107", flag:""},
    { name:"CO₂", v:"18", ref:"22–29", flag:"L"},
    { name:"BUN", v:"42", ref:"7–20", flag:"H"},
    { name:"Cr", v:"2.1", ref:"0.6–1.1", flag:"H"},
    { name:"Glu", v:"148", ref:"70–110", flag:"H"}
  ]},
  { panel:"Lactate", time:"07:42", values:[
    { name:"Lactate", v:"3.6", ref:"<2.0", flag:"HH"}
  ]},
  { panel:"Procalcitonin", time:"08:15", values:[
    { name:"PCT", v:"4.8", ref:"<0.5", flag:"HH"}
  ]}
];
