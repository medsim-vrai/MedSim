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
      // Probe by trying to fetch a (cached) personas list; for the join page
      // we use a lightweight endpoint that doesn't require auth: the code
      // itself is the access token. Here we just trust the user entered
      // a valid code and let them pick from the full 24-persona library
      // — server will reject on submit if the persona isn't in this session.
      const res = await fetch("/api/personas").catch(() => null);
      // /api/personas is auth-gated for the operator; without that, fall back
      // to a public allowed list. For v2 we show all 24 personas; server
      // validates persona is in session at submit time.
      if (res && res.ok) {
        const data = await res.json();
        populate(data.personas || []);
      } else {
        // Fallback: just show a generic message; user picks an ID
        statusEl.textContent = "Enter your assigned persona ID below, then submit.";
        personaSelect.innerHTML = '<option value="">— ask the operator for your persona ID —</option>';
      }
      btnJoin.disabled = false;
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
