# @vrai/tablet-android

Capacitor wrapper for VRAI Faces on Android tablets. WebGPU support is
fine on Adreno; Tensor G3 needs WebGL2 fallback (ADR-0009).

## Required Android permissions

In `android/app/src/main/AndroidManifest.xml`:

```xml
<uses-feature android:name="android.hardware.touchscreen" android:required="true" />
<uses-permission android:name="android.permission.INTERNET" />
```

A foreground-service entitlement is not currently required — we do not
record audio. If the runtime ever begins recording mic input, a
microphone permission and foreground-service-type=microphone must be
added.

## Build

```bash
pnpm -F @vrai/tablet-android build:web
pnpm -F @vrai/tablet-android sync
pnpm -F @vrai/tablet-android open    # opens Android Studio
```
