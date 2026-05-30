# research/ — Gated-enhancement research briefs

Briefs for enhancements that would improve performance/fidelity but depend on
**gated sources or more complex systems not currently authorized** (paid/licensed
assets, heavier pipelines, external services).

## Why this exists (the strategy)
Rather than block the build or pull in an unauthorized dependency, we **capture the
research as a self-contained brief** here. Each brief defines the objective, why it's
gated, the research questions, evaluation criteria, deliverables, and how the result
re-enters the build. When the enhancement is later desired, the research runs quickly
in **Claude Cowork** (deep research), a go/no-go is decided, then it converts into an
ADR + a drop-in implementation. See `docs/ROADMAP.md` → "Research-driven enhancements".

## Briefs
| ID | Title | Gates | Status |
|----|-------|-------|--------|
| RB-001 | Real ARKit-52 blendshape rig (MediaPipe 468 topology) | Phase 1.2 | Open |
| RB-002 | On-device voice — name wake-word + trainee STT | Character devices (ADR-0024) | Open |

## Format
Each brief is authored as `RB-NNN_<slug>.html` (editable source) and rendered to
`RB-NNN_<slug>.pdf` (the Cowork-ready artifact) with the installed Playwright
chromium — no extra dependency:

```
node packages/core/scripts/render-pdf.mjs research/RB-NNN_<slug>.html research/RB-NNN_<slug>.pdf
```

## Lifecycle
1. Spot a gated/advanced enhancement → write a brief here (HTML → PDF).
2. When desired, run the brief in Claude Cowork (deep research) → recommendation + go/no-go.
3. Convert the decision into an ADR (`Memory_management.MD §7`) + implementation.
4. Mark the brief **Done** (link the ADR).
