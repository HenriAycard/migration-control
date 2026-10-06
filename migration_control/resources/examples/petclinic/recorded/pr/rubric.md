# Rubric — wave pull request

Grade `/mnt/session/outputs/pr-report.md`, `gate-logs/`, and the pull request itself on GitHub (read it with the GitHub tools). Each criterion is pass/fail.

1. **Verified before pushing.** On the mounted checkout of `main`, `git apply --check` succeeded and the wave's provable exit gates were re-run on the patched tree; their real output is in `gate-logs/` and quoted in the report. Gates the plan marks as not provable in a sandbox are listed as "to be run at rollout", never as passed.
2. **Exact change, right place.** A branch with the name given in the task exists, created from `main`; the pull request's changed files and content are exactly those of the wave patch — nothing more, nothing less. Nothing was pushed to `main` or any other branch.
3. **Pull request open, not merged.** One open pull request from that branch into `main`; it is not merged, closed or auto-merge enabled.
4. **Approver-ready description.** The PR body contains: what changes and why (from → to, CVEs closed), the file:line change list, a gate results table with quoted evidence, the rollback procedure, one unchecked approval box per approver role required by the plan for this wave, and an explicit "do not merge until every approver has signed off" line.
5. **Traceable report.** `pr-report.md` gives the PR URL and number, branch, commit SHA, files pushed and gate results, consistent with what is on GitHub.
