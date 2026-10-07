# Changelog

## 0.1.0 — first public release

- **`mig` CLI** driven by one `migration.yaml` per estate (GitHub + GitLab, public or private, local paths), with
  `init · validate · doctor · up · scan · plan · pr · approve · deny · status · outputs · stop · resume · eval · schedule · dashboard · skill`.
- **Runners**: `local` (Claude Code headless, one Docker container per run or directly on the host — works with a Claude
  subscription) and `managed` (Claude Managed Agents API). Same prompts, rubrics and report contracts in both.
- **Agents**: scanner (inventory, official versions, CVEs, code-located impact, real builds, cross-module order), planner
  (gated, reversible waves; proves the first code wave), PR agent (applies one wave, re-runs its gates). Each run is graded
  by an independent grader against a rubric, with fix-and-resubmit iterations.
- **Gated pull requests**: agents never get a write credential; `mig` pushes the branch and opens the GitHub PR / GitLab MR
  only after a human approves the diff; never merges.
- **Resilience**: runs paused by a Claude usage limit resume where they stopped.
- **Golden cases** (`mig eval`) tied to the scanner's config fingerprint.
- **Migration Control dashboard**: live flow, estate map, migration journey, decision deck, PR review and approval,
  narrated demo of your own recorded runs.
- **`/migrate` Claude Code skill** to set everything up from an interview.
