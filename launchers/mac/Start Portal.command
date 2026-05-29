#!/bin/bash
# medsim portal — macOS launcher (local mode, 127.0.0.1).
#
# Works on every Mac: MacBook Air, MacBook Pro, iMac, Mac mini, Mac Studio,
# Mac Pro — both Intel and Apple Silicon (M1/M2/M3/M4). Same script, no
# changes needed; macOS resolves the right Python for the architecture.
#
# Double-click this file in Finder to start the portal.
# First time only: macOS Gatekeeper may block — right-click → Open → Open.

cd "$(dirname "$0")/../.." || exit 1

# ---------------------------------------------------------------------------
# Find a Python ≥ 3.11.
#
# Apple's stock /usr/bin/python3 from the Xcode Command Line Tools is frozen
# at 3.9 and is too old for this project. We explicitly look for newer
# interpreters first (installed by Homebrew or python.org), then fall back
# to whatever `python3` resolves to and verify its version.
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

# Recreate .venv if it was made with too-old Python (e.g. a first-run that
# happened to pick up Apple's 3.9 before this launcher was hardened).
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

# MacBook note: `caffeinate` keeps the system, display, and disk awake for
# as long as run_portal.py is running. Without it, the portal stops the
# moment the screen sleeps. Keep the lid open and on AC power for best
# reliability during a teaching session.
if command -v caffeinate >/dev/null 2>&1; then
  caffeinate -dims python run_portal.py
else
  python run_portal.py
fi

echo
read -n 1 -s -r -p "Press any key to close..."
