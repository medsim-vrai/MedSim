// Render an HTML file to PDF using the already-installed Playwright chromium —
// no extra dependency (reportlab/weasyprint aren't available here). Used to
// produce the research briefs under vrai-faces/research/ from their HTML source.
//
// Run from packages/core (where @playwright/test resolves):
//   node scripts/render-pdf.mjs <input.html> <output.pdf>

import { chromium } from '@playwright/test';
import { resolve } from 'node:path';
import { pathToFileURL } from 'node:url';

const [inArg, outArg] = process.argv.slice(2);
if (!inArg || !outArg) {
  console.error('usage: node scripts/render-pdf.mjs <input.html> <output.pdf>');
  process.exit(1);
}

const browser = await chromium.launch();
try {
  const page = await browser.newPage();
  await page.goto(pathToFileURL(resolve(inArg)).href, { waitUntil: 'load' });
  await page.pdf({
    path: resolve(outArg),
    format: 'Letter',
    printBackground: true,
    margin: { top: '18mm', bottom: '18mm', left: '16mm', right: '16mm' },
  });
  console.log('wrote', resolve(outArg));
} finally {
  await browser.close();
}
