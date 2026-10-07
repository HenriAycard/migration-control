# migration-control

**Whole-estate version, CVE and upgrade migrations, run by Claude — on your machine with Claude Code, or on Claude Managed Agents — steered from a local dashboard.**

Point it at the repositories you migrate together (GitHub or GitLab, public or private). A scanner agent
inventories every component of every module, finds the latest official versions, security patches and CVEs,
locates the breaking changes in *your* code (`file:line`), actually builds on target versions in a sandbox,
and maps how modules constrain each other. A planner agent turns that into ordered, gated, reversible
migration waves and proves the first one. An independent grader checks every run against a rubric.
**Migration Control**, a local dashboard, shows all of it — live.

```
🗓️ schedule ─▶ 🔭 scanner ─▶ 🎯 grader ─▶ ✋ triage ─▶ 🗺️ planner ─▶ ✋ decisions ─▶ 🔀 PR agent ─▶ ✋ approve ─▶ PR / MR
                    │ 🧠 memory: "new since last scan"
```

## Try it in 30 seconds — no API key

```bash
pip install git+https://github.com/<you>/migration-control   # PyPI release: v2
mkdir petclinic && cd petclinic
mig init --example petclinic
mig dashboard --offline        # replays real recorded runs: 3 scans, a 7-wave plan, a gated PR
```

## Where the agents run

| `runner` | How | Auth | Code leaves your machine? |
|---|---|---|---|
| **`local` + `docker`** (default) | Claude Code headless, one container per run | `CLAUDE_CODE_OAUTH_TOKEN` (`claude setup-token`, Claude subscription) or `ANTHROPIC_API_KEY` | no (only model traffic) |
| `local` + `none` | Claude Code headless directly on this machine — no isolation, the agent runs builds without prompts | your normal Claude Code login | no |
| `managed` | Claude Managed Agents API: cloud sandbox, Outcome grader, memory store, scheduled deployment, sessions in the Console | `ANTHROPIC_API_KEY` with API credit | yes (cloned / mounted / uploaded into the sandbox) |

The prompts, rubrics, report schemas and dashboard are identical in all three. Locally, `mig` reproduces the
managed pieces: an independent grader pass after each attempt (up to `max_iterations`, failed criteria fed back to
the agent), `.mig/memory/` as the memory store, and `mig schedule install` (cron) instead of a deployment.
Works the same on a VPS: install Docker + Claude Code, `claude setup-token`, put the token in `.env`.

## Run it on your estate

```bash
mkdir my-estate && cd my-estate      # a small "control" repo, separate from your app repos
mig init                             # asks for your repos → writes migration.yaml
claude setup-token                   # local runner in Docker: put CLAUDE_CODE_OAUTH_TOKEN=... in .env (gitignored)
export GITHUB_TOKEN=... GITLAB_TOKEN=...   # only for private repos (read access is enough)
mig doctor                           # key, API, tokens, repo access
mig up                               # local: builds the sandbox image · managed: environment, skill, memory store, agents, deployment
mig scan                             # start a scan now
mig dashboard --serve                # http://127.0.0.1:8765 — follow it live
mig plan                             # once the scan is graded: build the migration plan
mig pr 4                             # prepare the PR/MR for wave 4 — then approve it in the dashboard (or `mig approve <run>`)
```

## From a wave to a pull request

`mig pr <wave>` (local runner) starts the **PR agent**: it applies the wave on fresh checkouts in the sandbox, re-runs the
wave's exit gates, and prepares one patch per module, `pr.json` and an approver-ready description — graded like every
other run. **It has no write credential.** You review the diff, gates and description in the wave's drawer
(`mig dashboard --serve`) and click *Approve & publish*, or run `mig approve <run>` / `mig deny <run> --reason …`.
Only then does `mig`, on your machine, push branch `migration/wave-<n>-…` and open one pull request (GitHub) or merge
request (GitLab) per repository with your token. Nothing is ever merged.

To publish, a module needs `token_env` with **write** access (GitHub fine-grained: Contents + Pull requests read/write;
GitLab: `api` or `write_repository`) and a branch to target (`ref` if it is a branch, otherwise `base_branch`).
Local-path modules get a patch to apply yourself.

`mig up` is idempotent: change `migration.yaml` and run it again. With the managed runner, agents get a new
version and the deployment gets the new kickoff. Everything created is recorded in `.mig/state.json`.
Local runs start in the background (`mig stop <run>` to stop one); add `--foreground` for cron / CI.

## migration.yaml

