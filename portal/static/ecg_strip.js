// MEDSIM V7 Phase 7 — ECG strip renderer (M24).
//
// Renders a continuously scrolling SVG ECG strip in a target
// element. Used by both the M25 Per-Patient Console and the M27
// Nursing Station mini-strip.
//
// API:
//    ECGStrip.attach(element, {rhythm, height, secondsVisible})
//        Mounts a strip in `element`. `rhythm` is one of the
//        catalog entries from GET /api/ecg/catalog. Returns a
//        controller with .setRhythm(newRhythm) + .stop().

(function (global) {
  'use strict';

  function interpolateBeat(complex, samples) {
    // `complex` = array of [t, mV]. Linearly interpolate to `samples`
    // evenly-spaced points across one beat cycle.
    const out = new Float32Array(samples);
    let segIdx = 0;
    for (let i = 0; i < samples; i++) {
      const t = i / samples;
      while (segIdx < complex.length - 1 && complex[segIdx + 1][0] < t) {
        segIdx++;
      }
      const [t0, v0] = complex[segIdx];
      const [t1, v1] = complex[Math.min(segIdx + 1, complex.length - 1)];
      const span = (t1 - t0) || 1;
      const f = (t - t0) / span;
      out[i] = v0 + (v1 - v0) * f;
    }
    return out;
  }

  function buildPath(samples, width, height, leftPad) {
    // Map mV [-1.5 .. +1.5] to y [0 .. height]
    const yMid = height / 2;
    const vScale = (height / 2) / 1.5;
    let d = '';
    for (let i = 0; i < samples.length; i++) {
      const x = leftPad + (i / samples.length) * width;
      const y = yMid - samples[i] * vScale;
      d += (i === 0 ? 'M' : 'L') + x.toFixed(1) + ',' + y.toFixed(1) + ' ';
    }
    return d;
  }

  function attach(container, opts) {
    const height = opts.height || 110;
    const secondsVisible = opts.secondsVisible || 6;
    let rhythm = opts.rhythm || null;
    let stopped = false;

    container.innerHTML = '';
    const svg = document.createElementNS('http://www.w3.org/2000/svg', 'svg');
    svg.setAttribute('viewBox', `0 0 100 ${height}`);
    svg.setAttribute('preserveAspectRatio', 'none');
    svg.style.width = '100%';
    svg.style.height = height + 'px';
    container.appendChild(svg);

    // M48 — Thinner stroke + muted color so the trace doesn't look
    // like it's glowing.  Pre-M48 was a saturated neon `#5dffae` at
    // 1.4 stroke; at the small ECG-canvas size that read as a
    // halo.  Softer green at 0.7 stroke matches real bedside
    // monitor traces.
    const path = document.createElementNS('http://www.w3.org/2000/svg', 'path');
    path.setAttribute('stroke', '#7fc99a');
    path.setAttribute('stroke-width', '0.7');
    path.setAttribute('fill', 'none');
    svg.appendChild(path);

    const label = document.createElementNS('http://www.w3.org/2000/svg', 'text');
    label.setAttribute('x', '2');
    label.setAttribute('y', '12');
    label.setAttribute('fill', '#7fc99a');
    label.setAttribute('font-size', '8');
    label.setAttribute('font-family', 'SF Mono, Menlo, Consolas, monospace');
    svg.appendChild(label);

    function tick() {
      if (stopped || !rhythm) {
        path.setAttribute('d', '');
        if (rhythm) label.textContent = rhythm.label;
        if (!stopped) requestAnimationFrame(tick);
        return;
      }
      // Compute how many beats fit in the visible window.
      const rate = rhythm.default_rate || 60;
      // For asystole / vfib, draw something distinguishable without
      // dividing by zero.
      const beatsVisible = Math.max(1, (rate / 60) * secondsVisible);
      const samplesPerBeat = 60;
      const totalSamples = Math.ceil(beatsVisible * samplesPerBeat);
      const t0 = Date.now() / 1000;
      // Phase: scroll the strip by advancing the start sample over time.
      const samples = new Float32Array(totalSamples);
      const beat = interpolateBeat(rhythm.complex || [[0, 0], [1, 0]],
                                    samplesPerBeat);
      const noise = rhythm.noise || 0;
      const irregularity = rhythm.irregularity || 0;
      let beatLenJitter = irregularity
        ? (1 + ((Math.sin(t0 * 1.3) + Math.cos(t0 * 2.1)) / 2) * irregularity)
        : 1;
      const phaseOffset = (t0 * (rate / 60)) % 1;
      for (let i = 0; i < totalSamples; i++) {
        const beatT = ((i / samplesPerBeat) + phaseOffset * beatLenJitter) % 1;
        const beatIdx = Math.floor(beatT * samplesPerBeat) % samplesPerBeat;
        let v = beat[beatIdx];
        if (noise) v += (Math.random() - 0.5) * 2 * noise;
        // Special-case VFib: keep waveform chaotic, ignore strict cycle.
        if (rhythm.id === 'vfib') {
          v = (Math.random() - 0.5) * 2 * 1.0;
        }
        // Asystole: flatline ± noise.
        if (rhythm.id === 'asystole') {
          v = (Math.random() - 0.5) * 2 * noise;
        }
        samples[i] = v;
      }
      const width = 100;
      path.setAttribute('d', buildPath(samples, width, height, 0));
      label.textContent = rhythm.label;
      requestAnimationFrame(tick);
    }
    tick();

    return {
      setRhythm(next) { rhythm = next; },
      stop()          { stopped = true; },
    };
  }

  global.ECGStrip = { attach };
})(window);
