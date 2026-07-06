# Service Community Module — Development Plan

**Project:** TrainingBridge / MedSim VRAI — **Service Community (FR-022)**
**Author:** Tech Lead
**Version:** 1.0 (codeable)
**Date:** 2026-07-05
**Sequencing directive:** Build **alongside V8 first** as a standalone service, link into V8 once tested/validated, then evaluate a **V9 cloud variation** as a later leg.

---

## 1. Overview & Principles

### 1.1 What we are building

The **Service Community module** lets an instructor model the *real clinical community* a cohort trains in — its **condition prevalence** (what illnesses/acuity actually occur locally) and its **demographic + visual makeup** (who the patients are, so avatars resemble the community) — and inject that context into MedSim simulations. It produces a portable, signed **community-block** consumed by V8 today and V9 later.

The module has two data planes that the research defines precisely and this plan wires together:

- **Clinical plane** — geospatial patient modeling (GPM) → locally prevalent conditions → scenario/case weighting.
- **Visual plane** — demographically-matched **synthetic** face cohorts (via FACE ENGINE) → avatars that look like the community.

Both planes are wrapped in the same governance envelope: a per-dataset **Sanitization & Data Declaration**, a per-element **Provenance / Source Declaration**, and a **standard community-block** exchange format.

### 1.2 Core principles

1. **Aggregate-only, no-PII by construction.** The community-block schema **cannot carry patient-level rows** — it is population statistics, public/aggregate sources, and synthetic targets only. `sanitization.contains_pii` is a hard `const:false` invariant; import fails closed on anything else. This is enforced at the schema layer, not by policy alone.
2. **Honest data, always labeled.** Every value declares its epistemic nature via a single load-bearing `source_type` enum: `factual-public | factual-nonpublic | hypothetical | expert-estimate`. Gap-fill is *allowed and expected*, but a filled gap is never dressed up as a source. Hypothetical data **must never claim a DOI** (false-provenance guard); synthetic faces always carry the visible "AI-GENERATED" label + C2PA marking inherited from FACE ENGINE.
3. **Provenance is a first-class product, not an afterthought.** Every element and every block can produce a machine-checkable reference list on demand (schema.org/Dataset JSON-LD + PROV-JSON), gated by a validator that fails on un-cited factual claims, dangling lineage, or missing stewards.
4. **Declare before you use.** No dataset enters a block without a completed Sanitization Declaration that satisfies **US (HIPAA), EU (GDPR), and India (DPDP 2023) simultaneously**, with a clear split between **[SELF]** (trained-instructor-attestable) and **[LEGAL]** (counsel/DPO/expert-required) fields.
5. **Robust, stable, easy to navigate.** Standalone service (independent deploy/restart, matches FACE ENGINE ops pattern), a linear declaration wizard, a gallery for reuse, and a versioned schema so blocks made today still import next year.
6. **Build on what exists.** GPM/M16, the demographic matrix (M1), the Condition Editor (151 presets/11 groups), the Community tab, `/api/geo/*`, the V8 export bridge, the C2PA/watermark/audit stack — all reused. The **new** work is: the condition-prevalence layer, the declaration/provenance capture, the block builder + export/import + signing, the instructor UI, and the V8 adapter.
7. **Standalone-first, contract-coupled.** V8 (and later V9) couple to the module through a **versioned contract + per-product adapter** — never internals — mirroring the identity-keystone pattern already used across the ecosystem.

### 1.3 Non-goals (v1)

- No patient-level data ingestion, ever.
- No generation of net-new clinical case *content* — v1 does **prevalence-weighted selection** from the existing case library (new-case generation deferred).
- No production DataCite DOI minting in v1 (internal persistent URIs `tbsim:…`; DOI minting is an open decision, §10).
- V9 cloud is **evaluation + handover only** in this plan; it is not implemented here.

---

## 2. Architecture

### 2.1 Shape: standalone service alongside V8, reusing the FACE ENGINE service pattern

The Service Community module is delivered as a **module inside the existing FACE ENGINE repo/service** (`github.com/medsim-vrai/face-engine`), not a separate deployable. Rationale: the two data planes it needs — GPM and face-cohort generation — already live there, so co-locating avoids a network hop for the module's core loop and reuses the service's audit/RBAC/C2PA stack verbatim. It is exposed under a **new FastAPI router** and a **new frontend tab**, and it stands alongside V8 exactly as FACE ENGINE already does.

```
┌────────────────────────────────────────────────────────────────────┐
│  FACE ENGINE service  (FastAPI, uvicorn :8790  +  React/Vite :5199) │
│                                                                      │
│  EXISTING (reused)                    NEW (Service Community, FR-022)│
│  ─────────────────                    ──────────────────────────────│
│  backend/geo/*        (GPM/M16)  ───▶ backend/community/             │
│  backend/matrix/*     (M1)            ├─ prevalence.py   (cond layer)│
│  backend/generate/*   (faces)         ├─ declaration.py  (sanitize)  │
│  backend/conditions/* (151 presets)   ├─ provenance.py   (sources)   │
│  backend/safety/*     (C2PA/wm)  ───▶ ├─ block.py        (builder)   │
│  backend/audit/*      (hashchain)     ├─ ingest.py       (gap-fill)  │
│  backend/export/vrai_bridge.py   ───▶ ├─ exchange.py     (imp/exp)   │
│  backend/store/*      (SQLite)   ───▶ ├─ signing.py glue (JCS+JWS)   │
│                                       └─ api/community.py (router)   │
│                                                                      │
│  frontend/  CommunityTab.tsx     ───▶ frontend/ ServiceCommunity/*   │
└────────────────────────────────────────────────────────────────────┘
                    │  versioned contract (community-block v1)
                    │  + service-token Bearer
                    ▼
┌──────────────────────────┐            ┌──────────────────────────────┐
│  V8 (medsim_v8, on-prem) │  later ──▶ │  V9 (MedSim VRAI CLOUD)       │
│  portal/community_adapter│            │  cloud adapter, multi-tenant  │
│  imports community-block │            │  (evaluation/handover only)   │
└──────────────────────────┘            └──────────────────────────────┘
```

Run (unchanged from FACE ENGINE): `cd repo && . .venv/bin/activate && uvicorn backend.app:app --port 8790` + `cd frontend && npm run dev`. New router registered in `backend/app.py` alongside the existing `geo`, `generate`, `conditions`, `vrai` routers.

### 2.2 How V8 links to it

V8 is coupled through a **thin adapter + a versioned contract**, never FACE ENGINE internals:

- **Contract:** the `community-block/1.0.0` JSON Schema (§3) is the sole interface. V8 validates any block it imports against the schema it ships.
- **Adapter (new, V8-side):** `medsim_v8/portal/community_adapter.py` — pulls or receives a community-block, validates it, verifies its `integrity` (JCS re-hash + optional JWS), rejects on `contains_pii ≠ false` or unknown-major `spec_version`, then projects the block onto V8's existing surfaces:
  - `clinical_prevalence[]` → scenario/case **weighting** in the authored-content / scenario layer (`authored_content.py`, scenario selection).
  - `demographics` + `face_cohort_spec` → a face-cohort request to FACE ENGINE via the **already-built** `request_face_from_engine()` path (`vrai_faces.py`, `POST /portal/face/request-engine/...`) and the M15 control adapter (`POST /api/vrai/request` → drop-file into V8).
  - block metadata + provenance → a read-only "Community context" panel in the V8 portal.
