// MEDSIM V4 — ops view "Character voices" panel.
//
// For each persona in the session:
//   - fetches GET /api/voices/candidates/{persona_id} → 5 ranked voices
//   - renders a <select> (+ "Browser voice (fallback)" option)
//   - on change → POST /api/control/voice to persist the assignment
//   - Preview button → POST /api/tts and play the audio, or speak a
//     sample line via SpeechSynthesis if ElevenLabs is unavailable.

(function () {
  "use strict";
  const ctx = window.MEDSIM2_OPS || {};
  const grid = document.getElementById("voice-grid");
  const healthEl = document.getElementById("voice-health");
  if (!grid) return;

  const assignments = ctx.voice_assignments || {};
  const SAMPLE = "Hello, I'm ready when you are. Go ahead and ask your questions.";

  // ── Health badge ──────────────────────────────────────────────────
  fetch("/api/voices/health", { credentials: "same-origin" })
    .then(r => r.json())
    .then(h => {
      if (!healthEl) return;
      if (h.available) {
        healthEl.textContent = `● ElevenLabs live — ${h.voice_count} voices`;
        healthEl.style.color = "#1f7a3a";
      } else {
        healthEl.textContent = "● Browser voices (ElevenLabs not configured)";
        healthEl.style.color = "#c47a04";
      }
    })
    .catch(() => { if (healthEl) healthEl.textContent = "● status unknown"; });

  // ── Per-persona candidate loading ─────────────────────────────────
  const cards = Array.from(grid.querySelectorAll(".voice-card"));
  cards.forEach(card => {
    const pid = card.dataset.personaId;
    const select = card.querySelector(".voice-select");
    const status = card.querySelector(`.voice-status[data-persona-id="${pid}"]`);

    fetch(`/api/voices/candidates/${encodeURIComponent(pid)}`, { credentials: "same-origin" })
      .then(r => r.json())
      .then(data => {
        const cands = data.candidates || [];
        const traits = data.traits || {};
        select.innerHTML = "";

        // Browser-fallback option always first.
        const browserOpt = document.createElement("option");
        browserOpt.value = "browser";
        browserOpt.textContent = "Browser voice (fallback)";
        select.appendChild(browserOpt);

        cands.forEach(v => {
          const o = document.createElement("option");
          o.value = v.voice_id;
          const tags = [v.gender, v.age && v.age.replace("_", " "), v.accent, v.descriptive]
            .filter(Boolean).join(" · ");
          o.textContent = `${v.name} — ${tags}`;
          select.appendChild(o);
        });

        // Restore prior assignment if any.
        const assigned = assignments[pid];
        select.value = (assigned && cands.some(v => v.voice_id === assigned))
          ? assigned : "browser";

        if (status) {
          status.textContent = cands.length
            ? `${cands.length} match ${traits.sex || "?"}/${(traits.age_band || "?").replace("_", " ")}` +
              (data.source === "fallback" ? " · fallback catalog" : "")
            : "no candidates";
        }
      })
      .catch(() => {
        select.innerHTML = '<option value="browser">Browser voice (fallback)</option>';
        if (status) status.textContent = "candidate load failed";
      });

    // Persist on change.
    select.addEventListener("change", () => {
      const fd = new FormData();
      fd.append("persona_id", pid);
      fd.append("voice_id", select.value);
      fetch("/api/control/voice", { method: "POST", body: fd, credentials: "same-origin" })
        .then(r => r.json())
        .then(() => {
          assignments[pid] = select.value === "browser" ? "" : select.value;
          if (status) {
            status.textContent = select.value === "browser"
              ? "→ browser voice" : "✓ assigned";
            setTimeout(() => { status.textContent = ""; }, 2500);
          }
        })
        .catch(() => { if (status) status.textContent = "save failed"; });
    });

    // Preview.
    const previewBtn = card.querySelector(`.voice-preview[data-persona-id="${pid}"]`);
    if (previewBtn) {
      previewBtn.addEventListener("click", () => previewVoice(select.value, status, pid));
    }
  });

  // ── Preview playback ──────────────────────────────────────────────
  async function previewVoice(voiceId, status, pid) {
    if (status) status.textContent = "synthesizing…";
    if (!voiceId || voiceId === "browser") {
      speakBrowser(SAMPLE);
      if (status) status.textContent = "browser voice";
      return;
    }
    try {
      const resp = await fetch("/api/tts", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        credentials: "same-origin",
        body: JSON.stringify({ text: SAMPLE, voice_id: voiceId }),
      });
      if (!resp.ok) {
        // 503 + {fallback:true} — degrade to browser TTS.
        speakBrowser(SAMPLE);
        if (status) status.textContent = "ElevenLabs unavailable — browser voice";
        return;
      }
      const blob = await resp.blob();
      const audio = new Audio(URL.createObjectURL(blob));
      audio.onended = () => { if (status) status.textContent = ""; };
      await audio.play();
      if (status) status.textContent = "▶ playing";
    } catch (e) {
      speakBrowser(SAMPLE);
      if (status) status.textContent = "browser voice";
    }
  }

  function speakBrowser(text) {
    try {
      window.speechSynthesis.cancel();
      window.speechSynthesis.speak(new SpeechSynthesisUtterance(text));
    } catch (e) { /* no speech synthesis — nothing to do */ }
  }
})();
