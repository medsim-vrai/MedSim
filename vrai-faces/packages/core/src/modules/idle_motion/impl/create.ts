import type { IdleMotionModule } from '@contracts/idle_motion';
import type { BlendshapeWeights, BootDeps } from '@contracts/shared';

/**
 * Tiny deterministic PRNG (mulberry32). Same seed → same sequence so the
 * soak fixture is reproducible across runs.
 */
function makeRng(seed: number): () => number {
  let s = seed >>> 0;
  return () => {
    s = (s + 0x6D2B79F5) >>> 0;
    let t = s;
    t = Math.imul(t ^ (t >>> 15), t | 1);
    t ^= t + Math.imul(t ^ (t >>> 7), t | 61);
    return ((t ^ (t >>> 14)) >>> 0) / 4294967296;
  };
}

/** Hermite smoothstep, 0..1 → 0..1, zero slope at both ends. */
function smoothstep(x: number): number {
  if (x <= 0) return 0;
  if (x >= 1) return 1;
  return x * x * (3 - 2 * x);
}

function add(out: BlendshapeWeights, key: string, v: number): void {
  out[key] = (out[key] ?? 0) + v;
}

// --- Blink: spontaneous lid closures. ~12–20/min → a 2.8–6 s interval. ---
const BLINK_INTERVAL_MIN = 2800;   // ms between blinks (lower bound)
const BLINK_INTERVAL_MAX = 6000;   // ms between blinks (upper bound)
const BLINK_CLOSE_MS     = 60;     // lids down — fast
const BLINK_OPEN_MS      = 130;    // lids back up — a touch slower
const BLINK_DUR          = BLINK_CLOSE_MS + BLINK_OPEN_MS;
const BLINK_DOUBLE_CHANCE = 0.12;  // occasionally a quick second blink
const BLINK_DOUBLE_GAP    = 200;   // ms from 1st blink start to the 2nd

// --- Micro-saccades: eyes fixate, then dart a small amount and hold. ---
const FIX_MIN     = 450;           // ms holding a gaze (lower bound)
const FIX_MAX     = 1800;          // ms holding a gaze (upper bound)
const SACCADE_MS  = 45;            // dart duration — eyes move fast
const SACCADE_AMP = 0.18;          // max gaze offset, as an additive weight

// --- Slow sway: a low-frequency drift so the gaze is never statue-still. ---
const SWAY_AMP      = 0.04;
const SWAY_PERIOD_X = 9000;        // ms
const SWAY_PERIOD_Y = 13000;       // ms — coprime-ish with X for a non-repeating feel

// Catch-up guard: cap schedule advancement per call so a huge time jump
// (e.g. tab was backgrounded) can't spin the loop forever. The remainder is
// absorbed on subsequent calls, so the PRNG draw count still tracks elapsed
// time rather than frame count — preserving determinism.
const CATCHUP_GUARD = 256;

