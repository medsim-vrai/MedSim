# CONTINUATION.md — Pause / Resume Protocol for V7 Build

This document is the contract that lets the V7 multi-patient build span
many sessions, pauses, and stoppages without loss of data or context.
It exists because the full plan is ~41 engineer-days across 22 modules
— far longer than any single session — so the build is deliberately
designed to checkpoint at module boundaries.

## The seven-step resume protocol

A fresh Claude Code session — with no memory of prior work — should be
able to continue the build cleanly by following these steps in order.

### 1. Read the workspace map
- `BUILD_STATE.md` — phase table with per-module status. **The source of truth for "where are we?"**
- `CLAUDE.md` — V7 overview and inherited V5/V6 context.
- `CONTINUATION.md` (this file) — the resume protocol.

### 2. Read the build script
- `../../Multipatient multi student simualtion/deliverables/Development_Plan.md`
  — the 22-module specification.
- `../../Multipatient multi student simualtion/research/p6_v7_architecture.md`
  — the design rationale for every architectural choice.

### 3. Pick the next module
From the `BUILD_STATE.md` phase table, find the lowest-numbered module
with status `NOT STARTED` whose `Blocked by` row is fully `DONE`. The
dependency graph is reproduced in `Development_Plan.md` §"Module
dependency graph"; if multiple modules are unblocked, prefer the
lowest module number (earlier phases tend to set up context later
phases depend on).

### 4. Read the module guide
Open `docs/module_guides/M{NN}_{slug}.md`. If the guide does not exist
yet, copy `docs/module_guides/MODULE_GUIDE_TEMPLATE.md` and fill in
the Purpose / Structure / Uses / Functions sections from the
Development Plan specification before coding. This forces the design
to be explicit before implementation — and gives the next session a
starting point.

### 5. Build
- New code lives where the Development Plan says it lives.
- v7-specific tests go in `tests/v7/`. Existing v6 tests stay where
  they are; they are the regression contract.
- Run the module's acceptance tests:
  `../medsim_v6/.venv/bin/python -m pytest tests/v7/ -q`
  (a dedicated `medsim_v7/.venv` is on the eventual cleanup list but
  is not blocking — v7 deps match v6 deps exactly).

### 6. Update artifacts
**Before marking the module DONE in `BUILD_STATE.md`, update:**
- The module's PDF guide: change-list entry, test-status section,
  current functions list.
- `BUILD_STATE.md` phase table row: status, files, tests, date.
- `BUILD_STATE.md` "What's been built so far" section: a short
  description of what landed.
- The session-log table at the bottom of `BUILD_STATE.md`.

### 7. Pause cleanly
If the session must pause mid-module:
- Commit what's done. Even partial code is better than rebuild from
  scratch; future-you reads the diff.
- In the module's PDF guide change-list, add an entry tagged
  `IN PROGRESS — pause point` describing exactly what remains.
- Set the module's status in `BUILD_STATE.md` to `IN PROGRESS` (not
  DONE).
- The next session sees the `IN PROGRESS` row first and resumes there.

## Data durability guarantees

The build is designed so that a pause never loses simulation content:

1. **SQLite is the system of record** at `~/.medsim/v7/medsim.db`. All
   chart events, device events, comparison reports, and (with M1) all
   room / student / activity rows are durable across server restarts.
2. **Schema migrations are append-only.** Each migration runs at most
   once, gated on `schema_version`. A v6 DB upgrading to v7 keeps every
   row; new columns get NULL/default.
3. **Per-module PDF guides are durable design memory.** Decisions made
   while building M4 are still there when you read M8.
4. **The persona library, the activity catalog, and the device
   inventory are seed data** in `portal/data/` and `portal/devices/`.
   Never invalidated by a code change; safe to read on every start.
5. **No global mutable state crosses module boundaries.** The
   `_active_room` singleton in `control_room.py` is created from DB
   state on demand and disposed cleanly at room end.

## When to NOT follow this protocol

- If the user explicitly says "skip the per-module guide, just code."
  Honor that — record the deviation in the session-log row.
- If a module fails its acceptance tests, do not mark it DONE. Leave
  the row `IN PROGRESS` with a failing-tests note. Future sessions
  treat that as the resume point.
- If a module's spec turns out to be wrong (e.g. the route refactor in
  M3 turns out to need a different strategy than P6 §4.1 suggests),
  update `docs/module_guides/M{NN}_{slug}.md` with the revised design
  AND post the rationale to the session log. Then implement the
  revision. **Do not edit the Development_Plan.md or P6 itself** —
  those are checkpointed research artifacts.

## Cross-references

- The study project lives at
  `/Users/petermarotta/Documents/Claude/Projects/Multipatient multi student simualtion/`.
  Its `Memory_Management.md` is the study tracker; this V7 BUILD_STATE
  is the implementation tracker. The two are linked at the section-2
  pointer in `Memory_Management.md`.
- The V6 baseline lives at `../medsim_v6/`. **Do not modify it.** It is
  the fallback if V7 has to be reverted. Read its `BUILD_STATE.md` to
  understand what behaviors V7 must preserve.
