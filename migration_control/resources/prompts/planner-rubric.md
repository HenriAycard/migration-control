# Rubric — migration plan

Grade `migration-plan.md`, `migration-plan.json`, `migration-plan-summary.md`, the `wave-<n>.patch` file and `evidence/` in /mnt/session/outputs/. Each criterion is pass/fail.

1. **Full coverage, traceable.** Every production component_key that impact-report.json marks outdated appears in exactly one wave or in `coverage.deferred` with a reason; `coverage.uncovered` is empty. Every change cites an `impact_ref` that exists in the report (or NEW with a file:line the grader can find in the code).
2. **Sound order.** Waves respect the report's cross-module constraints and migration_order; every `depends_on` points to an earlier wave; mandatory intermediate steps are explicit.
3. **Concrete waves.** Each wave has from → to targets, a change list with file:line, a rollback procedure, approvers and risk/effort. No calendar durations anywhere.
4. **Measurable gates.** Each wave has at least one entry gate and one exit gate with an exact command or procedure and a numeric/boolean pass criterion (e.g. "build: 0 failures", "contract tests byte-identical to baseline", "0 open CVEs for the wave's component_keys").
5. **First code wave actually proven.** The first wave that changes code was applied on a throwaway copy in the sandbox; `wave-<n>.patch` exists and applies cleanly to the pinned refs (`git apply --check`); its exit gates were run and their real output is quoted in `proof.steps` and evidence logs. Other waves carry an honest status backed by evidence ids.
6. **Approvable.** Open decisions from the report are listed as `blocking_decisions` with owner, the waves they block and a recommendation. `migration-plan-summary.md` fits on one page (about 60 lines or fewer): waves in order with title, approvers, risk/effort and status; blocking decisions; what was proven.
7. **Valid and consistent.** migration-plan.json validates against the JSON Schema given in the task (schema_version "1.0"), and matches migration-plan.md and the summary (same waves, same order, same statuses).
