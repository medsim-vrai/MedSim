# Memory_management.MD — VRAI Faces (MedSim V8)

> Persistent project memory consumed by Claude Code agents while building the
> VRAI Faces animated‑avatar subsystem **inside MedSim V8** (forked from V7
> on 2026‑05‑28 — see ADR‑0017). Treat this file as the single source of
> truth for cross‑agent context. Update it whenever a decision, contract, or
> module boundary changes. Keep entries short, dated, and linkable.
>
> **Where things live in V8:**
> - This file:    `medsim_v8/vrai-faces/Memory_management.MD`
> - Code root:    `medsim_v8/vrai-faces/packages/core/src/`
> - Coding guide: `medsim_v8/vrai-faces/docs/VRAI_Faces_Claude_Code_Guide.md`
> - MedSim host:  the existing FastAPI portal at `medsim_v8/portal/server.py`
>   exposes `GET /qr/face/<character_id>.svg` and a facilitator launcher at
>   `GET /portal/face/launch/<character_id>` (ADR‑0017).

---

## 0. How agents must use this file

1. **Read first.** Every agent loads this file before touching code.
2. **Append, do not rewrite.** Use the dated sections below; never delete history.
3. **One module per PR.** The modular boundaries in §3 are contracts — do not cross them without an ADR entry in §7.
4. **Cite memory entries** in commit messages (`MEM:dec-0007`) and in code comments where a non‑obvious choice was driven by a remembered constraint.
5. **Verify before recommending.** If a memory cites a file path, flag, or function, confirm it still exists before acting on it.

---

## 1. Project mission (frozen)

VRAI Faces provides a translucent, animatable 3D facial avatar that pairs with
the MedSim V7 AI‑driven character system. Avatars must:

- Be generated from a single front‑view 2D photograph.
- Render in Chrome with no install (WebGPU primary, WebGL2 fallback).
- Expose a single user‑facing **translucency slider** moving the look from
  opaque white → near‑invisible glass with only minimal rim/specular cues.
- Export a portable framework (glTF 2.0 with ARKit‑52 morph targets, optional
  VRM 1.0 wrapper) that bakes in the chosen translucency level.
- Animate from audio + LLM prompts (visemes for speech, blendshape weights for
  emotion, deterministic idle loops for life).
- Run **local‑first** to keep MedSim scenario PHI on‑device; cloud TTS allowed
  only behind a per‑tenant opt‑in and a signed BAA.

---

## 2. Stack of record (May 2026)

| Layer | Choice | Why locked in |
|---|---|---|
| Mesh capture | MediaPipe Face Landmarker (`@mediapipe/tasks-vision`) | Free, in‑browser, 478 verts + ARKit‑52 blendshapes |
| Renderer | Three.js r170+ (WebGPU renderer, WebGL2 fallback) | Mature, WebGPU now Baseline |
| Material | `MeshPhysicalMaterial` + Fresnel rim shader chunk | `transmission`, `thickness`, `ior`, low specular → ghost look |
| Export | glTF 2.0 with ARKit‑named morph targets; VRM 1.0 optional | De‑facto interchange for blendshape animation |
| TTS (primary) | Azure Speech HD V2 + Voice Live API | HIPAA‑BAA, **native 22‑viseme + 55‑blendshape stream**, near‑ElevenLabs quality, 140+ langs |
| TTS (premium "hero" persona) | ElevenLabs v3 (Enterprise + Zero Retention) | Best‑in‑class emotional voice; BAA via Enterprise; visemes derived via HeadAudio |
| TTS (low‑latency conversational) | Cartesia Sonic‑3 | 40–90 ms TTFA; phoneme timestamps; for back‑and‑forth interview scenarios |
| TTS (offline / cost fallback) | HeadTTS (Kokoro WebGPU), Piper WASM | Free, runs on device; used when network is down, WebGPU rejects, or per‑tenant cap is hit |
| Viseme bridge | HeadAudio AudioWorklet | Works with any audio source if TTS lacks visemes |
| Animation engine | TalkingHead.js | Purpose‑built Three.js + Mood + viseme runtime |
| Emotion driver | LLM → JSON blendshape weights (transformers.js local; Claude cloud allowed) | Deterministic, auditable, AU‑grounded |
| Build / runtime | Vite + TypeScript, ES modules, no bundled framework | Keep modules swappable |

Anything outside this list requires an ADR (see §7).

