// MEDSIM V7 — student join page (M9).
//
// Flow: pick name (or type one) → encounter list appears → tap an
// encounter → POST /portal/students/register → redirect to the
// existing v6 chat-station UI.

(function () {
  'use strict';

  const $ = (id) => document.getElementById(id);
  const cfg = window.STUDENT_JOIN || {};

  let chosenName = "";
  let chosenStudentId = "";
  let chosenRole = "bedside";

  function commitName(name, studentId) {
    chosenName      = (name || "").trim();
    chosenStudentId = studentId || "";
    if (!chosenName) {
      $("step-role")?.setAttribute("hidden", "");
      $("step-encounter")?.setAttribute("hidden", "");
      return;
    }
    // Phase 7 M27 — show the role-picker step. The encounter list
    // remains hidden until the student picks 'bedside'.
    const stepRole = $("step-role");
    if (stepRole) stepRole.hidden = false;
    $("step-encounter")?.setAttribute("hidden", "");
    setStatus(`Welcome, ${chosenName}. Pick your role to continue.`);
  }

  function setStatus(text, isErr) {
    const el = $("join-status");
    if (!el) return;
    if (!text) {
      el.hidden = true;
      el.textContent = "";
      el.className = "join-status";
      return;
    }
    el.hidden = false;
    el.textContent = text;
    el.className = "join-status" + (isErr ? " err" : "");
  }

  // Roster card click — pre-populates the name input + advances.
  document.querySelectorAll(".roster-card").forEach((card) => {
    card.addEventListener("click", () => {
      document.querySelectorAll(".roster-card").forEach(c => c.classList.toggle("active", c === card));
      const name = card.dataset.name || "";
      const sid  = card.dataset.studentId || "";
      const inp  = $("display-name");
      if (inp) inp.value = name;
      commitName(name, sid);
    });
  });

  // Free-form name input — commit on Enter or blur with content.
  const nameInput = $("display-name");
  if (nameInput) {
    nameInput.addEventListener("keydown", (ev) => {
      if (ev.key === "Enter") {
        ev.preventDefault();
        // Typing a new name clears any selected roster card; that's a new
        // student row, not a reattach to an existing one.
        document.querySelectorAll(".roster-card.active").forEach(c => c.classList.remove("active"));
        commitName(nameInput.value, "");
      }
    });
    nameInput.addEventListener("blur", () => {
      if (nameInput.value.trim()) {
        document.querySelectorAll(".roster-card.active").forEach(c => c.classList.remove("active"));
        commitName(nameInput.value, "");
      }
    });
  }

  // Role card click — bedside reveals encounter picker; nurse_station
  // posts to /portal/students/register_nurse directly.
  document.querySelectorAll(".role-card").forEach((card) => {
    card.addEventListener("click", async () => {
      const role = card.dataset.role;
      chosenRole = role;
      document.querySelectorAll(".role-card").forEach(c =>
        c.classList.toggle("active", c === card));
      if (role === "bedside") {
        const stepEnc = $("step-encounter");
        if (stepEnc) stepEnc.hidden = false;
        setStatus(`OK ${chosenName}, pick a bed to start.`);
        return;
      }
      // Nurse station — direct POST + redirect.
      setStatus("Joining as Nursing Station…");
      const body = new FormData();
      body.append("room_code", cfg.roomCode || "");
      body.append("display_name", chosenName);
      if (chosenStudentId) body.append("existing_student_id", chosenStudentId);
      try {
        const r = await fetch("/portal/students/register_nurse",
                                {method: "POST", body});
        if (!r.ok) {
          let msg = `Join failed (${r.status}).`;
          try { const j = await r.json(); if (j && j.detail) msg = j.detail; }
          catch (_) {}
          setStatus(msg, true);
          return;
        }
        const data = await r.json();
        if (data.redirect_url) {
          setStatus("Connecting…");
          window.location = data.redirect_url;
        }
      } catch (err) {
        setStatus("Network error: " + err, true);
      }
    });
  });

  // Encounter card click — POST register + redirect.
  document.querySelectorAll(".encounter-card").forEach((card) => {
    card.addEventListener("click", async () => {
      const name = (nameInput?.value || chosenName || "").trim();
      if (!name) {
        setStatus("Type your name (or pick from the roster) before choosing a bed.", true);
        return;
      }
      // Lock the UI while we POST.
      document.querySelectorAll(".encounter-card").forEach(c => c.disabled = true);
      setStatus("Joining encounter…");

      const body = new FormData();
      body.append("room_code", cfg.roomCode || "");
      body.append("encounter_id", card.dataset.encounterId || "");
      body.append("display_name", name);
      if (chosenStudentId) body.append("existing_student_id", chosenStudentId);

      try {
        const r = await fetch("/portal/students/register", {
          method: "POST", body,
        });
        if (!r.ok) {
          let msg = `Join failed (${r.status}).`;
          try {
            const j = await r.json();
            if (j && j.detail) msg = j.detail;
          } catch (_) { /* not JSON */ }
          setStatus(msg, true);
          document.querySelectorAll(".encounter-card").forEach(c => c.disabled = false);
          return;
        }
        const data = await r.json();
        if (data.redirect_url) {
          setStatus("Connecting…");
          window.location = data.redirect_url;
        } else {
          setStatus("Unexpected response (no redirect_url).", true);
          document.querySelectorAll(".encounter-card").forEach(c => c.disabled = false);
        }
      } catch (err) {
        setStatus("Network error: " + err, true);
        document.querySelectorAll(".encounter-card").forEach(c => c.disabled = false);
      }
    });
  });
})();