```yaml
version: 1
project: acme                         # names the agents, environment and memory store
estate:
  - name: billing-api
    repo: https://github.com/acme/billing-api.git
    ref: main                         # branch, tag or commit = "what runs in production"
    token_env: GITHUB_TOKEN           # private repo; omit for public ones
    depends_on: [ledger-db]           # → the grader checks this constraint is analysed
  - name: web
    repo: https://gitlab.com/acme/web
    token_env: GITLAB_TOKEN
    depends_on: [billing-api]
  - name: infra
    path: ./infra                     # local folder or .tar.gz
policy:
  target: latest official stable version and latest security patch for every component
  approvers: [tech-lead, security, platform-ops]
  rules: ["Never recommend a non-LTS Java release."]
sandbox:
  packages: { apt: [openjdk-17-jdk, maven] }   # pre-installed, cached across runs
agents:
  model: auto                         # newest Opus-class model, or an exact model id
  max_iterations: 3                   # grader retries
  budget_usd: 25                      # optional per-run spend cap
schedule:                             # optional — omit for manual runs only
  cron: "0 6 * * 6"
  timezone: Europe/Paris
```

Full reference: [`migration-config.schema.json`](migration_control/resources/schemas/migration-config.schema.json).
`mig validate` renders every prompt, rubric and agent into `.mig/rendered/` so you can read exactly what the agents get.

## How your code reaches the agent

**Local runner:** `mig` checks every module out into `.mig/work/<run>/workspace/` (clone with your token, or copy the
local path), mounts it at `/workspace` and deletes it after the run. Tokens never leave your machine.

**Managed runner:**

| Module | Mode | Fresh on scheduled runs? | Where the token goes |
|---|---|---|---|
| public GitHub / GitLab | **clone** — the agent runs `git clone` | ✅ | no token |
| private GitHub | **mount** — `github_repository` session resource | ✅ | Anthropic API, as the repository's authorization token |
| private GitLab, local path | **upload** — `mig` snapshots locally, Files API | ⚠️ snapshot from the last `mig up` | stays on your machine |

For uploaded modules on a schedule, re-run `mig up` (for example from your CI) to refresh the snapshot.

## What you get per scan

`impact-summary.md` (one page for approvers) · `impact-report.md` · `impact-report.json`
([schema 1.0](migration_control/resources/schemas/impact-report.schema.json), validated by the agent and
the grader) · `impact-report.xlsx` (auditors). Per plan: `migration-plan.{md,json}`, a one-page summary,
the proven wave's `.patch` and its evidence logs. `mig outputs <session>` downloads everything.

## Commands

| | |
|---|---|
| `mig init [--example petclinic]` | write `migration.yaml` (interactive) or copy an example |
| `mig validate` | check the config, render prompts to `.mig/rendered/` |
| `mig doctor` | key, API, tokens, repository access |
| `mig up` | create / update everything in your Anthropic workspace |
| `mig scan [--wait]` · `mig plan [--scan ID] [--wait]` | start runs |
| `mig pr <wave>` · `mig approve <run>` · `mig deny <run>` | prepare a wave's PR/MR · publish it · reject it |
| `mig stop <run>` · `mig resume <run>` | stop a local run · resume one paused by a Claude usage limit |
| `mig schedule install\|remove` (local) · `mig run-now` · `mig schedule pause\|unpause` (managed) | scheduling |
| `mig status` · `mig outputs [ID]` | last runs, grader verdicts, cost · download outputs |
| `mig dashboard [--serve] [--offline]` | build / serve Migration Control |

## Safety model

- Agents never push or open PRs: none of them gets a write credential. PRs/MRs are opened by `mig` on your machine, only after you approve the prepared diff, and never merged.
- The dashboard server only accepts actions carrying a per-start secret embedded in the page it serves (and same-origin requests), so other websites cannot trigger approvals on `127.0.0.1`.
- Every version, CVE and end-of-life claim needs an official source or is tagged `UNVERIFIED` (the bundled `regulated-sourcing` skill).
- Your API key and tokens are never written by `mig` — not to `.mig/`, not into prompts, not into the dashboard page, not on a `docker run` command line. The dashboard server listens on `127.0.0.1` only.
- Local runs use `bypassPermissions`: keep `isolation: docker` unless you accept the agent running builds and shell commands directly on your machine.
- Scans are not free: on the API a full scan of a mid-size estate is a few dollars, heavy estates more; on a Claude subscription a heavy scan uses a large share of your usage window. `mig status` shows the cost of the last runs; `agents.budget_usd` caps a run (API billing).

## Roadmap

See [docs/ROADMAP.md](docs/ROADMAP.md).

## License

Apache-2.0
