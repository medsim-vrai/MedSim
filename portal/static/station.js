// MEDSIM 2 — join page client. Loads available personas for a join code.

(function () {
  "use strict";
  const codeInput = document.getElementById("code-input");
  const personaSelect = document.getElementById("persona-select");
  const statusEl = document.getElementById("join-status");
  const btnJoin = document.getElementById("btn-join");
  if (!codeInput) return;

  async function loadPersonas() {
    const code = (codeInput.value || "").trim().toUpperCase();
    personaSelect.innerHTML = '<option value="">— enter a valid code —</option>';
    btnJoin.disabled = true;
    if (code.length < 4) { statusEl.textContent = ""; return; }
    statusEl.textContent = "Checking code…";
    try {
      // Public, code-scoped persona list — the join code is the access token
      // (no operator auth). Returns exactly the personas the instructor put in
      // this session/bed. (The old client hit the operator-only /api/personas,
      // which 401s for a public student and left this dropdown empty.)
      const res = await fetch(`/api/join/${encodeURIComponent(code)}/personas`).catch(() => null);
      if (res && res.ok) {
        const data = await res.json();
        const personas = data.personas || [];
        if (personas.length) {
          populate(personas);
          btnJoin.disabled = false;
        } else {
          statusEl.textContent = "No personas are assigned to this session yet — ask the operator.";
          personaSelect.innerHTML = '<option value="">— none assigned —</option>';
        }
      } else {
        statusEl.textContent = "That join code isn't active. Check the code on the control-room screen.";
        personaSelect.innerHTML = '<option value="">— invalid or expired code —</option>';
      }
    } catch (e) {
      statusEl.textContent = "Could not load personas. Try again or ask the operator.";
    }
  }

  function populate(personas) {
    personaSelect.innerHTML = '<option value="">— pick a persona —</option>';
    const groups = {};
    personas.forEach(p => {
      (groups[p.roleGroup] = groups[p.roleGroup] || []).push(p);
    });
    Object.keys(groups).sort().forEach(g => {
      const og = document.createElement("optgroup");
      og.label = g;
      groups[g].forEach(p => {
        const opt = document.createElement("option");
        opt.value = p.id;
        opt.textContent = `${p.id} — ${p.name} (${p.role})`;
        og.appendChild(opt);
      });
      personaSelect.appendChild(og);
    });
    statusEl.textContent = `Pick the persona you'll play. ${personas.length} available.`;
  }

  codeInput.addEventListener("input", () => {
    codeInput.value = codeInput.value.toUpperCase();
  });
  codeInput.addEventListener("change", loadPersonas);
  codeInput.addEventListener("blur", loadPersonas);
  if (codeInput.value) loadPersonas();
})();
