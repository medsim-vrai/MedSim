// medsim portal — voice session client (v2).
//
// Stack:
//   STT: Web Speech API (window.SpeechRecognition / webkitSpeechRecognition)
//   TTS: window.speechSynthesis (browser-native)
//   Latency masking: filler utterance fired immediately on transcript-final,
//     while the Claude call runs in parallel — matches §5.2 of the PDF.
//
// Cross-platform notes:
//   iOS Safari 14.5+ supports webkitSpeechRecognition but only with continuous=false.
//   We therefore keep continuous=false in BOTH modes and auto-restart in
//   "speaker on" mode after each reply finishes speaking.

(function () {
  "use strict";

  const SR = window.SpeechRecognition || window.webkitSpeechRecognition;
  const session = window.MEDSIM_SESSION || {};
  const chatLog = document.getElementById("chat-log");
  const talkBtn = document.getElementById("talk-btn");
  const talkStatus = document.getElementById("talk-status");
  const talkLabel = talkBtn.querySelector(".talk-label");
  const interimText = document.getElementById("interim-text");
  const pttBanner = document.getElementById("ptt-banner");
  const micBanner = document.getElementById("mic-banner");
  const latencyPill = document.getElementById("latency-pill");
  const charTiles = document.querySelectorAll(".character-tile");

  // --- State -------------------------------------------------------------
  let activeCharId = charTiles[0]?.dataset.charId || null;
  let activeProfile = parseProfile(charTiles[0]);
  let mode = "ptt";
  let recognition = null;
  let isListening = false;
  let inFlight = false;
  let speechEndAt = 0; // for latency measurement

  // Generic filler bank — short, role-neutral utterances spoken in the
  // character's voice while Claude is generating. Per §5.2 they buy ~1–2s.
  const FILLERS = [
    "Mm...", "Hmm.", "Let me think.", "One sec.", "Hold on.",
    "OK.", "Yeah, ah...", "Let me check.", "Right...",
  ];
  let lastFiller = "";

  // --- Helpers ----------------------------------------------------------

  function parseProfile(tile) {
    if (!tile) return {};
    try {
      return JSON.parse(tile.dataset.voiceProfile || "{}");
    } catch {
      return {};
    }
  }

  // V4 — per-character ElevenLabs voice assignment. This legacy V1 voice
  // session has no ControlSession to persist onto, so assignments live
  // client-side for the page lifetime.
  const charVoices = {};        // charId → voice_id ("" = browser)
  let activeVoiceId = charVoices[activeCharId] || "";

  // TTS routes through the shared MedSimTTS client: the active character's
  // assigned ElevenLabs neural voice, with automatic browser
  // SpeechSynthesis fallback when ElevenLabs is unavailable.
  function speak(text, profile) {
    if (!text || !window.MedSimTTS) return Promise.resolve();
    return window.MedSimTTS.speak(text, {
      voiceId:  activeVoiceId || "",
      language: ((profile && profile.language) || "en").split("-")[0],
      profile:  profile || {},
    });
  }

  function pickFiller() {
    let f;
    let tries = 0;
    do {
      f = FILLERS[Math.floor(Math.random() * FILLERS.length)];
      tries++;
    } while (f === lastFiller && tries < 4 && FILLERS.length > 1);
    lastFiller = f;
    return f;
  }

  function setStatus(text) {
    if (talkStatus) talkStatus.textContent = text;
  }

  function appendBubble(className, speaker, text) {
    const empty = chatLog.querySelector(".chat-empty");
    if (empty) empty.remove();
    const div = document.createElement("div");
    div.className = "bubble " + className;
    const span = document.createElement("span");
    span.className = "speaker";
    span.textContent = speaker;
    const p = document.createElement("p");
    p.textContent = text;
    div.appendChild(span);
    div.appendChild(p);
    chatLog.appendChild(div);
    chatLog.scrollTop = chatLog.scrollHeight;
    return div;
  }

  // --- Turn-taking ------------------------------------------------------

  async function sendTurn(text) {
    if (!text.trim() || inFlight) return;
    inFlight = true;
    speechEndAt = performance.now();

    const charName = document
      .querySelector(`.character-tile[data-char-id="${activeCharId}"] strong`)
      .textContent;
    appendBubble("student", `You → ${charName}`, text);
    setStatus("Sending...");

    // Latency masking: filler kicks off IMMEDIATELY in the character's voice.
    const filler = pickFiller();
    const fillerPromise = speak(filler, activeProfile);
    const firstAudibleAt = performance.now();
    if (latencyPill) {
      const ttfb = Math.round(firstAudibleAt - speechEndAt);
      latencyPill.textContent = `${ttfb}ms filler`;
    }

    // API call in parallel with the filler.
    let result;
    try {
      const fd = new FormData();
      fd.append("addressee", activeCharId);
      fd.append("message", text);
      const res = await fetch(`/portal/session/${session.id}/turn`, {
        method: "POST",
        body: fd,
      });
      result = await res.json();
    } catch (err) {
      result = { ok: false, error: "Network error: " + err };
    }

    // Wait for the filler to finish naturally (it's short — 0.5–1.5s).
    await fillerPromise;

    if (result.ok) {
      appendBubble("character", result.character_name, result.reply);
      setStatus("Speaking...");
      const fullResponseAt = performance.now();
      if (latencyPill) {
        const total = Math.round(fullResponseAt - speechEndAt);
        latencyPill.textContent = `filler ${Math.round(firstAudibleAt - speechEndAt)}ms · full ${total}ms`;
      }
      await speak(result.reply, activeProfile);
    } else {
      appendBubble("character error", "System", result.error || "Unknown error");
    }

    inFlight = false;
    setStatus("Idle");

    // Speaker-on mode: auto-restart listening after the reply finishes.
    if (mode === "continuous") {
      setTimeout(() => startListening(), 200);
    }
  }

  // --- Recognition lifecycle --------------------------------------------

  function startListening() {
    if (!recognition || isListening || inFlight) return;
    try {
      // V6 — prime the shared audio element inside the user gesture so
      // the async TTS reply (post-LLM) survives Chrome's autoplay policy.
      if (window.MedSimTTS) {
        if (window.MedSimTTS.prime) window.MedSimTTS.prime();
        // Stop any TTS in progress (barge-in)
        window.MedSimTTS.cancel();
      }
      recognition.start();
      isListening = true;
      setStatus("Listening...");
      talkBtn.classList.add("active");
    } catch (e) {
      // already started or transient error — ignore
    }
  }

  function stopListening() {
    if (!recognition || !isListening) return;
    try {
      recognition.stop();
    } catch (e) { /* ignore */ }
    isListening = false;
    talkBtn.classList.remove("active");
  }

  function setupRecognition() {
    if (!SR) {
      if (pttBanner) pttBanner.hidden = false;
      talkBtn.disabled = true;
      return;
    }
    recognition = new SR();
    recognition.continuous = false; // iOS-safe; we auto-restart in continuous mode
    recognition.interimResults = true;
    recognition.lang = "en-US";

    recognition.onresult = (event) => {
      let interim = "";
      let final = "";
      for (let i = event.resultIndex; i < event.results.length; i++) {
        const r = event.results[i];
        if (r.isFinal) final += r[0].transcript;
        else interim += r[0].transcript;
      }
      interimText.textContent = interim;
      if (final.trim()) {
        interimText.textContent = "";
        // Stop listening before sending — mic frees up for the TTS reply.
        stopListening();
        sendTurn(final);
      }
    };

    recognition.onerror = (event) => {
      isListening = false;
      talkBtn.classList.remove("active");
      if (event.error === "not-allowed" || event.error === "service-not-allowed") {
        if (micBanner) micBanner.hidden = false;
        setStatus("Mic blocked");
      } else if (event.error === "no-speech") {
        setStatus("No speech");
      } else if (event.error === "aborted") {
        setStatus("Idle");
      } else {
        setStatus("Error: " + event.error);
      }
    };

    recognition.onend = () => {
      isListening = false;
      talkBtn.classList.remove("active");
      setStatus("Idle");
    };
  }

  function setMode(newMode) {
    mode = newMode;
    if (mode === "continuous") {
      talkLabel.textContent = "Tap to start";
      talkBtn.classList.add("continuous");
    } else {
      talkLabel.textContent = "Hold to talk";
      talkBtn.classList.remove("continuous");
    }
    if (isListening) stopListening();
  }

  // --- UI wiring --------------------------------------------------------

  charTiles.forEach((tile) => {
    tile.addEventListener("click", () => {
      charTiles.forEach(t => t.classList.remove("active"));
      tile.classList.add("active");
      activeCharId = tile.dataset.charId;
      activeProfile = parseProfile(tile);
      activeVoiceId = charVoices[activeCharId] || "";
    });
  });

  // --- V4 voice picker --------------------------------------------------
  // For each character, fetch 5 candidate ElevenLabs voices filtered by
  // the character's inferred sex, populate a <select>, and let the
  // operator preview + assign. Assignments update charVoices and the
  // matching character tile's data-voice-id.
  const SAMPLE = "Hello — go ahead and ask me your question.";

  function speakSample(voiceId) {
    if (!window.MedSimTTS) return;
    window.MedSimTTS.speak(SAMPLE, { voiceId: voiceId || "", profile: {} });
  }

  function initVoicePicker() {
    const healthEl = document.getElementById("el-health");
    if (healthEl) {
      fetch("/api/voices/health", { credentials: "same-origin" })
        .then(r => r.json())
        .then(h => {
          healthEl.textContent = h.available
            ? `● ElevenLabs live — ${h.voice_count} voices`
            : "● Browser voices (ElevenLabs not configured)";
          healthEl.style.color = h.available ? "#1f7a3a" : "#c47a04";
        })
        .catch(() => { healthEl.textContent = "● status unknown"; });
    }

    document.querySelectorAll(".voice-assign-row").forEach(row => {
      const cid = row.dataset.charId;
      const sex = row.dataset.sex || "U";
      const age = row.dataset.age || "middle_aged";
      const select = row.querySelector(".vc-select");
      const preview = row.querySelector(".vc-preview");

      const params = new URLSearchParams({ sex: sex, age_band: age });
      fetch("/api/voices/candidates?" + params.toString(), { credentials: "same-origin" })
        .then(r => r.json())
        .then(data => {
          const cands = data.candidates || [];
          select.innerHTML = "";
          const browserOpt = document.createElement("option");
          browserOpt.value = "browser";
          browserOpt.textContent = "Browser voice (fallback)";
          select.appendChild(browserOpt);
          cands.forEach(v => {
            const o = document.createElement("option");
            o.value = v.voice_id;
            const tags = [v.gender, (v.age || "").replace("_", " "), v.accent]
              .filter(Boolean).join(" · ");
            o.textContent = `${v.name} — ${tags}`;
            select.appendChild(o);
          });
        })
        .catch(() => {
          select.innerHTML = '<option value="browser">Browser voice (fallback)</option>';
        });

      select.addEventListener("change", () => {
        const vid = select.value === "browser" ? "" : select.value;
        charVoices[cid] = vid;
        const tile = document.querySelector(`.character-tile[data-char-id="${cid}"]`);
        if (tile) tile.dataset.voiceId = vid;
        if (cid === activeCharId) activeVoiceId = vid;
      });

      if (preview) {
        preview.addEventListener("click", () => {
          speakSample(select.value === "browser" ? "" : select.value);
        });
      }
    });
  }
  initVoicePicker();

  document.querySelectorAll("input[name=mode]").forEach((radio) => {
    radio.addEventListener("change", (e) => setMode(e.target.value));
  });

  if (talkBtn) {
    // PTT mode: hold to talk; continuous mode: tap to start, tap to stop.
    talkBtn.addEventListener("pointerdown", (e) => {
      e.preventDefault();
      if (mode === "ptt") {
        startListening();
      } else {
        // continuous: toggle
        if (isListening) stopListening();
        else startListening();
      }
    });

    talkBtn.addEventListener("pointerup", () => {
      if (mode === "ptt") stopListening();
    });
    talkBtn.addEventListener("pointerleave", () => {
      if (mode === "ptt") stopListening();
    });
    talkBtn.addEventListener("pointercancel", () => {
      if (mode === "ptt") stopListening();
    });
  }

  setupRecognition();
})();
