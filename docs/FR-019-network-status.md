# FR-019 — Network & device-status view (instructor "see what's connected")

**Status:** **N1 + N2 DONE** (2026-06-28) — live snapshot endpoint + the Mission
Control topology view with BOTH layouts. Remaining: **N0** (roster ROLES — the
student-tier data model, decision 1, likely its own FR), **N4** (dynamic layout at
multi-room/unit scale), and the richer device link-state (instructor-managed links,
decision 2 — v1 derives state from heartbeats). **Design decisions captured
2026-06-27** (see Decisions). **Logged:** 2026-06-27.

### Built (2026-06-28) — N1 + N2
- `portal/network_status.py` — `build_snapshot()` assembles a `NetworkSnapshot`
  from `control_room` (room/encounters/shared personas/staff roster) + `ehr_db`
  (`device_stations`) + `library` (persona names/roles). Returns an empty-but-valid
  snapshot when idle. Device class from `device_kind` (telemetry/vent → physio
  "manikin"; pump/PIA → supporting; cart → operational); state from heartbeat
  freshness (recent → active, stale → fault); roles normalized to the closed enum.
- `GET /api/network/snapshot` (auth-gated) → the snapshot; polled ~2.8 s.
- `GET /portal/network` → `templates/network.html` (standalone full-screen view) +
  `static/network.js` (vanilla-JS SVG renderer; links derived in the UI; Option A
  tiered + Option C radial; class colors / state line-styles / pips / chips /
  animations per the handoff; layout choice persisted to `localStorage.medsim_view`).
- Mission Control entry: a **"Network & devices"** card in the Operate panel
  (`/api/control/operate`) → Open / **Pop out** (reuses the existing card pop-out).
- Tests: `tests/v8/test_network_status.py` (snapshot assembly + classification +
  degrade-on-unknown + the 3 routes + auth gate). Verified visually (both layouts,
  full encoding, students tier, responsive 2-col) against `sample_payload.json`.

**v1 simplifications (carry decisions 1 & 2 forward):** the STUDENT tier reads the
**existing** med-cart staff roster (not yet the N0 roles model — students replacing
AI characters / AI-student questioners / floor-nurse char); device state is
**heartbeat-derived** (active/fault), not the instructor-managed-links + idle/
available split. The snapshot SHAPE already matches the contract, so both refinements
enrich the same feed without a UI rewrite.

