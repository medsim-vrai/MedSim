// OffscreenCanvas renderer worker (Code Guide §3.3). Lives behind a
// feature detect — main thread falls back to in-page WebGPU/WebGL2 if
// `transferControlToOffscreen` isn't available.
//
// Wire protocol (kept tiny — main thread posts opaque commands):
//   { type: 'init',   canvas: OffscreenCanvas }
//   { type: 'resize', w: number, h: number }
//   { type: 'frame',  weights: Float32Array }     // 52 ARKit weights
//   { type: 'dispose' }

interface InitMsg    { type: 'init'; canvas: OffscreenCanvas }
interface ResizeMsg  { type: 'resize'; w: number; h: number }
interface FrameMsg   { type: 'frame'; weights: Float32Array }
interface DisposeMsg { type: 'dispose' }
type Msg = InitMsg | ResizeMsg | FrameMsg | DisposeMsg;

let canvas: OffscreenCanvas | null = null;

self.onmessage = (e: MessageEvent<Msg>) => {
  const m = e.data;
  switch (m.type) {
    case 'init':    canvas = m.canvas; break;
    case 'resize':  if (canvas) { canvas.width = m.w; canvas.height = m.h; } break;
    case 'frame':   /* real impl: forward weights to the three.js renderer */ break;
    case 'dispose': canvas = null; break;
  }
};
