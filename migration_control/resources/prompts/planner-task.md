Build the migration plan for the estate, as of today, from the validated impact report of scan session $scan_session.

Inputs in your sandbox:
- /mnt/session/uploads/impact-report.json — the validated report (schema 1.0). Source of truth for findings, impact ids, build ids, cross-module constraints and decisions.
- The code, pinned exactly as the report describes. Set every module up side by side under /workspace/ first:

$module_setup

Deliverables in /mnt/session/outputs/:
- migration-plan-summary.md — ONE page for approvers (max ~60 lines): waves in order (title, approvers, risk/effort, status), blocking decisions, what was proven and how.
- migration-plan.md — waves in order; per wave: targets, intermediate steps, changes (file:line + impact ref), entry gates, exit gates, rollback, approvers, risk/effort, evidence/status. Then coverage, blocking decisions, proof.
- wave-<n>.patch — git diff of the first wave that changes code, against the pinned refs, with paths prefixed by the module name (must pass `git apply --check` from /workspace on a fresh setup).
- evidence/ — logs of every proof command you ran.
- migration-plan.json — same content; it MUST validate against this JSON Schema (draft 2020-12). Validate before finishing (`pip install jsonschema`; Draft202012Validator with FormatChecker) and fix every error.

$schema
