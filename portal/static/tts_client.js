// MEDSIM V4 — shared text-to-speech client with ElevenLabs + fallback.
//
//   window.MedSimTTS.speak(text, { voiceId, language, profile })  -> Promise
//   window.MedSimTTS.cancel()
//
// Behavior:
//   - voiceId set and not "browser": stream ElevenLabs audio via an
//     <audio> element pointed at GET /api/tts (progressive playback —
//     starts before synthesis finishes, ~200 ms perceived latency).
//   - On ANY ElevenLabs failure (503 fallback signal, network error,
//     decode error) OR when voiceId is empty/"browser": fall back to the
//     browser SpeechSynthesis path with the persona's voice profile.
//
// This module is the single TTS entry point for both the chat station
// and the operator PTT panel. It replaces the per-file speak() helpers
// that V2/V3 carried.

(function () {
  "use strict";

  let availableVoices = [];
  let currentAudio = null;
  // V6 — autoplay-policy workaround. Chrome (and Safari to a lesser
  // extent) only allows audio.play() without a user gesture if the
  // element has been "unlocked" by a prior gesture-driven play(). The
  // PTT flow is async (STT → server → LLM → speak), so by the time we
  // try to play the character's reply, the user activation from the
  // PTT button press has expired and audio.play() silently fails.
  //
  // Fix: keep one shared <audio> element. The first time the user taps
  // PTT (or any other primer), prime() runs synchronously inside that
  // gesture, plays a tiny silent buffer, and from then on the element
  // is considered "user-activated" — subsequent programmatic plays on
  // it succeed even when called from async code.
  let primedAudio = null;
  let primedOnce = false;
  const SILENT_WAV =
    "data:audio/wav;base64,UklGRiQAAABXQVZFZm10IBAAAAABAAEAQB8AAEAfAAABAAgAZGF0YQAAAAA=";

  function ensurePrimedAudio() {
    if (primedAudio) return primedAudio;
    primedAudio = new Audio();
    primedAudio.preload = "auto";
    primedAudio.crossOrigin = "anonymous";
    return primedAudio;
  }

  function prime() {
    // Must be called inside a user-gesture handler the FIRST time, then
    // subsequent calls are no-ops.
    if (primedOnce) return Promise.resolve(true);
    const a = ensurePrimedAudio();
    a.src = SILENT_WAV;
    const p = a.play();
    if (p && typeof p.then === "function") {
      return p.then(
        () => { primedOnce = true; return true; },
        () => false   // gesture wasn't fresh enough — caller can retry
      );
    }
    primedOnce = true;
    return Promise.resolve(true);
  }

  function loadVoices() {
    availableVoices = window.speechSynthesis ? window.speechSynthesis.getVoices() : [];
  }
  loadVoices();
  if (window.speechSynthesis && window.speechSynthesis.onvoiceschanged !== undefined) {
    window.speechSynthesis.onvoiceschanged = loadVoices;
  }

  // ── Browser SpeechSynthesis fallback (the V2/V3 path) ──────────────
  function pickVoice(profile) {
    if (!availableVoices.length || !profile) return null;
    const hints = profile.voice_hints || [];
    for (const h of hints) {
      const v = availableVoices.find(v => v.name.toLowerCase().includes(h.toLowerCase()));
      if (v) return v;
    }
    const lang = (profile.language || "en-US").toLowerCase().split("-")[0];
    const langVoices = availableVoices.filter(v => v.lang.toLowerCase().startsWith(lang));
    const gender = (profile.gender || "").toLowerCase();
    if (gender && langVoices.length) {
      const re = gender === "female"
        ? /samantha|karen|susan|victoria|allison|moira|tessa|fiona|ava|female/i
        : /daniel|tom|fred|alex|aaron|albert|bruce|male/i;
      const m = langVoices.find(v => re.test(v.name));
      if (m) return m;
    }
    return langVoices[0] || availableVoices[0] || null;
  }

  function speakBrowser(text, profile) {
    return new Promise(resolve => {
      if (!text || !window.speechSynthesis) { resolve(); return; }
      const utt = new SpeechSynthesisUtterance(text);
      const v = pickVoice(profile || {});
      if (v) utt.voice = v;
      utt.rate = (profile && profile.rate) || 1.0;
      utt.pitch = (profile && profile.pitch) || 1.0;
      utt.onend = () => resolve();
      utt.onerror = () => resolve();
      window.speechSynthesis.speak(utt);
    });
  }

  // ── ElevenLabs streaming playback ──────────────────────────────────
  // Resolves TRUE if ElevenLabs playback started (caller must NOT fall
  // back — that would double the audio), FALSE only if playback never
  // began (dead key / 503 / network stall → caller uses browser voice).
  function playElevenLabs(text, voiceId, language) {
    return new Promise(resolve => {
      let settled = false;
      let started = false;          // true once audio actually begins playing
      const done = (played) => { if (!settled) { settled = true; resolve(played); } };

      const params = new URLSearchParams({
        text: String(text).slice(0, 1200),
        voice_id: voiceId,
      });
      if (language) params.set("language", language);

      // V6 — reuse the primed <audio> element if available. This is what
      // lets async TTS playback (the PTT reply) bypass Chrome's autoplay
      // policy, which would otherwise silently block the new Audio().play()
      // call once the original user gesture has expired.
      //
      // M37 — Explicitly reset the element before assigning the new src.
      // Without this, Chrome/Safari fire `ended` prematurely on the
      // SECOND playback through a reused primed element (the filler→
      // reply pattern in station_chat.js): the element retains `ended=
      // true` + `currentTime=<filler duration>` from the prior play, and
      // setting `src` alone doesn't fully clear those.  Pausing,
      // detaching the previous src, resetting currentTime, and calling
      // load() forces a clean state machine reset before the new stream
      // begins.  Wrapped in try/catch because some browsers throw
      // InvalidStateError when load() is called too early.
      const audio = primedAudio || new Audio();
      try { audio.pause(); } catch (e) {}
      try { audio.removeAttribute("src"); } catch (e) {}
      try { audio.load(); } catch (e) {}
      try { if (audio.currentTime !== 0) audio.currentTime = 0; } catch (e) {}
      audio.src = "/api/tts?" + params.toString();
      audio.preload = "auto";
      try { audio.load(); } catch (e) {}
      currentAudio = audio;

      // This guard ONLY covers the "playback never starts" case (dead
      // key, 503, network stall). It is cleared the instant playback
      // begins — otherwise it would fire mid-playback on a long reply
      // and trigger a browser-voice fallback ON TOP of the ElevenLabs
      // audio, producing two overlapping voices.
      const startGuard = setTimeout(() => { if (!started) done(false); }, 9000);
      const markStarted = () => { started = true; clearTimeout(startGuard); };

      audio.addEventListener("playing", markStarted, { once: true });
      audio.onended = () => {
        clearTimeout(startGuard);
        if (currentAudio === audio) currentAudio = null;
        done(true);
      };
      audio.onerror = () => {
        clearTimeout(startGuard);
        if (currentAudio === audio) currentAudio = null;
        // Once playback has begun, never fall back — replaying the line
        // in the browser voice would overlap/duplicate the audio. Only a
        // pre-start error (bad key / 503) triggers the browser fallback.
        done(started);
      };
      const playResult = audio.play();
      if (playResult && typeof playResult.then === "function") {
        playResult.then(markStarted).catch(() => {
          clearTimeout(startGuard);
          done(started);   // started is false here → caller falls back cleanly
        });
      }
      // If play() returns no promise (very old engines), the "playing"
      // event listener above still flips `started`; the start guard
      // covers the never-starts case.
    });
  }

  // ── Public API ─────────────────────────────────────────────────────
  async function speak(text, opts) {
    opts = opts || {};
    if (!text) return;
    cancel();  // never overlap utterances
    const voiceId = opts.voiceId;
    if (voiceId && voiceId !== "browser") {
      const played = await playElevenLabs(text, voiceId, opts.language || "");
      if (played) return;
      // ElevenLabs failed — degrade silently to the browser voice.
    }
    return speakBrowser(text, opts.profile || {});
  }

  function cancel() {
    try { if (window.speechSynthesis) window.speechSynthesis.cancel(); } catch (e) {}
    if (currentAudio) {
      try { currentAudio.pause(); } catch (e) {}
      currentAudio = null;
    }
  }

  window.MedSimTTS = { speak, cancel, pickVoice, prime };
})();
