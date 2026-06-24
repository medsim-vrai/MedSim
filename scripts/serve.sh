#!/usr/bin/env bash
# ---------------------------------------------------------------------------
# Training Bridge MedSim — portal launcher (Mission Control card UI)
#
# One entry point for the dev/field-test loop. Always restart-safe: it stops
# any portal already running before starting a fresh one (no stale code, no
# "address already in use").
#
#   bash scripts/serve.sh            # LOCAL  → https://127.0.0.1:8765, opens Chrome
#   bash scripts/serve.sh lan        # LAN    → https://<this-mac-ip>:8765 (tablets),
#                                    #           headless, logs to /tmp/medsim_portal.log
#   bash scripts/serve.sh stop       # stop any running portal and exit
#
# What it sets for you:
#   • MEDSIM_DEFAULT_VIEW=console  — land on the card UI (/portal/console), not classic.
#   • VRAI_FACES_SERVE=portal      — serve the BUILT avatar app from the portal origin
#                                    (:8765). REQUIRED for tablet avatars — otherwise the
#                                    QR sends the tablet to the vite dev server (:5173) and
#                                    the avatar binding fetch is cross-origin → "binding
#                                    fetch failed" / no skin / PTT unreachable.
#
# Notes:
#   • run_portal auto-re-mints the TLS leaf for the CURRENT LAN IP at boot (#70), so the
#     cert always matches the QR IP. NEVER pass the IP as --host, NEVER --remint (that
#     regenerates the CA and forces re-trust on every device).
#   • After any restart the operator must RE-LOGIN (in-memory vault auth is cleared);
#     G1 auto-resumes the room.
#   • Override the port with MEDSIM_PORT=… , the log path with MEDSIM_LOG=… .
# ---------------------------------------------------------------------------
set -euo pipefail
cd "$(dirname "$0")/.."

MODE="${1:-local}"
PORT="${MEDSIM_PORT:-8765}"
LOG="${MEDSIM_LOG:-/tmp/medsim_portal.log}"
PY=".venv/bin/python"

[[ -x "$PY" ]] || { echo "✗ $PY not found — create the venv first."; exit 1; }

# Always stop any prior instance first.
pkill -TERM -f run_portal.py 2>/dev/null && sleep 1 || true

if [[ "$MODE" == "stop" ]]; then
  echo "✓ Portal stopped."
  exit 0
fi

export MEDSIM_DEFAULT_VIEW=console
export VRAI_FACES_SERVE="${VRAI_FACES_SERVE-portal}"
export MEDSIM_PORT="$PORT"

case "$MODE" in
  lan)
    export MEDSIM_HOST=0.0.0.0
    export MEDSIM_NO_BROWSER=1
    IP="$(ipconfig getifaddr en0 2>/dev/null || ipconfig getifaddr en1 2>/dev/null || echo '<this-mac-ip>')"
    echo "▶ Starting portal for LAN/tablets → https://$IP:$PORT"
    echo "  log: $LOG   ·   stop: bash scripts/serve.sh stop"
    nohup "$PY" run_portal.py > "$LOG" 2>&1 &
    sleep 3
    echo "  PID $!  ·  recent log:"
    tail -n 12 "$LOG" 2>/dev/null || true
    echo "  Operator: open https://$IP:$PORT/login  (then /portal/console?mode=setup)"
    echo "  Watch live:  tail -f $LOG"
    ;;
  local|"")
    echo "▶ Starting portal locally → https://127.0.0.1:$PORT  (Ctrl-C to stop)"
    exec "$PY" run_portal.py
    ;;
  *)
    echo "Usage: bash scripts/serve.sh [local|lan|stop]"; exit 2 ;;
esac
