#!/bin/bash
# medsim portal — macOS launcher (LAN mode, 0.0.0.0).
#
# Works on every Mac: MacBook Air, MacBook Pro, iMac, Mac mini, Mac Studio,
# Mac Pro — both Intel and Apple Silicon (M1/M2/M3/M4). Same script for all.
#
# Use this to access the portal from an iPad/iPhone on the same Wi-Fi as
# the Mac running the portal. The console prints a LAN URL like
# http://192.168.x.x:8765 — open that in Safari on iOS/iPadOS.
#
# First time only: macOS Gatekeeper may block — right-click → Open → Open.

cd "$(dirname "$0")/../.." || exit 1

# ---------------------------------------------------------------------------
# Find a Python ≥ 3.11. See the local launcher for the full rationale; this
# is the same logic.
# ---------------------------------------------------------------------------
python_ok() {
  command -v "$1" >/dev/null 2>&1 && \
    "$1" -c 'import sys; sys.exit(0 if sys.version_info >= (3, 11) else 1)' 2>/dev/null
}

PY=""
for cmd in python3.13 python3.12 python3.11 python3; do
  if python_ok "$cmd"; then
    PY="$cmd"
    break
  fi
done

if [ -z "$PY" ]; then
  detected=$(python3 --version 2>/dev/null || echo "(not installed)")
  echo
  echo "  Error: Python 3.11 or newer is required."
  echo "  Detected: $detected"
  echo
  echo "  Install a newer Python and run this launcher again:"
  echo
  if command -v brew >/dev/null 2>&1; then
    echo "    brew install python@3.12       (Homebrew detected — recommended)"
  else
    echo "    Install Homebrew first:  https://brew.sh"
    echo "    then run:                brew install python@3.12"
  fi
  echo "    Or use the official installer: https://www.python.org/downloads/"
  echo
  read -n 1 -s -r -p "Press any key to close..."
  exit 1
fi

echo "Using $PY ($("$PY" --version))"

if [ -d ".venv" ] && ! python_ok .venv/bin/python; then
  echo "Existing .venv uses too-old Python — recreating with $PY..."
  rm -rf .venv
fi

if [ ! -d ".venv" ]; then
  echo "Creating virtual environment with $PY..."
  "$PY" -m venv .venv
fi

# shellcheck disable=SC1091
source .venv/bin/activate

if ! python -c "import portal.server" 2>/dev/null; then
  echo "Installing dependencies (one-time, ~30 seconds)..."
  pip install --quiet --upgrade pip
  pip install --quiet -e ".[serve]"
fi

export MEDSIM_HOST=0.0.0.0

# MacBook note: `caffeinate` keeps the system, display, and disk awake while
# the portal is running. Critical in iPad mode — if the MacBook sleeps, the
# iPad/iPhone connection drops mid-scenario. Keep the lid open and on AC
# power for best reliability during a teaching session.
if command -v caffeinate >/dev/null 2>&1; then
  caffeinate -dims python run_portal.py
else
  python run_portal.py
fi

echo
read -n 1 -s -r -p "Press any key to close..."
