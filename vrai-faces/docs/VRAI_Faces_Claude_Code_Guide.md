# VRAI Faces — Claude Code Development Guide

> A working manual for the Claude Code agents that will build VRAI Faces.
> Pair with `Memory_management.MD` (architectural memory),
> `VRAI_Faces_Technical_Strategy.pdf` (what + why), and
> `VRAI_Faces_Tablet_Integration_Strategy.pdf` (where it runs).
>
> This document is the **how**: the file layout, the coding patterns,
> the performance recipes, and the stability rails that protect low
> latency on iPad and Android tablets.

---

## 0. The agent loop (read this first)

1. **Read** `Memory_management.MD` and the relevant module `README.md`.
2. **Confirm** the contract you're about to touch is still current
   (grep for the type name; check the ADRs).
3. **Open** an ADR entry *before* changing a contract.
4. **Write** the smallest PR that completes one row of the §3 module map.
5. **Test** at three layers: typecheck, unit, Playwright E2E.
6. **Measure** against the latency budget; if a stage slips, append a
   row to `Memory_management.MD §8` with the number and a one-line
   mitigation.
7. **Mark the task complete only when** typecheck is green, unit tests
   pass, and the relevant Playwright lane is green.

If any of these gates fails, the task stays in_progress and a follow-up
task is opened. Never paper over a red gate.

---

## 1. Repository shape

```
vrai-faces/
├── packages/
│   ├── core/                          # the shared web bundle
│   │   ├── package.json
│   │   ├── tsconfig.json              # strict: true, noUncheckedIndexedAccess: true
│   │   ├── vite.config.ts
│   │   ├── src/
│   │   │   ├── main.ts                # app entry; mounts the shell
│   │   │   ├── shell/                 # UI shell (controls, slider, layout)
│   │   │   ├── modules/
│   │   │   │   ├── face_ingest/
│   │   │   │   ├── mesh_builder/
│   │   │   │   ├── shader_translucent/
│   │   │   │   ├── avatar_exporter/
│   │   │   │   ├── animation_runtime/
│   │   │   │   ├── audio_pipeline/
│   │   │   │   ├── tts_provider/
│   │   │   │   ├── emotion_driver/
│   │   │   │   ├── idle_motion/
│   │   │   │   ├── medsim_adapter/
│   │   │   │   ├── diagnostic_panel/
│   │   │   │   └── memory_state/
│   │   │   ├── types/                 # cross-module typed contracts
│   │   │   ├── workers/               # web workers + audio worklets
│   │   │   └── perf/                  # latency meters, soak harness
│   │   └── test/
│   │       ├── unit/                  # vitest
│   │       └── e2e/                   # playwright (desktop + iOS + Android)
│   ├── tablet-ios/                    # Capacitor iOS shell
│   └── tablet-android/                # Capacitor Android shell
├── Memory_management.MD
├── VRAI_Faces_Claude_Code_Guide.md    # this file
└── pnpm-workspace.yaml
```

Every module folder MUST contain:

```
modules/<name>/
├── README.md         # 1 page: what, contract, gotchas
├── index.ts          # the public barrel — the ONLY thing other modules import
├── types.ts          # local types not exposed publicly
├── impl/             # private implementation files
└── __tests__/        # vitest unit tests
```

**Cross-module imports go through `index.ts`. Period.** A lint rule
enforces this so an agent cannot accidentally reach into another
module's `impl/`.

---

## 2. The module contract template

Every public surface is a typed interface in `src/types/` plus a barrel
that re-exports a single object. Example for `shader_translucent`:

