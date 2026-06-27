# FR-017 — Scenario exchange (export / import & edit between MedSim VRAI systems)

**Status:** PLANNED — backlog note (not yet built). **Logged:** 2026-06-26.

## Problem
Instructors build scenarios on their own MedSim VRAI install but can't share them
with peers on a different install. Today a scenario lives only as local YAML
(`scenarios/*.yaml`) that references character YAML **by id** (`characters/*.yaml`);
Studio-authored scenarios live in `data/authored/scenarios.json` + `personas.json`
with `AUTH-…` UUID ids. Nothing packages a scenario **plus its dependencies** so it
can move to another machine — so good scenarios stay siloed.

## Goal (instructor request)
In the scenario-building area, let an instructor:
- **Pull up an existing scenario, edit it, and export** it to a shareable file.
- **Import** a scenario file authored on another MedSim system, then **edit** it.

Scenarios become portable, shareable teaching assets between systems.

## Proposed design
### Export bundle — self-contained + versioned
One downloadable file (v1: a single `*.medsim-scenario.json`; move to `.zip` if we
later embed avatar binaries) containing:
- the **scenario** object (full),
- **every referenced character** (resolved from `scenario.characters[]`),
- referenced **authored personas** (for Studio scenarios),
- a **`_manifest`**: format version, source MedSim version, export timestamp,
  checksum, and a list of assets **not** embedded (avatar portraits/skins) so the
  importer knows to reassign.

Avatar/skin images are large and path-bound (`data/face_portraits/{id}.skin`,
`data/face_skins/*.png`) → **referenced by name in the manifest, not embedded** in
v1; importer shows a "reassign avatars" checklist.

### Import — with id / asset remap (collision-safe)
- Validate the manifest (format version + checksum); curate/reject on mismatch.
- **Remap to avoid collisions:** regenerate the scenario id if taken (reuse the
  `_unique_id` / `duplicate_scenario` pattern in `scenarios.py`); for each bundled
  character, if the id exists locally either **link to the existing one** or import
  under a new suffixed id (instructor choice); remap authored persona UUIDs.
- Land scenario + characters via the existing `scenarios.save_scenario()` (and the
  character-save path), then drop the instructor into the **edit form** to adjust
  before first launch.
- Surface unresolved refs (missing characters, unassigned avatars, `kb_scope`
  items not present locally) as a **post-import checklist**.

### UI seam
- **`/portal/scenarios`** (`templates/scenarios.html`): add **Export** to each
  row's action group (next to Edit / Duplicate / Delete) and an **Import scenario**
  button in the header (next to "+ New scenario").
- Optional Export button on the scenario **edit form** and on **Scenario Studio**
  after save.
- Import flow = file picker → **preview** (what's in the bundle + any collisions) →
  confirm → land → edit.

### Endpoints (proposed)
- `GET  /portal/scenarios/{id}/export` → assembles + downloads the bundle.
- `GET  /portal/scenarios/import` → import form / preview.
- `POST /portal/scenarios/import` → multipart upload → validate → remap → save →
  redirect to the edit form.

## Round-trip integrity
The export must capture everything `runtime.create_session()` needs so an imported
scenario instantiates **identically**: `patient` + `baseline_vitals` +
`vitals_timeline`, the full referenced **characters**, `curriculum`
(touchpoints / unlocked / deterioration_threshold), `allowed_tools`, `kb_scope`.
Local-context (FR-013a) items referenced by `kb_scope` are install-specific →
either bundle the referenced items or flag them as external dependencies in the
manifest.

## Open questions
- Bundle format: single JSON now vs `.zip` (needed once avatar images embed).
- Character-id collisions: auto-suffix vs instructor-mediated merge/link.
- Does `kb_scope` local-context travel with the bundle, or stay host-provided?
- Provenance/trust: instructors will share via email/USB — do we sign bundles?
- Schema versioning: forward/backward compatibility across MedSim versions.

## Files (when built)
- **New:** `portal/scenario_exchange.py` (assemble / validate / remap),
  `templates/scenario_import.html`.
- **Touch:** `scenarios.py` (reuse `save_scenario` / `duplicate_scenario` /
  `_unique_id`), `server.py` (3 routes), `templates/scenarios.html` (Export/Import
  buttons), optionally `scenario_form.html` + `scenario_studio.html`.
- **Tests:** export→import→identical-run round-trip; collision remap; malformed /
  wrong-version bundle rejected; authored-scenario persona remap.

## Related
- Builds on the scenario CRUD in `scenarios.py` and the Scenario Studio (FR-013b).
- `kb_scope` ties to local context (FR-013a / FR-013a P2 ingestion).
