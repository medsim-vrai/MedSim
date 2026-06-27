#!/usr/bin/env bash
# ===========================================================================
# Training Bridge MedSim — clean-slate RESET between field tests.
#
#   bash scripts/reset.sh               # archive runtime state (recoverable)
#   bash scripts/reset.sh --purge-backups   # also delete old .bak archives
#
# WHY: rooms / sessions / device registrations / staff assignments and the
# G1 resume snapshot all live in ONE runtime DB. Between tests they linger
# (the server auto-resumes the old room, stale devices show up, etc.). This
# archives that DB so the next launch starts from a clean, empty room.
#
# CLEARS (archived, not destroyed):
#   ~/.medsim/v7/medsim.db   — rooms, sessions, devices, events, staff, snapshot
#   portal/data/scanned_documents/  — per-run student-scanned chart docs (deleted)
# PRESERVES:
#   ~/.medsim/vault.enc            — credentials (password still works)
#   portal/data/face_skins/        — saved/developed face skins
#   scenarios + sample_scenarios   — patient/scenario library (in the repo)
#   portal/data/certs/             — TLS cert/CA (no device re-trust needed)
#
# Safe + reversible: the DB is renamed to medsim.db.bak.<timestamp>, and the
# 5 most recent archives are kept. To undo the last reset: stop the server and
# `mv` the newest .bak back to medsim.db.
# ===========================================================================
set -euo pipefail
cd "$(dirname "$0")/.."

V7_DIR="$HOME/.medsim/v7"
DB="$V7_DIR/medsim.db"

# Stop the portal first so it isn't holding the DB or re-writing the snapshot
# on exit (which would re-create the state we're trying to clear).
pkill -TERM -f run_portal.py 2>/dev/null && { echo "• Stopped running portal."; sleep 1; } || true

if [[ "${1:-}" == "--purge-backups" ]]; then
  rm -f "$V7_DIR/"medsim.db.bak.* 2>/dev/null || true
  echo "✓ Old runtime-DB archives removed."
fi

if [[ -f "$DB" ]]; then
  STAMP="$(date +%Y%m%d-%H%M%S)"
  mv "$DB" "$DB.bak.$STAMP"
  # Move the SQLite WAL/SHM sidecars too, so the fresh DB starts truly clean.
  for sfx in -wal -shm; do
    [[ -f "$DB$sfx" ]] && mv "$DB$sfx" "$DB.bak.$STAMP$sfx" || true
  done
  echo "✓ Runtime state cleared → archived to medsim.db.bak.$STAMP"
else
  echo "• No runtime DB found — already a clean slate."
fi

# FR-014 — per-run student-scanned chart documents are ephemeral (keyed by the old
# run's encounter ids); delete them so the next scenario starts with clean charts.
if [[ -d "portal/data/scanned_documents" ]]; then
  rm -rf portal/data/scanned_documents/* 2>/dev/null || true
  echo "✓ Cleared scanned chart documents."
fi

# Keep only the 5 most recent archives.
ls -1t "$V7_DIR/"medsim.db.bak.* 2>/dev/null | tail -n +6 | xargs rm -f 2>/dev/null || true

echo "  Preserved: vault, face skins, scenarios, TLS certs."
echo "  Fresh launch:  bash scripts/start.sh        (clean room)"
