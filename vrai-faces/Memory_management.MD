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
- **ADR‑0027 | 2026‑05‑30 | Device security posture (Phase 6 A6) — three decisions: (1) HTTPS / secure context is REQUIRED on the device surface — it is what unlocks WebGPU avatar rendering, the on‑device mic (`getUserMedia` → `device_stt`), and `crypto.subtle`; dev uses the local‑CA cert (`scripts/make-dev-cert.sh`) + cert‑gated TLS in vite + uvicorn, prod uses a real / MDM‑distributed cert; `face_ingest`'s non‑crypto hash fallback stays ONLY as a graceful degrade, never the intended path. (2) The `/api/face/*` device routes (binding / speak / listen / skins / WS) keep the LAN‑origin trust the portal already uses for join codes — no operator auth, no PHI‑writing or credential surface — but the AI‑spend route `/api/face/<id>/listen` SHOULD gain a per‑session device token (minted at QR/launch, carried in the launch URL, validated + expired with the session) so a stray LAN client can't drive an avatar or spend Anthropic budget. (3) Cached consented skins (the Phase 5.7 device skin pack) are PHI‑at‑rest: cache only the actively‑paired character's skins, CLEAR‑ON‑UNPAIR / session‑end + a manual "forget faces" control, NEVER cache secrets/tokens, rely on browser eviction; encryption‑at‑rest is a follow‑up if a compliance review demands it.** | On‑device voice (ADR‑0026) + device caching (Phase 5.7) make the tablet a longer‑lived data‑at‑rest + compute surface, so the security the operator wants "added back" must be written down: secure‑context is now a hard dependency (not just a tablet‑mic nicety), the no‑auth device routes are an EXPLICIT (not accidental) LAN‑trust decision, and caching consented faces broadens where PHI lives. Re‑asserts ADR‑0001 (local‑first) + ADR‑0014 (PHI fail‑closed; mic audio never leaves the device). | HTTPS stays gated on cert presence (default dev HTTP unchanged until certs exist — no regression). The per‑session device token is a RECORDED hardening follow‑up, not built in this ADR. The PHI‑at‑rest rules UNBLOCK building the Phase 5.7 skin pack (clear‑on‑unpair + manual forget are now specified). No new dependency.
- **ADR‑0028 | 2026‑05‑30 | Durable device serving (Phase 6 A7) — for DEPLOYED tablets the portal serves the BUILT avatar app itself from ONE origin (`VRAI_FACES_SERVE=portal`), retiring the separate vite `:5173` server, the cross‑origin `api`/WS, and the second TLS cert. Dev/HMR (the Develop button) is unchanged.** | Every recurring tablet failure this session — `binding fetch failed`, "connection is not secure", the unskinned demo‑fallback — traced to TWO servers each holding a SEPARATE cert (vite `:5173` for the app + uvicorn `:8765` for the api) with a cross‑origin bind + speech WS hopping between them; ANY drift (a changed LAN IP, a stale vite holding an old cert, mismatched lifetimes) breaks the tablet. Patching the certs fixed instances, not the class. Collapsing the app + api + WS onto ONE origin with ONE cert removes the entire failure class ("build it out so it doesn't repeat"). | `run_portal.py` builds `dist/` once if missing, then `portal/server.py` (gated on `_portal_serves_app()` = env + dist present) serves `/face/<id>` → `dist/index.html` (SPA), mounts `/assets` (hashed bundles + bundled Kokoro/MediaPipe/face models), and serves the root PWA files (`app-sw.js`, `manifest.webmanifest`, icons). `_vrai_faces_url` then points the QR at the PORTAL origin with `api` = the same origin, so binding/listen/speak/WS are all same‑origin (one cert, no cross‑origin); `_ensure_vrai_app_for_qr` skips the vite autostart in this mode. Default (no env) is unchanged dev: vite `:5173` + cross‑origin `api`. No new dependency. Rides under ADR‑0027 (HTTPS/secure context still required; the per‑session token still applies) and unblocks the ADR‑0026 on‑device pilot on a stable surface.
- **ADR‑0029 | 2026‑05‑31 | The recurring "not secure" (Mac AND tablet) is a CA‑TRUST problem, NOT a cert problem — resolved by trusting the existing CA correctly + churn‑proofing it, never by regenerating certs. Plain‑HTTP "treat‑as‑secure‑origin" is REJECTED for real use (PHI).** | `cert‑doctor` proved the served TLS is fully correct (cert/key moduli match, leaf chains to the CA, within validity, SAN covers the LAN IP) yet macOS `security verify‑cert` returns `CSSMERR_TP_NOT_TRUSTED`: the CA sits in the keychain UNtrusted, and it had been re‑minted (which silently invalidates trust on every device that trusted the old one). Past "fixes" regenerated certs → MORE re‑trust churn. The fix is trust + stop the churn. | Added `scripts/trust‑ca‑mac.sh` (sets the CA as a trusted root in the System keychain — the user runs it once with `sudo`, since trusting a root is a system‑security change I must not make for them), `scripts/cert‑doctor.sh` (read‑only diagnosis incl. the decisive trust check, the tablet install steps, and the CA fingerprint; SAN is parsed from `-text` because macOS LibreSSL lacks `-ext`), and a re‑mint GUARD in `make‑dev‑cert.sh` (`FORCE=1` now REFUSES unless `REMINT_CA=yes`, so the CA is mint‑once / trust‑once and survives DHCP IP changes via leaf‑only reissue). Plain‑HTTP + Chrome `#unsafely‑treat‑insecure‑origin‑as‑secure` was REJECTED for anything but non‑PHI testing — it would put the trainee transcript (PHI, ADR‑0014) unencrypted on the LAN. Reasserts ADR‑0027 (HTTPS/secure context is required on the device surface).
- **ADR‑0030 | 2026‑05‑31 | Fleet networking = OWN the network + address the portal by NAME + push trust/config via MDM. The recurring tablet‑connectivity failures are an uncontrolled‑network problem, fixed at the infrastructure layer, not in app code.** | Live debugging proved the failure CLASS: the system needs every device on one flat, mutually‑reachable, secure LAN, and uncontrolled networks break that — client/AP isolation, range‑extender/double‑NAT "same‑subnet‑different‑LAN" splits (the actual outage: tablet on `192.168.1.x` via an extender, gateway `.1`, but never reaching the Mac at `.185`), guest isolation, band‑steering, captive portals, and DHCP IP churn that also breaks the cert SAN + baked‑in QRs. At fleet scale these are near‑certain. Scope: dev/internal pilot = one site, 15–60 devices, our own AP/router, MDM‑managed tablets; deployment/sales = 60+/permanent/multi‑site. | Documented in `docs/NETWORK-STRATEGY.md`. Decisions: (1) deploy our OWN controller‑managed Wi‑Fi (UniFi‑class; never consumer mesh/extenders), one SSID, **client isolation OFF**, on a deliberately non‑`192.168.x` subnet (`10.50.10.0/24`). (2) The portal is `portal.medsim.lan` (gateway local DNS + DHCP reservation); the cert, QRs, and `api` origin all use the NAME, so DHCP IP changes never break TLS again (structural fix to the churn). (3) **MDM pushes the Root CA (managed trust), the Wi‑Fi profile, and the app web‑clip/kiosk** — eliminating every manual per‑device step (CA trust, join, install) that caused this session's pain; Android managed trust avoids the user‑CA caveat. (4) Single‑origin portal (ADR‑0028), wired + autostart + UPS. (5) Network‑layer PHI containment (ADR‑0001/0014): device VLAN reaches the portal only, no internet; portal egress = Anthropic (BAA) only; mic/STT on‑device (ADR‑0026). **→ Option 3 transition (noted in full):** `step‑ca` (ACME) or public‑cert + split‑horizon DNS (zero CA install — best for sales); device/server/mgmt VLAN segmentation; WPA‑Enterprise + per‑device certs; portal on 443 behind a reverse proxy; dedicated/per‑site host; pre‑cache + local model bundling for first‑load at scale; a reproducible "site kit" (IaC). First software step: `MEDSIM_PUBLIC_HOST` so the portal/cert/QR target the hostname, not the auto‑detected IP.
- **ADR‑0031 | 2026‑06‑01 | Portal‑side avatar voice — when an operator‑assigned ElevenLabs voice exists, the PORTAL synthesizes the character's reply and ships the audio to the avatar over the speech WS; the tablet plays it instead of synthesizing locally. On‑device Kokoro remains the path for WebGPU‑capable hardware. This REVISES ADR‑0023's "text‑only wire / on‑device synth" for the avatar's OUTPUT voice only.** | Device bring‑up proved the no‑WebGPU tablet cannot run ANY on‑device ONNX model — Kokoro TTS fails with the identical wasm "no available backend" wall as whisper STT — so ADR‑0023's on‑device synthesis has no path there, and the browser‑`speechSynthesis` stopgap uses the wrong (OS‑default) voice with no real lip‑sync. The portal already owns an ElevenLabs TTS (`voices.synthesize_stream`, used by the operator stations) and the per‑persona voice the operator assigned (`sess.voice_assignments`); routing the avatar through it yields the correct voice, works on ANY device (the tablet only decodes audio), and drives energy‑derived `jawOpen` lip‑sync from real audio. PHI (ADR‑0014): the reply is the character's scripted, AI‑generated words — never trainee free‑text — so server‑side synthesis moves no trainee PHI off‑portal; this is the avatar OUTPUT path only (mic/STT stays on‑device, ADR‑0026), and premium‑cloud‑primary was already ADR‑0011's intent. | `vrai_faces._synthesize_voice(sess, cid, reply)` resolves `voice_assignments[cid]` + the session/process ElevenLabs key, collects the mp3 stream, base64‑encodes it, and returns `(b64, "mp3")` — `(None, None)` (→ text‑only frame → device built‑in voice) when no voice/key is set or synthesis fails (never fails the turn). `speech_frame`/`push_speech` gained `audio_b64`/`audio_format`, emitting `audioB64` + `audioFormat` in the VRAISpeechFrame; `/api/face/{id}/listen` calls it before `push_speech`. Client `medsim_adapter/impl/parse.ts` adds `audioB64` to the wire schema and hydrates it into the `audio` ArrayBuffer the `audio_pipeline` already plays (mp3 → `decodeAudioData`); audio is primed by `firstGesture`. No new dependency (ElevenLabs already in use). SW → `vrai‑shell‑v9`.
- **ADR‑0032 | 2026‑06‑01 | Fleet hardware = WebGPU‑capable tablets; on‑device PTT STT = `whisper‑tiny.en` (transformers.js, WebGPU) confirming ADR‑0026. Validate an iPad and a Snapdragon/Adreno Android head‑to‑head on the real‑device pilot, then standardize on the winner; retire the non‑PHI cloud STT on a pass. Disqualify Samsung Exynos/Xclipse + pre‑Vulkan/Android<12.** | RB‑002/ADR‑0026 already chose the engine but assumed a WASM CPU fallback would cover non‑WebGPU devices; this session DISPROVED that — the test Samsung tablet's ONNX‑runtime WASM backend won't register for whisper OR Kokoro, so the dependable on‑device path is **WebGPU, not WASM‑fallback**. WebGPU on Android is a per‑GPU lottery (Chrome 121+/Android 12+: **Adreno/Mali yes, Samsung Xclipse/Exynos "WIP", ~23% of devices lack Vulkan 1.1**), while **iPad is uniform — every A12+ iPad gets WebGPU on iPadOS 26 / Safari 26** with best‑in‑class MDM. A WebGPU device runs the WHOLE on‑device stack (STT + Kokoro TTS + lip‑sync), closing the last PHI gap (trainee audio stays local — ADR‑0001/0014) in one hardware decision; the portal‑ElevenLabs voice (ADR‑0031) becomes an optimization, not a crutch. A BAA‑covered cloud STT is REJECTED (satisfies ADR‑0014 but breaks ADR‑0001 local‑first). | Decision memo: `docs/DECISION‑2026‑06‑01‑hardware‑stt.md`. Validation units (the only spend approved now): **1× iPad 11th‑gen (A16)** + **1× Galaxy Tab S9 (Snapdragon 8 Gen 2 / Adreno 740, Knox MDM)** → run `docs/PILOT‑2026‑05‑30‑on‑device.md` (PTT release→text <1.5 s, clinical WER <12%, model ≤80 MB / cold ≤5 s, no 20‑min thermal throttle, backend=webgpu). On a pass: bundle whisper‑tiny via `setup:assets`, standardize the fleet on the winner, demote cloud STT to a labelled non‑PHI testing toggle (or remove). Fallbacks if WebGPU underperforms on the chosen device: vosk‑browser (CPU, audit GPL `.wasm`) or Capacitor‑native (iOS `SFSpeechRecognizer requiresOnDeviceRecognition`). Option‑3 cert = public‑cert + split‑horizon DNS (decide at that boundary). Unparks task #50 against the purchased unit; the final platform pick is ratified after the pilot.
- **ADR‑0033 | 2026‑06‑01 | Cross‑platform is first‑class: the HOST runs on macOS + Windows (+ Linux) and the DEVICE runs on iPad + Android. Build portable solutions, not macOS/Android‑only ones. Initial test combo = Mac host + iPad device, but every solution must support both sides.** | User directive ("develop solutions that support both apple and android devices… support Windows as well"). The app is a web/PWA and the portal is Python/FastAPI, so the core is already portable — `run_portal.py` already branches `platform.system()` for browser launch, and the client already uses `SpeechRecognition ?? webkitSpeechRecognition`, `AudioContext ?? webkitAudioContext`, a Safari‑vs‑Chrome ORT‑build switch, `firstGesture` iOS audio prime, and iOS `apple‑mobile‑web‑app‑*` PWA tags. The ONLY macOS‑bound pieces were the bash cert scripts (`make‑dev‑cert.sh`, `cert‑doctor.sh`, `trust‑ca‑mac.sh`) — a hard blocker for a Windows host. | Added **`scripts/dev_cert.py`** — a pure‑Python, cross‑platform twin of make‑dev‑cert + cert‑doctor (uses the already‑declared `cryptography` dep, **no new library**, no openssl/bash on Windows). It writes the exact files `run_portal._tls_files()` serves (`rootCA.pem`/`-key`, `dev‑cert.pem`/`dev‑key.pem`), **reuses the existing CA (mint‑once, ADR‑0029** — only the leaf reissues) and issues a **397‑day leaf so iPad/Safari accepts it**; tested on macOS (gen + CA‑reuse + `openssl verify` OK + doctor green). Added **`scripts/trust‑ca‑windows.ps1`** (admin; clears stale CA copies → imports rootCA to `LocalMachine\Root`; the Windows twin of trust‑ca‑mac.sh — a system‑security step the USER runs; written carefully, validate on first Windows host). Quickstart: **`docs/CROSS‑PLATFORM.md`** (host setup per OS incl. PowerShell/cmd env‑var syntax; iPad vs Android CA‑install incl. iOS's extra Certificate Trust Settings toggle). The macOS bash scripts stay (Mac path unchanged). No app code change needed — the device layer was already portable.
- **ADR‑0034 | 2026‑06‑01 | RB‑001 executed (deep research) → CONDITIONAL GO on a real ARKit‑52 blendshape deformation basis: build `face_mesh_morphbasis.json` by deformation‑transferring USC ICT‑FaceKit's MIT 53 ARKit‑named expression shapes onto MediaPipe's Apache‑2.0 canonical 468‑vertex mesh, plus author ONE supplemental `eyesClosed` (AU43) morph. Replaces the procedural 4‑of‑52 `morph_basis.ts`; $0 mandatory procurement.** | The research‑driven‑enhancement lifecycle for RB‑001 (`research/RB‑001_findings.md`). ICT‑FaceKit is the ONLY source that clears the MUST‑PASS license bar (clinical + commercial + **redistributable in a bundled on‑device app**) AND already speaks ARKit naming: every commercial pipeline (MetaHuman, Ready Player Me, Avatar SDK, Reallusion) is disqualified because their EULAs forbid redistributing extracted blendshape deltas; every other academic model is non‑commercial (Basel BFM, FaceWarehouse, standard FLAME) or PCA‑not‑ARKit (FLAME‑Open, CC‑BY‑4.0). MediaPipe ships only the neutral 468 mesh (the base) + a coefficient **predictor** (the runtime signal, NOT a basis — the real basis is on Google's unreleased GHUM mesh). Clinically: ARKit‑52 covers ~4/5 of the PSPI pain signal natively (AU4→browDown, AU6→cheekSquint, AU7→eyeSquint, AU9→noseSneer, AU10→mouthUpperUp); the one gap — **sustained eye closure AU43** (ARKit has only transient `eyeBlink`/AU45) — is the SAME morph that unlocks drowsiness/PERCLOS, so authoring `eyesClosed` is the single high‑value supplement. | One‑time OFFLINE bake (determinism + PHI hold: generation‑time only, static asset, no runtime camera/GHUM/predictor, nothing leaves device). Toolchain: open‑source NRICP + Sumner‑Popović deformation transfer (NumPy/SciPy) seeded from the MIT `vasiliskatr/deformation_transfer_ARkit_blendshapes` repo (swap target→MediaPipe‑468, source→ICT); R3DS Wrap optional paid higher‑fidelity alt (bake machine only, no output‑license effect). Output: 52 (+`eyesClosed`) ARKit‑named entries of sparse `{vertexIndex,dx,dy,dz}` 468‑vtx deltas, float16/int16, ~0.4–1.2 MB (~0.3–0.8 MB gzipped). Pin the MediaPipe topology revision (468 vs 478‑iris; issue #5760) + commit the asset hash; **QA every shape vs ARKit reference (ICT has documented FACS mislabels — don't trust names)**; resolve a possible `tongueOut` gap. **Effort ~3–5 days.** Implementation: produce the asset, swap `mesh_builder/impl/morph_basis.ts` to load it with a **fallback to the current procedural basis if absent**, regenerate + verify; `avatar_exporter` already bakes deltas by ARKit name → drop‑in, no contract change. Ship attribution: "USC ICT — ICT‑FaceKit (MIT)" + "Google MediaPipe canonical_face_model (Apache‑2.0)". No new runtime dependency.
- **ADR‑0035 | 2026‑06‑05 | RB‑001 rig ACCEPTED (per‑shape QA) + `eyesClosed` (AU43) wired into the clinical pain/drowsy driver; the remaining visual artifacts are texture/topology limitations, deferred to RB‑003.** | Per‑shape visual QA of all 52 ARKit shapes on the live avatar (Mac, Chrome/WebGPU, `?debug` morph panel): **46/52 correct, ZERO mislabels** — the bake AND the ICT→ARKit name‑map are validated. The 6 flags are NOT rig errors but artifacts of morphing a SINGLE static portrait over the 468 mesh: no inner‑mouth geometry (jawOpen/mouthClose/mouthFunnel stretch lip texture into the gap — the "blurry tongue"), mouth‑corner texture tear (smile/mouthUpperUp/noseSneer), lower‑eyelid smear (eye‑closure shapes), and the omitted `tongueOut`. Worst at weight 1.0 (the QA stress‑test), milder at the partial/blended weights real speech+emotion use. | Wired `eyesClosed`: `face_topology.MORPH_TARGETS` = ARKit‑52 + `eyesClosed` (a DEDICATED sustained‑closure target, distinct from idle_motion's transient `eyeBlink`), used by the mesh + QA panel; `avatar_exporter` bakes it by name (no contract change). emotion_driver clinical moods now compose it: **pain** = PSPI (AU4 browDown + AU6 cheekSquint + AU7 eyeSquint + AU43 eyesClosed + frown/stretch grimace); **drowsy** = PERCLOS (sustained `eyesClosed` 0.55 + tired inner brow + slack jaw). Two QA‑surfaced bugs also fixed: the baked deltas were **double‑divided by canonicalHeight (~17× too small → influences correct but rig invisible)** → `morph_basis` scale is now the live face height only (+ regression test); and `frameAvatar` framed the **outlier‑bloated bbox** (stray landmarks ~3× the face) → now frames the CORE face via a 5% percentile trim, with a tunable fill (default 0.6) + a live per‑device `setFrameFill` slider (re‑fits on resize). Opened **RB‑003 (avatar visual fidelity)** — inner‑mouth geometry, per‑region eye/lip texture handling, synthesized `tongueOut` — as the path to close the texture artifacts (the rig itself is done). 115 tests green.
- **ADR‑0036 | 2026‑06‑05 | RB‑003 executed (deep research) → GO on closing the 4 visual artifacts in THREE phases, all $0‑procurement offline‑bake + drop‑ins (the RB‑001 pattern), no rig‑contract change. The pivotal principle: the inner‑mouth cavity MUST render OPAQUE (`transparent:false`), NEVER transmissive — three.js `transmission` only refracts OPAQUE backdrop geometry, so an opaque dark cavity shows through exactly where the lips part and does NOT bleed through closed lips (the lips' see‑through is transmission, not alpha; bleed is purely GEOMETRIC → recess the proxy with `jawOpen`). Prereq: bump three.js r170→≥r181.** | RB‑003 findings (`research/RB‑003_findings.md`, 5‑agent deep research). The 4 artifacts (RB‑001 QA) are inherent to morphing ONE static portrait over the 468 mesh: UV = landmark x,y and three.js morph targets displace position/normal but NEVER uv (`face_topology.ts:104‑105`), so high‑travel verts drag their fixed texel → corner‑tear + eyelid‑smear; and the open mouth has no interior. Premises verified vs our code: three `^0.170.0` (r170) + material = transmission + `DoubleSide` + `depthWrite:false` + opacity 0.55‑1.0. License MUST‑PASS holds with ZERO new procurement: **ICT‑FaceKit (MIT — the SAME source as RB‑001/ADR‑0034)** for the cavity/teeth/tongue + **MakeHuman base (CC0)** for an alt tongue; dev‑time tools gltf‑transform (MIT) + meshoptimizer (Apache‑2.0). REJECTED license landmines: LaMa inpainting weights (Apache code but **Places2 NON‑COMMERCIAL** weights), Z‑Anatomy (**CC‑BY‑SA viral**), Sketchfab/TurboSquid/CGTrader (EULA forbids bundling — same trap RB‑001 flagged for MetaHuman/RPM). On‑device ~60 fps (it adds **+1 opaque draw call**, a few hundred tris; the transmission pass is already paid when the ghost slider leaves 1.0). | Per‑artifact GO + phasing. **Phase 0 (prereq, S):** bump three.js r170→≥r181 to clear the live WebGPU transmission‑on‑animation bug (#31768; fixes in r181) + re‑run the RB‑001 per‑shape QA to confirm no avatar regression (non‑trivial 11‑minor jump) + a ~15‑min fold‑vs‑stretch diagnostic at the commissure. **Phase 1 (S, $0):** an OPAQUE dark "mouth‑bag" dome behind the lip ring driven by `jawOpen` (`BackSide`, `depthWrite:true`, near‑black) + a baked **ΔUV channel** in the morph basis (`uv += Σ wᵢ·ΔUVᵢ` for `mouthSmile*/mouthUpperUp*/noseSneer*/mouthStretch*` and `eyeBlink*/eyesClosed/eyeLookDown*`) closing corner‑tear + eyelid‑smear + `tongueOut` as a deterministic `+Z/−Y` transform of a CC0/MIT tongue sub‑mesh (= the ARKit coefficient). **Phase 2 (M, if QA wants):** upgrade the dome to a decimated ICT‑FaceKit teeth+tongue+socket (≤800 tris → tens of KB GLB), a margin‑feather (TSL `mix()` to mucosa tint over the last 1‑2 mm), the conditional triangle‑fold guard (only if the diagnostic shows real winding inversion), and an optional ≤1 K² KTX2 teeth atlas. New `oral_cavity` module (build/load GLB, parent to head, drive by `jawOpen`/`tongueOut`); `mesh_builder/morph_basis.ts` + `shader_translucent` carry the ΔUV; reuse the RB‑001 bake harness (Umeyama‑align borrowed geometry into the MediaPipe frame). Offline‑bake + drop‑in holds determinism + PHI (ADR‑0001/0005/0014); keeps the ARKit‑52 + `eyesClosed` names. RISKS (watch‑items, not blockers): the ghost‑end composite look at opacity 0.55 (fallback = anchor cavity visibility to the opacity slider — fade the interior as the face goes ghost); empirical ΔUV magnitudes (~0.5‑1 day tuning vs the QA panel); re‑verify the avatar after the bump; **pin three.js exactly** going forward (the transmission path moves across minors). No new RUNTIME dependency. → register OPT‑none (this is fidelity, not perf); converts RB‑003 to Done on Phase‑1 ship.
- **ADR‑0036 ADDENDUM | 2026‑06‑06 | RB‑003 Phase‑1 SHIPPED — implementation diverged from the brief's plan; recorded for future‑me.** | (1) **The corner‑tear / eyelid‑smear were NOT a UV problem.** Root cause: the geometry shipped position morph targets with **no normal morphs** (`morphAttributes.normal` absent), so every blendshape moved vertices while shading stayed pinned to the NEUTRAL‑pose normals → deformed regions (eyelids, lips, jaw) mis‑lit as dark/faceted/jagged on EVERY expression. Fix = `computeMorphNormals()` recomputes per‑shape smooth normals on the deformed mesh and stores the delta (`face_topology.ts` + `mesh_builder/create.ts`); three's WebGPU `MorphNode` consumes `morphAttributes.normal` (verified r181, `MorphNode.js:260`). The planned **ΔUV channel was built then ABANDONED** (wrong frame — shading, not texture stretch); no bake harness needed. (2) **The opaque "mouth‑bag" dome was abandoned** (the flat proxy fought the curved/deforming lip ring) → replaced by a **shader‑darken** of the inner‑lip‑masked fragments by `jawOpen` (`mesh_builder` bakes the per‑vertex `innerMouth` mask; `shader_translucent` darkens `mask^0.65 × jawOpen × 4`). `tongueOut` = procedural tongue (scale/protrude by the coefficient). Also shipped: surface‑specular **reflectionGate** (matte above translucency 0.8). Validated on iPad across eyesClosed/blink/lookDown/smile/tongueOut/jawOpen — smooth, no regression ("good enough"). Commits 5e25dd2 / cb84b11 / 8eea540. **PHASE‑2 FUTURE IMPROVEMENTS (deferred, none block ship):** (a) **true mouth interior** — the face is a single shell, so a FULL `jawOpen` gape reveals the chin front below the darkened opening; a real cavity/teeth sub‑mesh (the ICT‑FaceKit Phase‑2 plan above) is the cure. (b) **mesh subdivision** — the coarse 468 eye/lip rings pinch into small dark notches at the inner‑eye + active mouth corners when folded; subdivision (smoother rings + finer mask contour) is the consistent fix. (c) **`mouthClose` re‑bake** — its deltas fold the mesh through itself at full influence (only visible driven SOLO at 1.0; never in real animation, which modulates `jawOpen`).
- **ADR‑0037 | 2026‑06‑06 | Browser/device deployment standard + character voice = SERVER‑SIDE TTS (the iPad is WebKit; on‑device TTS is impossible there).** | iPads ARE in the character fleet. iOS forces ALL browsers onto WebKit, so "Chrome on iPad" changes nothing — confirmed on device: a 3rd WebGPU model (on‑device Kokoro TTS) → `RangeError: out of memory` (the avatar renderer + whisper STT already fill the tablet GPU), and `speechSynthesis` is gesture‑locked (silently refuses the async reply ~5 s after PTT release — no audio, so no envelope‑driven lip‑sync = "no animation"). The Web Audio AudioContext IS unlockable on a gesture (ADR‑0008) but had no audio source. | DECISION (full doc: `docs/BROWSER-DEPLOYMENT-STANDARD.md`): **(1) Device classes** — *character tablets* (iPad WebKit + Android Chromium) are built to the **WebKit floor**; *operator / management / non‑character* devices standardize on **Chrome/Chromium**. **(2) Character voice = server‑side TTS** — the portal synthesizes the (non‑PHI) reply → audio bytes in the speech frame (`audioB64`) → the client plays via the gesture‑unlocked AudioContext → energy‑envelope visemes drive `jawOpen` + `frame.emotion` drives expression. Bypasses BOTH WebKit blockers. On‑device Kokoro disabled on the character path (latched off; optional for Chromium only). Engine = self‑hosted local (Kokoro/HeadTTS/Piper) RECOMMENDED for local‑first; ElevenLabs optional cloud premium (already wired). **(3) Caching** — SW precaches shell+ORT; persist whisper+MediaPipe models; server‑audio DELETES the largest model from the device (startup + memory win); a character device's WebGPU budget = renderer + STT only. | CONSEQUENCES: works on iPad AND Chromium; one consistent voice; lighter/faster device startup; adds a portal TTS dependency (self‑host to stay local). PHI‑safe (reply is non‑PHI; trainee STT stays on device — ADR‑0001/0014). OPEN: portal TTS engine choice; keep/drop optional client Kokoro; audio transport (inline base64 vs short‑lived fetch URL). Already shipped (this session): client TTS **watchdog + `kokoroBroken` latch + browser‑speech fallback + diagnostics** so the path can never silently hang again.

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

