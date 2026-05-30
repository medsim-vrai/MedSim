// "Develop the face from an image" — a top-of-screen control that lets the
// facilitator import a portrait and rebuild the avatar from it. On pick it
// hands the File to `onPick`; main.ts wires that to face_ingest → mesh_builder
// → renderer (replacing the current avatar). Status text reflects progress so
// a slow build (MediaPipe + geometry) doesn't look frozen.

export interface ImportControlHandle {
  dispose(): void;
}

const STYLE_ID = 'vrai-import-style';
const STYLE_CSS = `
.vrai-import {
  position: fixed;
  left: 50%;
  top: max(18px, env(safe-area-inset-top));
  transform: translateX(-50%);
  display: flex;
  align-items: center;
  gap: 10px;
  padding: 10px 14px;
  border-radius: 24px;
  background: rgba(20, 20, 24, 0.78);
  backdrop-filter: blur(12px);
  -webkit-backdrop-filter: blur(12px);
  color: #fff;
  font: 14px -apple-system, system-ui, sans-serif;
  z-index: 50;
  user-select: none; -webkit-user-select: none;
  touch-action: manipulation;
}
.vrai-import button {
  min-height: 44px; padding: 0 16px;
  border: none; border-radius: 14px;
  background: rgba(255,255,255,0.12); color: #fff;
  font-size: 15px; cursor: pointer;
}
.vrai-import button:active { background: rgba(255,255,255,0.22); }
.vrai-import button[disabled] { opacity: 0.5; cursor: default; }
.vrai-import .vrai-import-status { font-size: 12px; opacity: 0.75; min-width: 0; }
.vrai-import .vrai-import-status.err { color: #ff9b9b; opacity: 1; }
`;

function ensureStyle(): void {
  if (document.getElementById(STYLE_ID)) return;
  const s = document.createElement('style');
  s.id = STYLE_ID;
  s.textContent = STYLE_CSS;
  document.head.appendChild(s);
}

/**
 * Mount the import control. `onPick` rebuilds the avatar from the chosen file
 * and resolves when done (or rejects on failure); the control shows progress
 * and re-enables itself afterward.
 */
export function mountImportControl(
  container: HTMLElement,
  onPick: (file: File) => Promise<void>,
): ImportControlHandle {
  ensureStyle();

  const panel = document.createElement('div');
  panel.className = 'vrai-import';
  panel.setAttribute('role', 'group');
  panel.setAttribute('aria-label', 'Import face image');

  const button = document.createElement('button');
  button.type = 'button';
  button.textContent = '📷 Import face';

  const status = document.createElement('span');
  status.className = 'vrai-import-status';

  const input = document.createElement('input');
  input.type = 'file';
  input.accept = 'image/*';
  input.style.display = 'none';

  panel.append(button, status, input);
  container.appendChild(panel);

  function setStatus(msg: string, isErr = false): void {
    status.textContent = msg;
    status.classList.toggle('err', isErr);
  }

  const onClick = (): void => { if (!button.disabled) input.click(); };

  const onChange = (): void => {
    const file = input.files?.[0];
    input.value = ''; // allow re-picking the same file
    if (!file) return;
    button.disabled = true;
    setStatus('Building…');
    void onPick(file)
      .then(() => setStatus('Loaded ✓'))
      .catch((e: unknown) => {
        setStatus(e instanceof Error ? e.message : 'Import failed', true);
      })
      .finally(() => { button.disabled = false; });
  };

  button.addEventListener('click', onClick);
  input.addEventListener('change', onChange);

  return {
    dispose() {
      button.removeEventListener('click', onClick);
      input.removeEventListener('change', onChange);
      panel.remove();
    },
  };
}