---

## 3. Module boundaries (contracts)

Each module ships as a separate folder under `src/modules/` with a typed
`index.ts` barrel, a `README.md`, and a unit test. Modules talk only through
the published types — never reach into another module's internals.

```
src/modules/
├── face_ingest/          # accepts image File|Blob → returns normalized PNG + face bbox
├── mesh_builder/         # PNG → Three.BufferGeometry + ARKit‑52 baseline weights
├── shader_translucent/   # wraps MeshPhysicalMaterial; exposes opacity(0..1)
├── avatar_exporter/      # mesh + material + morphs → .glb / .vrm
├── animation_runtime/    # blendshape buffer + 60Hz tick + mixer
├── audio_pipeline/       # mic / file / TTS stream → AudioBuffer + viseme stream
├── tts_provider/         # pluggable: HeadTTS | Piper | Azure | Google
├── emotion_driver/       # prompt → {blendshape: weight} JSON
├── idle_motion/          # blink + saccade + sway loops, deterministic seed
├── medsim_adapter/       # scenario character_id → avatar config + persona
├── diagnostic_panel/     # devtools overlay (off in production)
└── memory_state/         # reads/writes this file; surfaces decisions to agents
```

**Public types** live in `src/types/` (a separate folder) so modules import
types without importing each other.

---

## 4. The translucency contract

The single slider drives **one** runtime parameter, `opacityLevel ∈ [0, 1]`.
`shader_translucent` maps it as:

| `opacityLevel` | `material.transmission` | `material.opacity` | Fresnel rim | Specular |
|---|---|---|---|---|
| 1.00 (opaque) | 0.00 | 1.00 | off | normal |
| 0.66 | 0.35 | 1.00 | 0.3 | reduced |
| 0.33 | 0.75 | 0.85 | 0.6 | minimal |
| 0.00 (ghost) | 1.00 | 0.55 | 1.0 | near‑zero |

`avatar_exporter` bakes the current `opacityLevel` into the exported glTF as a
`KHR_materials_transmission` extension value and a `extras.vraiOpacity` field
so downstream tools can reconstruct the slider position.

---

## 5. Latency budget (per utterance, end‑to‑end)

| Stage | Target (local) | Target (cloud) |
|---|---|---|
| Prompt → first TTS audio chunk | ≤ 300 ms | ≤ 180 ms |
| Audio chunk → first viseme weight | ≤ 30 ms | ≤ 30 ms |
| Viseme weight → rendered frame | ≤ 16 ms (60 fps) | ≤ 16 ms |
| Emotion update | 10 Hz | 10 Hz |
| Idle loop tick | 60 Hz | 60 Hz |

Any module breaching its budget must add a row to §8 with the measurement
and a mitigation.

---

## 6. MedSim V7 integration contract

The `medsim_adapter` module is the only place that knows about MedSim. It
consumes a MedSim **scenario character** object (path on user's machine:
`Documents/Claude/Projects/Scenario structure to support character engagement/medsim_v8/`,
specifically the `scenarios/`, `characters/` and `schemas/` folders) and yields
a `VraiAvatarBinding`, plus it owns the audio interop channel.

### 6.1 Character binding

```ts
interface VraiAvatarBinding {
  characterId: string;            // MedSim character primary key
  sourcePhoto: Blob;              // front‑view portrait
  voiceProfile: TtsVoiceId;       // mapped from MedSim persona
  baselineMood: BlendshapeWeights;// neutral expression for this character
  opacityLevel: number;           // 0..1; persisted per character
  exportPath: string;             // last exported .glb location
}
```

### 6.2 Speech interop — `VRAISpeechFrame`

MedSim V7's speech output flows into VRAI Faces as a stream of frames.
The wire format is identical whether the transport is BroadcastChannel
(same‑origin) or WebSocket (cross‑app on a tablet):

```ts
interface VRAISpeechFrame {
  v: 1;                           // schema version (bump on break)
  characterId: string;            // which avatar speaks
  seq: number;                    // monotonic per utterance
  audio?: ArrayBuffer;            // PCM16 mono 24 kHz chunk (optional)
  audioFormat?: 'pcm16-24k' | 'opus' | 'mp3';
  visemes?: Array<{
    t: number;                    // ms from utterance start
    id: string;                   // ARKit blendshape name
    w: number;                    // weight 0..1
  }>;
  text?: string;                  // optional transcript for accessibility
  endOfUtterance?: boolean;       // true on final frame
  emotion?: {                     // optional per‑utterance mood
    label: string;
    weights: Record<string, number>;
  };
}
```