- **Transport:** two supported modes — (a) **file exchange** (educator exports a `.tbcb.json` block, imports into V8; zero network), and (b) **service-to-service** pull from FACE ENGINE with a **service-token Bearer** on the contract route (consistent with the ecosystem's contract-route auth). File exchange is the v1 default (robust, offline-friendly, matches how educators actually share).

**Sequencing guard:** the V8 adapter is built and validated against fixtures **before** any live V8↔service wiring is switched on. Link only after the block round-trips cleanly in isolation (P4).

### 2.3 The V9 cloud variation (later leg)

V9 gets its **own adapter**, not a fork of the module. Because the block is transport-agnostic and residency-neutral (aggregate/public/synthetic only), the same `community-block/1.0.0` contract carries into V9 unchanged. What changes for cloud is *around* the block, not the block: multi-tenant scoping, object-store residency, per-tenant signing keys, and the contract-hub coupling (identity keystone). Detailed in §11.

---

## 3. The Community-Block Data Model

The single portable artifact is the **community-block**: an aggregate-only, versioned JSON document consumed by V8 and V9 and shareable between educators. It embeds the demographic mix, condition prevalence, face-cohort spec, the sanitization declaration, and the provenance/source list. **Invariant: no patient-level rows, ever.**

### 3.1 Schema location & versioning

- Canonical schema: `backend/community/schemas/community-block/1.0.0.json` (JSON Schema Draft 2020-12), `$id: https://tbsim.company/schemas/community-block/1.0.0.json`, `format: "tbsim.community-block"`.
- **Two independent SemVer axes:**
  - `spec_version` — the schema. Consumers **route on major**: accept same-major, reject unknown-major, tolerate unknown minor/patch (forward-compat: additive-only within a major; `additionalProperties:false` on core objects means new fields ship as a minor bump + relaxed sub-objects).
  - `identity.block_version` — the *content* revision; `identity.block_id` (UUID) is stable across revisions of the same community; `identity.supersedes` links a revision to what it replaces.

### 3.2 Top-level structure (required unless noted)

| Key | Purpose | Standard anchor |
|---|---|---|
| `format` / `spec_version` | Identity + schema routing | SemVer |
| `identity` | `block_id`, `block_version`, `name`, `created_at`, `created_by` (org/role, **no PII**), `supersedes`, `tags` | — |
| `geography` | `scope` (nation…zcta/hsa/custom), `label`, `gazetteer` (FIPS/GEOID/ISO), `boundary` | **GeoJSON RFC 7946**, WGS84/CRS84 only, **no `crs` member** |
| `demographics` | `population_estimate` (count, not a member list), `as_of`, `strata[]` | FHIR MeasureReport `stratifier.stratum` shape |
| `clinical_prevalence[]` *(opt)* | per condition: `condition` (CodeableConcept), `measure` (`prevalence_fraction`/`rate_per_100k`/`incidence_per_100k` + CI), optional `stratified_by[]`, `source_ref[]` | OMOP vocab pattern / FHIR CodeableConcept |
| `sdoh[]` *(opt)* | aggregate SDOH indices (SVI/ADI/uninsured %) — indices only | FHIR/gravity coding |
| `face_cohort_spec` *(opt)* | `cohort_size`, `targets[]` (axis/value/fraction), `derive_from_demographics`, `synthetic_only:const true` | FACE ENGINE M1 axes |
| `sanitization` | the no-PII declaration (§3.4) — **required** | §7 declaration |
| `provenance` | source list + per-element declarations (§3.5) — **required** | schema.org/Dataset + PROV-O + DataCite |
| `meta` *(opt)* | schema.org/Dataset projection for catalog/discovery | schema.org/Dataset |
| `integrity` *(opt but required for signed export)* | `canonicalization:"RFC8785"`, `hash_alg`, `content_hash`, optional detached `signature` (JWS) | RFC 8785 (JCS) + RFC 7515 |

Shared `$defs`: `CodeableConcept` (`system`/`code`/`display`), `Stratum` (`axis`/`value`/`fraction|count`, count `≥ min_cell_size` or null), `GeoJSON` (`Feature`/`FeatureCollection`, `not:{required:[crs]}`).

### 3.3 Two embedded declarations, co-located and mutually referential

Every block carries **two orthogonal declarations** that answer different questions and stay consistent by construction:

- **Sanitization** — *"Is this safe to expose?"* (it **is** a PROV `Activity` — `used` raw, `generated` exposed).
- **Provenance** — *"Where did this come from, can I cite it?"* (the PROV `Entity` + its `wasDerivedFrom`/`hadPrimarySource` edges).

They cross-reference (`SourceDeclaration.sanitization_ref` ↔ `SanitizationDeclaration`), roll up into the same block manifest, and — critically — when sanitization substitutes a synthetic value for a real one, the element's `source_type` **flips to `hypothetical`/`expert-estimate`** and the chain records the substitution, so the two can never silently disagree.

### 3.4 Embedded sanitization block (block-level roll-up)

```jsonc
"sanitization": {
  "contains_pii":   false,        // const:false — import MUST fail closed otherwise
  "aggregate_only": true,         // const:true — no patient-level rows
  "min_cell_size":  11,           // HIPAA-style k≥11 small-cell suppression
  "suppressed":     true,
  "method":         "small-cell-suppression+rounding",
  "synthetic_faces": true,
  "declared_at":    "…", "declared_by": "role:clinical-lead",
  "declaration_ref": "decl:…"     // → full cross-regime Declaration record (§7)
}
```
The block-level `sanitization` is the machine-enforced invariant; the full US/EU/India **Declaration** (§7, Sections A–G) is stored as a linked record and referenced by id, so the block stays small while the audit trail stays complete.

### 3.5 Embedded provenance (`sources[]` + per-element `SourceDeclaration`)

```jsonc
"provenance": {
  "sources": [{
    "id": "src-cdc-places-2024", "name": "CDC PLACES", "publisher": "CDC",
    "url": "https://…", "vintage": "2024", "license": "US-PD",
    "access": "aggregate-public", "retrieved_at": "2026-06-30T…"
  }],
  "generator": "gpm@1.4.0 / face-engine@0.9.0"
}
```
Each **stat** in `clinical_prevalence`/`sdoh`/`demographics` references a source via `source_ref[]`. Under the hood each referenced element carries a full `SourceDeclaration` (id, `source_name`, **`source_type`**, `citation`, `url`/`doi`, `retrieval_date`, `confidence` high|medium|low, `is_estimate`, `steward`, `derived_from[]`, `license`, `sanitization_ref`). `source_type` deterministically drives the PROV relation, the C2PA `digitalSourceType`, and the citation obligation:

| `source_type` | PROV relation | citation obligation |
|---|---|---|
| `factual-public` | `hadPrimarySource` | MUST have `url\|doi` + `retrieval_date` |
| `factual-nonpublic` | `wasDerivedFrom` + `wasAttributedTo` | MUST have `steward` + access note |
| `expert-estimate` | `wasAttributedTo` (the SME/panel) | MUST name expert + `is_estimate=true` |
| `hypothetical` | *(no source relation)* + `com.tbsim.synthetic{real_person:false}` | `is_estimate=true`; **MUST NOT carry a `doi`** |

### 3.6 Machine-checkable reference-list export (one source of truth, three serializations)

- **(a) schema.org/Dataset JSON-LD** — web-discoverable; `hasPart` per element, `isBasedOn` lineage, `citation`, `license`, `identifier`.
- **(b) PROV-JSON graph** — verifiable lineage; each `SourceDeclaration`→`prov:Entity`, `steward`→`prov:Agent` via `wasAttributedTo`, retrieval → `prov:Activity`.
- **(c) C2PA carrier** — when a block/element is exported *with an asset* (e.g., the face cohort), the same facts ride inside a `com.tbsim.provenance` custom assertion beside FACE ENGINE's existing `com.tbsim.synthetic` + `c2pa.actions`, with sources as C2PA `ingredients` — cryptographically bound and tamper-evident.

### 3.7 Types

The schema maps 1:1 to **pydantic v2** models (`backend/community/models.py`) for the service and to **TypeScript** interfaces (`frontend/ServiceCommunity/types.ts`) for the UI, generated from the same JSON Schema so drift is impossible.

---

## 4. Modules / Components

All new code lives under `backend/community/` (Python 3.14, FastAPI, pydantic v2) and `frontend/ServiceCommunity/` (React/Vite/TS), reusing existing service modules.

### 4.1 Ingestion + gap-fill with labels — `backend/community/ingest.py`

- **Inputs:** (a) GPM auto-pull (CDC PLACES `eav7-hnsx`, ACS via existing `geo/live.py`), (b) educator CSV/JSON upload of aggregate stats, (c) manual entry for gaps.
- **Gap-fill with mandatory labels:** any value not sourced from a public dataset must be entered as `hypothetical` or `expert-estimate`, and the UI **forces** `is_estimate=true` + `confidence` + a steward. This is how factual-nonpublic and hypothetical inputs fill local-population gaps *without* laundering their epistemic status.
- **Output:** normalized candidate elements, each a draft `SourceDeclaration`, staged for the block builder.
- **Endpoints:** `POST /api/community/ingest` (upload), `POST /api/community/ingest/manual`.

### 4.2 Declaration / provenance capture — `backend/community/declaration.py`, `backend/community/provenance.py`

- `declaration.py` — the cross-regime Sanitization Declaration (§7) as a pydantic model with Sections A–G, per-field `[SELF]`/`[LEGAL]` tagging, and a **gate**: if any `[LEGAL]` field is invoked, `legal_review_status` is required before the declaration can back an export.
- `provenance.py` — builds `SourceDeclaration` + `ProvenanceManifest`, computes `provenance_summary` (counts by `source_type`) and `weakest_link` (`min(confidence)` + un-cited factual elements), and emits the three serializations (§3.6). Reuses FACE ENGINE's `safety/provenance.py` conventions (`com.tbsim.*`, `confidence`, `is_estimate`, `ingredients`).
- **Validator** (`provenance.validate_block`) — hard-fails export if: a `factual-public` element lacks `url|doi`+`retrieval_date`; a `hypothetical` element carries a `doi`; any element lacks a `steward`; any `derived_from` is dangling; the block lacks the 6 DataCite mandatory properties; `sanitization.contains_pii ≠ false`; or any `[LEGAL]` field lacks legal sign-off. (Gate-vs-report is an open decision, §10 — default: **gate**.)

### 4.3 Geospatial profiler reuse — `backend/community/prevalence.py`

- Calls existing GPM: `geo/pipeline.resolve()` + `geo/profile.build_profile()` (place → `GeoResolution` + `CommunityProfile` with census/BRFSS/WHO strata). **No new geo code.**
- **New:** the condition-**prevalence layer** — maps resolved demographics → locally prevalent conditions using CDC PLACES + published prevalence tables, emitting `clinical_prevalence[]` entries with `measure`, CI, and `source_ref`. Ships a `prevalence_sources.json` reference set (public/aggregate only). Where local data is missing, prevalence entries are labeled `expert-estimate`/`hypothetical` per §4.1.

### 4.4 Block builder — `backend/community/block.py`

- Assembles `geography` (GeoJSON from GPM), `demographics` (strata), `clinical_prevalence`, `sdoh`, `face_cohort_spec` (derived from demographics or explicit targets), plus the embedded `sanitization` + `provenance`.
- Validates against the JSON Schema, runs the provenance validator, and stamps `meta`.
- **Endpoints:** `POST /api/community/blocks` (build/save), `GET /api/community/blocks`, `GET /api/community/blocks/{id}`, `POST /api/community/blocks/{id}/revision`. Persisted in the existing SQLite store (`backend/store/db.py`, new `community_block` table).

### 4.5 Export / import with signing — `backend/community/exchange.py`, `signing.py` glue

- **Export:** canonicalize block minus `integrity` per **RFC 8785 (JCS)** → SHA-256 → `content_hash` → optional detached **JWS** (EdDSA/ES256, reusing FACE ENGINE `certs/` dev chain) → write `integrity`. Emits `<name>.tbcb.json` + the reference-list serializations; when bundled with a face cohort, embeds `com.tbsim.provenance` into the C2PA manifest.
- **Import:** parse → schema-validate → route on `spec_version` major → verify `integrity` (JCS re-hash + JWS) → **fail closed** on `contains_pii ≠ false`, unknown major, dangling lineage, or broken hash.
- **Endpoints:** `POST /api/community/blocks/{id}/export`, `POST /api/community/import`.

### 4.6 V8 adapter — `medsim_v8/portal/community_adapter.py` (V8-side, new, uncommitted per pattern)

- Validates + verifies an imported block, then projects it: prevalence → scenario weighting; demographics/face_cohort → face request via existing `request_face_from_engine()`/M15 control adapter; provenance/meta → read-only portal panel.
- Guards: no-overwrite on existing portraits (already present), reject on schema/PII/integrity failure. Gated behind a config flag until P4 validation passes.

---

## 5. UI — Instructor "Service Community" area

New top-level tab `frontend/ServiceCommunity/` (React/Vite/TS), sibling to the existing `CommunityTab.tsx`, whose UX it ports and extends. Design goals: **linear, low-cognitive-load, hard to get wrong, upgradeable.**

### 5.1 Screens

1. **Gallery / home** — cards of saved community-blocks (name, place, population, `provenance_summary` badge, sanitization status, version). Actions: New, Open, Duplicate→revision, **Export**, **Import**. This is the "easy navigation" anchor — everything starts here.
2. **Define Service Area** — place search → GPM resolve → map (GeoJSON) + resolved demographic profile. One field, one result.
3. **Develop Context** — two panels: **Demographics** (editable strata) and **Condition Prevalence** (prevalence table, add/adjust, each row shows its `source_type` chip and confidence). Gap rows are visually distinct and force a label.
4. **Declaration flow** (the wizard, §5.2).
5. **Face Cohort** — derive targets from demographics or set explicit; trigger FACE ENGINE cohort; select faces (reuses Community tab picker + AI badge).
6. **Review & Export** — provenance summary, `weakest_link`, validator result (pass/fail with reasons), sign + export `.tbcb.json`.

### 5.2 The declaration flow (Sanitization + Provenance)

A **stepper** that mirrors research Sections A–G, one section per step, with inline `[SELF]`/`[LEGAL]` badges:

- **A** Identity & provenance → **B** Data nature/source/granularity (drives which later fields are mandatory) → **C** De-id method (Safe Harbor 18-item checklist is a literal checklist; Expert Determination flagged `[LEGAL]`) → **D** Re-id risk + small-cell check → **E** three jurisdiction attestations (US/EU/India, always all three) → **F** legal basis/consent (only if personal in any regime) → **G** sign-off.
- **Progressive disclosure:** hypothetical/aggregate paths collapse to a short path; individual-level factual data expands the full de-id + legal branch.
- **Legal gate:** any `[LEGAL]` field toggles a "Legal review required" banner and blocks final export until `legal_review_status` is filled.
- **Reusable:** a completed declaration is saved and can be attached to future blocks (dedup by dataset).

### 5.3 Navigation, robustness, upgradeability

- Persistent left nav (Gallery · Define · Develop · Declare · Faces · Review); breadcrumb; autosave drafts to the store (no lost work).
- Every destructive action confirmed; every block immutable once exported (new edits = new revision via `supersedes`).
- **Upgradeability:** the UI reads `spec_version` and renders a "schema vN" badge; unknown-minor fields are preserved on round-trip (never dropped), so newer blocks survive an older UI.

---

## 6. Reuse Map (build-on vs new)

| Capability | Home / file | Status | Action |
|---|---|---|---|
| Geo resolve/profile (GPM/M16) | `backend/geo/{pipeline,profile,live,model}.py`, `/api/geo/{resolve,profile}` | built | **reuse** as-is |
| Demographic strata (census/BRFSS/WHO) | `population_stratification_schema.md`, `backend/matrix/*` | built | **reuse** — block strata mirror it |
| Cohort face generation | `backend/generate/*`, `POST /api/geo/generate`, `/cohort` | built | **reuse** for `face_cohort_spec` |
| Condition presets (151/11 groups) | `backend/conditions/presets.py`, `/api/conditions` | built | **reuse** for on-face conditions |
| Community operator tab | `frontend/…/CommunityTab.tsx` | built | **port + extend** into ServiceCommunity |
| C2PA + watermark + `com.tbsim.*` | `backend/safety/{provenance,signing}.py` | built | **reuse** — provenance/sanitization assertions ride the same manifest |
| Hash-chain audit + RBAC | `backend/audit/*`, `OPERATOR_TOKENS` | built | **reuse** for declaration/export audit |
| SQLite store (FaceRecord) | `backend/store/{db,models}.py` | built | **extend** — add `community_block`, `declaration` tables |
| V8 export / drop-file / M15 | `backend/export/vrai_bridge.py`, `/api/vrai/request` | built | **reuse** for face delivery |
| V8 face request button | `medsim_v8/…/vrai_faces.py`, `POST /portal/face/request-engine/{cid}` | built (uncommitted) | **reuse** from adapter |
| **Condition-prevalence layer** | `backend/community/prevalence.py` | **NEW** | build |
| **Sanitization/Provenance capture** | `backend/community/{declaration,provenance}.py` | **NEW** | build |
| **Block builder + schema** | `backend/community/{block.py,schemas/…}` | **NEW** | build |
| **Export/import + signing (JCS/JWS)** | `backend/community/{exchange,signing}.py` | **NEW** | build |
| **Instructor UI** | `frontend/ServiceCommunity/*` | **NEW** | build |
| **V8 adapter** | `medsim_v8/portal/community_adapter.py` | **NEW** | build |

---

## 7. Governance & Compliance

### 7.1 Cross-regime declaration (US / EU / India — one record satisfies all three)

The declaration captures data **nature** (factual-public / factual-nonpublic / hypothetical), **granularity** (individual vs aggregate/community), **de-id method**, a **re-identification-risk statement**, and **three independent jurisdiction attestations** — because a dataset can be out-of-scope under HIPAA yet regulated under GDPR or DPDP. Key rules baked in:

- **HIPAA:** Safe Harbor (18 identifiers removed + actual-knowledge) is **[SELF]**; Expert Determination is **[LEGAL]**. Aggregate data is often outside PHI but still needs a stated basis + small-cell check.
- **GDPR:** anonymisation removes data from scope (Recital 26) but the bar is high (defeat singling-out/linkability/inference) and any "anonymous" reliance is **[LEGAL]**; **pseudonymisation is still personal data** (EDPB 01/2025) — never an out-of-scope claim.
- **DPDP 2023:** **no de-id safe harbor, no sensitive-data tier** — almost every scope/exemption claim is **[LEGAL]**; conservative default = treat as personal + document a lawful ground; the s.17 research exemption's safeguards were not fully notified as of 2026 (re-check before go-live).

**[SELF] vs [LEGAL] split** (keeps the module usable without over-promising): [SELF] = data-nature/source/granularity classification, the HIPAA 18-item checklist, actual-knowledge for Safe Harbor, small-cell check, steward sign-off. [LEGAL] = any anonymisation/Expert-Determination *claim*, GDPR Recital-26 reliance, all DPDP scope/exemption conclusions, every lawful-basis/consent field, and use of not-yet-public factual data.

### 7.2 Audit, residency, AI-labeling

- **Audit:** every declaration, block build, export, and import is written to the existing **hash-chained audit log** (`backend/audit/log.py`, `verify_chain` detects edits/deletes). Declarations are time-bound (re-review-due date), since re-identification risk drifts.
- **Residency:** v1 is on-prem/standalone; blocks are aggregate/public/synthetic only, so they carry no residency burden. V9 adds per-tenant residency (§11).
- **AI-labeling:** synthetic faces carry the visible "AI-GENERATED" label + DWT-DCT watermark + C2PA `com.tbsim.synthetic{real_person:false}` inherited from FACE ENGINE; the block's `face_cohort_spec.synthetic_only:const true` asserts no real portraits.

---

## 8. Phased Plan with Milestones

Each phase lists concrete coding tasks, deliverables, and tests. All work is additive; commit per milestone.

### P0 — Scaffold & schema (foundation)
- **Tasks:** create `backend/community/` package + `api/community.py` router (registered in `app.py`); author `schemas/community-block/1.0.0.json`; generate pydantic models (`models.py`) + TS types; add `community_block` + `declaration` tables to the store.
- **Deliverables:** schema file, models, router with `/api/health` extension reporting `community: enabled`.
- **Tests:** schema validates the canonical example + rejects a `contains_pii:true` block, a `crs`-bearing GeoJSON, and an unknown-major block; pydantic round-trips the example.

### P1 — Prevalence layer + ingestion + gap-fill
- **Tasks:** `prevalence.py` (GPM → conditions, `prevalence_sources.json`); `ingest.py` (CSV/JSON upload + manual entry with forced labels); wire `source_type` gap-fill rules.
- **Deliverables:** `POST /api/community/ingest`, `/ingest/manual`; prevalence for a fixture place (e.g., Hartford, already live in geo).
- **Tests:** prevalence produced for a fixture; manual gap entry forces `is_estimate`+steward; upload rejected if a factual row lacks a source.

### P2 — Declaration + provenance + validator
- **Tasks:** `declaration.py` (Sections A–G, [SELF]/[LEGAL] tagging, legal gate); `provenance.py` (SourceDeclaration, manifest, three serializations, validator).
- **Deliverables:** `POST /api/community/declarations`; reference-list export (JSON-LD + PROV-JSON).
- **Tests:** validator fails on un-cited factual / hypothetical-with-DOI / dangling lineage / missing steward / missing DataCite props / unsigned [LEGAL]; validator passes a clean block; JSON-LD + PROV-JSON validate.

### P3 — Block builder + export/import + signing
- **Tasks:** `block.py` (assemble/validate/persist/revision); `exchange.py` (JCS canonicalize, SHA-256, JWS sign, export/import); C2PA `com.tbsim.provenance` glue.
- **Deliverables:** build/export/import endpoints; `.tbcb.json` round-trips; signed + verified.
- **Tests:** JCS canonicalization is stable (byte-identical across key reorder); hash + JWS verify; import fails closed on tamper/PII/unknown-major; block→export→import→block is lossless (incl. unknown-minor field preservation).

### P4 — V8 link (the alongside→link step)
- **Tasks:** `community_adapter.py` (V8-side): validate/verify → project prevalence to scenario weighting + demographics/face_cohort to face request + provenance panel; config flag; face delivery via existing bridge.
- **Deliverables:** an imported block drives V8 scenario weighting + a matched face cohort + a read-only context panel, verified live on one community.
- **Tests:** adapter rejects bad blocks; end-to-end file-exchange import in V8; face cohort delivered via `request_face_from_engine`; no-overwrite guard holds.

### P5 — UI
- **Tasks:** `frontend/ServiceCommunity/*` — Gallery, Define, Develop, Declaration stepper, Face Cohort, Review/Export; port Community tab picker; autosave; schema-version badge.
- **Deliverables:** full instructor flow in browser, verified live.
- **Tests:** Playwright/RTL: new→define→develop→declare→faces→export→re-import happy path; legal gate blocks export; unknown-minor round-trip preserved in UI.

### P6 — Validation
- **Tasks:** end-to-end validation on 2–3 real communities; adversarial review of the validator + import fail-closed paths + declaration legal gate (same 4-lens pattern used on the Condition Editor); operator docs.
- **Deliverables:** validation report; hardened fixes; instructor guide + FAQ (mirror FACE ENGINE `docs/support/`).
- **Tests:** full regression green; audit chain verifies across the whole flow.

### P7 — V9 evaluation & handover (later leg)
- **Tasks:** §11 migration evaluation + handover checklist; **no V9 implementation** here.
- **Deliverables:** V9 migration memo + handover doc.

---

## 9. Testing & Validation Strategy

- **Schema conformance:** every fixture block validated against `1.0.0.json`; negative fixtures for each hard invariant (PII, `crs`, small-cell < k, unknown-major).
- **Property tests:** JCS canonicalization stability under key/whitespace permutation; hash/JWS verify; round-trip losslessness incl. forward-compat (unknown-minor preservation).
- **Provenance validator matrix:** one test per fail condition + a passing golden block; JSON-LD validated against schema.org, PROV-JSON against PROV-JSON schema.
- **Declaration logic:** [SELF]/[LEGAL] branching per data-nature/granularity path; legal gate blocks export.
- **Integration:** GPM reuse (real Hartford/live-census path), face-cohort delivery via existing bridge, V8 adapter projection.
- **Adversarial review (P6):** import fail-closed, false-provenance guard, concurrent block edits, empty/degenerate blocks — reusing the multi-lens review pattern proven on the Condition Editor.
- **Ops parity:** unit + `pytest` green (Python 3.14), `ruff` clean, `tsc` clean, matching the existing repo bar.

---

## 10. Risks & Open Decisions

1. **Identifier policy** — real DataCite DOIs (needs membership/allocator) vs internal `tbsim:…` URIs. *Default: internal URIs for v1; DOI minting deferred.*
2. **C2PA signing trust** — FACE ENGINE self-signs (untrusted). For third-party-provable provenance, a trusted/anchored credential + RFC-3161 TSA may be needed. *Default: structured-but-dev-signed for v1.*
3. **Validator: gate vs report** — hard-block export on un-cited factual elements (strict FORCE11 Evidence) vs emit-with-warning + audit entry. *Default: gate; revisit with instructors.*
4. **DPDP s.17 safeguards not fully notified (2026)** — the research exemption cannot be safely relied on until prescribed standards land; conservative default holds. **Re-check before go-live.**
5. **Synthetic-derived-from-real ambiguity** — AI faces trained on real datasets sit in unsettled legal territory across all three regimes; flagged [LEGAL], position technique/jurisdiction-dependent.
6. **UK divergence** — EDPB (strict) vs UK ICO ("motivated intruder"); if UK data/users are in scope, add a separate UK attestation rather than folding into "EU".
7. **v1 clinical-conditions scope** — prevalence-weighted selection vs new-case generation. *Default: selection.*
8. **Expert-estimate governance** — single SME vs Delphi panel; whether low-confidence estimates need a second steward. *Open.*
9. **V8↔service transport** — file exchange (default) vs service-to-service pull with service-token. *Default: file-first, service optional.*

---

## 11. V9 Migration Evaluation (later leg)

### 11.1 What carries unchanged
- The **community-block contract** (`community-block/1.0.0`) — transport- and residency-neutral by design; the same schema, validator, and export/import serve V9.
- **Aggregate-only / no-PII invariant** — makes the block cloud-safe: no residency burden on the block itself.
- **Provenance + sanitization declarations**, the JCS/JWS integrity, and the reference-list export.
- The **module logic** (prevalence, block builder, exchange) — pure functions over the schema, portable as-is.

### 11.2 What changes for cloud / multi-tenant
- **Adapter, not fork:** V9 gets its own `community_adapter` coupling through the same contract via the **integration-hub / identity keystone**, not FACE ENGINE internals.
- **Multi-tenant scoping:** `block_id`/declarations become tenant-scoped; RBAC moves from `OPERATOR_TOKENS` to per-tenant roles under the keystone.
- **Residency & storage:** blocks move from SQLite/file to per-tenant object storage; signing keys become per-tenant (KMS), replacing the shared dev `certs/`.
- **Signing trust:** cloud is the moment to upgrade to a trusted/anchored C2PA credential + TSA (Risk #2).
- **Face delivery:** V9 avatar export target already exists in the bridge (`target:"v9"`); needs FACE ENGINE reachable cloud-side (Azure/AWS move, not GoDaddy) — a known deferred item.
- **Local-context tie-in:** V9's existing `/ui/local-context` should *consume* the block, not duplicate it.

### 11.3 Handover checklist
- [ ] `community-block/1.0.0` schema + validator packaged for V9 import (versioned, same-major).
- [ ] V9 `community_adapter` spec against the contract (no internals).
- [ ] Tenant-scoping + RBAC mapping to the keystone defined.
- [ ] Residency + per-tenant KMS signing plan.
- [ ] Trusted C2PA credential + TSA decision resolved (Risk #2).
- [ ] FACE ENGINE cloud reachability decided (for `target:"v9"` face delivery).
- [ ] DPDP s.17 / GDPR-EDPB status re-checked at V9 go-live (Risks #4, #6).
- [ ] Local-context consumption (not duplication) confirmed.
- [ ] Migration memo + audit-continuity plan (hash-chain across on-prem→cloud) delivered.

---

**Key file paths (grounding):**
- FACE ENGINE service: `/Users/petermarotta/Documents/Claude/Projects/MedSim VRAI-FACE GENERATOR/` — reuse `backend/geo/*`, `backend/matrix/*`, `backend/generate/*`, `backend/conditions/presets.py`, `backend/safety/{provenance,signing}.py`, `backend/audit/*`, `backend/store/*`, `backend/export/vrai_bridge.py`, `frontend/…/CommunityTab.tsx`.
- New module: `backend/community/` + `backend/api/community.py` + `frontend/ServiceCommunity/` + `backend/community/schemas/community-block/1.0.0.json`.
- V8 adapter: `/Users/petermarotta/Documents/Claude/Projects/Scenario structure to support character engagement/medsim_v8/portal/community_adapter.py` (reuse `vrai_faces.py`, `POST /portal/face/request-engine/{cid}`).
- Concept/feature docs: `MedSim VRAI-FACE GENERATOR/docs/SERVICE_COMMUNITY_feature-concept.md`, `medsim_v8/vrai-faces/docs/FR-022-service-community.md`.

---

# Appendices — research artifacts

*The concrete, citable artifacts produced by the research phase (web-grounded). These are the schemas and reference base the plan refers to; keep them versioned with the plan.*

---

# Appendix A — Sanitization & Data Declaration schema (US · EU · India)

## "Sanitization & Data Declaration" Schema

A single declaration an instructor completes per dataset used to build local-population medical-simulation context. Designed so one completed record satisfies **US (HIPAA), EU (GDPR), and India (DPDP Act 2023)** at once. Field-level legend: **[SELF]** = self-attestable by a trained instructor; **[LEGAL]** = legal-review-required before the declaration can be relied on for that condition.

---

### Section A — Identity & Provenance

| # | Field | What the user must state | Notes / Regime hook |
|---|-------|--------------------------|---------------------|
| A1 | **Declaration ID / version** | Unique ID + version number | Enables audit trail; re-declare on any material change |
| A2 | **Data Steward** | Named individual + role + org + contact accountable for this dataset | GDPR "controller" locus; DPDP "Data Fiduciary" accountability (s.8); HIPAA workforce accountability |
| A3 | **Declaration date** + **review-due date** | Date signed; date for re-evaluation | HIPAA Expert Determination and GDPR anonymisation are time-bound (re-identification risk drifts as external data grows) |

### Section B — Data Nature & Source

| # | Field | What the user must state | Notes / Regime hook |
|---|-------|--------------------------|---------------------|
| B1 | **Data nature** (pick one) | (a) **Factual — public** (already lawfully published), (b) **Factual — not-yet-public** (real but unpublished/embargoed/internal), (c) **Hypothetical / synthetic** (invented or generated, not derived from real individuals) | Drives which downstream fields are mandatory. (c) largely escapes all three regimes **if** genuinely non-derived; **[LEGAL]** if synthesized *from* real records |
| B2 | **Granularity** (pick one) | (a) **Individual-level** (about identifiable persons), (b) **Aggregate / community-level** (counts, rates, prevalence by group/geo), (c) **Mixed** | Individual-level triggers full de-id analysis; aggregate is often outside HIPAA PHI but still needs a stated basis (small cells can re-identify) |
| B3 | **Source & type** | Origin (registry, census/health-authority open data, EHR extract, literature, instructor knowledge, AI-generated), URL/citation or internal reference, and collection date | Establishes lawful origin; needed for GDPR "reasonably available information" and DPDP publicly-available analysis |
| B4 | **Population / geography described** | The cohort and smallest geographic unit represented | Small geo + small cohort = re-identification risk even in aggregates; feeds B2 and E-fields |

### Section C — De-identification / Sanitization Method

| # | Field | What the user must state | Notes / Regime hook |
|---|-------|--------------------------|---------------------|
| C1 | **Method applied** (pick one+) | (a) **HIPAA Safe Harbor** — all 18 identifiers removed, (b) **HIPAA Expert Determination** — qualified expert certified "very small" risk, (c) **GDPR-grade anonymisation** — irreversible; resists singling-out/linkability/inference, (d) **Pseudonymisation only** (key exists → still personal data), (e) **Not applicable** (data never contained personal data — B1=c or B2=b aggregate) | See mapping table below |
| C2 | **Safe Harbor checklist** (if C1=a) | Confirm removal of each of the 18 identifiers (names; geo < state incl. ZIP unless first 3 digits of a >20,000-pop area; all date elements except year + age 90+ collapsed; phone; fax; email; SSN; MRN; health-plan #; account #; cert/license #; vehicle IDs; device IDs; URLs; IP; biometric; full-face photos; **any other unique identifying number, characteristic, or code**) **[SELF]** | 45 CFR 164.514(b)(2). Instructor can self-check the list |
| C3 | **Expert / statistical basis** (if C1=b or c) | Name/qualifications of expert, method, risk metric, and signed determination reference **[LEGAL]** | 164.514(b)(1) requires a person with statistical expertise; GDPR anonymisation claim needs equivalent rigor |
| C4 | **Transformations performed** | Generalization, suppression, aggregation, noise/perturbation, k-anonymity/date-shifting etc. | Evidence the three GDPR attacks were addressed |

### Section D — Re-identification-Risk Statement

| # | Field | What the user must state | Notes / Regime hook |
|---|-------|--------------------------|---------------------|
| D1 | **Residual-risk assessment** | Narrative: could a "motivated intruder"/anticipated recipient re-identify anyone, alone or combined with **reasonably available** other data? Rate very-small / low / residual | HIPAA "very small"; GDPR Recital 26 "means reasonably likely to be used"; WP29 05/2014 three risks |
| D2 | **Actual-knowledge attestation** | "I have no actual knowledge the retained data could identify an individual." **[SELF]** if C1=a; **[LEGAL]** otherwise | 164.514(b)(2)(ii) actual-knowledge clause |
| D3 | **Small-cell / aggregate check** | For aggregate data: confirm no cell is small enough to isolate an individual (e.g., minimum cell size / rare-attribute suppression) **[SELF]** | Aggregate ≠ automatically safe |

### Section E — Jurisdiction Attestations (all three, always)

| # | Field | What the user must state | Legend |
|---|-------|--------------------------|--------|
| E1 | **US / HIPAA** | Either "Data is **outside HIPAA** because [no covered-entity/BA relationship OR never PHI OR aggregate non-PHI]" **[SELF]** *or* "Data **was PHI** and is de-identified via Safe Harbor **[SELF]** / Expert Determination **[LEGAL]**." | |
| E2 | **EU / GDPR** | Either "**Anonymous** under Recital 26 (data protection principles do not apply)" — **[LEGAL]** to rely on — *or* "**Personal/pseudonymised data**; lawful basis = [see F]." State that singling-out, linkability, inference were considered. | EDPB 04/2025 (anonymisation) & 01/2025 (pseudonymisation): pseudonymised data **remains** personal data |
| E3 | **India / DPDP 2023** | State one: "**Truly anonymised** → outside DPDP (identity cannot be inferred)" **[LEGAL]**; *or* "**Personal data**; ground = consent (s.4/6) **or** legitimate use (s.7)"; *or* "**Research/statistical exemption** (s.17(2)(b)) — no individual-level decisions + govt-prescribed safeguards." Note DPDP has **no sensitive-data tier and no statutory de-id safe harbor**. **[LEGAL]** | s.17 standards not yet fully notified (as of 2026) → conservative default |

### Section F — Legal Basis / Consent (only if any of B1=a/b AND data is personal in any regime)

| # | Field | What the user must state | Legend |
|---|-------|--------------------------|--------|
| F1 | **GDPR lawful basis** | Art. 6 basis (+ Art. 9 condition if health data) | **[LEGAL]** |
| F2 | **DPDP ground** | Consent + notice reference, or Section 7 legitimate use, or Section 17 research basis | **[LEGAL]** |
| F3 | **Consent / authorization evidence** | Reference to consent record or HIPAA authorization, where the basis is consent | **[LEGAL]** |
| F4 | **Not-yet-public data clearance** | If B1=b: confirmation of rights/permission/embargo compliance to use unpublished factual data | **[LEGAL]** |

### Section G — Sign-off

| # | Field | |
|---|-------|--|
| G1 | **Steward attestation & signature** | "The above is accurate to my knowledge; I will re-declare on material change." **[SELF]** |
| G2 | **Legal review status** | Reviewed-by / date, **required** whenever any **[LEGAL]** field was invoked | |

---

### Method → Regime mapping (reference)

| Chosen method (C1) | US / HIPAA | EU / GDPR | India / DPDP |
|--------------------|-----------|-----------|--------------|
| Safe Harbor (18 removed) | De-identified, not PHI **[SELF]** | Strong, but **not automatically** GDPR-anonymous; assess residual risk **[LEGAL]** | Assess against "identity cannot be inferred" **[LEGAL]** |
| Expert Determination | Not PHI if expert certifies "very small" **[LEGAL]** | Often aligns with anonymisation, still assess 3 risks **[LEGAL]** | As above **[LEGAL]** |
| GDPR-grade anonymisation | Meets/exceeds HIPAA de-id | Outside GDPR (Recital 26) **[LEGAL]** | Likely outside DPDP **[LEGAL]** |
| Pseudonymisation only | Still PHI (key exists) | **Still personal data** (EDPB 01/2025) | **Still personal data** | 
| N/A — aggregate/hypothetical | Likely outside HIPAA **[SELF]**, confirm small-cells | Outside GDPR if truly non-personal | Outside DPDP if identity not inferable |

### Self-attestable vs. legal-review-required — summary
- **[SELF] (trained instructor):** data-nature/source classification (B1–B4), Safe Harbor 18-item checklist (C2), actual-knowledge for Safe Harbor (D2), small-cell aggregate check (D3), HIPAA "outside scope / Safe Harbor" attestation (E1), steward sign-off (G1).
- **[LEGAL] (counsel/DPO/qualified expert):** Expert Determination or any anonymisation *claim* (C3), GDPR Recital-26 "anonymous" reliance (E2), **all** DPDP scope/exemption conclusions (E3), every lawful-basis/consent field (F1–F4), and any use of not-yet-public factual data (F4). Rule of thumb: **claiming data is out-of-scope of a regime, or relying on a consent/legitimate-use basis, is [LEGAL]; merely stripping the HIPAA 18 identifiers is [SELF].**

---

# Appendix B — Provenance / source-declaration model

## Provenance / Source-Declaration Model

A single reusable object — the **SourceDeclaration** — attaches to (a) any individual **data element** and (b) any **community-block** (a curated group of elements: a locality profile, a prevalence layer, a scenario dataset). It is a thin projection of five standards, chosen so nothing here is invented: every field maps to PROV-O, DataCite 4.5, schema.org/Dataset, FORCE11, or C2PA.

### 1. Core object — `SourceDeclaration` (per data element)

| Field | Type / enum | Standard mapping | Notes |
|---|---|---|---|
| `id` | URI / DOI / UUID | DataCite `Identifier`; FORCE11 *Unique Identification*; PROV-O `prov:Entity` | The provenance subject. Prefer a DOI; fall back to a persistent internal URI (`tbsim:elem/…`). Machine-actionable + globally unique. |
| `source_name` | string | DataCite `Creator`/`Publisher`; schema.org `creator`/`publisher` | Human-readable origin ("WHO Global Health Observatory", "SME panel 2026-Q2", "hypothetical for training"). |
| `source_type` | enum: `factual-public` \| `factual-nonpublic` \| `hypothetical` \| `expert-estimate` | (project epistemic layer) → drives PROV-O relation + C2PA `digitalSourceType` | **The load-bearing field.** See §2. Answers "is this real, and can I show the receipt?" |
| `citation` | string (formatted) | DataCite citation form: `Creator (Year): Title. Publisher.`; schema.org `citation`; FORCE11 *Evidence* | Rendered human citation. Auto-composed from the fields below. |
| `url` | URL | schema.org `url`/`sameAs`; DataCite `RelatedIdentifier` | Landing page or canonical location. |
| `doi` | DOI string | DataCite `Identifier`; FORCE11 *Persistence* | Persistent id where one exists (empty allowed for non-public/hypothetical). |
| `retrieval_date` | ISO-8601 date | DataCite `Date` with **`dateType="Accessed"`** (use `Collected` for primary observation) | When the value was pulled. Required for `factual-public`. |
| `confidence` | enum: `high` \| `medium` \| `low` | (reuses FACE ENGINE `confidence` vocab) | Quality/certainty of the value. Pairs with `is_estimate`. |
| `is_estimate` | boolean | (reuses FACE ENGINE `is_estimate` flag) | `true` ⇒ value is modeled/interpolated, not directly sourced. Auto-`true` for `expert-estimate`/`hypothetical`. |
| `quality_note` | string (opt) | schema.org `description` | Free-text caveat ("2019 data, extrapolated to 2026", "n<30"). |
| `steward` | string / ORCID / role | PROV-O `prov:wasAttributedTo` + `prov:Agent`; DataCite `Contributor` role=`DataManager`; FORCE11 *Credit and Attribution* | Accountable owner of this declaration (person, ORCID, or role e.g. `role:clinical-lead`). |
| `derived_from` | list of `id` | **PROV-O `prov:wasDerivedFrom`** / `prov:hadPrimarySource`; schema.org **`isBasedOn`** | Lineage to parent element(s). Enables the chain FORCE11 *Specificity & Verifiability* requires. |
| `license` | SPDX id / URL | schema.org `license`; DataCite `Rights` | Reuse terms of the source. |
| `sanitization_ref` | `id` of a `SanitizationDeclaration` | (project) | Cross-link to the sibling declaration — see §5. |

### 2. `source_type` — the epistemic enum (and how it drives the standards)

| `source_type` | Meaning | PROV-O relation emitted | C2PA `digitalSourceType` (IPTC) | Citation obligation |
|---|---|---|---|---|
| `factual-public` | Verifiable, publicly reachable fact (public dataset, stats agency, peer-reviewed) | `prov:hadPrimarySource` | `.../digitalsourcetype/dataDrivenMedia` | **MUST** have `url` or `doi` + `retrieval_date` |
| `factual-nonpublic` | Real but access-restricted (licensed feed, institutional record, private communication) | `prov:wasDerivedFrom` + `prov:wasAttributedTo` | `.../dataDrivenMedia` | MUST have `steward` + access note; `doi` optional |
| `expert-estimate` | SME judgement / Delphi / calibrated guess | `prov:wasAttributedTo` (Agent = the expert/panel) | `.../humanEdits` (or custom `com.tbsim.expertEstimate`) | MUST name the expert/panel in `source_name` + set `is_estimate=true` |
| `hypothetical` | Invented for training; no real-world referent | *(no source relation)* + `com.tbsim.synthetic:{real_person:false}` | `.../trainedAlgorithmicMedia` or `com.tbsim.hypothetical` | `is_estimate=true`, `confidence` reflects plausibility only; **must never claim a `doi`** |

This mirrors the FACE ENGINE, which already marks synthetic content with `com.tbsim.synthetic:{synthetic:true, real_person:false}` and an IPTC `digitalSourceType`. `hypothetical` here is the data-side twin of that image-side marking.

### 3. Community-block wrapper — `ProvenanceManifest` (per community-block)

A community-block gets one manifest that (a) carries block-level DataCite mandatory metadata and (b) **rolls up** the per-element declarations.

| Field | Standard mapping |
|---|---|
| `identifier` (DOI/URI) | DataCite `Identifier` (M) |
| `title` | DataCite `Title` (M); schema.org `name` |
| `creators[]`, `publisher`, `publicationYear` | DataCite `Creator`/`Publisher`/`PublicationYear` (M) |
| `resourceTypeGeneral` = `Dataset` | DataCite `ResourceType` (M) |
| `elements[]` → `SourceDeclaration.id` | schema.org `hasPart`; each element is a `prov:Entity` |
| `provenance_summary` | counts by `source_type` (e.g. `{factual-public: 12, expert-estimate: 3, hypothetical: 5}`) — the block's "receipt at a glance" |
| `weakest_link` | `min(confidence)` + list of un-cited `factual-*` elements → the block cannot pass export while any `factual-*` element lacks `url|doi`+`retrieval_date` |
| `c2pa_manifest` | the signed manifest (§4) |
| `sanitization_manifest_ref` | link to the block's sanitization roll-up (§5) |

### 4. Machine-checkable **reference-list export** (two serializations, one source of truth)

**(a) schema.org/Dataset + JSON-LD** — web-discoverable, human-citable. Each element becomes an entry; lineage uses `isBasedOn`; sources use `citation`; the block uses `Dataset` with `distribution`, `license`, `creator`, `identifier`. This is the form Google Dataset Search / FAIR tooling consumes.

```jsonld
{ "@context":"https://schema.org/", "@type":"Dataset",
  "name":"East-Region locality prevalence block v3",
  "identifier":"https://doi.org/10.xxxx/tbsim.block.eastreg.v3",
  "creator":[{"@type":"Organization","name":"TBSIM Service Community"}],
  "license":"https://spdx.org/licenses/CC-BY-4.0",
  "hasPart":[
    {"@type":"Dataset","name":"malaria seasonal incidence",
     "citation":"WHO GHO (2024): Malaria incidence. WHO.",
     "sameAs":"https://www.who.int/data/gho",
     "isBasedOn":"tbsim:elem/who-gho-malaria-2024",
     "additionalProperty":[
       {"@type":"PropertyValue","name":"source_type","value":"factual-public"},
       {"@type":"PropertyValue","name":"retrieval_date","value":"2026-06-30"},
       {"@type":"PropertyValue","name":"confidence","value":"high"},
       {"@type":"PropertyValue","name":"steward","value":"role:clinical-lead"}]}
  ]}
```

**(b) PROV-O / PROV-JSON graph** — the verifiable lineage graph. Every `SourceDeclaration` → `prov:Entity`; `steward` → `prov:Agent` via `wasAttributedTo`; `derived_from` → `wasDerivedFrom`/`hadPrimarySource`; `retrieval_date` → a `prov:Activity` (`prov:used` the external source, `prov:endedAtTime` = retrieval_date). This is what satisfies FORCE11 *Specificity & Verifiability*.

**Validator (the "if asked, prove it" gate)** — export MUST fail if any of:
- an element with `source_type ∈ {factual-public}` has no `url|doi` **or** no `retrieval_date` (FORCE11 *Evidence* + *Access*),
- an element with `source_type=hypothetical` carries a `doi` (false-provenance guard),
- any element lacks a `steward` (FORCE11 *Credit/Attribution*),
- any `derived_from` id is dangling (broken lineage),
- the block lacks the 6 DataCite mandatory properties.
Pass ⇒ emit both serializations + the C2PA-bound copy.

**(c) C2PA carrier** — when the block or element is exported *as/with an asset*, the same facts ride inside a `com.tbsim.provenance` custom assertion in the C2PA manifest, alongside the FACE ENGINE's existing `c2pa.actions` and `com.tbsim.synthetic` assertions, with source elements listed as C2PA `ingredients` (`relationship:"inputTo"`). This makes provenance cryptographically bound and tamper-evident, not just adjacent metadata.

### 5. Composition with the **sanitization declaration**

They are **orthogonal, co-located, and mutually referential** — two assertions in one manifest answering two different questions:

| | Sanitization declaration | Provenance / source declaration |
|---|---|---|
| Question | "Is this element **safe to expose**?" (PII stripped, k-anon, synthetic-substituted) | "**Where did this element come from** and can I cite it?" |
| Verb | *transforms/removes* | *attributes/traces* |
| PROV view | it **is** a `prov:Activity` (`san:sanitize`) that `prov:used` the raw element and `prov:wasGeneratedBy`→ the exposed element | the `prov:Entity` + its `wasDerivedFrom`/`hadPrimarySource` edges |
| C2PA | `com.tbsim.sanitization` assertion + `c2pa.actions:{action:"c2pa.redacted"}` | `com.tbsim.provenance` assertion + `ingredients` |

**How they compose:**
1. Each `SourceDeclaration.sanitization_ref` points to the `SanitizationDeclaration` for the same element (and vice-versa), so a reviewer can pivot from "cite it" to "is it clean" in one hop.
2. In PROV-O they chain naturally: `raw_source --wasDerivedFrom--> sanitized_element`, where the sanitization Activity sits on that edge (`used` raw, `generated` sanitized, `wasAssociatedWith` the steward). Provenance describes the *ends* of the edge; sanitization describes the *edge*.
3. The reference-list export includes a `sanitization_status` badge per element (`raw` / `sanitized` / `synthetic-substitute`) pulled from the linked sanitization declaration — so one export shows **both** the receipt *and* the safety stamp.
4. Both roll up into the same community-block manifest and the same signed C2PA manifest store, so a single verification pass proves *source + safety + no-tamper* together. Critically, when sanitization replaces a real value with a synthetic one, the element's `source_type` flips to `hypothetical`/`expert-estimate` and the provenance chain records the substitution — the two declarations stay consistent by construction.

---

# Appendix C — Community-block exchange format (interop detail)

## Community-Block Exchange Format v1.0.0

A portable, aggregate-only JSON document describing a real clinical service community, consumed by V8 + V9 to localize simulations and by FACE GENERATOR to build a demographically-matched face cohort. **Invariant: no patient-level rows, ever.** Everything is population-level statistics, public/aggregate sources, and synthetic targets.

### Design decisions (standard → where it lands)

| Concern | Standard aligned to | How it lands in the block |
|---|---|---|
| Geography | **GeoJSON RFC 7946** | `geography.boundary` is a raw GeoJSON `Feature`/`FeatureCollection`; WGS84 only (CRS84 implicit — RFC 7946 forbids a `crs` member); `bbox` allowed |
| Demographic mix + prevalence | **FHIR R4 MeasureReport** stratifier/stratum + **Group.characteristic** | strata carry `code` + `value` (CodeableConcept-shaped: `system`/`code`/`display`) and a `fraction` (0–1) or `count`; mirrors summary-MeasureReport `stratum.population.count` without listing members |
| Condition coding | **OMOP CDM** vocab pattern / FHIR CodeableConcept | each condition binds `code.system` (SNOMED/ICD-10/OMOP concept_id) + `code.code` + human `display`; `prevalence` as rate per 100k or fraction |
| Wrapper metadata | **schema.org/Dataset** | `meta` mirrors `spatialCoverage`, `temporalCoverage`, `variableMeasured`, `license`, `creator`, `distribution` |
| Integrity / signing | **RFC 8785 (JCS)** + JWS | `integrity` block: canonicalize sans-`integrity`, SHA-256 → `content_hash`, detached JWS → `signature` |
| Population strata definitions | **US Census / CDC BRFSS / WHO** (FACE ENGINE `population_stratification_schema.md`) | sex · age bands · race/ethnicity axes reused verbatim so the block round-trips with GPM |

---

### JSON Schema (Draft 2020-12), `community-block/1.0.0`

```json
{
  "$schema": "https://json-schema.org/draft/2020-12/schema",
  "$id": "https://tbsim.company/schemas/community-block/1.0.0.json",
  "title": "CommunityBlock",
  "type": "object",
  "required": ["format", "spec_version", "identity", "geography", "demographics", "sanitization", "provenance"],
  "additionalProperties": false,
  "properties": {

    "format":       { "const": "tbsim.community-block" },
    "spec_version": { "type": "string", "pattern": "^\\d+\\.\\d+\\.\\d+$",
                      "description": "SemVer of THIS schema. Consumer routes on major." },

    "identity": {
      "type": "object",
      "required": ["block_id", "block_version", "name", "created_at", "created_by"],
      "additionalProperties": false,
      "properties": {
        "block_id":      { "type": "string", "format": "uuid",
                           "description": "Stable across versions of the same community." },
        "block_version": { "type": "string", "pattern": "^\\d+\\.\\d+\\.\\d+$",
                           "description": "SemVer of the CONTENT (data revisions), independent of spec_version." },
        "name":          { "type": "string", "maxLength": 200 },
        "description":   { "type": "string", "maxLength": 2000 },
        "created_at":    { "type": "string", "format": "date-time" },
        "created_by":    { "type": "string", "description": "Instructor/org display name — no personal email/PII." },
        "supersedes":    { "type": ["string","null"], "format": "uuid",
                           "description": "block_id this revision replaces, if any." },
        "tags":          { "type": "array", "items": { "type": "string" } }
      }
    },

    "geography": {
      "type": "object",
      "required": ["scope", "boundary"],
      "additionalProperties": false,
      "properties": {
        "scope":      { "enum": ["nation","state","county","tract","zcta","hsa","custom"] },
        "label":      { "type": "string", "description": "Human place name, e.g. 'Cook County, IL'." },
        "gazetteer":  { "type": "object",
                        "description": "Optional external IDs: FIPS, GEOID, ISO-3166, OSM relation.",
                        "additionalProperties": { "type": "string" } },
        "boundary":   { "$ref": "#/$defs/GeoJSON",
                        "description": "RFC 7946 Feature or FeatureCollection. WGS84 (CRS84) ONLY; no `crs` member." },
        "bbox":       { "type": "array", "items": { "type": "number" }, "minItems": 4, "maxItems": 6 }
      }
    },

    "demographics": {
      "type": "object",
      "required": ["population_estimate", "strata"],
      "additionalProperties": false,
      "properties": {
        "population_estimate": { "type": "integer", "minimum": 0,
          "description": "Aggregate head-count estimate. NOT a member list (FHIR Group.quantity semantics)." },
        "as_of":    { "type": "string", "description": "ISO-8601 temporalCoverage of the estimate." },
        "strata":   { "type": "array", "items": { "$ref": "#/$defs/Stratum" },
          "description": "One entry per demographic axis value; FHIR MeasureReport.stratifier.stratum shape." }
      }
    },

    "clinical_prevalence": {
      "type": "array",
      "description": "Locally prevalent conditions → drives case/scenario weighting.",
      "items": {
        "type": "object",
        "required": ["condition", "measure"],
        "additionalProperties": false,
        "properties": {
          "condition": { "$ref": "#/$defs/CodeableConcept" },
          "measure": {
            "type": "object",
            "required": ["type", "value"],
            "additionalProperties": false,
            "properties": {
              "type":  { "enum": ["prevalence_fraction","rate_per_100k","incidence_per_100k"] },
              "value": { "type": "number", "minimum": 0 },
              "ci_low":  { "type": ["number","null"] },
              "ci_high": { "type": ["number","null"] }
            }
          },
          "stratified_by": { "type": "array", "items": { "$ref": "#/$defs/Stratum" },
            "description": "Optional demographic breakdown of THIS condition." },
          "source_ref": { "type": "array", "items": { "type": "string" },
            "description": "IDs into provenance.sources[]." }
        }
      }
    },

    "sdoh": {
      "type": "array",
      "description": "Social determinants — aggregate indices only (e.g. SVI, ADI, uninsured %, food-desert %).",
      "items": {
        "type": "object",
        "required": ["factor", "value"],
        "additionalProperties": false,
        "properties": {
          "factor":  { "$ref": "#/$defs/CodeableConcept",
            "description": "e.g. system:'gravity-sdoh' or 'cdc-svi', code:'SVI_OVERALL'." },
          "value":   { "type": "number" },
          "unit":    { "type": "string", "description": "e.g. 'percentile','fraction','index'." },
          "source_ref": { "type": "array", "items": { "type": "string" } }
        }
      }
    },

    "face_cohort_spec": {
      "type": "object",
      "description": "Demographic targets handed to FACE GENERATOR (/api/geo/generate).",
      "additionalProperties": false,
      "properties": {
        "cohort_size": { "type": "integer", "minimum": 1, "maximum": 2000 },
        "targets": {
          "type": "array",
          "description": "Target fractions per demographic cell; SUM of fraction across a given axis ≈ 1.0.",
          "items": {
            "type": "object",
            "required": ["axis", "value", "fraction"],
            "additionalProperties": false,
            "properties": {
              "axis":     { "enum": ["sex","age_band","race_ethnicity"] },
              "value":    { "type": "string", "description": "Axis value from FACE ENGINE M1 matrix." },
              "fraction": { "type": "number", "minimum": 0, "maximum": 1 }
            }
          }
        },
        "derive_from_demographics": { "type": "boolean", "default": true,
          "description": "If true, FACE GENERATOR may compute targets from `demographics.strata` and ignore explicit `targets`." },
        "synthetic_only": { "const": true,
          "description": "Guardrail: faces are AI-generated + labeled; block asserts no real portraits." }
      }
    },

    "sanitization": {
      "type": "object",
      "description": "Machine-checkable 'contains no PII' declaration. REQUIRED. Import MUST reject if contains_pii=true.",
      "required": ["contains_pii", "aggregate_only", "min_cell_size", "method", "declared_at", "declared_by"],
      "additionalProperties": false,
      "properties": {
        "contains_pii":   { "const": false,
          "description": "Hard invariant. Any value but false → import MUST fail closed." },
        "aggregate_only": { "const": true,
          "description": "Asserts no patient-level rows; all figures are population statistics." },
        "min_cell_size":  { "type": "integer", "minimum": 1, "default": 11,
          "description": "Small-cell suppression threshold applied (HIPAA-style k≥11 recommended)." },
        "suppressed":     { "type": "boolean", "default": true,
          "description": "Cells below min_cell_size were suppressed/rounded." },
        "method":         { "type": "string",
          "description": "e.g. 'small-cell-suppression+rounding','public-aggregate-passthrough'." },
        "synthetic_faces":{ "type": "boolean", "default": true },
        "declared_at":    { "type": "string", "format": "date-time" },
        "declared_by":    { "type": "string", "description": "Role/org, not personal identity." }
      }
    },

    "provenance": {
      "type": "object",
      "description": "schema.org/Dataset-style source list. Every stat SHOULD reference a source id.",
      "required": ["sources"],
      "additionalProperties": false,
      "properties": {
        "sources": {
          "type": "array", "minItems": 1,
          "items": {
            "type": "object",
            "required": ["id", "name", "access"],
            "additionalProperties": false,
            "properties": {
              "id":       { "type": "string", "description": "Local ref id, e.g. 'src-census-acs-2024'." },
              "name":     { "type": "string" },
              "publisher":{ "type": "string", "description": "e.g. 'US Census Bureau','CDC BRFSS','WHO'." },
              "url":      { "type": ["string","null"], "format": "uri" },
              "vintage":  { "type": ["string","null"], "description": "Data year/period (temporalCoverage)." },
              "license":  { "type": ["string","null"], "description": "SPDX id or free text; public-domain expected." },
              "access":   { "enum": ["public","aggregate-public","synthetic","derived"] },
              "retrieved_at": { "type": ["string","null"], "format": "date-time" }
            }
          }
        },
        "generator": { "type": "string",
          "description": "Tool + version that built the block, e.g. 'gpm@1.4.0 / face-engine@0.9.0'." }
      }
    },

    "meta": {
      "type": "object",
      "description": "schema.org/Dataset projection for discovery/catalog. Optional, non-authoritative.",
      "additionalProperties": true,
      "properties": {
        "license":          { "type": "string" },
        "spatialCoverage":  { "type": "string" },
        "temporalCoverage": { "type": "string", "description": "ISO-8601 interval." },
        "variableMeasured": { "type": "array", "items": { "type": "string" } },
        "keywords":         { "type": "array", "items": { "type": "string" } }
      }
    },

    "integrity": {
      "type": "object",
      "description": "Computed over the block with `integrity` REMOVED, canonicalized per RFC 8785 (JCS).",
      "required": ["canonicalization", "hash_alg", "content_hash"],
      "additionalProperties": false,
      "properties": {
        "canonicalization": { "const": "RFC8785" },
        "hash_alg":     { "enum": ["SHA-256","SHA-384","SHA-512"] },
        "content_hash": { "type": "string", "pattern": "^[a-f0-9]{64,128}$",
          "description": "hex digest of JCS(block \\ integrity)." },
        "signature": {
          "type": ["object","null"],
          "additionalProperties": false,
          "description": "Optional detached JWS over the same canonical bytes.",
          "properties": {
            "alg":  { "enum": ["EdDSA","ES256","RS256"] },
            "kid":  { "type": "string", "description": "Key id / cert thumbprint." },
            "jws":  { "type": "string", "description": "Detached JWS (RFC 7515) — payload omitted." }
          }
        }
      }
    }
  },

  "$defs": {

    "CodeableConcept": {
      "type": "object",
      "required": ["system", "code"],
      "additionalProperties": false,
      "description": "FHIR-shaped coding. system=vocabulary URI/OID, code=concept id, display=human label.",
      "properties": {
        "system":  { "type": "string", "description": "e.g. 'http://snomed.info/sct','icd-10-cm','omop-concept'." },
        "code":    { "type": "string" },
        "display": { "type": "string" }
      }
    },

    "Stratum": {
      "type": "object",
      "required": ["axis", "value"],
      "additionalProperties": false,
      "description": "FHIR MeasureReport.stratifier.stratum shape. Provide fraction OR count (fraction preferred).",
      "properties": {
        "axis":     { "type": "string", "description": "e.g. 'sex','age_band','race_ethnicity','payer'." },
        "value":    { "$ref": "#/$defs/CodeableConcept" },
        "fraction": { "type": ["number","null"], "minimum": 0, "maximum": 1 },
        "count":    { "type": ["integer","null"], "minimum": 0,
          "description": "Aggregate count. MUST be ≥ sanitization.min_cell_size or null (suppressed)." }
      }
    },

    "GeoJSON": {
      "type": "object",
      "description": "RFC 7946 object. type ∈ Feature|FeatureCollection. No `crs` member (WGS84/CRS84 implicit).",
      "required": ["type"],
      "properties": {
        "type": { "enum": ["Feature","FeatureCollection"] }
      },
      "not": { "required": ["crs"] }
    }
  }
}
```

---

### Export / import discipline

**SemVer (two independent axes).**
- `spec_version` — the schema itself. Consumers route on **major**: accept same-major, reject unknown-major, tolerate unknown-minor/patch (see forward-compat).
- `identity.block_version` — the *content* revision of a community; `identity.block_id` is stable across content revisions, `supersedes` chains lineage.

**Forward-compat rules.**
- Additive-only within a major: new **optional** fields → minor bump; clarifications/fixes → patch. Removing/renaming a field or tightening a required set → **major** bump.
- Consumers MUST **ignore unknown fields** at the top level and inside `meta`/`gazetteer` (those are `additionalProperties: true`). Everything else is `additionalProperties: false` — so unknown keys there are a hard reject, which is what forces a major bump for structural change.
- **Fail closed on major mismatch**; **warn-and-proceed on minor ahead**; **accept on minor behind**.

**Signing / hashing (RFC 8785 + JWS).**
1. Build the full block including all data, `integrity` absent (or stripped).
2. `canonical = JCS(block)` per RFC 8785 (sorted keys UTF-16, normalized numbers, no whitespace).
3. `content_hash = hex(SHA-256(canonical))` → write into `integrity`.
4. Optional: detached JWS over the **same** `canonical` bytes → `integrity.signature.jws`.
5. Verify by stripping `integrity`, re-canonicalizing, recomputing the digest, comparing, then verifying the JWS. This is the standard JCS "remove signature field → canonicalize → sign/verify" pattern, so it's identical in Python and TS.

**"Contains no PII" invariant (enforced, not advisory).**
- `sanitization.contains_pii` is a `const false`; `aggregate_only` is `const true`; `face_cohort_spec.synthetic_only` and `sanitization.synthetic_faces` assert synthetic portraits. An importer **MUST** reject any block where these fail — schema validation alone enforces the invariant because the constants can't be anything else and still validate.
- Structural guardrail: the format has **no field capable of holding a patient-level row** — no member arrays, no identifiers beyond org/role display strings, no free-text narrative on individuals. PII can't be represented, so it can't leak. Small-cell suppression (`min_cell_size`, default k≥11) protects re-identification via tiny strata; suppressed cells carry `count: null`.

**Import algorithm (both V8 and V9).**
```
1. JSON-parse → validate against community-block/<major>.json
2. Check spec_version major == supported (else reject)
3. Recompute JCS hash; compare to integrity.content_hash (else reject: tampered)
4. If integrity.signature present: verify JWS against trusted kid (else reject/quarantine)
5. Assert sanitization.contains_pii === false && aggregate_only === true (else reject)
6. Upsert by identity.block_id; if block_version <= existing, no-op unless supersedes chain says otherwise
7. Project: geography→GPM, demographics+clinical_prevalence→case weighting + local-context,
   face_cohort_spec→FACE GENERATOR /api/geo/generate
```

---

### Python (pydantic v2) + TS parity

The schema is intentionally flat, closed (`additionalProperties:false` except two catalog maps), and uses only JSON primitives + enums, so it generates cleanly both ways.

```python
# pydantic v2 — abbreviated; full model mirrors the schema 1:1
from typing import Literal, Optional
from pydantic import BaseModel, Field, ConfigDict

class CodeableConcept(BaseModel):
    model_config = ConfigDict(extra="forbid")
    system: str
    code: str
    display: Optional[str] = None

class Sanitization(BaseModel):
    model_config = ConfigDict(extra="forbid")
    contains_pii: Literal[False]          # invariant: only False validates
    aggregate_only: Literal[True]
    min_cell_size: int = Field(default=11, ge=1)
    method: str
    declared_at: str
    declared_by: str

class CommunityBlock(BaseModel):
    model_config = ConfigDict(extra="forbid")
    format: Literal["tbsim.community-block"]
    spec_version: str = Field(pattern=r"^\d+\.\d+\.\d+$")
    identity: "Identity"
    geography: "Geography"
    demographics: "Demographics"
    sanitization: Sanitization
    provenance: "Provenance"
    clinical_prevalence: list["ClinicalPrevalence"] = []
    sdoh: list["Sdoh"] = []
    face_cohort_spec: Optional["FaceCohortSpec"] = None
    meta: Optional[dict] = None
    integrity: Optional["Integrity"] = None
```

```typescript
// TS — same contract; validate with Ajv against the JSON Schema at runtime
export interface CommunityBlock {
  format: "tbsim.community-block";
  spec_version: `${number}.${number}.${number}`;
  identity: Identity;
  geography: Geography;
  demographics: Demographics;
  clinical_prevalence?: ClinicalPrevalence[];
  sdoh?: Sdoh[];
  face_cohort_spec?: FaceCohortSpec;
  sanitization: Sanitization;   // contains_pii:false & aggregate_only:true are literal types
  provenance: Provenance;
  meta?: Record<string, unknown>;
  integrity?: Integrity;
}
export interface Sanitization {
  contains_pii: false; aggregate_only: true;
  min_cell_size: number; method: string; declared_at: string; declared_by: string;
}
```

**Canonicalize/hash helpers:** Python `rfc8785` (pip) → `hashlib.sha256`; TS `canonicalize` (npm, RFC 8785) → WebCrypto/`crypto.subtle.digest('SHA-256')`. Both emit identical bytes, so a block signed in V9-cloud verifies byte-identically when imported into V8-on-prem.

---

# Appendix D — Population & geospatial data-sources catalog

# Population & Geospatial Health Data for Medical-Simulation Context

A practical briefing on authoritative prevalence sources, synthetic-population methods, place-to-profile
pipelines, and responsible gap-filling — the "ready reference base" the Service Community module points to.

## 1. Authoritative sources by region

### United States — all US federal data is public domain (17 U.S.C. §105), freely reusable commercially with attribution

| Source | Region | What it provides | Access / API | License |
|---|---|---|---|---|
| **Census Bureau / ACS** | US, to **block group** | Demographic mix: age, sex, race/ethnicity, income, education, housing, insurance | REST API (free key); ACS 5-Year 2009–2024 | Public domain |
| **CDC PLACES** | US: county, place, **census tract**, ZCTA | Model-based **local prevalence**, 40 measures (12 outcomes, 7 preventive, 4 risk behaviors, 7 disabilities, 3 status, 7 social needs) | Socrata API / bulk (PLACES Data Portal); 2025 tract release | Public domain |
| **BRFSS** | US: national, state, **SMART** metro | The telephone-survey behavioral/risk data PLACES is modeled from; direct state & metro prevalence | Annual files, WEAT, SMART | Public domain |
| **CDC WONDER** | US: national→county | Mortality, natality, cancer, infectious disease, population counts (outcomes/mortality, not point-prevalence) | Menu query + WONDER API | Public domain |
| **County Health Rankings & Roadmaps** | US: **county** | Ranked composite: health behaviors, chronic conditions, outcomes, access, SDOH | CSV downloads; maps | Free reuse w/ attribution (check Terms) |
| **AHRQ SDOH Database** | US: county, ZIP, **tract**, 2009–2020 | Curated SDOH from 44 sources across 5 domains, pre-linked by geography | Bulk CSV/Excel | Public domain |
| **HRSA Area Health Resources Files** | US: **county** | Health workforce, facilities, population characteristics, utilization — supply-side/access | HRSA Data Warehouse download | Public domain |

### EU / Global

| Source | Region | What it provides | Access / API | License |
|---|---|---|---|---|
| **Eurostat** | EU + EEA, NUTS levels | Health status, causes of death, healthcare + demographics/socioeconomics | Free SDMX 3.0 & JSON APIs (no key) | Free reuse (commercial) w/ attribution |
| **WHO Global Health Observatory (GHO)** | Global, 194 states (mostly country-level) | 1,000+ health indicators | OData API, no auth (⚠ current OData API deprecating ~end 2025 — plan for successor) | Open/free (verify per dataset) |
| **IHME Global Burden of Disease (GBD 2023)** | Global → many countries subnational | Deep harmonized prevalence/incidence/DALYs by cause, age, sex, year | GBD Results Tool + GHDx | ⚠ **Non-commercial free; commercial use requires a paid University of Washington license** |

### India

| Source | Region | What it provides | Access / API | License |
|---|---|---|---|---|
| **NFHS-5 (2019–21)** | India: national, state/UT, **707 districts** | Population, health, nutrition; diabetes/BP, anemia, maternal/child, disability, WASH | Factsheets (OGD India); microdata (World Bank Microdata Library) | Open (OGD India NDSAP; WB registration) |
| **Census of India** | India, to village/ward | Demographic denominators, household amenities | Portal bulk tables | Government open data |
| **NSSO / NSO health rounds (MoSPI)** | India, national + state | Socio-economic + health expenditure/morbidity rounds | MoSPI microdata + reports | Government open data |

## 2. Synthetic-population methods

- **Synthea** — open-source generator of full **synthetic patient records** (FHIR/C-CDA/CSV); seeds from US Census demographics to city level, drives disease progression via 90+ guideline-based clinical modules. *Good for:* longitudinal, clinically-coherent individual EHRs for a locale. *Limits:* US-centric defaults; localizing to a non-US/fine-grained place needs demographics + geo files swapped and module frequencies tuned. Validated against clinical quality measures.
- **Iterative Proportional Fitting (IPF) / synthetic reconstruction** — fits a seed microdata sample to known **marginal totals** (census cross-tabs) so the synthetic population's joint distribution matches the area's margins. *Good for:* a demographically-representative population mix when you only have aggregate margins. Refinements: Hierarchical IPF, relative-entropy minimization, combinatorial optimization. A ready US national synthetic-populations dataset exists as a shortcut.
- **Composition:** IPF answers *"who lives here"* (denominator); prevalence sources (PLACES/GBD/NFHS) answer *"what conditions do they carry"*; Synthea turns each synthetic person into a coherent record. Order: reconstruct population → attach condition probabilities by stratum → instantiate records.

## 3. Place → profile (repeatable, provenance attached at every step)

1. **Resolve geography** — place → canonical geo-ID (US tract/ZCTA/FIPS; EU NUTS; India district): the downstream join key.
2. **Demographic denominator** — ACS (US) / Eurostat (EU) / Census+NFHS (India) → age×sex×race/ethnicity×income×education×insurance for that geo-ID (record source, vintage, geo level).
3. **Condition & SDOH prevalence** — join CDC PLACES (US tract), AHRQ SDOH, County Health Rankings; GBD/GHO (global); NFHS district (India). Store each measure with estimate, source, year, resolution.
4. **Reconstruct population** (IPF against ACS/census margins), then **assign conditions** by drawing on stratum-specific prevalence (not a flat area average) — preserves within-area heterogeneity.
5. **(Optional) Instantiate records** (Synthea or equivalent) for full clinical detail.
6. **Emit a provenance manifest** — every field → `{value, source, source_url, vintage, geo_level, method}`.

**Resolution caveat:** prevalence sources are model-based small-area (PLACES) or survey (BRFSS/NFHS) estimates with uncertainty; carry the geo level and flag when a coarser-geography value is borrowed for a finer place.

## 4. Gap-filling — responsible representation of missing data

Never silently invent; **label the epistemic status**. Two cases:
- **(a) Factual-but-not-yet-integrated** — real & knowable but not yet in the pipeline (newer release, local registry). Tag `status: sourced-pending` + citation, confidence **High**; treat as authoritative once verified.
- **(b) Hypothetical / expert-estimate** — no public figure exists. Tag `status: estimated`, record the **method** (interpolated from neighboring geography / analogous population / clinician judgment), the **basis**, and a confidence band (**Medium/Low**). Never present with the same weight as sourced values.

**Per-value field schema:**
```
{ value, unit,
  status: sourced | sourced-pending | estimated,
  confidence: high | medium | low,
  source, source_url, vintage, geo_level,
  method,   // "PLACES tract estimate" | "IPF from ACS margins" | "SME estimate 2026"
  note }    // rationale/caveat, surfaced in the sim UI
```
Build rules: confidence is first-class (sim renders "estimated" distinctly; instructors can filter to sourced-only for high-stakes debriefs); prefer sourced-with-borrowed-resolution over invented; estimates keep method+author so they're auditable and replaceable; **commercial-license watch** — prefer US federal + Eurostat; gate GBD behind the licensing decision.

## 5. Two load-bearing licensing facts (commercial product)
1. **US federal sources (ACS, PLACES, BRFSS, WONDER, AHRQ, HRSA) are public domain / freely reusable commercially;** Eurostat permits commercial reuse with attribution.
2. **IHME GBD is free only for non-commercial use — commercial use requires a paid University of Washington license.** Also budget for the WHO GHO OData API successor (current one deprecating ~end 2025).