```ts
// src/types/shader_translucent.ts
export interface ShaderTranslucentModule {
  /** Build a translucent material wrapping a Three.js mesh. */
  build(opts: { meshId: string }): TranslucentMaterial;

  /** Set the slider value (0 = ghost, 1 = opaque). */
  setOpacity(materialId: string, level: number): void;

  /** Read the current settings (for export). */
  snapshot(materialId: string): TranslucentMaterialSnapshot;

  dispose(): void;
}

export interface TranslucentMaterial { readonly id: string; }
export interface TranslucentMaterialSnapshot {
  opacityLevel: number;
  transmission: number;
  opacity: number;
  fresnelStrength: number;
  specularIntensity: number;
}
```

```ts
// src/modules/shader_translucent/index.ts
import type { ShaderTranslucentModule } from '../../types/shader_translucent';
import { createImpl } from './impl/create';

export const shaderTranslucent: ShaderTranslucentModule = createImpl();
```

Why this shape:

- The interface is the **contract** — what other modules code against.
- The barrel exports a single object — easy to stub in tests.
- The `impl/` folder can be rewritten without touching consumers.

---

## 3. Performance recipes

### 3.1 Hot-loop allocation rules

The 60 Hz animation tick allocates **nothing**. Pre-allocate all buffers
once at module boot; reuse them per frame.

```ts
// animation_runtime/impl/tick.ts
const SHAPE_COUNT = 52;
const weights = new Float32Array(SHAPE_COUNT);     // reused every tick
const tmpVisemes = new Float32Array(SHAPE_COUNT);  // reused every tick

export function tick(now: number, state: TickState) {
  // 1. zero the buffer
  weights.fill(0);

  // 2. sum sources
  addVisemeWeights(weights, state.viseme, now);
  addEmotionWeights(weights, state.emotion, now);
  addIdleWeights(weights, state.idle, now);

  // 3. clamp + write to GPU (Three.js morphTargetInfluences is a regular array,
  //    so we must copy — but only once per frame)
  const targets = state.mesh.morphTargetInfluences!;
  for (let i = 0; i < SHAPE_COUNT; i++) {
    const w = weights[i];
    targets[i] = w > 1 ? 1 : (w < 0 ? 0 : w);
  }
}
```

Rules of thumb:
- No `new`, no array literals, no closures created per frame.
- Use `Float32Array` for numeric buffers, not `number[]`.
- Use `for (let i = 0; i < n; i++)` over `forEach` in hot paths.
- Avoid `Object.assign` in hot paths; mutate fields directly.

### 3.2 Three.js geometry: write once, mutate forever

```ts
// mesh_builder/impl/create.ts
const positionAttr = new THREE.BufferAttribute(
  new Float32Array(VERT_COUNT * 3), 3
);
positionAttr.setUsage(THREE.DynamicDrawUsage);
geometry.setAttribute('position', positionAttr);
// later: positionAttr.array updated in place; positionAttr.needsUpdate = true;
```

Never call `geometry.setAttribute` in a hot loop — it forces a GPU
re-upload of the whole attribute layout.

### 3.3 OffscreenCanvas + worker for the renderer (optional)

On Capacitor iOS, `OffscreenCanvas` requires Safari 16.4+ (fine for our
target). When available, run the renderer in a Web Worker:

```ts
// renderer/spawn.ts
export function spawnRenderer(canvas: HTMLCanvasElement) {
  if (typeof OffscreenCanvas !== 'undefined' &&
      'transferControlToOffscreen' in canvas) {
    const off = canvas.transferControlToOffscreen();
    const worker = new Worker(new URL('./worker.ts', import.meta.url),
                              { type: 'module' });
    worker.postMessage({ type: 'init', canvas: off }, [off]);
    return { kind: 'worker', worker } as const;
  }
  // Fallback: same-thread renderer
  return { kind: 'main', ctx: canvas.getContext('webgpu') } as const;
}
```

This keeps the main thread free for touch + audio scheduling.

### 3.4 AudioWorklet is the only acceptable audio path

The main thread WILL stutter under render load. Schedule audio from a
worklet, never from `setTimeout` or `requestAnimationFrame`.

