#!/usr/bin/env bash
# ===========================================================================
# Training Bridge MedSim — ONE-COMMAND launch for tablet / field testing.
#
#   bash scripts/start.sh          # launch (for iPads on the LAN)
#   bash scripts/start.sh fresh    # clean-slate reset, THEN launch
#   bash scripts/start.sh stop     # stop the server
#
# Brings the whole system up the way TABLETS need it — this is the difference
# from a plain local run that only works in the Mac's own browser:
#   • binds the LAN (MEDSIM_HOST=0.0.0.0) so iPads can actually reach it
#   • run_portal auto-re-mints the TLS cert for the CURRENT LAN IP at boot,
#     so moving Wi-Fi networks doesn't break TLS on the tablets
#   • serves the avatar app from the portal origin (tablet avatars need this)
#   • lands on the Mission Control card UI
#   • opens the operator console on THIS Mac at the LAN URL — so every QR code
#     the portal generates carries the LAN IP, never 127.0.0.1
#
# After it's up: RE-PRINT the QR sheet (old codes may point at a previous IP),
# put the iPads on the SAME Wi-Fi with Private Wi-Fi Address OFF, and scan.
# ===========================================================================
set -euo pipefail
cd "$(dirname "$0")/.."

PORT="${MEDSIM_PORT:-8765}"
LOG="${MEDSIM_LOG:-/tmp/medsim_portal.log}"
PY=".venv/bin/python"

# ── stop ──────────────────────────────────────────────────────────────
if [[ "${1:-}" == "stop" ]]; then
  pkill -TERM -f run_portal.py 2>/dev/null && echo "✓ Server stopped." \
    || echo "Nothing was running."
  exit 0
fi

# fresh = clean-slate reset (archive the runtime DB) BEFORE launching, so the
# session starts with no stale room / devices / staff / resume snapshot.
if [[ "${1:-}" == "fresh" ]]; then
  bash "$(dirname "$0")/reset.sh"
  echo
fi

[[ -x "$PY" ]] || { echo "✗ $PY not found — create the venv first."; exit 1; }

IP="$(ipconfig getifaddr en0 2>/dev/null || ipconfig getifaddr en1 2>/dev/null || echo '127.0.0.1')"
if [[ "$IP" == "127.0.0.1" ]]; then
  echo "⚠ No LAN IP found (Wi-Fi off?). Tablets won't be able to connect."
fi

# Stop any existing instance first (no stale code, no port clash).
pkill -TERM -f run_portal.py 2>/dev/null && sleep 1 || true

export MEDSIM_HOST=0.0.0.0          # bind the LAN, not just localhost
export MEDSIM_PORT="$PORT"
export MEDSIM_DEFAULT_VIEW=console  # land on the card UI
export VRAI_FACES_SERVE=portal      # tablet avatars served from this origin
export MEDSIM_NO_BROWSER=1          # we open the LAN URL ourselves (not localhost)

echo "▶ Launching MedSim on the LAN → https://$IP:$PORT   (log: $LOG)"
nohup "$PY" run_portal.py > "$LOG" 2>&1 &
PID=$!

# Wait for the port to come up (~20s max).
for _ in $(seq 1 40); do
  lsof -nP -iTCP:"$PORT" -sTCP:LISTEN >/dev/null 2>&1 && break
  sleep 0.5
done

if ! lsof -nP -iTCP:"$PORT" -sTCP:LISTEN >/dev/null 2>&1; then
  echo "✗ Server didn't come up — last log lines:"; tail -n 20 "$LOG"; exit 1
fi

# Surface the cert / bind lines from the boot banner.
grep -iE "cert|re-mint|listening|lan|https" "$LOG" 2>/dev/null | tail -6 || true

# Open the operator console at the LAN URL so QR codes use the LAN IP.
open -a "Google Chrome" "https://$IP:$PORT/portal/console?mode=operate" 2>/dev/null \
  || open "https://$IP:$PORT/portal/console?mode=operate" 2>/dev/null || true

cat <<EOF

  ✅ Up on the LAN  ·  PID $PID
     Operator (this Mac):  https://$IP:$PORT
     Re-login (vault session clears on restart).

  📲 Tablets:  SAME Wi-Fi  ·  Private Wi-Fi Address OFF  ·  CA trusted
  ⚠  RE-PRINT the QR sheet now — old codes may point at a previous IP.

     Watch logs:  tail -f $LOG
     Stop:        bash scripts/start.sh stop
EOF
