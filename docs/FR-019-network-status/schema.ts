/**
 * MedSim — Network & Tool Status
 * Data contract for the instructor Control Center "Network & Tool Status" tool.
 *
 * This file defines the shape the UI consumes. The prototype hardcodes equivalent
 * data; in production these objects come from MedSim (see INTEGRATION in README.md).
 *
 * Design rule: the UI never invents status. Every node's appearance is a pure
 * function of `state`; every link's appearance is a pure function of its endpoint
 * device `state` (or, for student links, the relationship type). Keep it that way —
 * push truth from MedSim, render from truth.
 */

// ─────────────────────────────────────────────────────────────────────────────
// Enums
// ─────────────────────────────────────────────────────────────────────────────

/** The class of a node. Drives COLOR in the UI. */
export type DeviceClass =
  | 'control'    // the instructor control station itself (one per session)
  | 'operational'// shared operational devices: med cart, nurses station, records station
  | 'character'  // shared character roles: doctor, supervising nurse, charge nurse, RT, pharmacist
  | 'physio'     // patient MANIKIN — physical device linked to the physiologic engine
  | 'vrai'       // patient TABLET — VR/AI avatar interface presenting the patient character
  | 'supporting';// supporting patient devices: IV pump, alarm panel, etc.

/** The live link/availability status of a node. Drives LINE STYLE + status pip in the UI. */
export type LinkState =
  | 'active'     // linked & active — in use right now
  | 'idle'       // linked & idle — registered and ready, not currently in use
  | 'available'  // available — powered/known but unassigned to this scenario
  | 'fault';     // disconnected / offline / fault

/** Where a node physically lives. Common devices roam common areas; patient devices live in rooms. */
export type CommonArea = 'hall' | 'nurses_station' | 'wing' | 'unit';

/** A role a shared character device — or a student — can occupy. */
export type Role =
  | 'doctor'
  | 'supervising_nurse'
  | 'charge_nurse'
  | 'respiratory_therapist'
  | 'pharmacist';

// ─────────────────────────────────────────────────────────────────────────────
// Entities
// ─────────────────────────────────────────────────────────────────────────────

/**
 * A unit (e.g. ER, ICU, Med-Surg, Psych). Current system handles ONE unit with ONE room;
 * the contract is modeled for many so the layout engine can scale without a rewrite.
 */
export interface Unit {
  id: string;
  name: string;            // "Unit A", "ICU", …
  focus?: string;          // "ER" | "ICU" | "Med-Surg" | "Psych" | …
  rooms: Room[];
}

export interface Room {
  id: string;
  label: string;           // "Room 1"
  capacity: number;        // up to 8 patients per room
  patients: Patient[];     // 1..capacity occupied beds; empty beds are (capacity - patients.length)
}

/** The patient as a network entity. Rendered as a CIRCLE. Composed of 1–2 device parts + supporting devices. */
export interface Patient {
  id: string;
  tag: string;             // MedSim-assigned, e.g. "PT-01"
  bed: number;             // 1..capacity
  /** Physical manikin (class 'physio'). May be absent when the manikin is out of the room. */
  manikin?: Device;
  /** Tablet/avatar interface (class 'vrai'). */
  tablet?: Device;
  /** Supporting devices assigned to this patient (class 'supporting'): IV pumps, alarm panels, … */
  supporting: Device[];
}

/** Any non-patient, non-student node rendered as a BLOCK. */
export interface Device {
  id: string;
  tag: string;             // MedSim-assigned device id, e.g. "CART-01", "MAN-01", "MD-01"
  name: string;            // human label, e.g. "Med Cart", "Manikin", "Doctor"
  cls: DeviceClass;
  state: LinkState;
  /** For common devices: which area they're in. */
  area?: CommonArea;
  /** For 'character' devices: the role they represent. */
  role?: Role;
  /**
   * Optional assignment of a shared device/character to a specific patient or character.
   * Renders as a dashed "assigned" connector. e.g. a Doctor character assigned to PT-01.
   */
  assignedToPatientId?: string;
}

/**
 * A student/participant. Rendered as a PILL with a person glyph (NOT a device block) —
 * students are people in the network, not equipment.
 * A student may be assigned 1+ patients and may fill a shared character role
 * (typically charge_nurse or supervising_nurse).
 */
export interface Student {
  id: string;
  tag: string;             // e.g. "STU-01"
  name: string;            // display name (anonymized id is fine for the test scheme)
  patientIds: string[];    // 1..N assigned patients → dashed "student→patient" links
  role: Role | null;       // role filled, if any → dotted "student→role" link to that character node
}

/** The control station. Exactly one per session. Rendered as the hub / top node. */
export interface ControlStation {
  id: string;
  tag: string;             // "CTRL-01"
  name: string;            // "Instructor Control"
  state: LinkState;        // normally 'active'
}

/**
 * The full snapshot the UI renders. MedSim should be able to produce this on demand
 * (poll) and/or push deltas (see INTEGRATION). The UI is stateless w.r.t. truth —
 * it renders whatever the latest snapshot says.
 */
export interface NetworkSnapshot {
  sessionId: string;
  timestamp: string;       // ISO 8601, when this snapshot was generated
  control: ControlStation;
  /** Shared common devices (operational + character) available across the simulation. */
  commonDevices: Device[];
  units: Unit[];
  students: Student[];
}

// ─────────────────────────────────────────────────────────────────────────────
// Derived links (computed by the UI from the snapshot — not sent over the wire)
// ─────────────────────────────────────────────────────────────────────────────

export type LinkKind =
  | 'control'   // control → device/patient-device (colored by the target's class, styled by target state)
  | 'local'     // patient circle → its manikin/tablet/supporting (colored by class, styled by state)
  | 'assign'    // shared device/character → patient (dashed)
  | 'student'   // student → assigned patient (dashed, student color)
  | 'role';     // student → filled role node (dotted, student color)

export interface DerivedLink {
  fromId: string;
  toId: string;
  kind: LinkKind;
  cls: DeviceClass | 'student';
  state: LinkState | 'assign' | 'role';
}
