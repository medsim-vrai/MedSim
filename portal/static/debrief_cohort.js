// MEDSIM V7 — cohort debrief UI (M15).
// PEARLS tab switching + commitments editor + save-notes round-trip.

(function () {
  'use strict';

  const cfg = window.COHORT_DEBRIEF || {};
  let commitments = (cfg.initialCommitments || []).slice();

  // ── Tab switching ─────────────────────────────────────────────────
  document.querySelectorAll('.pearls-tab').forEach((tab) => {
    tab.addEventListener('click', () => {
      const phase = tab.dataset.phase;
      document.querySelectorAll('.pearls-tab').forEach(t =>
        t.classList.toggle('active', t === tab));
      document.querySelectorAll('.pearls-panel').forEach(p =>
        p.classList.toggle('active', p.dataset.panel === phase));
    });
  });

  // ── Print ────────────────────────────────────────────────────────
  document.getElementById('btn-print')?.addEventListener('click', () => {
    // Open every collapsed encounter-facet so the print view is complete.
    document.querySelectorAll('details.encounter-facet').forEach(d => d.open = true);
    // Show every panel so all 6 tabs print in order.
    document.querySelectorAll('.pearls-panel').forEach(p => p.classList.add('active'));
    window.print();
  });

  // ── Reactions notes ──────────────────────────────────────────────
  const saveBtn = document.getElementById('save-notes');
  const noteStatus = document.getElementById('notes-status');
  saveBtn?.addEventListener('click', async () => {
    saveBtn.disabled = true;
    if (noteStatus) noteStatus.textContent = 'Saving…';
    const text = document.getElementById('reactions-notes')?.value || '';
    try {
      const r = await fetch(`/api/debrief/cohort/${encodeURIComponent(cfg.roomId)}/notes`, {
        method: 'POST', credentials: 'same-origin',
        headers: {'Content-Type': 'application/json'},
        body: JSON.stringify({
          reactions_notes: text,
          commitments: commitments,
        }),
      });
      if (!r.ok) {
        if (noteStatus) noteStatus.textContent = `Save failed (${r.status}).`;
      } else if (noteStatus) {
        noteStatus.textContent = `Saved ${new Date().toLocaleTimeString()}`;
      }
    } catch (err) {
      if (noteStatus) noteStatus.textContent = 'Network error: ' + err;
    } finally {
      saveBtn.disabled = false;
    }
  });

  // ── Commitments editor (Application phase) ────────────────────────
  function renderCommitments() {
    const list = document.getElementById('commitments-list');
    if (!list) return;
    list.innerHTML = commitments.map((c, i) =>
      `<li><span class="commitment-text">${escapeHTML(c)}</span>` +
      `<button type="button" class="commitment-remove" data-idx="${i}">✕</button></li>`
    ).join('');
    list.querySelectorAll('.commitment-remove').forEach(btn => {
      btn.addEventListener('click', () => {
        const idx = parseInt(btn.dataset.idx, 10);
        commitments.splice(idx, 1);
        renderCommitments();
      });
    });
  }
  function escapeHTML(s) {
    return String(s == null ? '' : s)
      .replace(/&/g, '&amp;').replace(/</g, '&lt;')
      .replace(/>/g, '&gt;').replace(/"/g, '&quot;');
  }
  document.getElementById('commitment-add')?.addEventListener('click', () => {
    const inp = document.getElementById('commitment-input');
    const text = (inp?.value || '').trim();
    if (!text) return;
    commitments.push(text);
    if (inp) inp.value = '';
    renderCommitments();
  });
  document.getElementById('commitment-input')?.addEventListener('keydown', (ev) => {
    if (ev.key === 'Enter') { ev.preventDefault();
      document.getElementById('commitment-add')?.click(); }
  });
  // Bind existing remove buttons rendered server-side.
  document.querySelectorAll('.commitment-remove').forEach(btn => {
    btn.addEventListener('click', () => {
      const idx = parseInt(btn.dataset.idx, 10);
      commitments.splice(idx, 1);
      renderCommitments();
    });
  });
})();
