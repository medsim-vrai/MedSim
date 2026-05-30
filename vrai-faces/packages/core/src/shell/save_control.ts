// "Save skin" — pushes the current avatar face to the portal's skin library
// (POST ${apiBase}/api/face/skins), so a developed face can be saved + labeled
// from inside the app and later assigned to characters. Only mounted when the
// app was launched with ?api= (a portal to save to). CORS on the portal allows
// this cross-origin POST.

export interface SaveControlHandle {
  dispose(): void;
}

const STYLE_ID = 'vrai-save-style';
const STYLE_CSS = `
.vrai-save {
  position: fixed;
  /* Top-centre, directly under the Import control — an obvious, fixed home that
     never collides with the diagnostics panel (top-right) or the slider. */
  left: 50%;
  top: calc(74px + env(safe-area-inset-top, 0px));
  transform: translateX(-50%);
  display: flex; align-items: center; gap: 8px;
  padding: 10px 14px; border-radius: 22px;
  background: rgba(20, 20, 24, 0.82);
  backdrop-filter: blur(12px); -webkit-backdrop-filter: blur(12px);
  color: #fff; font: 14px -apple-system, system-ui, sans-serif;
  z-index: 50; user-select: none; -webkit-user-select: none;
  box-shadow: 0 4px 16px rgba(0,0,0,0.35);
}
.vrai-save input[type="text"] {
  width: 160px; height: 40px; padding: 0 10px;
  border: 1px solid rgba(255,255,255,0.18); border-radius: 10px;
  background: rgba(255,255,255,0.06); color: #fff; font-size: 14px;
}
.vrai-save button {
  height: 40px; padding: 0 14px; border: none; border-radius: 12px;
  background: rgba(255,255,255,0.12); color: #fff; font-size: 14px; cursor: pointer;
}
.vrai-save button:active { background: rgba(255,255,255,0.22); }
.vrai-save button[disabled] { opacity: 0.5; cursor: default; }
.vrai-save .vrai-save-status { font-size: 12px; opacity: 0.8; }
.vrai-save .vrai-save-status.err { color: #ff9b9b; opacity: 1; }
`;

function ensureStyle(): void {
  if (document.getElementById(STYLE_ID)) return;
  const s = document.createElement('style');
  s.id = STYLE_ID;
  s.textContent = STYLE_CSS;
  document.head.appendChild(s);
}

function extFor(blob: Blob): string {
  return blob.type === 'image/jpeg' ? 'jpg'
    : blob.type === 'image/webp' ? 'webp'
    : blob.type === 'image/svg+xml' ? 'svg'
    : 'png';
}

export function mountSaveControl(
  container: HTMLElement,
  opts: { apiBase: string; getFace: () => Blob | null },
): SaveControlHandle {
  ensureStyle();

  const panel = document.createElement('div');
  panel.className = 'vrai-save';
  panel.setAttribute('role', 'group');
  panel.setAttribute('aria-label', 'Save skin');

  const label = document.createElement('input');
  label.type = 'text';
  label.maxLength = 80;
  label.placeholder = 'Skin label';
  label.setAttribute('aria-label', 'Skin label');

  const button = document.createElement('button');
  button.type = 'button';
  button.textContent = '💾 Save skin';

  const status = document.createElement('span');
  status.className = 'vrai-save-status';

  panel.append(label, button, status);
  container.appendChild(panel);

  function setStatus(msg: string, isErr = false): void {
    status.textContent = msg;
    status.classList.toggle('err', isErr);
  }

  const onClick = (): void => {
    const blob = opts.getFace();
    if (!blob) { setStatus('Import a face first', true); return; }
    const fd = new FormData();
    fd.append('label', label.value.trim() || 'Untitled skin');
    fd.append('image', blob, `skin.${extFor(blob)}`);
    button.disabled = true;
    setStatus('Saving…');
    void fetch(`${opts.apiBase.replace(/\/+$/, '')}/api/face/skins`, { method: 'POST', body: fd })
      .then(async (r) => {
        const j = (await r.json().catch(() => null)) as { ok?: boolean; label?: string } | null;
        if (r.ok && j?.ok) setStatus(`Saved “${j.label ?? label.value}” ✓`);
        else setStatus('Save failed', true);
      })
      .catch(() => setStatus('Save failed (portal unreachable)', true))
      .finally(() => { button.disabled = false; });
  };
  button.addEventListener('click', onClick);

  return {
    dispose() {
      button.removeEventListener('click', onClick);
      panel.remove();
    },
  };
}