```ts
// audio_pipeline/impl/scheduler.worklet.ts
class TtsScheduler extends AudioWorkletProcessor {
  // ring buffer for incoming chunks
  private ring = new Float32Array(48000 * 2);  // 2 s @ 24 kHz stereo
  private writeIdx = 0;
  private readIdx = 0;

  constructor() {
    super();
    this.port.onmessage = (e) => this.enqueue(e.data as Float32Array);
  }
  process(_in: Float32Array[][], outputs: Float32Array[][]) {
    const out = outputs[0][0];
    for (let i = 0; i < out.length; i++) {
      out[i] = this.readIdx === this.writeIdx ? 0 : this.ring[this.readIdx++];
      if (this.readIdx >= this.ring.length) this.readIdx = 0;
    }
    return true;
  }
  private enqueue(chunk: Float32Array) {
    for (let i = 0; i < chunk.length; i++) {
      this.ring[this.writeIdx++] = chunk[i];
      if (this.writeIdx >= this.ring.length) this.writeIdx = 0;
    }
  }
}
registerProcessor('tts-scheduler', TtsScheduler);
```

The main thread sends `Float32Array` chunks as they arrive from the TTS
provider; the worklet never blocks the renderer.

### 3.5 Backpressure: drop oldest, never block

For all real-time streams (audio, visemes, emotion updates), the policy
is **drop oldest on overflow**, never block the producer.

```ts
// utils/dropping_queue.ts
export class DroppingQueue<T> {
  private buf: T[] = [];
  constructor(private max: number) {}
  push(v: T) {
    if (this.buf.length >= this.max) this.buf.shift();
    this.buf.push(v);
  }
  popAll(): T[] { const out = this.buf; this.buf = []; return out; }
}
```

Use this for incoming `VRAISpeechFrame` packets when the consumer is
behind. Document the drop in the diagnostic panel.

### 3.6 Bundle splitting

```ts
// shell/lazy.ts
export const lazyMedsim = () => import('../modules/medsim_adapter');
export const lazyEmotion = () => import('../modules/emotion_driver');
export const lazyExport = () => import('../modules/avatar_exporter');
```

Lazy-load anything not needed for first paint. TTS voices and the LLM
model are fetched on first speak, not on app boot. Target first-paint
bundle ≤ 1.2 MB compressed (excluding WASM).

### 3.7 The "first speak warmup" trick

The first TTS call is always slow because the model is cold. Hide it:
warm the model on the first user gesture (when the AudioWorklet is also
primed). The cost is paid against UI exploration, not against the
clinical scenario.

```ts
// app-shell/firstGesture.ts
window.addEventListener('pointerdown', async function once() {
  window.removeEventListener('pointerdown', once);
  primeAudioContextOnce(audioCtx);
  // Warmup — silent
  void tts.warmup();
  void emotion.warmup();
}, { once: true });
```

---

## 4. Stability rails

### 4.1 Strict TypeScript, no `any`

`tsconfig.json`:

```json
{
  "compilerOptions": {
    "strict": true,
    "noUncheckedIndexedAccess": true,
    "noFallthroughCasesInSwitch": true,
    "noImplicitOverride": true,
    "exactOptionalPropertyTypes": true,
    "useUnknownInCatchVariables": true
  }
}
```

A CI step grep-fails any new `any` introduced in `src/`.

### 4.2 Validate at the edges (Zod)

Anything that arrives over a wire (BroadcastChannel, WebSocket,
LLM JSON) is parsed by a Zod schema before it touches a module:

```ts
// medsim_adapter/impl/parse.ts
const frameSchema = z.object({
  v: z.literal(1),
  characterId: z.string(),
  seq: z.number().int(),
  audio: z.instanceof(ArrayBuffer).optional(),
  audioFormat: z.enum(['pcm16-24k','opus','mp3']).optional(),
  visemes: z.array(z.object({
    t: z.number(), id: z.string(), w: z.number().min(0).max(1),
  })).optional(),
  text: z.string().optional(),
  endOfUtterance: z.boolean().optional(),
  emotion: z.object({
    label: z.string(),
    weights: z.record(z.number()),
  }).optional(),
});

export function parseFrame(raw: unknown) {
  return frameSchema.parse(raw);
}
```

