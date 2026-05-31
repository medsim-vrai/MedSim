// Generate the PWA / home-screen icons by rasterizing a branded HTML icon with
// the already-installed Playwright chromium (no extra dependency — same approach
// as render-pdf.mjs). The icon echoes the avatar: a translucent face with a soft
// Fresnel rim on a dark ground.
//
// Run from packages/core:
//   node scripts/make-icons.mjs [outDir=public]
//
// Writes: icon-192.png, icon-512.png, icon-maskable-512.png, apple-touch-icon.png

import { chromium } from '@playwright/test';
import { resolve } from 'node:path';
import { mkdirSync } from 'node:fs';

const OUT = resolve(process.argv[2] || 'public');
mkdirSync(OUT, { recursive: true });

/** Branded icon at `size` px; `pad` is the maskable safe-zone fraction per side. */
function iconHtml(size, pad) {
  const inner = Math.round(size * (1 - pad * 2));
  const headW = Math.round(inner * 0.62);
  const headH = Math.round(inner * 0.78);
  const eye = Math.max(2, Math.round(inner * 0.05));
  const rim = Math.round(size * 0.06);
  const sheen = Math.round(size * 0.05);
  const mouthW = Math.round(inner * 0.22);
  const mouthH = Math.round(inner * 0.1);
  const mouthB = Math.max(1, Math.round(size * 0.012));
  return `<!doctype html><html><head><meta charset="utf-8"><style>
    html,body{margin:0;padding:0}
    .bg{width:${size}px;height:${size}px;display:flex;align-items:center;justify-content:center;
        background:radial-gradient(120% 120% at 50% 35%, #16243f 0%, #0b0f1a 72%);}
    .head{width:${headW}px;height:${headH}px;
        border-radius:50% 50% 48% 48% / 55% 55% 45% 45%;
        background:radial-gradient(62% 56% at 50% 42%,
            rgba(243,214,184,0.96) 0%, rgba(214,169,134,0.88) 55%, rgba(120,150,200,0.28) 100%);
        box-shadow:0 0 ${rim}px rgba(150,190,255,0.55), inset 0 0 ${sheen}px rgba(255,255,255,0.28);
        position:relative;}
    .eye{position:absolute;width:${eye}px;height:${eye}px;border-radius:50%;background:#191921;top:42%;}
    .eye.l{left:32%}.eye.r{right:32%}
    .mouth{position:absolute;left:50%;top:63%;transform:translateX(-50%);
        width:${mouthW}px;height:${mouthH}px;
        border-bottom:${mouthB}px solid rgba(120,60,50,0.8);border-radius:0 0 60% 60%;}
  </style></head><body>
    <div class="bg"><div class="head"><span class="eye l"></span><span class="eye r"></span><span class="mouth"></span></div></div>
  </body></html>`;
}

const targets = [
  { name: 'icon-192.png', size: 192, pad: 0.06 },
  { name: 'icon-512.png', size: 512, pad: 0.06 },
  { name: 'icon-maskable-512.png', size: 512, pad: 0.16 }, // content inside the central safe zone
  { name: 'apple-touch-icon.png', size: 180, pad: 0.0 },   // iOS rounds + frames it itself
];

const browser = await chromium.launch();
try {
  for (const t of targets) {
    const page = await browser.newPage({ viewport: { width: t.size, height: t.size }, deviceScaleFactor: 1 });
    await page.setContent(iconHtml(t.size, t.pad), { waitUntil: 'load' });
    await page.screenshot({ path: resolve(OUT, t.name), clip: { x: 0, y: 0, width: t.size, height: t.size } });
    await page.close();
    console.log('wrote', t.name);
  }
} finally {
  await browser.close();
}
