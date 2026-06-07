// The single user-facing translucency control. ADR-0010 + §4 contract.
//
// Mounts as a fixed bottom-of-screen panel: range slider + numeric stepper +
// numeric input, plus an optional small face-SIZE scaler on the right (drives
// renderer.setFrameFill). Compact build (~half the original footprint) so it
// stays out of the way during QA. The container is the app shell DIV.

import { shaderTranslucent } from '@modules/shader_translucent';

export interface TranslucencySliderHandle {
  setValue(level: number): void;
  getValue(): number;
  dispose(): void;
}

const STYLE_ID = 'vrai-translucency-style';
const STYLE_CSS = `
.vrai-tslider {
  position: fixed;
  left: 50%;
  bottom: max(16px, env(safe-area-inset-bottom));
  transform: translateX(-50%);
  display: flex;
  align-items: center;
  gap: 7px;
  padding: 7px 11px;
  border-radius: 16px;
  background: rgba(20, 20, 24, 0.78);
  backdrop-filter: blur(12px);
  -webkit-backdrop-filter: blur(12px);
  color: #fff;
  font: 12px -apple-system, system-ui, sans-serif;
  z-index: 50;
  user-select: none;
  -webkit-user-select: none;
  touch-action: manipulation;
}
.vrai-tslider button {
  min-width: 30px; min-height: 30px;
  border: none; border-radius: 9px;
  background: rgba(255,255,255,0.10); color: #fff;
  font-size: 16px; cursor: pointer; padding: 0;
}
.vrai-tslider button:active { background: rgba(255,255,255,0.20); }
.vrai-tslider input[type="range"] {
  width: 110px; height: 30px;
  -webkit-appearance: none; appearance: none;
  background: transparent; cursor: pointer;
}
.vrai-tslider input[type="range"].vrai-size { width: 80px; }
.vrai-tslider input[type="range"]::-webkit-slider-runnable-track {
  height: 4px; background: rgba(255,255,255,0.25); border-radius: 2px;
}
.vrai-tslider input[type="range"]::-webkit-slider-thumb {
  -webkit-appearance: none; appearance: none;
  width: 18px; height: 18px; border-radius: 9px;
  background: #fff; margin-top: -7px; box-shadow: 0 2px 6px rgba(0,0,0,0.3);
}
.vrai-tslider input[type="number"] {
  width: 44px; height: 30px;
  border: 1px solid rgba(255,255,255,0.18); border-radius: 8px;
  background: rgba(255,255,255,0.06); color: #fff;
  font-size: 13px; text-align: center;
}
.vrai-tslider .vrai-label { opacity: 0.7; font-size: 10px; }
.vrai-tslider .vrai-div {
  width: 1px; align-self: stretch; margin: 2px 1px;
  background: rgba(255,255,255,0.16);
}
`;

function ensureStyle(): void {
  if (document.getElementById(STYLE_ID)) return;
  const s = document.createElement('style');
  s.id = STYLE_ID;
  s.textContent = STYLE_CSS;
  document.head.appendChild(s);
}

function clamp01(v: number): number {
  return v < 0 ? 0 : v > 1 ? 1 : v;
}

/**
 * @param onSize     optional — wires a small face-size scaler (renderer.setFrameFill).
 * @param initialSize the renderer's current frame-fill (default 0.6).
 */
export function mountTranslucencySlider(
  container: HTMLElement,
  materialId: string,
  initial = 1,
  onSize?: (fill: number) => void,
  initialSize = 0.6,
): TranslucencySliderHandle {
  ensureStyle();
  let level = clamp01(initial);
  shaderTranslucent.setOpacity(materialId, level);

  const panel  = document.createElement('div');
  panel.className = 'vrai-tslider';
  panel.setAttribute('role', 'group');
  panel.setAttribute('aria-label', 'Translucency');

  const label = document.createElement('div');
  label.className = 'vrai-label';
  label.textContent = 'Translucency';

  const minus = document.createElement('button');
  minus.type = 'button'; minus.textContent = '−';
  minus.setAttribute('aria-label', 'Less translucent');

  const range = document.createElement('input');
  range.type = 'range'; range.min = '0'; range.max = '100'; range.step = '1';
  range.value = String(Math.round(level * 100));
  range.setAttribute('aria-label', 'Translucency slider');

  const plus = document.createElement('button');
  plus.type = 'button'; plus.textContent = '+';
  plus.setAttribute('aria-label', 'More translucent');

  const num = document.createElement('input');
  num.type = 'number'; num.min = '0'; num.max = '100'; num.step = '1';
  num.value = range.value;
  num.setAttribute('aria-label', 'Translucency percent');

  panel.append(label, minus, range, plus, num);

  // Optional face-SIZE scaler (renderer.setFrameFill, 0.3–1.6) — small, on the right.
  let sizeRange: HTMLInputElement | null = null;
  const onSizeInput = (): void => { if (sizeRange) onSize?.(Number(sizeRange.value)); };
  if (onSize) {
    const div = document.createElement('div');
    div.className = 'vrai-div';
    const sizeLabel = document.createElement('div');
    sizeLabel.className = 'vrai-label';
    sizeLabel.textContent = 'Size';
    sizeRange = document.createElement('input');
    sizeRange.type = 'range'; sizeRange.min = '0.3'; sizeRange.max = '1.6'; sizeRange.step = '0.05';
    sizeRange.value = String(initialSize);
    sizeRange.className = 'vrai-size';
    sizeRange.setAttribute('aria-label', 'Avatar size');
    sizeRange.addEventListener('input', onSizeInput);
    panel.append(div, sizeLabel, sizeRange);
  }

  container.appendChild(panel);

  function set(next: number): void {
    level = clamp01(next);
    shaderTranslucent.setOpacity(materialId, level);
    const pct = Math.round(level * 100);
    if (range.value !== String(pct)) range.value = String(pct);
    if (num.value !== String(pct))   num.value   = String(pct);
  }

  const onRange = (): void => set(Number(range.value) / 100);
  const onNum   = (): void => set(Number(num.value) / 100);
  const onMinus = (): void => set(level - 0.05);
  const onPlus  = (): void => set(level + 0.05);

  range.addEventListener('input', onRange);
  num.addEventListener('input', onNum);
  num.addEventListener('change', onNum);
  minus.addEventListener('click', onMinus);
  plus.addEventListener('click',  onPlus);

  return {
    setValue(v) { set(v); },
    getValue()  { return level; },
    dispose() {
      range.removeEventListener('input', onRange);
      num.removeEventListener('input', onNum);
      num.removeEventListener('change', onNum);
      minus.removeEventListener('click', onMinus);
      plus.removeEventListener('click',  onPlus);
      if (sizeRange) sizeRange.removeEventListener('input', onSizeInput);
      panel.remove();
    },
  };
}
