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
import { lookupMesh } from '@utils/resource_registry';

/** Minimal shape of what the live-diagnostic reads off the attached mesh. */
interface MeshLike {
  geometry?: {
    userData?: Record<string, unknown>;
    getAttribute?(name: string): { count: number; array?: ArrayLike<number> } | undefined;
    morphAttributes?: { position?: ReadonlyArray<unknown> };
  };
  morphTargetInfluences?: ReadonlyArray<number>;
  material?: { type?: string };
}

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

  const diagEl = document.createElement('div');
  diagEl.className = 'meta';
  diagEl.style.cssText = 'font-size:10px;margin-top:6px;opacity:.75;line-height:1.5;white-space:pre-line';

  wrap.append(title, selRow, sliderRow, metaRow, btnRow, diagEl);
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

  // Live diagnostic — localizes a "nothing moves" issue. Reads the attached mesh
  // (snapshot().attached is the public API) and shows: is a mesh attached, is it
  // the 468 baked topology, does the shape resolve to a morph index, and is its
  // influence actually being written each tick. If `infl` tracks the slider but
  // the face is still, the break is rendering — not the data path.
  const updateDiag = (): void => {
    const ids = anim.snapshot().attached;
    const mesh = ids.length ? (lookupMesh(ids[0]!) as unknown as MeshLike | undefined) : undefined;
    const name = names[idx] ?? '';
    if (!mesh) { diagEl.textContent = `attached: ${ids.length} — no mesh resolved`; return; }
    const vtx = mesh.geometry?.getAttribute?.('position')?.count ?? '?';
    const morphAttrs = mesh.geometry?.morphAttributes?.position?.length ?? 0;
    const mnames = mesh.geometry?.userData?.['morphTargetNames'];
    const mi = Array.isArray(mnames) ? mnames.indexOf(name) : -1;
    const infl = mesh.morphTargetInfluences;
    const iv = mi >= 0 && infl ? (infl[mi] ?? 0).toFixed(2) : 'n/a';
    // Framing telemetry: camera distance (frameAvatar sets this — initial is 2.0)
    // + the actual window size, to tell "frameAvatar didn't run" from "small window".
    const vrai = (window as unknown as { __vrai?: { camera?: { position?: { z?: number } } } }).__vrai;
    const camZ = vrai?.camera?.position?.z;
    const camStr = typeof camZ === 'number' ? camZ.toFixed(2) : 'n/a (need ?diag=1)';
    // Geometry bounding box (base positions) — to compare the mesh extent against
    // the visibly-textured face. If box >> visible face, framing the box leaves the
    // face small even at high FRAME_FILL.
    const pos = mesh.geometry?.getAttribute?.('position');
    let boxStr = 'box ?';
    if (pos?.array) {
      let nx = Infinity, xx = -Infinity, ny = Infinity, xy = -Infinity, nz = Infinity, xz = -Infinity;
      const a = pos.array;
      for (let i = 0; i < pos.count; i += 1) {
        const x = a[i * 3]!, y = a[i * 3 + 1]!, z = a[i * 3 + 2]!;
        if (x < nx) nx = x; if (x > xx) xx = x;
        if (y < ny) ny = y; if (y > xy) xy = y;
        if (z < nz) nz = z; if (z > xz) xz = z;
      }
      boxStr = `box ${(xx - nx).toFixed(2)}x${(xy - ny).toFixed(2)}x${(xz - nz).toFixed(2)}`;
    }
    diagEl.textContent =
      `mesh ${vtx}v · ${morphAttrs} morphs · ${mesh.material?.type ?? '?'}\n`
      + `"${name}" idx ${mi} · infl ${iv}\n`
      + `cam z ${camStr} · ${boxStr} · win ${window.innerWidth}x${window.innerHeight}`;
  };
  const diagTimer = window.setInterval(updateDiag, 200);
  updateDiag();

  refresh();

  return () => {
    window.clearInterval(diagTimer);
    anim.setEmotion({}, 0);
    wrap.remove();
  };
}
