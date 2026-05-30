// MEDSIM 2 — control-room wizard client.
// Drives the 5-step setup wizard: system check → scenario → curriculum
// context → characters → network. Each step has a "Continue" button that
// validates and reveals the next pane.

(function () {
  "use strict";

  const form = document.getElementById("control-form");
  if (!form) return;
  const panes = Array.from(form.querySelectorAll(".wiz-pane"));
  const steps = Array.from(document.querySelectorAll(".wizard-steps .step"));
  // V3 — step IDs are strings so we can have "2b" between "2" and "3".
  // V7 — additionally "4" (single-mode characters) and "4r" (room-mode
  // encounters) sit at the same logical position; only one is visible
  // at a time based on the mode toggle. We track the currently-active
  // sequence (with either 4 or 4r) and update it when mode flips.
  function buildSequence(mode) {
    return steps
      .filter(s => {
        if (s.dataset.stepSingle !== undefined) return mode === "single";
        if (s.dataset.stepRoom   !== undefined) return mode === "room";
        return true;
      })
      .map(s => String(s.dataset.step));
  }
  let mode = "single";
  let sequence = buildSequence(mode);
  let current = sequence[0] || "1";

  function showStep(id) {
    if (!sequence.includes(id)) return;
    current = id;
    panes.forEach(p => p.classList.toggle("active", String(p.dataset.pane) === current));
    steps.forEach(s => s.classList.toggle("active", String(s.dataset.step) === current));
    window.scrollTo({ top: 0, behavior: "smooth" });
  }

  function nextStep() { return sequence[Math.min(sequence.length - 1, sequence.indexOf(current) + 1)]; }
  function prevStep() { return sequence[Math.max(0, sequence.indexOf(current) - 1)]; }

  // ---- V7 mode toggle (single ↔ room of N) -----------------------------
  //
  // M32 — In room mode the wizard skips Steps 2 / 2b / 3 entirely.
  // Those steps are single-patient defaults; each room-mode encounter row
  // authors its own scenario / EHR / curriculum inside Step 4r drawers.
  // The instructor's flow becomes: Step 1 (system check) → Step 4r
  // (per-bed authoring) → Step 5 (network launch).
  function applyMode(newMode) {
    mode = newMode;
    // Mode card visual state
    document.querySelectorAll(".mode-card").forEach(card => {
      card.classList.toggle("active", card.dataset.mode === mode);
    });
    // Step strip — hide single-only steps in room mode, room-only in single.
    steps.forEach(s => {
      if (s.dataset.stepSingle !== undefined) s.hidden = (mode !== "single");
      if (s.dataset.stepRoom   !== undefined) s.hidden = (mode !== "room");
    });
    // Panes — hide both off-mode pane categories. (M32 added
    // data-pane-single to panes 2 / 2b / 3 so they vanish in room mode.)
    panes.forEach(p => {
      if (p.dataset.paneSingle !== undefined) p.hidden = (mode !== "single");
      if (p.dataset.paneRoom   !== undefined) p.hidden = (mode !== "room");
    });
    // M32 — HTML5 'required' on single-mode fields would block the JS
    // submit handler in room mode (browser validation fires before
    // submit). Toggle 'required' on / off based on mode.
    form.querySelectorAll("[data-required-single]").forEach(el => {
      if (mode === "single") el.setAttribute("required", "");
      else                   el.removeAttribute("required");
    });
    // Rebuild the navigation sequence and jump to step 1 (a clean restart
    // avoids "current step disappeared" edge cases when toggling mid-flow).
    sequence = buildSequence(mode);
    if (mode === "room") renderRoomEncounterRows();
    refreshStepNumbers();
    showStep(sequence[0] || "1");
  }

  // M32 — renumber the visible step-strip labels based on their position
  // in the active sequence. So in room mode the strip reads
  // "1 · System check  ·  2 · Encounters  ·  3 · Network" instead of the
  // gappy "1 · System check  ·  2 · Encounters  ·  5 · Network".
  function refreshStepNumbers() {
    steps.forEach(s => {
      if (!s.dataset.labelBody) {
        // Cache the original label body once (everything after "N · ").
        const parts = s.textContent.split("·");
        s.dataset.labelBody = parts.slice(1).join("·").trim() || s.textContent.trim();
      }
    });
    sequence.forEach((stepId, i) => {
      const s = steps.find(x => String(x.dataset.step) === stepId);
      if (!s) return;
      s.textContent = `${i + 1} · ${s.dataset.labelBody}`;
    });
  }
  document.querySelectorAll('input[name="wizard_mode"]').forEach(input => {
    input.addEventListener("change", () => {
      if (input.checked) applyMode(input.value);
    });
  });
  applyMode("single");

  function renderRoomEncounterRows() {
    const host = document.getElementById("room-encounter-rows");
    const nInput = document.getElementById("room-n");
    if (!host || !nInput) return;
    const personas    = (window.MEDSIM2.personasForRoom || []);
    const ehrs        = (window.MEDSIM2.ehrIds || []);
    const activities  = (window.MEDSIM2.activitiesForRoom || []);
    const n = Math.max(2, Math.min(10, parseInt(nInput.value, 10) || 4));
    // Preserve any values the operator already filled in (including
    // any per-row scenario text + collapsed/expanded state).
    // M40 — Also capture the Characters + Curriculum drawer state
    // (which checkboxes are checked, program/week values) so a row
    // re-render (triggered by the room-N input changing) doesn't
    // wipe the operator's drawer selections.
    const prev = Array.from(host.querySelectorAll(".encounter-row")).map(row => ({
      label:        row.querySelector('[data-field="label"]')?.value || "",
      persona:      row.querySelector('[data-field="persona"]')?.value || "",
      ehr:          row.querySelector('[data-field="ehr"]')?.value || "",
      activity:     row.querySelector('[data-field="activity"]')?.value || "",
      scenarioText: row.querySelector('[data-field="scenario_text"]')?.value || "",
      scenarioOpen: !row.querySelector('.scenario-drawer')?.hidden,
      // M40 — drawer state
      personaList:  Array.from(
        row.querySelectorAll('[data-row-persona]:checked'),
      ).map(cb => cb.value),
      avatarList:   Array.from(
        row.querySelectorAll('[data-row-avatar]:checked'),
      ).map(cb => cb.value),
      modulesList:  Array.from(
        row.querySelectorAll('[data-row-module]:checked'),
      ).map(cb => cb.value),
      programId:    row.querySelector('[data-row-program]')?.value || "",
      week:         row.querySelector('[data-row-week]')?.value || "",
    }));
    host.innerHTML = "";
    for (let i = 0; i < n; i++) {
      const existing = prev[i] || {};
      const row = document.createElement("div");
      row.className = "encounter-row";
      const personaOpts = personas.map(p =>
        `<option value="${p.id}" ${existing.persona === p.id ? "selected" : ""}>${p.name} (${p.id} · ${p.role})</option>`
      ).join("");
      const ehrOpts = ehrs.map((e, idx) =>
        `<option value="${e.id}" ${(existing.ehr || (idx === 0 ? e.id : "")) === e.id ? "selected" : ""}>${e.name}</option>`
      ).join("");
      // V7 M12 — Activity picker. "(none)" is the default; picking
      // one fires the change handler below which pre-fills label,
      // persona, AND the row's scenario textarea.
      const activityOpts = ['<option value="">— (no activity) —</option>']
        .concat(activities.map(a =>
          `<option value="${a.activity_id}" ${existing.activity === a.activity_id ? "selected" : ""}>${a.label}</option>`
        )).join("");
      // Per-row scenario drawer — collapsed by default so the row
      // stays compact. The operator hits "Edit scenario" to expand
      // a textarea unique to this bed. If an Activity is picked, the
      // change handler fills the textarea with the activity's
      // scenario_text. Operator edits stack on top.
      const scenarioText = (existing.scenarioText || "")
        .replace(/&/g, "&amp;").replace(/</g, "&lt;");
      const drawerOpen = existing.scenarioOpen ||
                          (existing.scenarioText && existing.scenarioText.trim());
      // M31 — per-row Characters + Curriculum drawers (collapsed by
      // default). The persona drawer is a multi-select grid that
      // matches the single-patient Step 4 UX; curriculum drawer
      // mirrors Step 3 (program + week + modules). Each row's data is
      // stashed in data-* attributes so submit can pick it up.
      const personaCheckboxes = personas.map(p => {
        const checked = (existing.personaList || []).includes(p.id) ||
                          (existing.persona === p.id);
        const avatarOn = (existing.avatarList || []).includes(p.id);
        return `<label class="row-persona-card">
          <input type="checkbox" data-row-persona value="${p.id}" ${checked ? "checked" : ""}>
          <span><strong>${p.name}</strong> <span class="muted small">${p.id} · ${p.role}</span></span>
          <span class="row-persona-avatar" onclick="event.stopPropagation()"
                title="Open this character on a tablet with a VRAI Faces avatar"
                style="display:inline-flex;align-items:center;gap:4px;margin-left:auto;white-space:nowrap">
            <input type="checkbox" data-row-avatar value="${p.id}" ${avatarOn ? "checked" : ""}>
            <span class="muted small">🪞 avatar</span>
          </span>
        </label>`;
      }).join("");
      const allModules = (window.MEDSIM2.modulesForRoom || []);
      const moduleCheckboxes = allModules.map(m => {
        const checked = (existing.modulesList || []).includes(m.id);
        return `<label class="row-module-card">
          <input type="checkbox" data-row-module value="${m.id}" ${checked ? "checked" : ""}>
          <span><strong>${m.id}</strong> ${(m.title || m.id).replace(/</g, '&lt;')}
            <span class="muted small">${(m.nclexDomain || '').replace(/</g, '&lt;')}</span></span>
        </label>`;
      }).join("");
      const programs = (window.MEDSIM2.programsForRoom || []);
      const programOpts = ['<option value="">— wizard-wide program —</option>']
        .concat(programs.map(p =>
          `<option value="${p.id}" ${existing.programId === p.id ? "selected" : ""}>${p.label}</option>`
        )).join("");

      row.innerHTML = `
        <div class="encounter-row-main">
          <div class="row-num">${i + 1}</div>
          <select data-field="activity" title="Pre-fill from a saved activity">${activityOpts}</select>
          <input type="text" data-field="label" placeholder="Bed ${i + 1} — label"
                 value="${(existing.label || `Bed ${i + 1}`).replace(/"/g, '&quot;')}">
          <select data-field="persona" title="Primary patient persona">${personaOpts}</select>
          <select data-field="ehr">${ehrOpts}</select>
        </div>
        <div class="encounter-row-tabs">
          <button type="button" class="row-tab" data-toggle-scenario>
            ${drawerOpen ? '▾' : '✎'} Scenario
          </button>
          <button type="button" class="row-tab" data-toggle-characters>
            ▸ Characters
            <span class="row-tab-count" data-count-personas>${(existing.personaList || []).length || 1}</span>
          </button>
          <button type="button" class="row-tab" data-toggle-curriculum>
            ▸ Curriculum
            <span class="row-tab-count" data-count-modules>${(existing.modulesList || []).length}</span>
          </button>
        </div>
        <div class="scenario-drawer" ${drawerOpen ? '' : 'hidden'}>
          <label class="muted small">Bed-specific scenario text
            <textarea data-field="scenario_text" rows="3"
              placeholder="Free-form case for THIS bed. Leave blank to fall back to the activity's text OR the Step 3 general scenario.">${scenarioText}</textarea>
          </label>
          <p class="muted small">Tip: pick an Activity above to pre-fill, then edit. Cleared text falls back to the Step 3 general scenario.</p>
        </div>
        <div class="characters-drawer" hidden>
          <p class="muted small">Pick every persona this bed's scenario uses — patient (primary above) + family + staff. Tick 🪞 avatar to give that character a tablet face/device for this bed.</p>
          <div class="row-persona-grid">
            ${personaCheckboxes}
          </div>
        </div>
        <div class="curriculum-drawer" hidden>
          <p class="muted small">Optional per-bed curriculum override. Leave blank to use Step 3 wizard-wide values.</p>
          <div class="curriculum-row">
            <label class="small muted">Program
              <select data-row-program>${programOpts}</select>
            </label>
            <label class="small muted">Week
              <input type="number" data-row-week min="1" max="60"
                     value="${existing.week || ''}" placeholder="—">
            </label>
          </div>
          <p class="muted small" style="margin-top:8px">Modules (additive to Step 3 wizard-wide modules):</p>
          <div class="row-module-grid">
            ${moduleCheckboxes}
          </div>
        </div>
      `;
      host.appendChild(row);
    }
  }

  // Toggle handlers for the Characters + Curriculum drawers.
  document.addEventListener("click", (ev) => {
    const charBtn = ev.target.closest("[data-toggle-characters]");
    const currBtn = ev.target.closest("[data-toggle-curriculum]");
    if (!charBtn && !currBtn) return;
    const row = (charBtn || currBtn).closest(".encounter-row");
    if (!row) return;
    const sel = charBtn ? ".characters-drawer" : ".curriculum-drawer";
    const drawer = row.querySelector(sel);
    if (!drawer) return;
    drawer.hidden = !drawer.hidden;
    (charBtn || currBtn).innerHTML = drawer.hidden
      ? (charBtn ? '▸ Characters' : '▸ Curriculum')
      : (charBtn ? '▾ Characters' : '▾ Curriculum');
    // Re-append the count badge.
    const count = charBtn
      ? row.querySelectorAll('[data-row-persona]:checked').length
      : row.querySelectorAll('[data-row-module]:checked').length;
    const badge = document.createElement("span");
    badge.className = "row-tab-count";
    badge.textContent = count;
    (charBtn || currBtn).appendChild(badge);
  });

  // Update count badges on checkbox change.
  document.addEventListener("change", (ev) => {
    if (!ev.target.matches('[data-row-persona], [data-row-module]')) return;
    const row = ev.target.closest(".encounter-row");
    if (!row) return;
    const pCount = row.querySelectorAll('[data-row-persona]:checked').length;
    const mCount = row.querySelectorAll('[data-row-module]:checked').length;
    const pBadge = row.querySelector('[data-count-personas]');
    const mBadge = row.querySelector('[data-count-modules]');
    if (pBadge) pBadge.textContent = pCount || 1;
    if (mBadge) mBadge.textContent = mCount;
  });

  // Toggle the per-row scenario drawer.
  document.addEventListener("click", (ev) => {
    const btn = ev.target.closest("[data-toggle-scenario]");
    if (!btn) return;
    const row = btn.closest(".encounter-row");
    const drawer = row?.querySelector(".scenario-drawer");
    if (!drawer) return;
    drawer.hidden = !drawer.hidden;
    btn.textContent = drawer.hidden ? "✎ Edit scenario" : "▾ Hide scenario";
    if (!drawer.hidden) {
      drawer.querySelector("textarea")?.focus();
    }
  });

  // V7 M12 — Activity picker handler. When the operator selects an
  // activity for a row, pre-fill label + persona + scenario text
  // (the scenario text is stashed in a data attribute on the row,
  // since there's no per-row textarea — it gets carried into the
  // POST body in submitRoom).
  document.addEventListener("change", (ev) => {
    if (!ev.target || ev.target.dataset?.field !== "activity") return;
    const aid = ev.target.value;
    const row = ev.target.closest(".encounter-row");
    if (!aid || !row) {
      if (row) row.dataset.scenarioText = "";
      return;
    }
    const a = (window.MEDSIM2.activitiesForRoom || []).find(x => x.activity_id === aid);
    if (!a) return;
    // Stash for submit. dataset.scenarioText is the historical
    // fallback used when the row's textarea is empty; the textarea
    // (filled below) is the new authoritative per-row source.
    row.dataset.scenarioText  = a.scenario_text || "";
    row.dataset.activityId    = a.activity_id;
    row.dataset.chartMode     = a.default_chart_mode || "shared";
    row.dataset.seedModulesJson = JSON.stringify(a.seed_modules || []);
    // Pre-fill label + persona.
    const labelInput   = row.querySelector('[data-field="label"]');
    const personaInput = row.querySelector('[data-field="persona"]');
    if (labelInput   && !labelInput.value.trim().startsWith("Bed "))  {
      /* respect manual edits */
    } else if (labelInput) {
      labelInput.value = a.label;
    }
    if (personaInput && a.seed_persona_id) {
      const opt = Array.from(personaInput.options).find(o => o.value === a.seed_persona_id);
      if (opt) personaInput.value = a.seed_persona_id;
    }
    // Phase 7 follow-up — pre-fill the per-row scenario textarea
    // from the activity's scenario_text so the operator sees what
    // they'll send, and can edit on top. Only overwrites the
    // textarea if it's empty OR matches a prior activity's text —
    // i.e. it doesn't stomp on operator edits.
    const scenarioInput = row.querySelector('[data-field="scenario_text"]');
    if (scenarioInput) {
      const prevActivityText = row.dataset.lastActivityScenarioText || "";
      const isEmpty   = !scenarioInput.value.trim();
      const isUntouched = scenarioInput.value === prevActivityText;
      if (isEmpty || isUntouched) {
        scenarioInput.value = a.scenario_text || "";
      }
      row.dataset.lastActivityScenarioText = a.scenario_text || "";
    }
    // M40 — Mirror single-patient applySample(): pre-populate the
    // row's Characters + Curriculum drawer checkboxes from the
    // Activity's seed data. The previous M31 code stashed
    // seed_modules into a dataset for submit, but the drawer
    // checkboxes stayed empty — operators had to manually re-check
    // every module. Now they see the same auto-fill experience as
    // the single-patient Step 2 template picker.
    if (a.seed_persona_id) {
      const personaCb = row.querySelector(
        `[data-row-persona][value="${cssEscape(a.seed_persona_id)}"]`,
      );
      if (personaCb) personaCb.checked = true;
    }
    const seedModules = Array.isArray(a.seed_modules) ? a.seed_modules : [];
    if (seedModules.length) {
      const wantModules = new Set(seedModules);
      row.querySelectorAll('[data-row-module]').forEach(cb => {
        if (wantModules.has(cb.value)) cb.checked = true;
      });
    }
    // Refresh the tab-strip badge counts so the operator sees the
    // auto-fill landed (e.g. "Characters · 1", "Curriculum · 3").
    updateRowTabBadges(row);
  });

  // M40 — Small CSS.escape polyfill — persona IDs are like "P-014" so
  // selector-safe in practice, but stay defensive in case a future
  // catalog adds a non-identifier id.
  function cssEscape(s) {
    if (typeof CSS !== 'undefined' && CSS.escape) return CSS.escape(s);
    return String(s).replace(/([^a-zA-Z0-9_-])/g, "\\$1");
  }

  // M40 — Recompute and write the two tab-strip badge counts on a
  // row. Extracted so multiple call sites (Activity pick, checkbox
  // change, persona dropdown change) stay in sync.
  function updateRowTabBadges(row) {
    if (!row) return;
    const pCount = row.querySelectorAll('[data-row-persona]:checked').length;
    const mCount = row.querySelectorAll('[data-row-module]:checked').length;
    const pBadge = row.querySelector('[data-toggle-characters] .row-tab-count');
    const mBadge = row.querySelector('[data-toggle-curriculum] .row-tab-count');
    if (pBadge) pBadge.textContent = String(pCount);
    if (mBadge) mBadge.textContent = String(mCount);
  }

  // M40 — When the operator picks a different primary persona on
  // the row, auto-check that persona's Characters-drawer checkbox.
  // Mirrors how `applySample` in single mode keeps the persona list
  // and the persona dropdown in sync — the primary is always part
  // of the cast.
  document.addEventListener("change", (ev) => {
    if (!ev.target || ev.target.dataset?.field !== "persona") return;
    const row = ev.target.closest(".encounter-row");
    if (!row) return;
    const pid = ev.target.value;
    if (!pid) return;
    const cb = row.querySelector(
      `[data-row-persona][value="${cssEscape(pid)}"]`,
    );
    if (cb && !cb.checked) {
      cb.checked = true;
      updateRowTabBadges(row);
    }
  });

  document.addEventListener("change", (ev) => {
    if (ev.target && ev.target.id === "room-n") renderRoomEncounterRows();
  });

  form.querySelectorAll("[data-next]").forEach(btn => {
    btn.addEventListener("click", () => {
      if (!validateStep(current)) return;
      showStep(nextStep());
    });
  });
  form.querySelectorAll("[data-back]").forEach(btn => {
    btn.addEventListener("click", () => showStep(prevStep()));
  });

  function validateStep(id) {
    if (id === "2") {
      const name = form.elements.scenario_name.value.trim();
      if (!name) {
        alert("Scenario name required.");
        return false;
      }
    }
    if (id === "2b") {
      // V3 — at least one EHR radio must be selected. Pre-checked by default.
      const ehr = form.querySelector('input[name="ehr_id"]:checked');
      if (!ehr) {
        alert("Pick a records system before continuing.");
        return false;
      }
    }
    if (id === "4") {
      const picked = form.querySelectorAll('input[name="personas"]:checked').length;
      if (picked === 0) {
        if (!confirm("No personas selected. The session needs at least one. Go back and pick personas?")) {
          return false;
        }
        showStep("4");
        return false;
      }
    }
    if (id === "4r") {
      const rows = document.querySelectorAll("#room-encounter-rows .encounter-row");
      if (rows.length < 2) {
        alert("Room mode needs at least 2 encounters.");
        return false;
      }
      const blank = Array.from(rows).filter(r =>
        !(r.querySelector('[data-field="persona"]')?.value || "").trim()
      ).length;
      if (blank > 0) {
        alert(`${blank} encounter row(s) need a persona pick before continuing.`);
        return false;
      }
    }
    return true;
  }

  // ---- Step 1 — system check -------------------------------------------
  function check(id, label, value, ok) {
    const card = document.getElementById(id);
    if (!card) return;
    card.classList.add(ok ? "ok" : "warn");
    const p = card.querySelector("p");
    if (p) p.innerHTML = `<span class="badge ${ok ? 'ok' : 'warn'}">${label}</span>`;
  }
  const ua = navigator.userAgent;
  check("chk-browser", /Chrome|Chromium|Edg/.test(ua) ? "Chrome detected" : (/Safari/.test(ua) ? "Safari detected" : "Other"), null, true);
  const hasSR = !!(window.SpeechRecognition || window.webkitSpeechRecognition);
  check("chk-stt", hasSR ? "Web Speech API available" : "Not available", null, hasSR);
  const hasTTS = !!window.speechSynthesis;
  check("chk-tts", hasTTS ? "SpeechSynthesis available" : "Not available", null, hasTTS);
  const hostBound = !(/127\.0\.0\.1|localhost/.test(window.MEDSIM2.baseUrl));
  check("chk-host", hostBound ? "LAN-bound (mobile can reach)" : "Localhost only — mobile cannot join", null, hostBound);

  const micBtn = document.getElementById("btn-mic");
  if (micBtn) micBtn.addEventListener("click", async () => {
    try {
      await navigator.mediaDevices.getUserMedia({ audio: true });
      check("chk-mic", "Microphone OK", null, true);
    } catch (e) {
      check("chk-mic", "Permission denied", null, false);
    }
  });

  // ---- Step 2 — template picker ----------------------------------------
  const templateSelect = document.getElementById("template-select");
  const templateSummary = document.getElementById("template-summary");

  function applySample(s) {
    if (!s) return;
    form.elements.scenario_name.value = s.name || "";
    form.elements.scenario_notes.value = s.notes || "";
    form.elements.scenario_text.value = s.scenario_text || "";
    // program + week (populates the week select then sets value)
    if (s.program_id) {
      const progSel = document.getElementById("ctx-program");
      progSel.value = s.program_id;
      populateWeeks();
      if (s.week) {
        document.getElementById("ctx-week").value = String(s.week);
      }
    }
    // modules (use the sample list as ground truth — overrides week-derived set)
    const wantModules = new Set(s.modules || []);
    form.querySelectorAll('input[name="modules"]').forEach(cb => {
      cb.checked = wantModules.has(cb.value);
    });
    // personas
    const wantPersonas = new Set(s.personas || []);
    form.querySelectorAll('input[name="personas"]').forEach(cb => {
      cb.checked = wantPersonas.has(cb.value);
    });
    updatePersonaCount();
    templateSummary.textContent =
      `Loaded ${(s.personas || []).length} persona${(s.personas || []).length === 1 ? '' : 's'} · ` +
      `${(s.modules || []).length} module${(s.modules || []).length === 1 ? '' : 's'}` +
      (s.program_id ? ` · ${s.program_id}${s.week ? ' wk ' + s.week : ''}` : '') +
      '. Edit any field as needed.';
  }

  function applyV1(s) {
    if (!s) return;
    form.elements.scenario_name.value = s.name || "";
    const note = s.patient_summary
      ? `Imported from v1 scenario "${s.id}" — patient: ${s.patient_summary}. Pick personas and modules below to complete v2 setup.`
      : `Imported from v1 scenario "${s.id}". Pick personas and modules below.`;
    form.elements.scenario_notes.value = note;
    templateSummary.textContent =
      'v1 scenarios use the legacy character format — name and notes auto-filled. Add personas and modules manually.';
  }

  if (templateSelect) {
    templateSelect.addEventListener("change", () => {
      const value = templateSelect.value;
      if (!value) {
        templateSummary.textContent = "";
        return;
      }
      const sep = value.indexOf(":");
      const kind = value.slice(0, sep);
      const id = value.slice(sep + 1);
      if (kind === "sample") {
        const s = (window.MEDSIM2.samples || []).find(x => x.id === id);
        applySample(s);
      } else if (kind === "v1") {
        const s = (window.MEDSIM2.v1Scenarios || []).find(x => x.id === id);
        applyV1(s);
      }
    });
  }

  // ---- Step 3 — curriculum context -------------------------------------
  const programSel = document.getElementById("ctx-program");
  const weekSel = document.getElementById("ctx-week");
  const weekFocus = document.getElementById("ctx-week-focus");
  const moduleFilter = document.getElementById("ctx-module-filter");

  function populateWeeks() {
    const programs = window.MEDSIM2.programs || [];
    const prog = programs.find(p => p.id === programSel.value);
    weekSel.innerHTML = '<option value="">—</option>';
    if (!prog) {
      weekSel.disabled = true;
      weekFocus.textContent = "";
      return;
    }
    prog.weeks.forEach(w => {
      const opt = document.createElement("option");
      opt.value = w.week;
      opt.textContent = `Week ${w.week} · ${w.phase}`;
      weekSel.appendChild(opt);
    });
    weekSel.disabled = false;
  }
  function applyWeekModules() {
    const programs = window.MEDSIM2.programs || [];
    const prog = programs.find(p => p.id === programSel.value);
    if (!prog) return;
    const w = prog.weeks.find(x => String(x.week) === weekSel.value);
    if (!w) { weekFocus.textContent = ""; return; }
    weekFocus.textContent = w.focus + " — auto-checked modules: " + w.modules.join(", ");
    const wanted = new Set(w.modules);
    document.querySelectorAll('input[name="modules"]').forEach(cb => {
      cb.checked = wanted.has(cb.value);
    });
  }
  if (programSel) {
    programSel.addEventListener("change", () => { populateWeeks(); weekFocus.textContent = ""; });
    weekSel.addEventListener("change", applyWeekModules);
  }
  if (moduleFilter) moduleFilter.addEventListener("input", () => {
    const q = moduleFilter.value.toLowerCase();
    document.querySelectorAll(".module-row").forEach(row => {
      const hay = (row.dataset.id + " " + row.dataset.title + " " + row.dataset.domain).toLowerCase();
      row.style.display = hay.includes(q) ? "" : "none";
    });
  });

  // ---- Step 4 — persona filter & counter -------------------------------
  document.querySelectorAll(".role-tab").forEach(btn => {
    btn.addEventListener("click", () => {
      document.querySelectorAll(".role-tab").forEach(b => b.classList.remove("active"));
      btn.classList.add("active");
      const f = btn.dataset.filter;
      document.querySelectorAll("#persona-grid .persona-card").forEach(card => {
        card.style.display = (f === "all" || card.dataset.roleGroup === f) ? "" : "none";
      });
    });
  });
  function updatePersonaCount() {
    const n = form.querySelectorAll('input[name="personas"]:checked').length;
    const out = document.getElementById("personas-selected-count");
    if (out) out.textContent = n;
  }
  form.querySelectorAll('input[name="personas"]').forEach(cb => cb.addEventListener("change", updatePersonaCount));

  // ---- Step 5 — submit -------------------------------------------------
  // Single mode posts the form to /portal/control/start (v6 path 1:1).
  // Room mode collects per-encounter rows and JSON-POSTs to
  // /api/room/start (M4), landing the operator on /portal/room.
  async function submitSingle(result) {
    if (result) { result.textContent = "Starting session…"; result.className = "test-result"; }
    const fd = new FormData(form);
    // Strip room-mode field so the form doesn't carry it forward.
    fd.delete("wizard_mode");
    const res = await fetch("/portal/control/start", { method: "POST", body: fd });
    const data = await res.json();
    if (data.ok && data.redirect_url) {
      window.location = data.redirect_url;
      return;
    }
    if (result) { result.textContent = data.message || "Failed."; result.className = "test-result err"; }
  }

  async function submitRoom(result) {
    if (result) { result.textContent = "Starting room…"; result.className = "test-result"; }
    // M32 — Room label now comes from the dedicated input on Step 4r,
    // since Step 2 (Scenario) is hidden in room mode. Fall back to the
    // (now-hidden) scenario_name field if anyone wrote into it before
    // toggling, and finally to a generic label.
    const labelFromStep4r = (document.getElementById("room-label-input")?.value || "").trim();
    const labelFromStep2  = (form.elements.scenario_name?.value || "").trim();
    const label = labelFromStep4r || labelFromStep2 || "Room";
    const defaultChartMode = document.getElementById("room-chart-mode")?.value || "shared";
    const programId  = form.elements.program_id?.value || null;
    const weekStr    = form.elements.week?.value || "";
    const week       = weekStr && /^\d+$/.test(weekStr) ? parseInt(weekStr, 10) : null;
    const modules    = Array.from(form.querySelectorAll('input[name="modules"]:checked')).map(cb => cb.value);
    const scenarioText  = (form.elements.scenario_text?.value || "").trim();
    const scenarioNotes = (form.elements.scenario_notes?.value || "").trim();
    const defaultEhrId  = form.querySelector('input[name="ehr_id"]:checked')?.value || null;
    // V8 — avatar opt-in is PER ENCOUNTER in room mode: each bed's Characters
    // drawer has its own "🪞 avatar" checkbox per persona (data-row-avatar),
    // collected per-row below. The single-mode name="avatar_personas" grid is a
    // different finalize path (/portal/control/start) and must NOT be read here,
    // or every room bed would get an empty avatar list.

    const rows = Array.from(document.querySelectorAll("#room-encounter-rows .encounter-row"));
    if (rows.length < 2) {
      if (result) { result.textContent = "Need at least 2 encounters in Room mode."; result.className = "test-result err"; }
      return;
    }
    const encounters = rows.map((row, i) => {
      const rowLabel = (row.querySelector('[data-field="label"]')?.value || `Bed ${i + 1}`).trim();
      const persona  = row.querySelector('[data-field="persona"]')?.value || null;
      const ehr      = row.querySelector('[data-field="ehr"]')?.value || defaultEhrId;
      const activityId = row.querySelector('[data-field="activity"]')?.value || null;
      // M31 — per-row Characters multi-select + Curriculum overrides.
      // Patient persona is included first so legacy fields stay
      // populated for the v6-compat paths; family + staff personas
      // join the list.
      const rowPersonas = Array.from(
        row.querySelectorAll('[data-row-persona]:checked'),
      ).map(cb => cb.value);
      const rowAvatars = Array.from(
        row.querySelectorAll('[data-row-avatar]:checked'),
      ).map(cb => cb.value);
      const combinedPersonas = persona && !rowPersonas.includes(persona)
        ? [persona, ...rowPersonas]
        : (rowPersonas.length ? rowPersonas : (persona ? [persona] : []));
      const rowModulesPicked = Array.from(
        row.querySelectorAll('[data-row-module]:checked'),
      ).map(cb => cb.value);
      const rowProgram = row.querySelector('[data-row-program]')?.value || null;
      const rowWeekRaw = row.querySelector('[data-row-week]')?.value || "";
      const rowWeek    = rowWeekRaw && /^\d+$/.test(rowWeekRaw) ? parseInt(rowWeekRaw, 10) : null;
      // V7 M12 + Phase 7 per-row authoring — scenario_text resolution
      // priority (most-specific first):
      //   1. The row's textarea value (operator-typed for this bed).
      //   2. The activity-derived text stashed when an Activity was
      //      picked (preserved if the operator never edited).
      //   3. Step 3's free-form general scenario (wizard-wide
      //      fallback).
      const rowTextareaText = (row.querySelector('[data-field="scenario_text"]')?.value || "").trim();
      const rowScenarioText = rowTextareaText
                                || row.dataset.scenarioText
                                || scenarioText;
      let   rowModules      = modules;
      if (row.dataset.seedModulesJson) {
        try {
          const seed = JSON.parse(row.dataset.seedModulesJson);
          if (Array.isArray(seed) && seed.length) {
            rowModules = Array.from(new Set([...modules, ...seed]));
          }
        } catch (_) { /* malformed — ignore */ }
      }
      const rowChartMode = row.dataset.chartMode || defaultChartMode;
      // M31 — merge per-row module picks into the row's modules.
      if (rowModulesPicked.length) {
        rowModules = Array.from(new Set([...rowModules, ...rowModulesPicked]));
      }
      return {
        scenario_name:        rowLabel,
        scenario_notes:       scenarioNotes,
        program_id:           rowProgram || programId,
        week:                 rowWeek !== null ? rowWeek : week,
        modules:              rowModules,
        scenario_text:        rowScenarioText,
        ehr_id:               ehr,
        persona_id:           persona,
        patient_persona_id:   persona,
        personas:             combinedPersonas,
        avatar_personas:      combinedPersonas.filter(pid => rowAvatars.includes(pid)),
        chart_mode:           rowChartMode,
        label:                rowLabel,
        activity_id:          activityId || null,
      };
    });
    // Validate every row has a persona pick.
    const missing = encounters.filter(e => !e.persona_id).length;
    if (missing > 0) {
      if (result) { result.textContent = `${missing} encounter row(s) are missing a persona.`; result.className = "test-result err"; }
      return;
    }

    const res = await fetch("/api/room/start", {
      method:  "POST",
      headers: { "Content-Type": "application/json" },
      body:    JSON.stringify({ label, encounters }),
    });
    if (!res.ok) {
      const detail = await res.text();
      if (result) { result.textContent = `Room start failed (${res.status}). ${detail}`; result.className = "test-result err"; }
      return;
    }
    // Land on the charge-nurse dashboard.
    window.location = "/portal/room";
  }

  form.addEventListener("submit", async (e) => {
    e.preventDefault();
    const result = document.getElementById("start-result");
    try {
      if (mode === "room") await submitRoom(result);
      else await submitSingle(result);
    } catch (err) {
      if (result) { result.textContent = "Network error: " + err; result.className = "test-result err"; }
    }
  });

  // V8 — avatar skin picker in the Step-4 persona grid. Clicking a thumbnail
  // assigns that skin to the persona (persists immediately, same endpoint as the
  // Personas page), highlights it, and ticks "Use avatar". Delegated so it works
  // for every persona card. These are <button type=button>, so they never submit
  // the wizard form.
  document.addEventListener("click", async (e) => {
    const btn = e.target.closest(".avatar-skin-thumb");
    if (!btn) return;
    e.preventDefault();
    e.stopPropagation();
    const personaId = btn.dataset.persona;
    const skinId = btn.dataset.skin || "";
    const wrap = btn.closest(".avatar-skins");
    if (wrap) wrap.querySelectorAll(".avatar-skin-thumb").forEach((b) => b.classList.toggle("sel", b === btn));
    const esc = (window.CSS && CSS.escape) ? CSS.escape(personaId) : personaId;
    const cb = form.querySelector('input[name="avatar_personas"][value="' + esc + '"]');
    if (cb) cb.checked = !!skinId;
    try {
      const fd = new FormData();
      fd.append("skin_id", skinId);
      await fetch("/portal/personas/" + encodeURIComponent(personaId) + "/avatar", { method: "POST", body: fd });
    } catch (_) { /* UI already updated optimistically */ }
  });
})();
