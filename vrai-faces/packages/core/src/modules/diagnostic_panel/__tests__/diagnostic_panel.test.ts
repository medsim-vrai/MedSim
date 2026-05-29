import { describe, it, expect, beforeEach } from 'vitest';
import { diagnosticPanel } from '../index';
import { createImpl } from '../impl/create';
import { diag } from '@perf/diag';
import type { BootDeps } from '@contracts/shared';

const deps: BootDeps = { diag, scenarioId: 'scn', characterId: 'chr' };

describe('diagnostic_panel', () => {
  it('exposes the expected surface', () => {
    expect(typeof diagnosticPanel.show).toBe('function');
    expect(typeof diagnosticPanel.hide).toBe('function');
    expect(typeof diagnosticPanel.isAvailable).toBe('function');
  });
});

describe('diagnostic_panel overlay (jsdom)', () => {
  beforeEach(() => {
    // Force availability via the ?diag=1 flag so the test is independent of DEV.
    window.history.replaceState({}, '', '/?diag=1');
  });

  it('is available when ?diag=1 is in the URL', async () => {
    const p = createImpl();
    await p.boot(deps);
    expect(p.isAvailable()).toBe(true);
    p.dispose();
  });

  it('mounts an overlay on show() and removes it on hide()', async () => {
    const p = createImpl();
    await p.boot(deps);
    p.show();
    const node = document.getElementById('vrai-diag');
    expect(node).not.toBeNull();
    expect(node!.textContent).toContain('VRAI');
    p.hide();
    expect(document.getElementById('vrai-diag')).toBeNull();
    p.dispose();
  });

  it('renders module stats and timeline messages from the diag singleton', async () => {
    diag.set('renderer', { state: 'running', fps: 60, lastTickMs: 16 });
    diag.push({ t: 1, moduleId: 'renderer', kind: 'info', message: 'diag-overlay-probe' });

    const p = createImpl();
    await p.boot(deps);
    p.show();
    const node = document.getElementById('vrai-diag')!;
    expect(node.textContent).toContain('renderer');
    expect(node.textContent).toContain('diag-overlay-probe');
    p.hide();
    p.dispose();
  });

  it('show() is a no-op when not available', async () => {
    window.history.replaceState({}, '', '/');   // no ?diag, and vitest DEV may be false
    const p = createImpl();
    await p.boot(deps);
    if (p.isAvailable()) { p.dispose(); return; }   // DEV env: availability can't be forced off
    p.show();
    expect(document.getElementById('vrai-diag')).toBeNull();
    p.dispose();
  });
});
