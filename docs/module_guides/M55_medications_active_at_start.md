# M55 — Medications card on encounters + active-at-start toggle + med-cart filter

**Phase:** Phase 7 follow-on (post-M54, operator feedback)
**Status:** **DONE**
**Blocked by:** M25 (Per-Patient Console), M47 (room-level med carts), M54 (collapsible-panel pattern)
**Blocks:** none
**Estimated effort:** 0.5 day

---

## 1. Purpose

> "Medication section needs to be added to the encounters. Click on
> the header to have it open up of the assigned medications for the
> scenario and allow the instructor to click on the medication to be
> present or in use at the start of the scenario. These medication
> will show up in the med cart under the name of the patient
> character in the encounter."

Today the M47 med cart shows EVERY med from every linked encounter's
seed MAR — fine for a quick demo but noisy in a real drill where
only a subset of the patient's home meds are actually being given
at the start of the scenario.

M55 lets the instructor scope the cart per patient from the
encounter console.

---

## 2. What ships

### 2.1 Collapsible **💊 Medications** card
A new card on the Per-Patient Console (`encounter_console.html`),
collapsed by default — matches the M54 nurse-station threshold
panel pattern. Click the header (an `h2` styled as a `role="button"`
with ARIA + a rotating caret) to expand. Inside, one section per
persona on the encounter; each section lists every med from that
persona's seed MAR with a checkbox.

```
┌─────────────────────────────────────────────────────────────┐
│ ▸ 💊 Medications — mark which meds are active at scenario   │
│                    start                                    │
├─────────────────────────────────────────────────────────────┤  expanded
│ Jane Diaz (P-014)                  default — all active  ↺ │
│   [✓] Furosemide  40 mg IV q6h                              │
│   [✓] Lisinopril  10 mg PO daily                            │
│   [✓] Heparin     5,000 U SQ q8h         ⚠ high-alert       │
│   [ ] Atorvastatin 20 mg PO HS                              │
│                                                             │
│ Marcus Kowalski (P-007)            explicit list         ↺ │
│   [✓] Norepinephrine 4 mg IV continuous  ⚠ high-alert       │
│   [ ] Fentanyl       50 mcg IV q1h        ⚠ high-alert      │
└─────────────────────────────────────────────────────────────┘
```

Tick / untick → JS POSTs the full active-list for that persona to
the server. The "↺ Reset" button per persona DELETEs the explicit
list, restoring "show every med" default behavior.

### 2.2 Data model
`portal/control_session.py` — `Encounter` (= `ControlSession`)
gains:

```python
active_medications: dict[str, list[str]] = field(default_factory=dict)
```

Semantics:
- `persona_id NOT in active_medications` → cart shows EVERY med for
  that patient (back-compat with pre-M55 carts).
- `persona_id in active_medications` → cart shows ONLY the meds
  whose lowercased `name` is in the list. Empty list = no meds for
  that patient.
- No schema migration — in-memory only. Dies with the server.

### 2.3 API
Three new routes under existing instructor / vault guards:

| Method | Route | Purpose |
|--------|-------|---------|
| `GET`  | `/api/encounter/{eid}/medications` | List every persona's seed MAR + `active` flag per med + `explicit_active_list` flag per persona. |
| `POST` | `/api/encounter/{eid}/medications/active` | Body `{persona_id, active_med_names: [...]}` — replace ONE persona's active list. |
| `DELETE` | `/api/encounter/{eid}/medications/active/{persona_id}` | Reset one persona to default (every med shows). |

POST normalizes the list: `str(n).strip().lower()`. Whitespace and
case insensitive on lookup so "Furosemide" matches "furosemide".

### 2.4 Med-cart bootstrap filter
`portal/devices/routes.py` — the cabinet bootstrap that builds
`characters[]` for the cart UI was previously returning every med
from `seeds_for_all_personas(enc)`. M55 inserts a filter:

```python
for c in per_enc:
    pid = c.get("character_id") or ""
    if pid in active_map:
        active_lower = set(active_map.get(pid) or [])
        c["medications"] = [
            m for m in (c.get("medications") or [])
            if (m.get("name") or "").strip().lower() in active_lower
        ]
    # ... still tag with encounter_id + encounter_label
```

When the persona has no explicit list, the cart sees the full med
list. The cart UI doesn't need to change — it just receives a
smaller list.

---

## 3. Files touched

