Prepare the pull request for wave $wave of the migration plan from plan run $plan_run, as of today.

Inputs:
- /mnt/session/uploads/migration-plan.json — use the entry with "wave": $wave.
- $patch_line
- /mnt/session/uploads/plan-evidence/ — the planner's proof logs and gate scripts (if any).
- The modules, checked out at their production refs (git repositories, clean working trees):

$module_setup

Deliverables in /mnt/session/outputs/:
- One <module>.patch per module you changed (`git -C /workspace/<module> diff`), paths relative to the module root.
- pr-description.md — the pull request body, written for approvers: what changes and why (component, from -> to, CVEs closed, with sources), the file:line change list, a gate results table (gate, command, result, quoted evidence), gates left for rollout, the rollback procedure, an approvers checklist with one unchecked box per approver role the plan requires for this wave, and the line "Do not merge until every approver has signed off".
- gate-logs/ — raw output of every gate you ran.
- pr.json — it MUST validate against this JSON Schema (draft 2020-12). Validate it before finishing (`pip install jsonschema`; Draft202012Validator) and fix every error. Use a branch name like migration/wave-$wave-<short-slug>.

$schema
