# @vrai/tablet-ios

Capacitor wrapper for VRAI Faces on iPadOS. Per ADR-0006, the iPadOS 26
PWA path has a background-audio regression that breaks clinical use, so
we ship a Capacitor shell with `UIBackgroundModes` audio.

## Required iOS Info.plist keys

When `pnpm sync` runs, edit `ios/App/App/Info.plist` and ensure:

```xml
<key>UIBackgroundModes</key>
<array>
  <string>audio</string>
</array>
<key>NSMicrophoneUsageDescription</key>
<string>VRAI Faces does not record audio. This entitlement is required
by AudioWorklet only and is never used to capture.</string>
```

## Build

```bash
pnpm -F @vrai/tablet-ios build:web    # vite build + cap copy
pnpm -F @vrai/tablet-ios sync         # update native project
pnpm -F @vrai/tablet-ios open         # opens Xcode
```

The Xcode project is created by `npx cap add ios` on first setup —
that step is intentionally manual (it writes to `ios/`).
