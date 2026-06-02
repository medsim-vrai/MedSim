// Morph-target QA panel (RB-001 / ADR-0034 acceptance) — DEBUG-ONLY.
//
// main.ts dynamically imports + mounts this only when ?debug is set, so it is
// absent from the production bundle entirely. It steps through every ARKit-52
// shape and drives its weight 0->1 on the LIVE avatar (via the emotion channel,
// setEmotion(.,0)) so the morph deformation can be eyeballed — the way we catch
// ICT-FaceKit's documented FACS mislabels (e.g. confirm `mouthPucker` puckers and
// `mouthSmileLeft` lifts the correct corner). A subtle idle blink/sway may overlay;
// the shape at weight 1 dominates. `baked` tags which shapes carry a real delta vs
// which are flat (e.g. tongueOut, omitted from the bake).

import type { AnimationRuntimeModule } from '@contracts/animation_runtime';

const STYLE = `
.vrai-morphqa{position:fixed;left:12px;bottom:12px;z-index:60;width:250px;
  font:12px/1.4 -apple-system,system-ui,sans-serif;color:#eef;
  background:rgba(20,22,30,.82);backdrop-filter:blur(12px);-webkit-backdrop-filter:blur(12px);
  border:1px solid rgba(255,255,255,.12);border-radius:10px;padding:10px 12px;
  user-select:none;-webkit-user-select:none}
.vrai-morphqa h4{margin:0 0 8px;font-size:12px;font-weight:700;letter-spacing:.2px;opacity:.9}
.vrai-morphqa .row{display:flex;align-items:center;gap:6px;margin:6px 0}
.vrai-morphqa select{flex:1;min-width:0;background:#11131a;color:#eef;border:1px solid #333;
  border-radius:6px;padding:3px 4px;font:inherit}
.vrai-morphqa button{background:#2b2f3a;color:#eef;border:1px solid #444;border-radius:6px;
  padding:3px 8px;cursor:pointer;font:inherit}
.vrai-morphqa button:hover{background:#363b48}
.vrai-morphqa input[type=range]{flex:1;min-width:0}
.vrai-morphqa .meta{display:flex;justify-content:space-between;align-items:center;opacity:.85;font-size:11px;margin-top:4px}
.vrai-morphqa .tag{font-size:10px;font-weight:700;padding:1px 7px;border-radius:8px}
.vrai-morphqa .tag.baked{background:#1d4a2b;color:#bdf5cf}
.vrai-morphqa .tag.flat{background:#4a3a1d;color:#f5e3bd}
`;

/** Mount the QA panel. Returns a teardown that clears the pose + removes the DOM. */
export function mountMorphQaPanel(
  host: HTMLElement,
  anim: AnimationRuntimeModule,
  names: ReadonlyArray<string>,
  baked: ReadonlySet<string>,
): () => void {
  if (!document.getElementById('vrai-morphqa-style')) {
    const s = document.createElement('style');
    s.id = 'vrai-morphqa-style';
    s.textContent = STYLE;
    document.head.appendChild(s);
  }

  const wrap = document.createElement('div');
  wrap.className = 'vrai-morphqa';

  const title = document.createElement('h4');
  title.textContent = 'morph QA · RB-001';

  const selRow = document.createElement('div');
  selRow.className = 'row';
  const prev = document.createElement('button');
  prev.textContent = '◀';
  prev.title = 'previous shape';
  const sel = document.createElement('select');
  names.forEach((n, i) => {
    const o = document.createElement('option');
    o.value = String(i);
    o.textContent = n;
    sel.appendChild(o);
  });
  const next = document.createElement('button');
  next.textContent = '▶';
  next.title = 'next shape';
  selRow.append(prev, sel, next);

  const sliderRow = document.createElement('div');
  sliderRow.className = 'row';
  const slider = document.createElement('input');
  slider.type = 'range';
  slider.min = '0';
  slider.max = '1';
  slider.step = '0.01';
  slider.value = '1';
  const val = document.createElement('span');
  val.style.width = '30px';
  val.style.textAlign = 'right';
  sliderRow.append(slider, val);

  const metaRow = document.createElement('div');
  metaRow.className = 'meta';
  const idxLabel = document.createElement('span');
  const tag = document.createElement('span');
  metaRow.append(idxLabel, tag);

  const btnRow = document.createElement('div');
  btnRow.className = 'row';
  const reset = document.createElement('button');
  reset.textContent = 'reset (0)';
  reset.style.flex = '1';
  btnRow.append(reset);

  wrap.append(title, selRow, sliderRow, metaRow, btnRow);
  host.appendChild(wrap);

  let idx = 0;

  const apply = (): void => {
    const w = Number(slider.value);
    val.textContent = w.toFixed(2);
    const name = names[idx] ?? '';
    anim.setEmotion(w > 0 && name ? { [name]: w } : {}, 0);
  };
  const refresh = (): void => {
    sel.value = String(idx);
    idxLabel.textContent = `${idx + 1} / ${names.length}`;
    const isBaked = baked.has(names[idx] ?? '');
    tag.textContent = isBaked ? 'baked' : 'no delta';
    tag.className = `tag ${isBaked ? 'baked' : 'flat'}`;
    apply();
  };
  const step = (d: number): void => {
    idx = (idx + d + names.length) % names.length;
    slider.value = '1';
    refresh();
  };

  prev.addEventListener('click', () => step(-1));
  next.addEventListener('click', () => step(1));
  sel.addEventListener('change', () => { idx = Number(sel.value); slider.value = '1'; refresh(); });
  slider.addEventListener('input', apply);
  reset.addEventListener('click', () => { slider.value = '0'; apply(); });

  refresh();

  return () => {
    anim.setEmotion({}, 0);
    wrap.remove();
  };
}
