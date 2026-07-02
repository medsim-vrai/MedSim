# Handoff: Network & Tool Status (Instructor Control Center)

## Overview

A new **tool/panel for the MedSim instructor Control Center**: a live, at-a-glance map of the
simulation's device and participant network. The instructor opens it to answer one question fast —
**what is linked and active, what is ready, and what is faulted or unassigned** — across every
device and every student in the running scenario.

The map renders the simulation hierarchy top-down:

```
CONTROL  ──►  COMMON / SHARED  ──►  PATIENT  ──►  STUDENT / PARTICIPANT
(instructor)  (operational +       (manikin +     (assigned to patients;
              character roles)      tablet +        may fill charge/
                                    supporting)     supervisor roles)
```

Each node is color-coded by **class** and its connection line is styled by **link state**. The view
**polls MedSim and updates live** as equipment connects, idles, faults, or as assignments change.
Two layout options are provided; the instructor picks whichever reads better and the choice is
remembered for the session.

This is the design + behavior spec for that tool. It documents intended look, the data it consumes,
and exactly where the real MedSim feed plugs in.

---

## About the design files

The file in this bundle — `MedSim Device Topology.dc.html` — is a **design reference prototype built
in HTML/SVG**, not production code to ship as-is. It demonstrates the intended visual system and live
behavior using **mock data and a simulated polling loop**.

The task is to **recreate this design inside the MedSim Control Center's existing environment**
(its current UI framework, component library, theming, and data layer) — and to **replace the mock
data with the real MedSim feed**. If the Control Center has no established web UI layer yet, pick the
framework that best fits the rest of the product and implement there. Reuse MedSim's existing design
system for chrome (panels, headers, buttons); the prototype's specific tokens below are the source of
truth for the **diagram itself** (node shapes, class colors, link-state styling).

## Fidelity

**High-fidelity visuals, mock data.**

- **Visuals (hifi):** colors, typography, node/link rendering, legend, and the two layouts are final
  and should be reproduced faithfully — the encoding (color = class, line style = state) is the
  product, so don't drift it.
- **Data + layout geometry (prototype-only):** node coordinates are hand-placed for exactly one room
  with three patients. **Do not port the coordinates.** Production must **compute layout from data**
  (see "Dynamic layout requirements"). All node identities, tags, and states in the prototype are
  stand-ins for the real MedSim feed.

---

## Where this lives

A dedicated tool in the Control Center, surfaced however the Control Center surfaces tools (a tab, a
dockable panel, or a full-screen "Network Status" mode). It is **read-only monitoring** in v1 — the
instructor observes; they don't edit topology from here. (Per-device inspect/click-through is a
fast-follow, see "Roadmap".)

Recommended default placement: a full-width panel. Minimum comfortable render area ≈ 760 px wide for
the diagram column plus ≈ 340 px for the legend column.

---

## Views (two selectable options)

The instructor toggles between two readings of the **same live data** via a segmented control at the
top. Selection persists (see "State & persistence"). Both must stay fully wired and live — this is a
preference, not an either/or build.

### Shared chrome (both views)

- **Header (top-left):** title "MedSim · Device Link Topology" + one-line description of the encoding.
- **Live status strip:** a `POLLING` indicator (pulsing dot) followed by live counts —
  `N active · N idle · N available · N fault` — recomputed every poll across all devices.
- **Segmented control:** `OPTION A · TIERED` / `OPTION C · RADIAL HUB`.
- **Diagram card:** white card, the selected diagram, a header line showing the option name +
  `ROOM 1 · UNIT A · CAP 8`.
- **Legend card (right):** device classes, link states, notation, tag scheme. Always visible.

### Option A — Tiered Schematic

Vertical tiers, control bus at top fanning down to participants at the bottom. Reads like a
signal-flow diagram.

- **Tier 1 — Control:** single control node, centered top. A faint animated "scan" ring conveys
  active polling.
- **Tier 2 — Common · Shared Devices:** operational devices in a row, character roles in a row
  beneath. Each links up to the control bus via a fanned cubic-bezier path.