If parsing throws, the frame is dropped, the error is logged with a
schema-version tag, and the avatar falls back to `baselineMood`.

### 4.3 Fail-soft, not fail-fast

In a clinical scenario, a crashed avatar is worse than a slightly wrong
one. Every module has a fail-soft path:

| Module fails | Fail-soft behavior |
|---|---|
| `tts_provider` | Show transcript only; emotion + idle still play |
| `audio_pipeline` | No visemes — mouth holds neutral; transcript shown |
| `emotion_driver` | Hold `baselineMood`; idle still plays |
| `mesh_builder` | Show last-known mesh; new photo upload disabled |
| `shader_translucent` | Force `opacityLevel = 0.66`; rebuild material |
| `medsim_adapter` | Surface schema-mismatch toast; continue with last frame |

Every fail-soft fires a `vrai:error` event picked up by the diagnostic
panel and (in prod) a one-line telemetry log.

### 4.4 Lifecycle: boot, run, dispose

```ts
export interface Lifecycle {
  boot(deps: BootDeps): Promise<void>;
  dispose(): void;
}
```

The app shell calls `dispose()` on:
- `visibilitychange` → hidden
- App background (Capacitor lifecycle hook)
- Battery < 5%
- A new scenario / character switch

`dispose()` must release: GPU buffers (Three.js `geometry.dispose()`,
`material.dispose()`), AudioWorklets (`port.close()`, `disconnect()`),
and Web Workers (`worker.terminate()`).

### 4.5 No globals except the diagnostic registry

A single `diag` singleton tracks per-module state for the dev overlay.
No other global mutable state is allowed.

```ts
// perf/diag.ts
export const diag = {
  modules: new Map<string, ModuleStat>(),
  timeline: new RingLog<TimelineEvent>(2048),
};
```

---

## 5. Testing strategy

### 5.1 Three layers

| Layer | Tool | What it asserts |
|---|---|---|
| Type | `tsc --noEmit` | Contracts hold; no `any`; strict flags pass |
| Unit | `vitest` | Pure functions, parsers, ring buffers, math |
| End-to-end | `playwright` + Capacitor preview | UI + audio + render on real-ish devices |

### 5.2 Fixture clip

A locked fixture (`test/fixtures/fixture_2026_05.json`) defines:

- One portrait PNG (synthetic, no PII)
- One text utterance ("Good morning. Tell me about your symptoms.")
- The expected viseme timing (±50 ms tolerance)
- The expected blendshape weights at three timestamps

Every PR that touches the speech path must keep this fixture green.

### 5.3 Soak test

`test/e2e/soak.spec.ts` runs 5 minutes of:
- Slider sweep 0 → 1 → 0 (60 cycles)
- A new utterance every 6 s
- Random emotion prompt every 8 s

Assertions:
- Heap growth ≤ 5%
- Sustained ≥ 55 fps on M2 iPad / SD 8 Gen 3
- No unhandled errors
- AudioWorklet underruns ≤ 1 per minute

### 5.4 Per-platform CI lanes

| Lane | Runner | Trigger |
|---|---|---|
| desktop-chromium | GitHub Actions ubuntu-latest | Every PR |
| desktop-webkit | macOS-14 + webkit | Every PR |
| ios-real | macOS-14 + iPhone XS sim (closest stand-in) | Main + tags |
| android-real | ubuntu + emulator (Pixel Tablet API 34) | Main + tags |

---

## 6. Module READMEs — required sections

Every `modules/<name>/README.md` MUST have these five sections:

