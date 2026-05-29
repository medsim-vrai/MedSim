// MEDSIM 2 — station chat client (per-device, post-join).
// PTT speech-to-text → POST turn → response shown + spoken via TTS using
// the persona's voice profile. Falls back to text input if SR unavailable.

(function () {
  "use strict";
  const ctx = window.MEDSIM2_STATION || {};
  const chatLog = document.getElementById("chat-log");
  const talkBtn = document.getElementById("talk-btn");
  const talkStatus = document.getElementById("talk-status");
  const interimText = document.getElementById("interim-text");
  const latencyPill = document.getElementById("latency-pill");
  const textForm = document.getElementById("text-form");
  const voiceCtrls = document.getElementById("voice-controls");

  const SR = window.SpeechRecognition || window.webkitSpeechRecognition;
  let recognition = null;
  let isListening = false;
  let inFlight = false;
  let speechEndAt = 0;

  const FILLERS = ["Mm…", "Hmm.", "Let me think.", "One sec.", "Hold on.", "OK.", "Right…"];

  // V4 — TTS goes through the shared MedSimTTS client: the persona's
  // assigned ElevenLabs neural voice (ctx.voice_id) with automatic
  // fallback to browser SpeechSynthesis using the voice profile.
  function speak(text) {
    if (!text || !window.MedSimTTS) return Promise.resolve();
    return window.MedSimTTS.speak(text, {
      voiceId:  ctx.voice_id || "",
      language: ((ctx.voice_profile && ctx.voice_profile.language) || "en").split("-")[0],
      profile:  ctx.voice_profile || {},
    });
  }
  function appendBubble(cls, speaker, text) {
    const empty = chatLog.querySelector(".chat-empty");
    if (empty) empty.remove();
    const d = document.createElement("div"); d.className = "bubble " + cls;
    const s = document.createElement("span"); s.className = "speaker"; s.textContent = speaker;
    const p = document.createElement("p"); p.textContent = text;
    d.appendChild(s); d.appendChild(p); chatLog.appendChild(d);
    chatLog.scrollTop = chatLog.scrollHeight;
    return d;
  }

  async function sendTurn(message) {
    if (!message.trim() || inFlight) return;
    inFlight = true;
    speechEndAt = performance.now();
    appendBubble("student", "Student", message);

    // Filler in the persona's voice
    const fillerPromise = speak(FILLERS[Math.floor(Math.random() * FILLERS.length)]);
    if (latencyPill) latencyPill.textContent = `filler ${Math.round(performance.now() - speechEndAt)}ms`;

    try {
      const fd = new FormData();
      fd.append("message", message);
      const res = await fetch(`/api/station/${encodeURIComponent(ctx.join_code)}/${encodeURIComponent(ctx.station_id)}/turn`, {
        method: "POST", body: fd,
      });
      const data = await res.json();
      await fillerPromise;
      if (data.ok) {
        appendBubble("character", data.character_name || ctx.persona_name, data.reply);
        if (latencyPill) latencyPill.textContent = `total ${Math.round(performance.now() - speechEndAt)}ms`;
        await speak(data.reply);
      } else {
        appendBubble("character error", "System", data.error || "Unknown error");
      }
    } catch (err) {
      appendBubble("character error", "System", "Network error: " + err);
    } finally {
      inFlight = false;
      if (talkStatus) talkStatus.textContent = "Idle";
    }
  }

  // Heartbeat every 15s
  setInterval(() => {
    fetch(`/api/station/${encodeURIComponent(ctx.join_code)}/${encodeURIComponent(ctx.station_id)}/heartbeat`, { method: "POST" });
  }, 15000);

  // Mode toggle: ptt vs text
  document.querySelectorAll('input[name=mode]').forEach(r => r.addEventListener("change", e => {
    if (e.target.value === "text") { voiceCtrls.hidden = true; textForm.hidden = false; textForm.querySelector("textarea").focus(); }
    else { voiceCtrls.hidden = false; textForm.hidden = true; }
  }));

  // Text form fallback
  if (textForm) textForm.addEventListener("submit", e => {
    e.preventDefault();
    const ta = textForm.querySelector("textarea");
    const msg = ta.value.trim();
    if (msg) { ta.value = ""; sendTurn(msg); }
  });

  // PTT
  if (!SR) {
    if (talkBtn) { talkBtn.disabled = true; }
    if (talkStatus) talkStatus.textContent = "STT unavailable — use text mode";
    return;
  }
  recognition = new SR();
  recognition.continuous = false;
  recognition.interimResults = true;
  recognition.lang = "en-US";
  recognition.onresult = e => {
    let interim = "", final = "";
    for (let i = e.resultIndex; i < e.results.length; i++) {
      const r = e.results[i];
      if (r.isFinal) final += r[0].transcript; else interim += r[0].transcript;
    }
    interimText.textContent = interim;
    if (final.trim()) {
      interimText.textContent = "";
      try { recognition.stop(); } catch {}
      isListening = false; talkBtn.classList.remove("active");
      sendTurn(final);
    }
  };
  recognition.onend = () => { isListening = false; talkBtn.classList.remove("active"); if (talkStatus) talkStatus.textContent = "Idle"; };
  recognition.onerror = e => { isListening = false; talkBtn.classList.remove("active"); if (talkStatus) talkStatus.textContent = "Error: " + e.error; };

  function start() {
    if (isListening || inFlight) return;
    try { if (window.MedSimTTS) { window.MedSimTTS.prime && window.MedSimTTS.prime(); window.MedSimTTS.cancel(); } recognition.start(); isListening = true; talkBtn.classList.add("active"); if (talkStatus) talkStatus.textContent = "Listening…"; } catch {}
  }
  function stop() { if (!isListening) return; try { recognition.stop(); } catch {} }
  talkBtn.addEventListener("pointerdown", e => { e.preventDefault(); start(); });
  talkBtn.addEventListener("pointerup", stop);
  talkBtn.addEventListener("pointerleave", stop);
  talkBtn.addEventListener("pointercancel", stop);
})();