export function createImpl(): IdleMotionModule {
  let _deps: BootDeps | null = null;
  let rng = makeRng(1);

  // Re-anchored on the first sample after boot/setSeed so the timeline is
  // relative to t0 (reproducible for a given seed + nowMs sequence).
  let inited = false;

  // Blink schedule (absolute nowMs).
  let nextBlinkAt = 0;
  let blinkStart = -1e9;           // start time of the in-flight blink
  let pendingDouble = false;       // a second blink is queued (double-blink)

  // Saccade schedule + gaze state.
  let gazeX = 0, gazeY = 0;        // current fixation target (additive weight units)
  let fromX = 0, fromY = 0;        // gaze at the start of the active dart
  let saccadeStart = -1e9;
  let nextSaccadeAt = 0;

  const rand = (lo: number, hi: number): number => lo + (hi - lo) * rng();

  function init(now: number): void {
    blinkStart = -1e9;
    pendingDouble = false;
    nextBlinkAt = now + rand(BLINK_INTERVAL_MIN, BLINK_INTERVAL_MAX);

    gazeX = gazeY = fromX = fromY = 0;
    saccadeStart = -1e9;
    nextSaccadeAt = now + rand(FIX_MIN, FIX_MAX);

    inited = true;
  }

  /** Lid-closure amount for the in-flight blink at `now`, 0..1. */
  function blinkAt(now: number): number {
    const e = now - blinkStart;
    if (e < 0 || e >= BLINK_DUR) return 0;
    if (e < BLINK_CLOSE_MS) return smoothstep(e / BLINK_CLOSE_MS);          // 0 → 1
    return 1 - smoothstep((e - BLINK_CLOSE_MS) / BLINK_OPEN_MS);           // 1 → 0
  }

  return {
    async boot(deps) { _deps = deps; inited = false; },
    dispose() { _deps = null; inited = false; },

    setSeed(seed) { rng = makeRng(seed); inited = false; },

    sample(nowMs, out: BlendshapeWeights) {
      void _deps;
      if (!inited) init(nowMs);

      // 1. Advance the blink schedule up to `now` (time-driven, so the event
      //    timeline is independent of frame rate).
      let g = 0;
      while (nowMs >= nextBlinkAt && g++ < CATCHUP_GUARD) {
        blinkStart = nextBlinkAt;
        if (pendingDouble) {
          pendingDouble = false;
          nextBlinkAt = blinkStart + rand(BLINK_INTERVAL_MIN, BLINK_INTERVAL_MAX);
        } else if (rng() < BLINK_DOUBLE_CHANCE) {
          pendingDouble = true;
          nextBlinkAt = blinkStart + BLINK_DOUBLE_GAP;
        } else {
          nextBlinkAt = blinkStart + rand(BLINK_INTERVAL_MIN, BLINK_INTERVAL_MAX);
        }
      }

      // 2. Advance the saccade schedule: each crossing starts a dart toward a
      //    fresh small gaze target, then holds for a randomized fixation.
      g = 0;
      while (nowMs >= nextSaccadeAt && g++ < CATCHUP_GUARD) {
        fromX = gazeX; fromY = gazeY;
        gazeX = (rng() * 2 - 1) * SACCADE_AMP;
        gazeY = (rng() * 2 - 1) * SACCADE_AMP;
        saccadeStart = nextSaccadeAt;
        nextSaccadeAt = saccadeStart + rand(FIX_MIN, FIX_MAX);
      }

      // 3. Resolve gaze: dart fromX/Y → gazeX/Y over SACCADE_MS, then hold,
      //    plus a slow sinusoidal sway so the eyes drift between darts.
      const k = smoothstep((nowMs - saccadeStart) / SACCADE_MS);
      const gx = fromX + (gazeX - fromX) * k
        + Math.sin((nowMs / SWAY_PERIOD_X) * Math.PI * 2) * SWAY_AMP;
      const gy = fromY + (gazeY - fromY) * k
        + Math.sin((nowMs / SWAY_PERIOD_Y) * Math.PI * 2) * SWAY_AMP;

      // 4. Emit. Blink is symmetric on both lids; gaze splits into the ARKit
      //    look-direction pairs. Always write the blink keys (even at 0) so
      //    the additive contract reads back a defined value.
      const blink = blinkAt(nowMs);
      out.eyeBlinkLeft  = (out.eyeBlinkLeft  ?? 0) + blink;
      out.eyeBlinkRight = (out.eyeBlinkRight ?? 0) + blink;

      if (gx >= 0) {
        add(out, 'eyeLookOutRight', gx);   // both eyes track to the model's right
        add(out, 'eyeLookInLeft',   gx);
      } else {
        add(out, 'eyeLookOutLeft',  -gx);  // …to the model's left
        add(out, 'eyeLookInRight',  -gx);
      }
      if (gy >= 0) {
        add(out, 'eyeLookUpLeft',  gy);
        add(out, 'eyeLookUpRight', gy);
      } else {
        add(out, 'eyeLookDownLeft',  -gy);
        add(out, 'eyeLookDownRight', -gy);
      }
    },
  };
}
