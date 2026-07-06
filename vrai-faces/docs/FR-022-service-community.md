# FR-022 — SERVICE COMMUNITY (geospatial patient modeling + service-population faces)

**Priority:** P2 (feature) · **Status:** **Proposed / planning note** (filed 2026-07-05 from operator
directive) · **Effort:** L–XL · **Lands in:** V8 instructor control interface + FACE ENGINE (FACE
GENERATOR) integration · **Depends on:** FACE ENGINE geo/matrix/condition modules (built), FR-013
local-context layer, Scenario Studio (FR-013b).

> This is a **note in planning**, not a spec. It captures the concept, what already exists to build
> on, where it lives in the UI, and how it interfaces the FACE GENERATOR + geospatial modeling.

## 1 · Goal

Give the **instructor** a tool that models the **service community** where students do their clinical
rotations — the real local population — so simulations reflect the clinical reality students will
actually meet. A "service community" is defined once per site/course and then **feeds both the clinical
content and the visual makeup** of the simulated patients.

## 2 · The two sections

**A. Clinical context — what conditions are seen here (geospatial patient modeling).**
A geospatial patient-modeling system generates the **local clinical context**: which conditions and
acuity patterns are prevalent in this community's population, so scenarios and patient charts are drawn
from the epidemiology of the actual catchment area (not a generic textbook mix). This is the "what
walks through the door here" layer, and it seeds patient/scenario generation with local prevalence.

**B. Visual representation — who this community looks like (FACE GENERATOR).**
A representative **synthetic population of faces** matched to the community's demographic mix (age, sex,
ancestry distribution), so the patient avatars visually resemble the people students will serve. Clinical
signs can be rendered onto those faces (jaundice, pallor, edema, rashes, etc.) via the FACE ENGINE
Condition Editor so appearance and condition stay coherent.

## 3 · What already exists to build on (FACE ENGINE review, 2026-07-05)

The FACE GENERATOR project (`.../Projects/MedSim VRAI-FACE GENERATOR/`, Phase-1 complete, 83 tests
green) already implements most of the machinery this feature composes:

- **M16 geo — geospatial community profiler** (`backend/geo/`), consuming a **GPM (Geospatial Patient
  Modeling)** toolkit (`reference/Geospatial_Patient_Modeling_Report.*`). API: `GET /api/geo/resolve`
  (place → geocode), `GET /api/geo/profile` (place → demographic/clinical profile), `POST /api/geo/generate`
  + `POST /api/geo/cohort` (build a demographically-matched cohort), `GET /api/geo/fixtures`.
- **M1 matrix** — demographic axes, palettes, cohort sampler (the "who looks like this community" engine).
- **Condition Editor** — renders **151 condition presets across 11 clinical groups** onto a synthetic
  face as a new, lineage-linked, watermarked library entry (same synthetic person, contained edits).
  `condition_taxonomy.json` is the taxonomy.
- **Operator UI already has a "Community" tab** (React+Vite: Generate / **Community** / Library).
- **V8 integration path exists:** `M15 /api/vrai/request` control adapter + **M13 V8 export** (has
  already delivered a real face onto persona P-001 in `medsim_v8`).
- **Governance baked in:** AI-generated visible label (EU AI Act Art. 50 / India SGI), C2PA +
  invisible watermark, real-face similarity rejection, RBAC + audit, EU/India data-residency discipline.

**Net:** the geo profiler, the demographic matrix, the condition renderer, the community UI, and the V8
export bridge are **built**. SERVICE COMMUNITY is primarily a **V8-side composition + instructor UX**,
not new generative infrastructure.

## 4 · Where it lives — the instructor control interface

A new **"Service Community"** area in the V8 instructor interface (a section in Mission Control **Set up**,
next to ⚙ Local context and ✨ Scenario Studio — it is a sibling "context" tool). It should let the
instructor:
1. **Define / import the localized context** — pick or enter the community (place / catchment / an
   imported profile), review the returned geospatial profile (demographic mix + prevalent conditions),
   and adjust/curate it. This is the logical place to *develop and import* the localized context.
2. **Section A — Clinical context:** review + tune the local condition/acuity prevalence; save it as a
   context overlay that Scenario Studio + patient generation draw from (extends FR-013 local-context).
3. **Section B — Service population:** generate the representative face cohort for this community and
   review it in a gallery; these become the pool the wizard assigns patient/character faces from, with
   optional condition rendering.
4. **Bind to a course/site** so every session built for that site inherits its community context.

## 5 · How it interfaces the FACE GENERATOR + geospatial modeling

V8 (the on-prem portal) calls the FACE ENGINE service (standalone, its own API on :8790) through the
existing bridge, so V8 never re-implements generation:

- **Resolve + profile the community:** V8 → `GET /api/geo/resolve` then `GET /api/geo/profile` → the
  local demographic + clinical profile (Section A's prevalence + Section B's demographic targets).
- **Generate the population:** V8 → `POST /api/geo/generate` / `/api/geo/cohort` → a demographically
  matched face cohort; faces land in the FACE ENGINE library.
- **Render clinical signs (optional):** Condition Editor on selected faces → condition-rendered variants.
- **Deliver into V8:** `M15 /api/vrai/request` control adapter + `M13` export → faces attach to V8
  personas/skins (the same path that put a face on P-001), reachable from the **Avatar skins** library and
  the wizard swatch strips (see Operator Guide Part II).
- **Local clinical context:** the geo profile's prevalence feeds the **FR-013 local-context overlay** +
  Scenario Studio so generated scenarios/patients reflect local epidemiology.

Config: V8 needs a `FACE_ENGINE_BASE_URL` (+ its RBAC token) to reach the service; when unset the
Service Community area is hidden (progressive disclosure), matching the existing hidden-if-absent pattern.

## 6 · Open questions / decisions (for a later spec)

- **Data source & fidelity of the GPM model** — which datasets drive local prevalence (public health /
  census), and the honesty bar for "local context" (representative, not a claim about real individuals).
- **Residency & consent posture** for community faces (FACE ENGINE already enforces EU/India residency
  + AI labeling — confirm it carries through V8 display).
- **Where the condition prevalence plugs in** — as an FR-013 overlay, a Scenario Studio input, or both.
- **Coupling:** is FACE ENGINE a required dependency for a site, or an optional add-on (recommend
  optional / flag-gated so V8 runs without it).
- **Deployment:** FACE ENGINE is a separate service — on-prem alongside V8, or a shared instance.

## 7 · Acceptance sketch (thin MVP)

Instructor opens **Service Community**, enters a community, sees its geospatial profile (demographic mix
+ top local conditions), generates a small representative face cohort, and saves it as the site's context;
a session built for that site pulls patient faces from that cohort and its scenarios reflect the local
condition prevalence. FACE ENGINE governance (AI label, watermark, audit) is intact end-to-end.

**Detailed development & coding plan:** `FR-022-service-community-DEVELOPMENT-PLAN.md` (architecture, community-block schema, phased P0–P6 V8-first build, V9 migration leg, + appendices: US/EU/India declaration, provenance model, block format, data-sources catalog).