## Goal
A live, at-a-glance map the instructor opens from **Mission Control** (a tab →
**open or pop out**, reusing the existing card pop-out pattern) to answer fast:
**what's linked and active, what's ready, what's faulted/unassigned** — across every
device, every patient, and how the **students are deployed** in the running scenario.
Read-only monitoring in v1 (observe, don't edit).

## Design source of truth
A full design handoff is bundled in **`docs/FR-019-network-status/`**:
- `README.md` — behavior + visual-encoding spec (the encoding IS the product:
  **color = device class, line style = link state**, dashed/dotted = relationships).
- `schema.ts` — the `NetworkSnapshot` data contract (entities + enums + derived links).
- `sample_payload.json` — a worked snapshot fixture.
- `MedSim Device Topology.dc.html` — an interactive **HTML/SVG prototype** (mock data
  + simulated polling). **Reference only** — recreate it inside MedSim's chrome with
  the real feed; do **not** ship the prototype or port its hand-placed coordinates.

Two selectable layouts of the **same** live data: **Option A — Tiered** (control bus
fanning down Control → Common/Shared → Patient room → Students) and **Option C —
Radial hub** (control at center). Hierarchy:
`CONTROL → COMMON/SHARED → PATIENT (manikin + tablet + supporting) → STUDENT`.

## How it maps onto MedSim (the integration — this is the real work)
The UI is a pure render of a `NetworkSnapshot`; MedSim must produce that snapshot
from its live state. Mapping the contract's entities to existing sources:

| Snapshot entity | MedSim source | Notes / gaps |
|---|---|---|
| `control` | the active session / Mission Control (`control_room`) | one per session — easy |
| `commonDevices` (operational) | med cart, nurses station, records terminal, PIA | exist as devices; **state** from connected-station heartbeats |
| `commonDevices` (character) | shared + scenario characters / roles | characters are AI, not hardware — "state" needs a meaning (paired? engaged?) |
| `units → rooms → patients` | `control_room.encounters` (each bed = patient_persona_id + scenario) | one room/unit today; contract scales |
| `patient.manikin` (physio) | physiologic device / PhysioBridge link (FR-012) | may be absent (manikin out of room → `available`) |
| `patient.tablet` (vrai) | the VRAI Faces avatar tablet pairing | online/offline from station heartbeats |
| `patient.supporting` | per-bed advanced devices — IV pump, alarm/PIA (FR-012) | device registry per encounter |
| `students[]` (patientIds + role) | **partial** — med-cart roster + records-terminal staff scoping | ⚠️ **biggest gap** — see Q1 |
| device `state` (active/idle/available/fault) | connected-stations roster + heartbeats | gives online/offline; **active-vs-idle ("in use") + available** need a richer signal — see Q2 |

### Feed (snapshot → UI)
- **v1 (poll):** a `GET /api/network/snapshot` that assembles the `NetworkSnapshot`
  from the room/devices/roster; the view polls ~3 s (matches the prototype). Reuses
  the connected-stations + device + roster data already gathered for the operator
  cockpit.
- **Later (push):** ride the existing per-room WebSocket (`/ws/room/{code}`) to push
  device/assignment deltas so the map updates instantly (the relay already exists).
- Links are **derived in the UI** from the snapshot (control→devices, patient→parts,
  device.assignedToPatientId→patient, student.patientIds→patients, student.role→role).

## Suggested staged build
- **N0 — roster ROLES (prerequisite, per decision 1):** extend the assignment area
  with a roles checklist (allied health + supervisor + charge nurse); a student in a
  role replaces that AI character; add AI-student allied-health questioners + a
  floor-nurse character with a patient assignment. This is what makes the STUDENT
  tier's data exist (sizable — may be split into its own FR).
- **N1 — snapshot endpoint:** ✅ DONE (2026-06-28). `network_status.build_snapshot()`
  + `GET /api/network/snapshot`; assembled from encounters / connected-stations /
  staff roster / persona library. Test-backed against the `sample_payload.json` shape.
  (Instructor-managed links — decision 2 — deferred; v1 state is heartbeat-derived.)
- **N2 — Mission Control entry + BOTH layouts live:** ✅ DONE (2026-06-28). A "Network
  & devices" Operate card → open + pop-out; renders Option A (tiered) AND Option C
  (radial) from the live snapshot, polling ~2.8 s; full encoding tokens (class colors,
  link-state line styles, pips, chips, animations) per the handoff; layout persisted.
  (Both up front — decision 4.) Vanilla-JS SVG, no build step (decision 5).
- **N4 — dynamic layout at scale:** compute geometry from data (1–8 beds, multi-room,
  multi-unit); legible paging/grouping; smooth transitions on assignment changes.
  (v1 lays out from data already — single room scales to 8 beds; multi-room/unit +
  the busy-arc anti-overlap are the remaining work.)
- **Roadmap (post-v1, per handoff):** per-node inspect/click-through; unit/room
  selector + zoom; fault alerting (toast/badge).

## Decisions (answered 2026-06-27)
1. **Student deployment = extend the existing assignment area with ROLES.** In the
   place students↔patients are already assigned (the roster / Assignments step), add
   a **roles pull-down / checklist** — the allied-health roles already listed, plus
   **supervisor** and **charge nurse**. Assigning a student to a role means the
   **student REPLACES that role's AI character**. For the supervisory roles
   (charge / supervisor), spawn **AI "students"** that act as allied-health staff
   (they pose questions to the trainee), and add a new **floor-nurse character** that
   carries a patient assignment. → This extended roster is the **source of truth for
   the STUDENT tier**. (It's a meaty prerequisite — see N0; possibly its own FR.)
2. **Device state from instructor-managed links + reference setups.** A device reads
   **available** until the instructor **adds/links it** into the setup; once linked
   it's "in the scenario." Support **saved reference link-setups** (reusable
   baselines) as one starting point; otherwise links accrue as devices connect.
   (active-vs-idle can refine later off heartbeat / recent-activity.)
3. **Character node = active when the character is active AND its device is
   connected** (engaged + station paired); otherwise present/idle.
4. **Both layouts up front** (Tiered + Radial) — instructors get the choice of
   visualization. (Not phased.)
5. **Vanilla JS** SVG, matching the server-rendered card UI (no build step).

## Files (when built)
- New: `portal/network_status.py` (assemble the snapshot), a `GET /api/network/snapshot`
  route, a Mission Control "Network" tab/card + the diagram view (SVG).
- Touch: `portal/templates/console.html` (the tab/entry), the connected-stations /
  device / roster accessors it reads from.
- Tests: snapshot assembly against the contract; link-derivation; degrade-on-unknown.

## Related
- Builds on the connected-stations roster + device registry (FR-011/FR-012) and the
  per-room WS (FR-016). The med-cart roster + records scoping feed the student tier.