If `visemes` is absent, `audio_pipeline` derives them from the audio
chunk via HeadAudio (see ADR‑0008 for the iOS Worklet prime).

Agents must NOT mutate MedSim scenario files; they are read‑only inputs.

---

## 7. Architectural Decision Records (append‑only)

> Format: `ADR‑NNNN | YYYY‑MM‑DD | Decision | Driver | Consequence`

- **ADR‑0001 | 2026‑05‑28 | Local‑first deployment** | Clinical PHI must not leave device; offline reliability for hospital networks | Adds WebGPU dependency; older devices need WASM fallback path.
- **ADR‑0002 | 2026‑05‑28 | MediaPipe Face Landmarker for mesh** | Free, browser‑native, ARKit‑52 out of box | Generic topology (no per‑identity sculpt). If photoreal sculpt later required, add server‑side TEASER pass behind a feature flag.
- **ADR‑0003 | 2026‑05‑28 | glTF 2.0 with ARKit morph naming as export** | Universal interchange; VRM 1.0 builds on it | Naming discipline enforced via lint rule in `avatar_exporter`.
- **ADR‑0004 | 2026‑05‑28 | TalkingHead.js as animation runtime** | Purpose‑built, MIT, mature Mood system | Tie to one upstream maintainer — mitigate by vendoring a known‑good commit.
- **ADR‑0005 | 2026‑05‑28 | LLM emits JSON blendshape weights, not free text** | Deterministic, auditable, lint‑checkable | Slightly more prompt engineering; pays for itself in QA.
- **ADR‑0006 | 2026‑05‑28 | Tablet packaging = Capacitor (iPadOS + Android), not raw PWA** | iPadOS 26 PWA has a confirmed background-audio regression that breaks clinical use; Capacitor's `UIBackgroundModes` audio is the supported path | Adds a thin native shell per platform; web codebase remains shared.
- **ADR‑0007 | 2026‑05‑28 | MedSim audio interop = `VRAISpeechFrame` over BroadcastChannel (same-origin) and WebSocket (cross-app)** | One contract serves both modes; matches MedSim's existing speech output cleanly | `medsim_adapter` owns the channel; the schema is versioned in `src/types/`.
- **ADR‑0008 | 2026‑05‑28 | AudioWorklet "silent prime" required on iOS** | iOS Safari has a long-standing bug where AudioWorklets emit silence until another audio source has played. Prime with a one-sample silent `<audio>` on the first user gesture | Mandatory in `audio_pipeline`'s init path; covered by a Playwright iOS test.
- **ADR‑0009 | 2026‑05‑28 | WebGPU is feature-detected with WebGL2 fallback at boot** | Adreno tablets are fine; Tensor G3 / iOS edge cases are not. The renderer chooses the backend once and never switches | Two render paths shipped; CI runs both lanes.
- **ADR‑0010 | 2026‑05‑28 | Touch UI: ≥56 px primary hit targets; slider always paired with stepper + numeric input; long-press = fine mode** | Tablet thumb precision is unreliable on bare sliders | Enforced as a lint rule on the control library.
- **ADR‑0011 | 2026‑05‑28 | REVERSAL of ADR‑0001's TTS preference: external high‑quality voice is now PRIMARY; local is FALLBACK** | The clinical realism gap between local Kokoro/Piper and premium external voices is too wide for trainee believability; latency from premium providers is competitive (Cartesia 40–90 ms TTFA, Azure 200–400 ms) and is dominated by network jitter not provider compute | Adds a hard requirement for the failover chain in ADR‑0013 and the PHI guardrail in ADR‑0014.
- **ADR‑0012 | 2026‑05‑28 | TTS provider tiering — Azure HD V2 default; ElevenLabs v3 for hero personas; Cartesia for conversational; local fallback always shipped** | One provider doesn't optimize for all three of {native visemes, emotional quality, ultra‑low latency}; mixing exploits each provider's strength | `tts_provider` carries a `tier` field on each request; the router enforces tier→provider mapping and never silently downgrades for non‑cost reasons.
- **ADR‑0013 | 2026‑05‑28 | Failover chain order: primary → premium → conversational → local; chain hops are SILENT to UI but ALWAYS surfaced in diagnostic_panel and telemetry** | A patient persona that suddenly speaks in a different voice mid‑scenario destroys trainee immersion; we'd rather drop one utterance than swap voices | If two consecutive cloud failures occur, voice is locked to local for the remainder of the scenario; facilitator UI shows a clear "fallback voice" banner.
- **ADR‑0014 | 2026‑05‑28 | PHI guardrail: only BAA‑covered providers (Azure, ElevenLabs Enterprise+ZRM, Deepgram, AWS Polly, Resemble) ever receive trainee free‑text; scripted scenario content may use any tier** | Most premium providers don't offer BAA on default tiers; trainee‑typed text is the channel most likely to contain PHI by accident | `tts_provider` flags each request as `scripted | trainee_input | unknown`; trainee_input and unknown route ONLY to the BAA pool; classifier is fail‑closed.
- **ADR‑0015 | 2026‑05‑28 | Native visemes preferred over derived visemes when both are available; derived viseme bridge (HeadAudio) is mandatory in the path of any non‑native provider** | Native (Azure, AWS Polly speech marks) materially outperforms derived for sustained phonemes and silence handling; derived is "good enough" not "great" | `audio_pipeline` detects whether the active provider emits visemes; if not, the HeadAudio worklet is added to the chain automatically.
- **ADR‑0016 | 2026‑05‑28 | Cost guardrails: per‑tenant monthly character cap; cap‑80% triggers a switch to local; cap‑100% hard‑stops all cloud calls until next billing cycle** | Premium voices can rack up unpredictable cost on long scenarios | `tts_provider` consults a usage meter before each call; meter persists in `memory_state`.
- **ADR‑0017 | 2026‑05‑28 | MedSim V8 = MedSim V7 fork + VRAI Faces tablet surface; portal exposes `/qr/face/<id>.svg` and `/portal/face/launch/<id>`** | V7's existing portal already runs FastAPI + segno QR generation; reusing it as the launch host avoids a second service on the LAN. The QR encodes a LAN URL (`VRAI_FACES_BASE_URL` env var) that the tablet camera opens directly | The vrai-faces dev server (`vite`) is the URL the QR points at in dev; in prod the same path is served from `dist/`. `medsim_adapter` is the only place that touches MedSim runtime state.
- **ADR‑0018 | 2026‑05‑28 | Pause/Resume — `memory_state` aggregates per‑module `SnapshotHooks` and writes one `SessionState` blob to IndexedDB per (scenarioId, characterId) on tab‑hidden, low battery, or shell signal** | Tablets sleep often during scenarios; trainees expect to pick up exactly where they left off. A single aggregate write is faster and atomic vs N partial writes | Every module that holds runtime state implements `Resumable<T>` with structured‑clone‑safe `T`. PHI free‑text is NEVER persisted — only structured runtime state. `resumeAll()` is called from `main.ts` at boot.
- **ADR‑0019 | 2026‑05‑29 | `emotion_driver` runs transformers.js ON‑DEVICE — hybrid: a small quantized GoEmotions‑class model + the existing lexicon as fallback AND as the override for clinical affects (pain/drowsy); cloud Claude stays per‑scenario opt‑in** | The lexicon stand‑in can't handle paraphrase/negation/intensity, but local‑first (ADR‑0001) forbids a cloud default and off‑the‑shelf emotion models have no pain/drowsy labels | Adds a pinned transformers.js dep + a model entry in the tools sheet; the model loads in `warmup()`, never at boot; lexicon retained as the zero‑model fallback; output stays JSON blendshape weights (ADR‑0005); any cloud path remains gated by the ADR‑0014 fail‑closed PHI classifier. Implemented in Phase 3 (see `docs/ROADMAP.md`).
- **ADR‑0020 | 2026‑05‑29 | Local TTS fallback = HeadTTS/Kokoro (WebGPU) with a Piper‑WASM floor, chained Kokoro→Piper** | ADR‑0011 makes premium cloud voice primary and local the fallback; the fallback must STILL work when the network, WebGPU, or the cost cap fails — Kokoro gives near‑premium quality on WebGPU, Piper‑WASM guarantees a CPU floor when WebGPU is rejected (ADR‑0009) | `tts_provider` keeps its TIER_CHAIN tail `…→ headtts‑kokoro → piper‑wasm`; both engines are pinned in `VRAI_Faces_Tools_Resources.xlsx`; models load lazily, never at boot; both are on‑device so they sit inside the ADR‑0014 BAA pool (PHI‑safe). Wired in Phase 2 (see `docs/ROADMAP.md`).
- **ADR‑0021 | 2026‑05‑29 | AMENDS ADR‑0020: drop Piper‑WASM — Kokoro's onnxruntime‑web WASM/CPU backend IS the local floor** | `piper-tts-web` pins conflicting `onnxruntime-web@1.20` + `@huggingface/transformers@3.3` (vs Kokoro's 1.26 / 4.2 → duplicate clashing runtimes) and Piper voices are ~63 MB EACH; meanwhile Kokoro already falls back to `device:'wasm'` (CPU) when WebGPU is absent, so it covers the floor Piper was meant to provide | `tts_provider` TIER_CHAIN drops `piper‑wasm` (chains end at `headtts‑kokoro`); the `piper-wasm` provider literal is retained but unused, pending a possible lean revisit (run Piper on the existing onnxruntime-web 1.26 + a phonemizer) captured as a research brief if wanted.
- **ADR‑0022 | 2026‑05‑29 | Portal attaches character portraits from local consented files (`portal/data/face_portraits/<id>.{png,jpg,jpeg,webp}`); a neutral non‑photographic placeholder is served when none exists** | The MedSim card (`schemas/character.json`) carries no portrait, but the avatar needs a source image to build face geometry; local‑first + the facial‑image rule forbid scraping/gathering faces | `medsim_adapter`'s binding gets `sourcePhoto` inlined as a `data:` URI by `GET /api/face/<id>/binding`; the portal only READS local files (facilitator‑supplied, consented); a missing portrait → placeholder + `mesh_builder` canonical‑topology fallback. Implemented in Phase 4.3.
- **ADR‑0023 | 2026‑05‑29 | The portal speak path pushes `VRAISpeechFrame`s carrying TEXT + emotion only — never audio bytes; the tablet synthesizes audio on‑device** | Local‑first (ADR‑0001) + the PHI guardrail (ADR‑0014) and the on‑device Kokoro + lexicon emotion already built in Phases 2–3 mean the wire should carry the scripted line, not rendered audio | `POST /api/face/<id>/speak` (and in‑process `push_speech`) emit `{v:1, characterId, seq, text, emotion?, endOfUtterance}` over the speech WebSocket; `seq` is seeded from the wall clock so a portal restart never replays a value the adapter has already de‑duped. Implemented in Phase 4.3.
- **ADR‑0024 | 2026‑05‑29 | Character devices — a per‑character QR opens the Chrome interface (avatar OR audio‑only); push‑to‑talk is trainee→character; the name‑trigger AND PTT transcription are ON‑DEVICE only (no ambient or raw trainee audio leaves the tablet)** | An always‑listening cloud wake‑word + cloud STT of trainee speech (Web Speech API → Google) would breach local‑first (ADR‑0001) and the PHI guardrail (ADR‑0014 — trainee_input is PHI); the operator's existing Web‑Speech PTT is operator‑only, not trainee PHI, so it isn't a precedent for the bedside device | The device app gains a hold‑to‑talk control + an on‑device keyword‑spotter for the character's name; transcribed text routes through a portal trainee‑input endpoint to the character AI → a `VRAISpeechFrame` back so the avatar replies (reusing the Phase 4.3 speak path). The per‑character device QR already exists (`/qr/face/<id>.svg`). The on‑device STT + wake‑word model is heavy/maturing in‑browser → **gated, captured in RB‑002**; not built inline until researched (ROADMAP §4).
- **ADR‑0025 | 2026‑05‑30 | DEMO STOPGAP for the character device: the app may transcribe trainee speech with the browser's cloud Web Speech API for hold‑to‑talk AND the name‑trigger — but OFF by default, behind an explicit "cloud voice — not for PHI" toggle, for non‑PHI live testing ONLY** | We need an end‑to‑end voice→avatar loop NOW to surface integration issues during live testing; the PHI‑safe on‑device path (ADR‑0024) is gated on RB‑002 and not yet ready, so a clearly‑fenced cloud stopgap unblocks testing without pretending to be the shippable answer | New route `POST /api/face/<id>/listen` (no auth — device‑origin trust like binding/speak) takes the transcript → runs the character AI turn (borrowing the active control‑session's Anthropic key, reusing `runtime.take_turn`) → `push_speech` so the avatar replies; with no running scenario it echoes the heard text so the pipeline still exercises. Cloud STT (audio leaves the device) is permitted ONLY behind the explicit opt‑in toggle and NEVER in a PHI session; this ADR is **superseded by RB‑002's on‑device engine** (swap `device_stt` + `name_trigger` behind the same UI). No new third‑party lib (Web Speech is a browser built‑in) → no tools‑sheet line. Client `shell/device_voice.ts`; off by default.
- **ADR‑0026 | 2026‑05‑30 | On‑device trainee voice (Phase 6 — executes RB‑002, adversarially‑verified): PTT STT = the already‑bundled `transformers.js` running `whisper‑tiny.en` (ONNX, MIT) on WebGPU with a WASM fallback — lazy + service‑worker‑cached like Kokoro; `vosk‑browser` (Apache‑2.0, no‑WebGPU) is the CPU floor pending a `.wasm` license audit. The name wake‑word stays DEFERRED: no clean open in‑browser keyword‑spotter handles arbitrary per‑scenario names, so when built it is fuzzy/phonetic matching over a rolling on‑device STT buffer (no dedicated model). Cloud on‑device Web Speech (Option C) and Picovoice Porcupine are REJECTED.** | RB‑002: WebGPU now ships by default in Safari 26 (fall 2025), so in‑browser Whisper is newly viable on iPad; Chrome on‑device Web Speech is a NO‑GO on iOS Safari (routes to Apple cloud) + Android; Porcupine needs an AccessKey call‑home + per‑device commercial license (>3 users/mo) + is localStorage‑fragile — all conflict with local‑first (ADR‑0001) and the PHI fail‑closed rule (ADR‑0014: mic audio must never leave the device). | **Supersedes ADR‑0025** — the cloud‑STT PTT stopgap retires once `device_stt` lands. Adds shell modules `device_stt` (PTT audio→text) and later `name_trigger`, swapped behind the existing `device_voice` UI; `whisper‑tiny.en` (MIT) joins the tools sheet as a lazy asset (whisper‑base ~200 MB exceeds the ~80 MB budget → tiny only; quantized‑WebGPU decoder gibberish is a known bug to test for). **SHIP‑GATED on an on‑device pilot** measuring PTT latency / clinical WER / thermal on real iPad‑class Safari 26 (every RB‑002 number is laptop/desktop; clinical WER unmeasured). Capacitor‑native `SFSpeechRecognizer(requiresOnDeviceRecognition)` is the documented iOS fallback. PTT‑first, name‑trigger‑next.

