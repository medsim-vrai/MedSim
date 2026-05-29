// medsim portal — client-side interactivity.

// ---- Credential "Test" buttons -------------------------------------------
document.querySelectorAll("[data-test-key]").forEach((btn) => {
  btn.addEventListener("click", async () => {
    const key = btn.dataset.testKey;
    const target = document.querySelector(`[data-result-for="${key}"]`);
    if (!target) return;
    target.textContent = "Testing…";
    target.className = "test-result";
    const fd = new FormData();
    fd.append("key", key);
    try {
      const res = await fetch("/portal/credentials/test", {
        method: "POST",
        body: fd,
      });
      const data = await res.json();
      target.textContent = data.message || "(no message)";
      target.className = "test-result " + (data.ok ? "ok" : "err");
    } catch (err) {
      target.textContent = "Network error: " + err;
      target.className = "test-result err";
    }
  });
});

// ---- Scenario "Launch" — text mode or voice mode (v2) -------------------
document.querySelectorAll("[data-launch-id]").forEach((btn) => {
  btn.addEventListener("click", async () => {
    const id = btn.dataset.launchId;
    const mode = btn.dataset.launchMode || "text";
    const card = btn.closest(".entity-card") || document;
    const target = card.querySelector(`[data-launch-result="${id}"]`);
    if (target) {
      target.textContent = "Starting session…";
      target.className = "test-result";
    }
    // Disable both launch buttons on this card while in flight
    card.querySelectorAll("[data-launch-id]").forEach((b) => (b.disabled = true));
    try {
      const res = await fetch(
        `/portal/scenarios/${encodeURIComponent(id)}/launch`,
        { method: "POST" }
      );
      const data = await res.json();
      if (data.ok && data.redirect_url) {
        const url = mode === "voice"
          ? `${data.redirect_url}/voice`
          : data.redirect_url;
        window.location = url;
        return;
      }
      if (target) {
        target.textContent = data.message || "Launch failed.";
        target.className = "test-result err";
      }
      card.querySelectorAll("[data-launch-id]").forEach((b) => (b.disabled = false));
    } catch (err) {
      if (target) {
        target.textContent = "Network error: " + err;
        target.className = "test-result err";
      }
      card.querySelectorAll("[data-launch-id]").forEach((b) => (b.disabled = false));
    }
  });
});

// ---- Confirmation dialogs for destructive forms --------------------------
document.querySelectorAll("form[data-confirm]").forEach((form) => {
  form.addEventListener("submit", (event) => {
    if (!confirm(form.dataset.confirm)) {
      event.preventDefault();
    }
  });
});

// ---- Home page "Load example data" --------------------------------------
const loadBtn = document.getElementById("load-examples");
if (loadBtn) {
  loadBtn.addEventListener("click", async () => {
    const target = document.getElementById("load-result");
    if (target) {
      target.textContent = "Loading…";
      target.className = "muted";
    }
    loadBtn.disabled = true;
    try {
      const res = await fetch("/portal/examples/load", { method: "POST" });
      const data = await res.json();
      if (target) {
        target.textContent = data.message;
        target.className = data.ok ? "ok" : "err";
      }
      if (data.ok) {
        setTimeout(() => window.location.reload(), 1200);
      } else {
        loadBtn.disabled = false;
      }
    } catch (err) {
      if (target) {
        target.textContent = "Network error: " + err;
        target.className = "err";
      }
      loadBtn.disabled = false;
    }
  });
}

// ---- Session chat -------------------------------------------------------
const turnForm = document.getElementById("turn-form");
if (turnForm) {
  const chatLog = document.getElementById("chat-log");
  const charButtons = turnForm.querySelectorAll(".char-btn");
  const textarea = turnForm.querySelector("textarea");
  const submitBtn = turnForm.querySelector("button[type=submit]");
  const sessionId = turnForm.dataset.sessionId;

  let activeChar = charButtons.length > 0 ? charButtons[0].dataset.charId : null;

  charButtons.forEach((btn) => {
    btn.addEventListener("click", () => {
      charButtons.forEach((b) => b.classList.remove("active"));
      btn.classList.add("active");
      activeChar = btn.dataset.charId;
      textarea.focus();
    });
  });

  // Enter to send, Shift+Enter for newline
  textarea.addEventListener("keydown", (e) => {
    if (e.key === "Enter" && !e.shiftKey) {
      e.preventDefault();
      turnForm.requestSubmit();
    }
  });

  turnForm.addEventListener("submit", async (e) => {
    e.preventDefault();
    if (!activeChar) {
      alert("Pick a character to address first.");
      return;
    }
    const message = textarea.value.trim();
    if (!message) return;

    // Clear empty-state if present
    const empty = chatLog.querySelector(".chat-empty");
    if (empty) empty.remove();

    const charName = document
      .querySelector(`.char-btn[data-char-id="${activeChar}"]`)
      .textContent.trim();

    appendBubble(chatLog, "student", `You → ${charName}`, message);
    textarea.value = "";
    submitBtn.disabled = true;
    const loadingBubble = appendBubble(
      chatLog,
      "character loading",
      charName,
      "…thinking"
    );

    try {
      const fd = new FormData();
      fd.append("addressee", activeChar);
      fd.append("message", message);
      const res = await fetch(`/portal/session/${sessionId}/turn`, {
        method: "POST",
        body: fd,
      });
      const data = await res.json();
      loadingBubble.remove();
      if (data.ok) {
        appendBubble(chatLog, "character", data.character_name, data.reply);
      } else {
        appendBubble(
          chatLog,
          "character error",
          "System",
          data.error || "Unknown error"
        );
      }
    } catch (err) {
      loadingBubble.remove();
      appendBubble(chatLog, "character error", "System", "Network error: " + err);
    } finally {
      submitBtn.disabled = false;
      textarea.focus();
    }
  });
}

function appendBubble(container, className, speaker, text) {
  const div = document.createElement("div");
  div.className = "bubble " + className;
  const span = document.createElement("span");
  span.className = "speaker";
  span.textContent = speaker;
  const p = document.createElement("p");
  p.textContent = text;
  div.appendChild(span);
  div.appendChild(p);
  container.appendChild(div);
  container.scrollTop = container.scrollHeight;
  return div;
}