- **Tier 3 — Patient Room:** a dashed-bordered room rectangle (`ROOM 1 · UNIT A · CAP 8`) holding
  patient circles. Each patient circle has its manikin and tablet blocks stacked beneath it, with
  supporting devices (IV/alarm) below those, connected by short local links. Empty beds render as a
  faint dashed "+" row labeled `BEDS 4–8 · OPEN CAPACITY`.
- **Tier 4 — Students · Participants:** student pills below the room. Dashed links fan **up** to each
  assigned patient circle; a dotted link runs up to the character node for any **role filled**.
- Tier dividers are thin dashed rules with small mono labels.

### Option C — Radial Control Hub

Control at the center, shared devices on an arc above, patient room below, students at the bottom —
a compact hub-and-spoke overview.

- **Center:** control node + animated scan ring.
- **Upper arc:** the 8 shared devices positioned on a radius around the hub; straight radial links
  from center to each, colored/styled by class/state.
- **Patient room (lower center):** dashed room rect with patient circles; each patient gets two thin
  radial links from the hub (manikin = physio color, tablet = vrai color). Tiny device "chips"
  (M / T / I / A) ring each patient circle, colored/styled by state.
- **Students (bottom):** same student pills + dashed assignment links up to patients and a dotted
  role link up to the relevant ring node.

---

## Visual encoding spec (reproduce exactly)

### Node types

| Entity | Shape | Notes |
|---|---|---|
| Control station | Rounded block with filled status dot (and scan ring) | One per session; hub of the graph |
| Device (operational / character / physio / vrai / supporting) | Rounded rectangle, 5 px radius | Left edge has a 3.5 px class-color bar; tag (mono) + name (sans); status **pip** top-right |
| Patient | Circle, ~25 px radius | Tag centered (e.g. `PT-01`); bed label above |
| Student / participant | **Pill** (fully rounded), filled tint `#fbeef3`, person glyph at left | Shows tag + summary, e.g. `STU-01 · 2 PTS · CHARGE NURSE` |

**Status pip** (top-right of device blocks):
- active → filled class-color dot
- idle → hollow class-color ring
- available → hollow gray dotted ring
- fault → filled red dot + faint blinking red halo

### Link rendering — line style encodes state

All links are SVG paths, `stroke-linecap: round`. Color comes from the **class** (control links and
local links use the *target's* class color); style comes from **state**:

| State / kind | Stroke | Width | Dash | Opacity | Animation |
|---|---|---|---|---|---|
| `active` | class color | 1.7 | `7 5` | 1.0 | marching ants (`flow`) |
| `idle` | class color | 1.2 | none (solid) | 0.5 | — |
| `available` | `#b9b6ae` (gray) | 1.0 | `1.5 5` (dotted) | 0.85 | — |
| `fault` | `#c0473f` (red) | 1.4 | `5 4` | 0.9 | slow blink |
| `assign` (device/character → patient) | class color | 1.2 | `4 3` | 0.65 | — |
| `student` → patient | `#b0567f` (student) | 1.2 | `4 3` | 0.65 | — |
| `role` (student → role) | `#b0567f` (student) | 1.2 | `1 4` (fine dotted) | 0.7 | — |

Routing: Option A uses fanned cubic beziers from the control node; local patient-device links are
short straight segments. Option C uses straight radial lines from the hub. Routing is a layout
concern — keep the **style table above** identical regardless of routing.

---

## Data contract

The UI consumes a `NetworkSnapshot`. Full typed contract: **`schema.ts`**. A worked example matching
the prototype's scenario: **`sample_payload.json`**.

Key principles:

1. **Truth lives in MedSim; the UI is a pure render of the latest snapshot.** Never let the UI infer
   or cache status independently.
2. **Class drives color, state drives line style, relationships drive the dashed/dotted links.** These
   three are orthogonal and must be derived from the snapshot, never hardcoded.
3. **Links are derived in the UI**, not sent over the wire — compute them from the snapshot:
   - control → every common device and every patient manikin/tablet
   - patient circle → its manikin / tablet / supporting devices (local)
   - any `device.assignedToPatientId` → that patient (`assign`)
   - each `student.patientIds[]` → those patients (`student`)
   - each `student.role` → the matching character device node (`role`)
4. **Enums are closed.** `DeviceClass` and `LinkState` are fixed sets. Unknown values must degrade
   gracefully (render neutral gray, do not crash) and be logged — see "Edge cases".

### Entities (summary — see schema.ts for fields)

- `ControlStation` — one per session.
- `Device` — `{ id, tag, name, cls, state, area?, role?, assignedToPatientId? }`.
- `Patient` — `{ id, tag, bed, manikin?, tablet?, supporting[] }` (manikin/tablet are `Device`s).
- `Student` — `{ id, tag, name, patientIds[], role|null }`.
- `Room` / `Unit` — nesting for scale-out (capacity up to 8 patients/room; many rooms/units later).

---

## Integration — replacing the mock

The prototype fakes the feed in two places; both must be swapped for the real MedSim data layer.

**1. Seed data.** The prototype hardcodes `NODES`, `STUDENTS`, and an `INIT` state map. Replace with
an initial `NetworkSnapshot` fetched from MedSim on mount.

**2. Live polling.** The prototype runs `setInterval(this.tick, 2800)` cycling scripted state changes.
Replace with the real source:

- **Preferred — push:** subscribe to MedSim's device/network event stream (WebSocket / SSE / native
  event bus). On each event, apply the delta (or request a fresh snapshot) and re-render.
