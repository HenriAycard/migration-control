# Roadmap

Scope (decided): open-source, GitHub + GitLab with tokens, single-user local dashboard,
versions + CVEs + upgrades. Engine = the `mig` CLI; entry point = a Claude Code skill.
Runners: `local` (Claude Code headless, Docker or host — default) and `managed` (Claude Managed Agents API).

## v0 — anyone can scan their estate and steer it from the dashboard ✅ (this release)
- `migration.yaml` + schema; module fetch modes clone / mount / upload (GitHub & GitLab).
- Prompts, rubrics and report schemas rendered from the config (module and approver enums injected).
- `mig init · validate · doctor · up · scan · plan · run-now · status · outputs · schedule · dashboard`.
- Idempotent provisioning in `.mig/state.json`; agents re-versioned when the config changes; deployment kickoff re-pushed.
- Data-driven dashboard (any number of modules), empty state, live feed via `mig dashboard --serve`.
- Petclinic example with recorded real runs (`mig init --example petclinic` → `mig dashboard --offline`).

## v0.2 — local runner ✅
- `runner: {type: local, isolation: docker|none}`: Claude Code headless (`claude -p --output-format stream-json`), modules checked
  out locally, same prompts/rubrics/schemas; local grader loop (`--json-schema` verdict, failed criteria fed back via `--resume`);
  `.mig/memory/`; background runs + `mig stop`; live feed; `mig schedule install|remove` (cron).
- Verified with a fake `claude` (tests/test_local.py + CLI walk-through) and with a **real petclinic scan in Docker on a Claude
  subscription (2026-10-06)**: 44.5 min active, grader `needs_revision` (incomplete inventory) → fix via `--resume` → `satisfied`;
  184 components, 749 unique production CVEs, 8 builds attempted, report valid against schema 1.0, xlsx produced, memory written.
  Equivalent API list cost reported by Claude Code: ~$21.65 for the two iterations.
- Not yet run for real: the local planner, `isolation: none`, cron scheduling.
- Known gaps: cron uses the machine's timezone; on Linux the container runs as the host uid (no passwd entry) — untested.

### Managed runner — verified against the live API (2026-10-06)
- `mig doctor`; `mig up` steps model pick → environment create → `POST /v1/skills` multipart upload (`display_title`, `files[]`) → memory store create.

### Not verified yet
- Agent create onwards (`mig up` stopped on the workspace's credit balance), the deployment create/update
  (`resources` + `schedule` on update), and a first `mig scan` / `mig plan` end to end.

## v1 — close the loop
- **`mig pr <wave>`**: the agent produces the patch + description from the plan; the dashboard shows the diff with ✋ Approve / Deny;
  `mig` then pushes the branch and opens the PR (GitHub) or MR (GitLab) with the local token — the token never enters the sandbox.
  Optional mode: the agent opens the PR itself through the GitHub MCP server, every write `always_ask`.
- **Claude Code skill `/migrate`**: interview → writes `migration.yaml` → `mig doctor && mig up && mig scan`.
- **`mig eval`**: replay golden cases against a new agent version before promoting it to the deployment.
- Demo mode for any project (today it only plays the bundled petclinic recording).
- Approvals relay in the dashboard for any `requires_action` session.

## v2
- GitHub Actions workflow (scheduled `mig up` to refresh uploaded snapshots; `mig scan --wait` in CI).
- PyPI release.
- Finer target policies (e.g. "Java 21 LTS", "Angular N-1", per-module pins).
