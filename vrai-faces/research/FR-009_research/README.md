# FR-009 Deep-Research Durability Pack

Everything needed to CONTINUE or AUDIT the shift-handoff research regardless of what happens
to any running session. Created 2026-06-11 after the volatile /tmp output of run 1 was lost
to cleanup (recovered from the session context into `run1_2026-06-12_claims-and-sources.md`).

## Contents
- `run1_2026-06-12_claims-and-sources.md` — the durable evidence base: 25 verification-target
  claims with sources + the full 22-source fetch set + run stats. Run 1 verification DID NOT
  complete (usage cap) — treat claims as unverified extractions until run 2 lands.
- `deep-research-script.js` — the exact workflow script (verifier prompt carries the
  "verification pass 2" cache-bust marker).
- `wf_82632781-47e_journal-snapshot.tar.gz` — compressed snapshot of the workflow journal
  (the resume cache: search/fetch agent results). Restores cached-prefix resume if the
  live journal is ever cleaned.
- `run2_*.{json,log}` — run-2 verification results (written when the run completes/stops).

## How to resume / re-run verification (any future session)
1. Live journal (preferred): if
   `~/.claude/projects/<this-project>/<session>/subagents/workflows/wf_82632781-47e/` exists,
   invoke:
   `Workflow({ scriptPath: <copy of deep-research-script.js>, resumeFromRunId: "wf_82632781-47e", args: <the research question — full text in run1 md / the script's QUESTION> })`
   Search/Fetch replay from cache; only Verify + Synthesize run live.
2. Journal lost: untar the snapshot back to that path, then resume as above.
3. Worst case: re-run fresh with the same args (full re-search, ~15 min, ~1M subagent tokens).

## Status log
- 2026-06-11 ~16:45 — run 1: search/fetch complete (22 sources, 109 claims); verification
  killed by session usage cap (resets 8:20pm); all 25 claims 3-abstain.
- 2026-06-11 ~20:31 — run 2 launched (resume + cache-busted verifier): Search/Fetch cached,
  Verify running live. Result lands in run2 files here + the FR-009 PDF gets revised per
  verdicts (the standing instruction: modify deliverables based on the review).
