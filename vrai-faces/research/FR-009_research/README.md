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
- 2026-06-11 ~20:31 — run 2 launched. NOTE: the first (args-less) resume attempt had
  "completed" with an error, finalizing run 1's cache — so run 2 re-ran Search/Fetch LIVE,
  then entered Verify.
- 2026-06-11 ~20:49 — run 2 KILLED by a session interrupt mid-verify. Secured here:
  **62 verifier verdicts — 62 upheld, 0 refuted** (run2_verdicts.jsonl/.md; journal snapshot
  refreshed to include them). Every claim examined survived adversarial verification; the
  3-vote protocol still needs the remaining votes + synthesis for formal closure.
- 2026-06-12 morning — run 3 (resume): cache-replayed prior votes, completed the framework
  cluster: **9 claims CONFIRMED 3–0** (AHRQ MHS IV I-PASS-moderate/SBAR-low + profession split
  ×2 sources · JAN 2025 Swiss nursing I-PASS pilot ×2 · NEW 2026 scoping review of I-PASS in
  NURSE handovers ×2 incl. quantitative outcomes) before the next usage cap (resets 1:50pm).
  Remaining ~16 claims: every vote cast upholds them, formally short of the 3-vote protocol.
  **Zero refutations across all passes.** Full output: run3_2026-06-12_full-output.json.
- 2026-06-12 afternoon — run 4 (post-window resume): **20/25 confirmed at full protocol,
  2 refuted 0–3 (the excluded IJGHR source), 3 stranded by the next quota window** — then
  closed by DIRECT source verification (all nine facts quote-confirmed). **VERIFICATION
  COMPLETE.** Deliverables revised to final: quantified perception gap (8.1 vs 7.1), receiver
  read-back mandate + named observation tools, training-effectiveness source [11], instrument
  rows marked ✓. See run2_verdicts.md for the final record.