### Modified
- `portal/control_session.py` — `active_medications: dict[str, list[str]] = field(default_factory=dict)` on `ControlSession`.
- `portal/server.py` — 3 new routes (`GET /api/encounter/{eid}/medications`, `POST /api/encounter/{eid}/medications/active`, `DELETE /api/encounter/{eid}/medications/active/{persona_id}`).
- `portal/devices/routes.py` — cabinet bootstrap filter against `enc.active_medications` per persona.
- `portal/templates/encounter_console.html` — new collapsible "💊 Medications" card.
- `portal/static/encounter_console.js` — `wireMedsToggle`, `bootMedications`, `renderMedications`, `onMedToggle`, `onMedReset` + `cssEscape` helper.
- `portal/static/encounter_console.css` — `.meds-card` + `.meds-persona` + `.meds-row` + collapsed-state rules.

### New
- `tests/v7/test_medications_active.py` — 13 acceptance tests.
- `docs/module_guides/M55_medications_active_at_start.{md,pdf}` — this guide.

---

## 4. Acceptance

Source: `tests/v7/test_medications_active.py` (13 tests).

1. **Dataclass** — `ControlSession.active_medications` defaults to `{}`.
2. **GET endpoint** — returns personas + seed MARs; `explicit_active_list=False` until first operator interaction; every med has `active=True` by default.
3. **POST** — sets the explicit list; subsequent GET reports `explicit_active_list=True` and flips the `active` flag accordingly. Empty list = "no meds active" (different from default-all).
4. **DELETE** — resets one persona to default; subsequent GET reports `explicit_active_list=False` again.
5. **Cart filter** — after POSTing an active list, the M47 cabinet bootstrap returns only the listed med under that patient. Without a POST, every med still appears (back-compat preserved).
6. **Encounter console** — template renders `id="card-medications"` with `meds-collapsed` class, `id="meds-toggle"` with `aria-expanded="false"` + `aria-controls="meds-body"`, caret marker, body section.
7. **JS handlers** — `wireMedsToggle`, `bootMedications`, `renderMedications`, `onMedToggle`, `onMedReset` all present; hit `/medications` + `/medications/active` routes; Enter/Space keyboard accessibility.
8. **CSS** — `.meds-card.meds-collapsed .meds-body` hides body; `.meds-persona` + `.meds-row` + `.meds-high-alert` styling.

All 13 pass. Full v7 suite **458 passed, 1 skipped, 0 regressions** (was 445 pre-M55).

---

## 5. Operator demo

1. Open a multi-patient room with 2-3 encounters.
2. Drill into one encounter (`/portal/room/encounter/{id}`).
3. The new **▸ 💊 Medications** card sits between Devices and Network/QR. Click the header — it expands, listing every persona on this encounter with their full seed MAR. All boxes are ticked (default).
4. Untick a med (say, Atorvastatin). The persona's status badge flips from "default — all active" to "explicit list".
5. Open the M47 med cart (linked to this encounter). Atorvastatin is gone from this patient's section; the other meds remain.
6. Click ↺ Reset on the persona. Atorvastatin reappears on the cart on the next refresh.

---

## 6. Notes / future hooks

- **No schema migration**. `active_medications` is in-memory only;
  dies with the server. Same lifecycle as the M30 `lead_student_id`
  and M53 `lead_label`. If the operator wants persistence across
  restarts, a schema-v6 migration would add a JSON column to
  `control_session` (out of scope here).
- **No bulk-apply UI** like M53's lead-assignments. If the operator
  needs to mark the same med active across N beds, a bulk endpoint
  could land later — the route signature would mirror
  `/api/room/lead_assignments` (`assignments[]` with `encounter_ids[]`).
- **Match is by name**, lowercase + stripped. The med_id from the
  seed isn't used (it's not stable across re-seeds; we considered
  it and rejected). If the seed library ever introduces two meds
  with the same name on one patient, the filter would treat them
  as one — the seed builder de-duplicates today so this is fine.
- **MAR display** on the cart is unchanged otherwise — `dose`,
  `route`, `frequency`, `high_alert`, `current_status`, etc. all
  flow through from the seed. M55 just filters which rows survive.
- **No chart-event** is written when the operator toggles a med.
  This is a configuration step before the scenario starts, not a
  clinical action. If the operator wants an audit trail (who
  toggled what when), wrap the POST handler in
  `ehr_db.append_event(type="meds.active_set", ...)`.

---

**Closes:** the operator's M55 ask in full.
