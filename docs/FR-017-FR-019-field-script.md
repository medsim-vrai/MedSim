# FR-017 Scenario Exchange + FR-019 N0/N4 — Field-Test Script

**Scope:** the session's shipped work — **FR-017** scenario export/import between
MedSim systems, **FR-019 N0** roster ROLES (a student fills an AI character seat),
**FR-019 N4** scale layout + instructor-managed device links — plus the
same-session regressions worth re-checking (per-seat auth, login key re-arm,
tablet speech in/out, card-system default). Run on the Mac (operator) + a tablet
or two. Mark each step PASS/FAIL; paste failures back to Claude Code with the
step #.

**Committed:** `fe2e24a` (FR-017 + FR-019 N0/N4 + code-review fixes; 1176 tests).
**Companion:** the base network view is documented in `FR-019-network-status.md`;
scenario exchange design in `FR-017-scenario-exchange.md`.

---

## 0. Preconditions

- **Launcher — state it, don't assume.**
  - Mac-browser-only tests (A, B, C, E): the local launcher is fine
    (`bash scripts/run_cards.sh` → `https://127.0.0.1:8760`).
  - Tablet tests (D): use the **LAN launcher** — `bash scripts/start.sh` →
    tablets reach `https://<LAN-IP>:8760`. `run_cards.sh` binds loopback only, so
    tablets get "portal unreachable" against it.
- **Seat:** sign in as **Admin** (master vault password) for the credential /
  EHR-admin checks; **Instructor** is fine for scenarios + network.
- After any restart: **re-login** (in-memory vault clears; login re-arms the
  Anthropic key so characters don't echo). The room resumes on its own.

---

## A. FR-017 — Scenario export / import  *(Mac)*

**A1 — Export round-trips**
1. Set up → **Scenarios**. Each row now has **Export** (next to Edit / Docs).
   Click it on a scenario that has characters (ideally one with a support doc).
2. ☐ A `*.medsim-scenario.json` downloads. Open it: expect `_manifest`
   (`checksum`, `external_assets`), `scenario`, `characters[]`, and any
   `support_documents` (base64).

**A2 — Import into this system**
1. Scenarios header → **Import…** → choose the file from A1 → **Import**.
2. ☐ Import succeeds. Because the ids already exist, the scenario lands under a
   **new suffixed id** (the original is untouched) and identical characters read
   **"linked."** A **Review & edit** button appears.
3. Click **Review & edit** → ☐ the edit form opens on the imported copy.

**A3 — Collision + post-import checklist**
1. Export a scenario whose scenario has a `kb_scope` tag and/or a character with
   an avatar. Import it.
2. ☐ The checklist warns to **reassign the avatar** and/or **provide the
   local-context tag** (those don't travel — consent- / install-specific).

**A4 — Robustness**
1. Open the downloaded JSON, change the scenario `name`, save, re-import.
   ☐ Imports with a **checksum-mismatch note** (not a hard failure); the new
   name shows.
2. ☐ (Sanity) an obviously-not-a-bundle file (any random `.json`) is refused
   with a clear message, nothing lands.

---

## B. FR-019 N0 — Roster roles fill the AI seat  *(Mac)*

1. Launch a room whose scenario includes a **doctor / respiratory therapist /
   pharmacist** character.
2. Set up → **Assignments** (or the classic-control roster). The role selector
   now offers **Doctor / Respiratory therapist / Pharmacist (fills the AI
   seat)**. Add a student to one.
3. Open **Operate → Network & devices**.
4. ☐ That character node shows a **student-colored dashed frame + the student's
   name**, and the student's **role link** points to *that* seat.
5. ☐ The seat reads **idle** until the student actually signs in (cabinet /
   records terminal); it flips **active** once they do. A student who was just
   rostered but never joined is **not** falsely "active."
6. ☐ A plain **Nurse** assignment does **not** fill any character seat (it's a
   bedside/cart role, not a character).

---

## C. FR-019 N4 — Scale + managed links  *(Mac)*

**C1 — Scale**
1. Build a room with **4–8 beds** (or a device-heavy single room). Open Network &
   devices; toggle **Tiered ↔ Radial** (top-right).
2. ☐ The layout **spreads to fit** — no cramming or overflow off the frame; the
   radial arc staggers when busy and stays inside the viewbox.
3. ☐ Changing an assignment triggers a brief **cross-fade**, not a hard flash,
   and only when the geometry actually changes.

**C2 — Instructor-managed links**
1. Tick **"Manage links."** Click a device node repeatedly.
2. ☐ It cycles **available → fault → auto**, shows a small **amber "managed"
   marker**, and the state sticks across the ~3 s polls. Works on tiles (Tiered)
   and chips (Radial).
3. End the session (or start a new one). ☐ The overrides **clear** — they're
   session-scoped, never persisted.

---

## D. Tablet regressions  *(needs the LAN launcher)*

1. On the iPad, re-scan a character QR. **Do the close-open twice dance** (fully
   swipe the tab away, reopen, repeat once) so the service worker takes the new
   build. If still stale: Settings → Safari → Advanced → Website Data → delete the
   `<LAN-IP>` entry, re-scan.
2. **Speech in (tail):** speak a sentence and release the button *right on* the
   last word. ☐ The whole sentence reaches the character — no clipped ending.
3. **Speech out (stage directions):** if the character emits `*an action*`.
   ☐ It's **shown in the transcript but not spoken**.
4. **Reply logic:** ☐ the patient answers **in character**, not the echo
   "I heard you say…". (If it echoes: the Anthropic key is rejected — see E2.)

---

## E. Auth / key regressions  *(Mac)*

1. **Seat gate:** sign in as **Instructor** → open `/portal/credentials`.
   ☐ **403** with a "sign in with the Admin seat" message. Re-sign as **Admin**.
   ☐ The page opens and shows the **Seat passwords** section (Instructor /
   Observer, optional, 8-char minimum; master password = the Admin seat).
2. **Key re-arm across restart:** with a room resumed, restart the server and log
   back in (Admin). ☐ Characters respond **without** re-starting the room (login
   re-arms the API key). If the key itself is stale, the character says
   "Anthropic API key was rejected — update it on the Credentials page."
3. **Card default:** a plain launch lands on the **card system** (`/portal/console`),
   not classic. ☐ (`MEDSIM_DEFAULT_VIEW=classic` opts back to classic.)

---

## Report

Paste failures to Claude Code as `<step#> — <what happened>`. For anything
speech- or bundle-related, include whether the tablet was on the fresh build
(step D1) and which launcher was used.
