# migration-control

**Whole-estate version, CVE and upgrade migrations, run by Claude Managed Agents — steered from a local dashboard.**

Point it at the repositories you migrate together (GitHub or GitLab, public or private). A scanner agent
inventories every component of every module, finds the latest official versions, security patches and CVEs,
locates the breaking changes in *your* code (`file:line`), actually builds on target versions in a sandbox,
and maps how modules constrain each other. A planner agent turns that into ordered, gated, reversible
migration waves and proves the first one. An independent grader checks every run against a rubric.
**Migration Control**, a local dashboard, shows all of it — live.

```
🗓️ schedule ─▶ 🔭 scanner ─▶ 🎯 grader ─▶ ✋ triage ─▶ 🗺️ planner ─▶ ✋ decisions ─▶ (v1: 🔀 PR / MR)
                    │ 🧠 memory: "new since last scan"
```

## Try it in 30 seconds — no API key

```bash
pip install git+https://github.com/<you>/migration-control   # PyPI release: v2
mkdir petclinic && cd petclinic
mig init --example petclinic
mig dashboard --offline        # replays real recorded runs: 3 scans, a 7-wave plan, a gated PR
```

## Run it on your estate

```bash
mkdir my-estate && cd my-estate      # a small "control" repo, separate from your app repos
mig init                             # asks for your repos → writes migration.yaml
export ANTHROPIC_API_KEY=...         # or put it in .env (gitignored by `mig init`)
export GITHUB_TOKEN=... GITLAB_TOKEN=...   # only for private repos (read access is enough)
mig doctor                           # key, API, tokens, repo access
mig up                               # creates environment, skill, memory store, agents, deployment
mig scan                             # start a scan now
mig dashboard --serve                # http://127.0.0.1:8765 — follow it live
mig plan                             # once the scan is graded: build the migration plan
```

`mig up` is idempotent: change `migration.yaml` and run it again — agents get a new version, the
deployment gets the new kickoff. Everything created is recorded in `.mig/state.json`.

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

## How your code reaches the sandbox

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
| `mig run-now` · `mig schedule pause\|unpause` | drive the scheduled deployment |
| `mig status` · `mig outputs [ID]` | last runs, grader verdicts, cost · download outputs |
| `mig dashboard [--serve] [--offline]` | build / serve Migration Control |

## Safety model

- Agents **report and plan only** — they never push, open PRs or touch your repositories (PR/MR creation is v1 and will be human-approved per write).
- Every version, CVE and end-of-life claim needs an official source or is tagged `UNVERIFIED` (the bundled `regulated-sourcing` skill).
- Your API key and tokens are never written by `mig` — not to `.mig/`, not into prompts, not into the dashboard page. The dashboard server listens on `127.0.0.1` only.
- Scans cost real money: a full scan of a mid-size estate is typically a few dollars, heavy estates more. `mig status` shows the list cost of the last runs; set `agents.budget_usd` to cap a run.

## Roadmap

See [docs/ROADMAP.md](docs/ROADMAP.md).

## License

Apache-2.0
