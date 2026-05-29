// MEDSIM V5 — EHR theme layers.
//
// One functional EHR engine (_core/ehr_app.jsx) is themed into the three
// records systems by this table. A theme sets the palette, the typeface,
// and the per-tab labels so Helix / Cyrus / Meridian read as distinct
// products without three separate codebases.
//
// The engine reads window.MEDSIM_THEMES[ window.MEDSIM_V3.EHR_ID ].

window.MEDSIM_THEMES = {
  helix: {
    id: "helix",
    name: "Helix Health",
    subtitle: "Epic-style",
    font: "Inter, system-ui, sans-serif",
    colors: {
      brand: "#143b8a", brandInk: "#0a234f", accent: "#c47a04",
      bg: "#eef1f7", panel: "#ffffff", ink: "#0c1733", ink2: "#3a4a6b",
      ink3: "#6b7896", line: "#dde2ee", ok: "#1f7a3a", warn: "#c47a04",
      danger: "#a02437", bandFrom: "#143b8a", bandTo: "#0a234f",
    },
    tabs: {
      summary: "Chart Review", vitals: "Vitals", notes: "Notes",
      orders: "CPOE", results: "Results", mar: "MAR",
    },
  },
  cyrus: {
    id: "cyrus",
    name: "Cyrus Care",
    subtitle: "Cerner-style",
    font: "Inter, system-ui, sans-serif",
    colors: {
      brand: "#0e4c5e", brandInk: "#0b3454", accent: "#247aa5",
      bg: "#eaeef2", panel: "#ffffff", ink: "#0b3454", ink2: "#37536b",
      ink3: "#6c8497", line: "#cfdae3", ok: "#2b7a2b", warn: "#c48f1a",
      danger: "#b13b3b", bandFrom: "#0e4c5e", bandTo: "#0b3454",
    },
    tabs: {
      summary: "Patient Summary", vitals: "iView Flowsheet", notes: "PowerNote",
      orders: "PowerOrders", results: "Results Review", mar: "MAR",
    },
  },
  meridian: {
    id: "meridian",
    name: "Meridian EHR",
    subtitle: "Meditech-style",
    font: "Inter, system-ui, sans-serif",
    colors: {
      brand: "#4a7556", brandInk: "#33503c", accent: "#b78b2b",
      bg: "#f0ede3", panel: "#ffffff", ink: "#1f2a26", ink2: "#39463f",
      ink3: "#6b7770", line: "#dad3c2", ok: "#3b6e3b", warn: "#b78b2b",
      danger: "#a3543b", bandFrom: "#4a7556", bandTo: "#33503c",
    },
    tabs: {
      summary: "Chart", vitals: "Vitals", notes: "Document",
      orders: "Orders", results: "Results", mar: "MAR",
    },
  },
};
