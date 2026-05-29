# vrai-faces

Translucent, animatable 3D facial-avatar surface for **MedSim V8**.

This workspace is the **how** for VRAI Faces. The **what / why** lives in:

- `../Memory_management.MD` — architectural memory; ADRs; module contracts.
- `../docs/VRAI_Faces_Claude_Code_Guide.md` — coding patterns, perf recipes, stability rails.
- Strategy PDFs in `/Users/petermarotta/Documents/Claude/Projects/Animated faces/`.

## Layout

```
vrai-faces/
├── packages/
│   ├── core/             # the shared web bundle (Vite + TS + Three.js)
│   ├── tablet-ios/       # Capacitor iOS wrapper (ADR-0006)
│   └── tablet-android/   # Capacitor Android wrapper
└── docs/                 # design notes, ADR scratch, perf logs
```

## Quickstart (when dependencies are installed)

```bash
pnpm install
pnpm dev            # vite dev server on :5173, hot-reload
pnpm typecheck      # tsc --noEmit, strict
pnpm test           # vitest unit tests
pnpm test:e2e       # playwright (desktop + iOS-sim + Android-emu lanes)
```

## How it plugs into MedSim V8

- The MedSim portal (`../portal/`) serves a QR code at
  `GET /qr/face/<characterId>`. The QR encodes a LAN URL that loads the
  `@vrai/core` bundle in full-screen mode.
- Speech output from MedSim flows as `VRAISpeechFrame` packets over
  BroadcastChannel (same-origin) or WebSocket (cross-app on a tablet) —
  see `Memory_management.MD §6.2`.
- The `medsim_adapter` module is the only module that knows about MedSim.

## Module boundary rule

Cross-module imports go through each module's `index.ts` barrel — never
into another module's `impl/`. A lint rule enforces this.
