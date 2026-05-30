#!/usr/bin/env bash
# ADR-0006 — iPadOS 26 PWA has a background-audio regression, so VRAI Faces
# ships as a Capacitor app with UIBackgroundModes=audio. This script applies
# the required Info.plist keys idempotently so they survive `cap sync` without
# a manual hand-edit.
#
# Run AFTER `npx cap add ios` (which generates ios/App/App/Info.plist) and
# after each `cap sync`. macOS only — uses PlistBuddy.
#
#   pnpm -F @vrai/tablet-ios apply:ios-perms
set -euo pipefail

PLIST="${1:-ios/App/App/Info.plist}"
PB=/usr/libexec/PlistBuddy
MIC_MSG="VRAI Faces does not record audio. This entitlement is required by AudioWorklet only and is never used to capture."

if [ ! -f "$PLIST" ]; then
  echo "error: $PLIST not found — run 'npx cap add ios' first." >&2
  exit 1
fi
if [ ! -x "$PB" ]; then
  echo "error: PlistBuddy not found at $PB — this step is macOS only." >&2
  exit 1
fi

# UIBackgroundModes = [audio]  (delete-then-add keeps it idempotent).
"$PB" -c "Delete :UIBackgroundModes" "$PLIST" 2>/dev/null || true
"$PB" -c "Add :UIBackgroundModes array" "$PLIST"
"$PB" -c "Add :UIBackgroundModes:0 string audio" "$PLIST"

# Microphone usage description — AudioWorklet links AVAudioSession; we never record.
if "$PB" -c "Set :NSMicrophoneUsageDescription $MIC_MSG" "$PLIST" 2>/dev/null; then
  :
else
  "$PB" -c "Add :NSMicrophoneUsageDescription string $MIC_MSG" "$PLIST"
fi

echo "OK: UIBackgroundModes=[audio] + NSMicrophoneUsageDescription applied to $PLIST"
