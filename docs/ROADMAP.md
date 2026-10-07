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
- **Real local planner run (2026-10-07)**: first attempt hit the subscription session limit (→ the pause/resume work below);
  re-run: 18 min active, grader `satisfied` first pass, 10 waves, 44/44 outdated components covered, 10 blocking decisions,
  wave 4 (ojdbc6 → ojdbc8) proven — `wave-4.patch` re-checked with `git apply --check` on a fresh checkout. ~$5.13 equivalent.
- Usage limits (subscription): a run that hits one is checkpointed as `paused` (workspace + conversation kept) and
  `mig resume <run>` continues the same conversation, or re-runs only the grader if that is where it stopped.
- Not yet run for real: `isolation: none`, cron scheduling.
- Known gaps: cron uses the machine's timezone; on Linux the container runs as the host uid (no passwd entry) — untested.

### Managed runner — verified against the live API (2026-10-06)
- `mig doctor`; `mig up` steps model pick → environment create → `POST /v1/skills` multipart upload (`display_title`, `files[]`) → memory store create.

### Not verified yet
- Agent create onwards (`mig up` stopped on the workspace's credit balance), the deployment create/update
  (`resources` + `schedule` on update), and a first `mig scan` / `mig plan` end to end.

## v1 — close the loop
- ✅ **`mig pr <wave>`** (local runner): PR agent prepares patches + `pr.json` + description, re-runs exit gates, graded; review in the
  wave drawer (diff, gates, description) → ✅ Approve & publish / ✋ Deny, or `mig approve|deny`; `mig` pushes `migration/wave-<n>-…`
  and opens a GitHub PR / GitLab MR per repo with the local token (askpass, never in argv); partial publishes resume; never merges.
  Dashboard POSTs need a per-start secret + same origin. Verified with a fake agent, a local bare repo and a fake GitHub API
  (tests/test_pr.py + a browser walk-through). Not yet against real GitHub / GitLab.
- Still open: `mig pr` on the managed runner; optional mode where the agent opens the PR itself via the GitHub MCP server.
- ✅ **Claude Code skill `/migrate`** (`mig skill install`): interview → `migration.yaml` → `mig validate · doctor · up`; runs only on the
  user's go-ahead; secrets never through the chat. Packaged + frontmatter tested; not yet exercised in a live interview.
- **`mig eval`**: replay golden cases against a new agent version before promoting it to the deployment.
- Demo mode for any project (today it only plays the bundled petclinic recording).
- Approvals relay in the dashboard for any `requires_action` session.

## v2
- GitHub Actions workflow (scheduled `mig up` to refresh uploaded snapshots; `mig scan --wait` in CI).
- PyPI release.
- Finer target policies (e.g. "Java 21 LTS", "Angular N-1", per-module pins).
