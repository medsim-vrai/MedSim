# @vrai/tablet-ios

Capacitor wrapper for VRAI Faces on iPadOS. Per ADR-0006, the iPadOS 26
PWA path has a background-audio regression that breaks clinical use, so
we ship a Capacitor shell with `UIBackgroundModes` audio.

## Required iOS Info.plist keys

`pnpm sync` runs `apply:ios-perms` (`scripts/apply-ios-permissions.sh`), which
idempotently applies the ADR-0006 keys to `ios/App/App/Info.plist` via
PlistBuddy — no hand-editing, and they survive every `cap sync`:

```xml
<key>UIBackgroundModes</key>
<array>
  <string>audio</string>
</array>
<key>NSMicrophoneUsageDescription</key>
<string>VRAI Faces does not record audio. This entitlement is required
by AudioWorklet only and is never used to capture.</string>
```

Run it standalone any time after `npx cap add ios`:

```bash
pnpm -F @vrai/tablet-ios apply:ios-perms
```

## Build

```bash
pnpm -F @vrai/tablet-ios build:web    # vite build + cap copy
pnpm -F @vrai/tablet-ios sync         # update native project
pnpm -F @vrai/tablet-ios open         # opens Xcode
```

The Xcode project is created by `npx cap add ios` on first setup —
that step is intentionally manual (it writes to `ios/`).
