// The single user-facing translucency control. ADR-0010 + §4 contract.
//
// Mounts as a fixed bottom-of-screen panel: range slider + numeric stepper +
// numeric input. Hit targets are ≥56px per ADR-0010. The container is
// expected to be the app shell DIV; the panel is appended to it.

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
  bottom: max(24px, env(safe-area-inset-bottom));
  transform: translateX(-50%);
  display: flex;
  align-items: center;
  gap: 12px;
  padding: 14px 18px;
  border-radius: 28px;
  background: rgba(20, 20, 24, 0.78);
  backdrop-filter: blur(12px);
  -webkit-backdrop-filter: blur(12px);
  color: #fff;
  font: 14px -apple-system, system-ui, sans-serif;
  z-index: 50;
  user-select: none;
  -webkit-user-select: none;
  touch-action: manipulation;
}
.vrai-tslider button {
  min-width: 56px; min-height: 56px;
  border: none; border-radius: 16px;
  background: rgba(255,255,255,0.10); color: #fff;
  font-size: 22px; cursor: pointer;
}
.vrai-tslider button:active { background: rgba(255,255,255,0.20); }
.vrai-tslider input[type="range"] {
  width: 220px; height: 56px;
  -webkit-appearance: none; appearance: none;
  background: transparent; cursor: pointer;
}
.vrai-tslider input[type="range"]::-webkit-slider-runnable-track {
  height: 6px; background: rgba(255,255,255,0.25); border-radius: 3px;
}
.vrai-tslider input[type="range"]::-webkit-slider-thumb {
  -webkit-appearance: none; appearance: none;
  width: 28px; height: 28px; border-radius: 14px;
  background: #fff; margin-top: -11px; box-shadow: 0 2px 6px rgba(0,0,0,0.3);
}
.vrai-tslider input[type="number"] {
  width: 72px; height: 56px;
  border: 1px solid rgba(255,255,255,0.18); border-radius: 12px;
  background: rgba(255,255,255,0.06); color: #fff;
  font-size: 18px; text-align: center;
}
.vrai-tslider .vrai-label { opacity: 0.7; font-size: 12px; }
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

export function mountTranslucencySlider(
  container: HTMLElement,
  materialId: string,
  initial = 1,
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
      panel.remove();
    },
  };
}
