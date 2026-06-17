#!/usr/bin/env bash
# ---------------------------------------------------------------------------
# Training Bridge MedSim — v7.1 "card launch"
#
# Boots the portal straight into the NEW Mission Control card system
# (/portal/console) instead of the classic home. Classic stays one click away:
#   • in the card UI (top-right):  "Switch to classic control room ↗"
#   • in the classic sidebar:      "🎛 Mission Control (cards)"
#
# It just sets MEDSIM_DEFAULT_VIEW=console and runs the normal launcher, so the
# "/" + login redirects land on the cards and Chrome opens straight to them.
#
# Usage:
#   bash scripts/run_cards.sh                 # local  -> https://127.0.0.1:8765
#   MEDSIM_HOST=0.0.0.0 bash scripts/run_cards.sh   # LAN (tablets)
#   MEDSIM_NO_BROWSER=1 bash scripts/run_cards.sh   # headless (no auto-open)
#
# The plain `python run_portal.py` still defaults to the CLASSIC home, so this
# script is the opt-in 7.1 card-first launch.
# ---------------------------------------------------------------------------
set -euo pipefail
cd "$(dirname "$0")/.."
export MEDSIM_DEFAULT_VIEW=console
exec .venv/bin/python run_portal.py