```md
# <module_name>

## Purpose
One paragraph. What is this module for? What is it NOT for?

## Public contract
A copy of the interface in `src/types/<module_name>.ts`.

## Dependencies
Which other modules / libraries this one talks to.

## Gotchas
The non-obvious things future-you needs to remember.

## Tests
Where the unit tests live; what the fixtures are.
```

If any of these is missing, the PR is rejected by a lint rule.

---

## 7. Common Claude Code prompts

These prompts are tuned for the project's conventions. Copy / adapt
them when handing tasks to agents.

### 7.1 Build a new module

```
Build the `<module_name>` module per the contract in
src/types/<module_name>.ts. Conform to the layout rules in §1 of
VRAI_Faces_Claude_Code_Guide.md and the lifecycle rules in §4.4.

You may import only from:
  - three (latest)
  - src/types/*
  - src/utils/*
  - <any explicitly-listed peer modules — none unless I say so>

Write the implementation in modules/<module_name>/impl/, the barrel
in modules/<module_name>/index.ts, and at least one vitest unit test
covering the happy path and the most likely failure path.

Add a README.md with the five required sections.

When you finish:
  1. Run `pnpm -F core typecheck` — must be 0 errors.
  2. Run `pnpm -F core test` — must be all green.
  3. Append an ADR entry to Memory_management.MD §7 if your
     implementation required a new constraint not yet documented.
```

### 7.2 Add a perf measurement

```
Add a measurement of <stage> in <module> against the budget in
Memory_management.MD §5. If the stage exceeds budget on either the
M2-iPad lane or the SD-8-Gen-3 lane, append a row to Memory_management.MD
§8 with the measured value and a one-line mitigation. Do NOT change
the budget without an ADR.
```

### 7.3 Fix a fail-soft regression

```
The fail-soft contract in §4.3 of VRAI_Faces_Claude_Code_Guide.md says
<module> must <behavior> when <input fails>. The fixture
test/e2e/soak.spec.ts shows this is not the case as of HEAD. Reproduce,
fix in modules/<module>/impl/, and add a vitest case that fails before
your fix and passes after.
```

### 7.4 Wire a new MedSim character field

```
MedSim is adding the field `<field>` to the character schema. Add it to
the Zod schema in modules/medsim_adapter/impl/parse.ts (optional with
default), thread it through into VraiAvatarBinding in
src/types/medsim_adapter.ts, and update any module that should consume
it. Bump the schema's `v` ONLY if a consumer becomes required.
```

---

## 8. Mistakes to refuse

If a prompt asks for any of the following, the agent must push back
before doing it:

- Adding a new third-party library not listed in the
  Libraries & Licenses tab of `VRAI_Faces_Tools_Resources.xlsx`.
- Reaching across a module boundary (importing
  `modules/X/impl/...` from `modules/Y/...`).
- Removing a fail-soft path to "clean up" the code.
- Calling a cloud service from a module that runs in local mode.
- Storing PHI in `localStorage` or `IndexedDB` without an explicit
  ADR allowing it.
- Adding `any`, `// @ts-ignore`, or `eslint-disable` to a hot file
  without an inline justification comment.

Each of these is either a contract break or a security regression.
The right response is to add an ADR explaining the trade-off, get
sign-off, and then proceed.

---

## 9. Daily working rhythm

A productive day looks like:

1. Open `Memory_management.MD`. Read the last three ADRs and any new
   §8 perf notes.
2. Pull the next task off the backlog (`VRAI_Faces_Tools_Resources.xlsx`
   → Dev Backlog tab, in dependency order).
3. Implement, type-check, unit-test.
4. Run the desktop Playwright lane locally.
5. If touching audio or render: run the M2-iPad lane in CI.
6. Open a PR; cite the ADR(s) you read and any you added.
7. On merge, mark the backlog row complete.

If you're blocked, open an ADR (even one paragraph) describing the
blocker. The next agent picks it up.

---

*End of guide. The contracts in this file are themselves subject to
ADR review — if you need to change a convention, open ADR-XXXX with
the rationale.*
