# Rubric — wave pull request (prepared, not published)

Grade `pr.json`, `pr-description.md`, every `<module>.patch` and `gate-logs/` in /mnt/session/outputs/, against the wave in /mnt/session/uploads/migration-plan.json and the checkouts under /workspace/. Each criterion is pass/fail.

1. **Exact change.** Every patch applies with `git apply --check` from the root of the matching /workspace/<module> once its working tree is reset (`git stash` or a fresh `git worktree`), and contains the wave's changes and nothing else (no unrelated files, no formatting churn). `pr.json.modules` lists exactly the modules and files the patches touch.
2. **Verified.** The wave's provable exit gates were actually run on the patched tree; their real output is in `gate-logs/` and quoted in `pr.json.gates`. Gates the plan marks as not provable in a sandbox are listed in `to_run_at_rollout`, never as PASS.
3. **Honest status.** `status` is READY only if every change applied and every provable gate passed; otherwise BLOCKED with a precise `blocked_reason`.
4. **Approver-ready description.** `pr-description.md` contains: what changes and why (from → to, CVEs closed, official sources), the file:line change list, the gate results table with quoted evidence, gates left for rollout, the rollback procedure, one unchecked approval box per approver role required by the plan for this wave, and an explicit "Do not merge until every approver has signed off" line.
5. **Valid and safe.** `pr.json` validates against the schema in the task (schema_version "1.0"); the branch name follows `migration/wave-<n>-…`; nothing was pushed or committed to a remote; no secret, token or machine-specific path appears in any output.