---

## 8. Performance / regression notes (append‑only)

> Format: `YYYY‑MM‑DD | module | metric | observed | budget | mitigation`

*(empty — populate during development)*

---

## 9. Open questions for the human

**Phase 0 decisions — resolved 2026‑05‑29** (see `docs/ROADMAP.md`; ADRs in §7):

- [ ] **MedSim V8 character schema path** inside `medsim_v8/schemas/` so
  `medsim_adapter` can wire its Zod schema to real types (scaffold validates
  `VRAISpeechFrame` only). → confirm during **Phase 4**.
- [x] **Cloud TTS timing** — **local‑only launch; cloud tiers (and cloud‑emotion)
  behind a flag, enabled in v1.1.** Local‑first by default; no BAA/key blocker at launch.
- [x] **Default "ghost" base color** — **per‑scenario** (carried on the character
  binding), default **clinical white**. Adds an optional `ghostColor` field through
  `medsim_adapter → shader_translucent` (Phase 4).
- [x] **Local voice bundle** — **balanced ~6–8 Kokoro/HeadTTS voices** (gender/age
  spread). Exact voice IDs chosen in Phase 2.
- [x] **Portal launchable‑character listing** — **derive from the MedSim
  scenario/character registry** (single source of truth; validates the QR id). Phase 4.
- [x] **Pause/resume durability** — **device‑restart durable**: survive tablet
  reboots and Capacitor app updates (persistent storage + stable origin + a
  SessionState schema‑version migration). Phase 5.

---

## 10. Agent etiquette

- Prefer reading a module's `README.md` before reading its source.
- When you discover an undocumented constraint, add it here before continuing.
- If a module's surface needs to grow, add a typed method to its `index.ts`
  AND a row to §3 in the same PR — never one without the other.
- When in doubt, write the ADR first.

