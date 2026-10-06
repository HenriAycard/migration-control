# Roadmap

Scope (decided): open-source, GitHub + GitLab with tokens, single-user local dashboard,
versions + CVEs + upgrades. Engine = the `mig` CLI; entry point = a Claude Code skill.

## v0 — anyone can scan their estate and steer it from the dashboard ✅ (this release)
- `migration.yaml` + schema; module fetch modes clone / mount / upload (GitHub & GitLab).
- Prompts, rubrics and report schemas rendered from the config (module and approver enums injected).
- `mig init · validate · doctor · up · scan · plan · run-now · status · outputs · schedule · dashboard`.
- Idempotent provisioning in `.mig/state.json`; agents re-versioned when the config changes; deployment kickoff re-pushed.
- Data-driven dashboard (any number of modules), empty state, live feed via `mig dashboard --serve`.
- Petclinic example with recorded real runs (`mig init --example petclinic` → `mig dashboard --offline`).

### Verified against the live API (2026-10-06)
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