- **Fallback — poll:** `GET` the current snapshot on an interval (the prototype's 2.8 s cadence is a
  reasonable default; tune to MedSim's update rate). Use it if no push channel exists.

Render is already reactive: when the snapshot changes, recompute derived links + counts and the
diagram updates. Preserve that one-way data flow.

**3. Tag binding.** Prototype tags (`CART-01`, `MAN-01`, `STU-01`, …) are a **test scheme**. In
production, `tag` and `id` come from MedSim's device registry; the UI just displays `tag` and keys on
`id`. Do not generate tags client-side.

**4. Relationship changes.** When MedSim reports an assignment/role/equipment change (a manikin moved
into a room, a student picking up a patient, a charge-nurse role handed off), the snapshot changes and
links re-render. Animate transitions subtly (fade/redraw) so the instructor notices the change without
the view jumping.

---

## Dynamic layout requirements

The prototype's coordinates are fixed for one room × three patients. Production must **lay out from
data**:

- **1–8 patients per room** (render occupied beds + remaining open-bed capacity).
- **Multiple rooms** within a unit.
- **Multiple units** (ER / ICU / Med-Surg / Psych) — current system is one room/one unit, but the
  contract and layout must scale without a rewrite. Treat unit/room as zoom/grouping levels.
- Both Option A (tiered) and Option C (radial) must accept variable counts and still stay legible
  (lanes/arcs computed, labels non-overlapping, links non-crossing where possible).
- Keep minimum legible sizes: device blocks readable at the tag+name scale below; never shrink hit/
  read targets past legibility when many nodes are present — prefer paging/grouping or a unit/room
  selector over cramming.

---

## State & persistence

- **`view`** — `'A' | 'C'`. The selected layout. Persisted to `localStorage` under the key
  **`medsim_view`** and restored on load, so the instructor's preference survives reloads during a
  session. (In the real Control Center, persist via whatever user/session-preference mechanism the app
  already uses; `localStorage` is the prototype stand-in.)
- **`snapshot`** — the latest `NetworkSnapshot` from MedSim (replaces the prototype's `st` map).
- **derived (memoized) per snapshot:** link list, status counts.

No other persistent state. The view is otherwise a pure function of `snapshot` + `view`.

---

## Interactions & behavior

- **Toggle views:** clicking a segment switches the diagram and updates the active-tab highlight;
  persists `view`. (Implementation note: in the prototype the active pill is forced to repaint by
  varying its render key when selection changes — reproduce equivalent correct active-state styling in
  your component lib.)
- **Live updates:** counts + nodes + links update on each snapshot/poll. Active links animate
  (marching ants); fault nodes/links blink subtly; control shows a scan ring.
- **No destructive actions in v1.** Read-only.

---

## Design tokens

### Color — surfaces & text
| Token | Hex |
|---|---|
| App background | `#e7e5df` |
| Card / paper | `#fffefb` |
| Card border | `#e0ddd6` |
| Ink (primary text) | `#22211d` |
| Muted text | `#6b675f` |
| Faint text / labels | `#8a8780`, `#a8a49b` |
| Hairline / divider | `#e6e3dc`, `#cfccc4` |
| Note / callout (yellow) | `#fef4a8` on `#5b531f` text |

### Color — node classes (the encoding — do not alter)
| Class | Hex |
|---|---|
| control | `#3a3f47` |
| operational | `#2f6db0` |
| character | `#8a4f9e` |
| physio (manikin) | `#1f8f7a` |
| vrai (tablet) | `#c2862c` |
| supporting | `#7b7f88` |
| student | `#b0567f` (pill tint `#fbeef3`) |
| patient (circle stroke) | `#22211d` |

### Color — status accents
| State | Hex |
|---|---|
| active (status chip) | `#2f8f6a` (green) |
| fault | `#c0473f` (red) |
| available / neutral | `#b9b6ae` |

### Typography
- **Sans:** "IBM Plex Sans" (names, body, legend) — weights 400/500/600.
- **Mono:** "IBM Plex Mono" (tags, section labels, technical readouts) — weights 400/500/600.
- Scale (px): page title 24/600; intro 12.5 mono; section labels 10 mono, letter-spacing .14em;
  node tag 8.5 mono; node name 10.5 sans/500; legend body 12 sans.

### Radii / spacing
- Card radius 6; device-block radius 5; class bar radius 1.5; student pill fully rounded (radius = h/2);
  segmented control 9 (track) / 6 (segment).
- Diagram drawn in a 600-wide SVG viewBox (heights ≈ 820 tiered / ≈ 838 radial), scaled to fit a
  ~700 px max-width column. **Treat these as proportions, not fixed production sizes.**

### Animation
| Name | Effect | Timing |
|---|---|---|
| `flow` | active-link marching ants (`stroke-dashoffset` 0 → -24) | 1 s linear infinite |
| `blink` | fault blink (opacity .9 ↔ .35) | 1.4 s ease-in-out infinite |
| `pulseRing` (`scan`) | control scan ring (scale .5 → 1.35, fade out) | 2.8 s ease-out infinite |
| `dotpulse` | polling indicator dot | 1.4 s ease-in-out infinite |
| poll cadence (mock) | scripted state cycle | 2.8 s (replace with real feed) |

---

## Edge cases to handle

- **Unknown device class / state** from the feed → render neutral gray, never crash; log for triage.
- **Disconnected vs. fault vs. available** are distinct: `fault` = was linked, now offline/error;
  `available` = known but unassigned; don't collapse them — the instructor needs the difference.
- **Manikin out of room** → `state: 'available'` (as PT-03 in the sample); the patient circle still
  renders, the manikin link reads available.
- **Reconnection** → state transitions `fault → idle/active`; animate the redraw.
- **Patient with no tablet or no manikin** → render what exists; don't assume both parts.
- **Student with 0 patients / no role** → still render the pill (a participant present but unassigned).
- **Re-assignment / role handoff mid-session** → links move; transition smoothly.
- **Scale:** many patients/rooms/units → page or group rather than overflow; keep labels legible.

---

## Roadmap (post-v1, not in this prototype)

- Per-node **inspect**: click a device/patient/student to see link history, last-seen, raw MedSim ids.
- **Unit/room selector** and zoom levels for multi-room / multi-unit (ER / ICU / Med-Surg / Psych).
- Alerting: surface new faults to the instructor (toast / badge) so they don't have to be watching.

---

## Files in this bundle

- `MedSim Device Topology.dc.html` — the interactive design prototype (open in a browser; toggle
  Option A / Option C; watch the simulated live polling). **Reference only.**
- `schema.ts` — the `NetworkSnapshot` data contract (entities, enums, derived links).
- `sample_payload.json` — a complete snapshot matching the prototype's scenario; use it as a fixture.
- `README.md` — this document.
