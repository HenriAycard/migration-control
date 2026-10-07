# migration-control

[![CI](https://github.com/HenriAycard/migration-control/actions/workflows/ci.yml/badge.svg)](https://github.com/HenriAycard/migration-control/actions/workflows/ci.yml)
![status: alpha](https://img.shields.io/badge/status-alpha-orange)

**Whole-estate version, CVE and upgrade migrations, run by Claude — on your machine with Claude Code, or on Claude
Managed Agents — steered from a local dashboard, with a human approving every write.**

Point it at the repositories you migrate together (GitHub or GitLab, public or private). A **scanner** agent inventories
every component of every module, finds the latest official versions, security patches and CVEs, locates the breaking
changes in *your* code (`file:line`), actually builds on target versions in a sandbox, and maps how modules constrain
each other. A **planner** turns that into ordered, gated, reversible migration waves and proves the first one. A **PR
agent** prepares the pull request for a wave — and you approve it before anything is pushed. An independent grader checks
every run against a rubric. **Migration Control**, a local dashboard, shows all of it live, and its 🎬 demo mode replays
your own recorded runs as a narrated walkthrough for sponsors, tech leads and security.

```
🔭 scanner ─▶ 🎯 grader ─▶ ✋ triage ─▶ 🗺️ planner ─▶ ✋ decisions ─▶ 🔀 PR agent ─▶ ✋ approve ─▶ PR / MR (never merged)
     │ 🧠 memory: "new since last scan"
```

## Try it in 30 seconds — no key, no cost

```bash
pipx install git+https://github.com/HenriAycard/migration-control    # or: pip install … in a venv
mkdir petclinic && cd petclinic
mig init --example petclinic
mig dashboard --offline        # real recorded runs: 3 scans, a 7-wave plan, a gated PR — try the 🎬 Demo button
```

## Requirements

- Python ≥ 3.9 and `git`.
- **Local runner (default):** [Claude Code](https://docs.claude.com/en/docs/claude-code) and a Claude subscription or an
  API key; Docker for the default per-run isolation.
- **Managed runner:** an Anthropic API key with credit (Claude Managed Agents).

## Where the agents run

| `runner` | How | Auth | Code leaves your machine? |
|---|---|---|---|
| **`local` + `docker`** (default) | Claude Code headless, one container per run | `CLAUDE_CODE_OAUTH_TOKEN` (`claude setup-token`, Claude subscription) or `ANTHROPIC_API_KEY` | no (only model traffic) |
| `local` + `none` | Claude Code headless directly on this machine — no isolation, the agent runs builds without permission prompts | your normal Claude Code login | no |
| `managed` | Claude Managed Agents API: cloud sandbox, Outcome grader, memory store, scheduled deployment, sessions in the Console | `ANTHROPIC_API_KEY` with API credit | yes (cloned / mounted / uploaded into the sandbox) |

Prompts, rubrics, report schemas and the dashboard are identical in all three. Locally, `mig` reproduces the managed
pieces: an independent grader pass after each attempt (failed criteria fed back to the agent, up to `max_iterations`),
`.mig/memory/` as the memory store, and cron (`mig schedule install`) instead of a deployment. A run that hits a Claude
usage limit is paused, not lost: `mig resume <run>`. Works the same on a VPS — Docker + Claude Code + `claude setup-token`.

## From Claude Code: `/migrate`

```bash
mig skill install            # → ~/.claude/skills/migrate   (or --project for ./.claude/skills)
```

Type `/migrate` in Claude Code: it interviews you about your repositories, writes `migration.yaml`, runs
`mig validate · doctor · up`, and starts scans, plans and PRs only when you say so. Secrets never go through the chat.

## Run it on your estate

```bash
mkdir my-estate && cd my-estate      # a small "control" folder/repo, separate from your app repos
mig init                             # asks for your repos → writes migration.yaml (+ .gitignore)
claude setup-token                   # in your own terminal; put CLAUDE_CODE_OAUTH_TOKEN=… in .env (gitignored)
export GITHUB_TOKEN=… GITLAB_TOKEN=… # only for private repos (read is enough to scan; write to publish PRs)
mig doctor                           # Docker, Claude auth, tokens, repository access
mig up                               # local: builds the sandbox image · managed: creates/updates the workspace objects
mig scan                             # runs in the background — `mig status`
mig dashboard --serve                # http://127.0.0.1:8765 — follow it live
mig plan                             # from the latest graded scan
mig pr 4                             # prepare wave 4's PR/MR — review and approve it in the wave's drawer
```

Runs are on demand; nothing is scheduled unless you add `schedule:` and run `mig schedule install`.

## From a wave to a pull request

`mig pr <wave>` (local runner) starts the **PR agent**: it applies the wave on fresh checkouts in the sandbox, re-runs the
wave's exit gates, and prepares one patch per module, `pr.json` and an approver-ready description — graded like every
other run. **It has no write credential.** You review the diff, gates and description in the wave's drawer
(`mig dashboard --serve`) and click *Approve & publish*, or run `mig approve <run>` / `mig deny <run> --reason …`.
Only then does `mig`, on your machine, push branch `migration/wave-<n>-…` and open one pull request (GitHub) or merge
request (GitLab) per repository with your token. Nothing is ever merged.

A module is published when it has `token_env` with **write** access (GitHub fine-grained: Contents + Pull requests
read/write; GitLab: `api`) and a branch to target (`ref` if it is a branch, otherwise `base_branch`). Local paths and
repos without `token_env` (e.g. upstream projects you cannot write to) get a patch to apply yourself.

## Golden cases: `mig eval`

Before trusting a changed config (prompts, rubric, policy, model), check it against scans you already trust:

```bash
mig eval add my-baseline       # derive evals/my-baseline.yaml from the latest satisfied scan — review it, commit it
mig eval check                 # free: check the latest scan against every case
mig eval run                   # re-scan each case (isolated, empty memory) and check it — costs a scan per case
mig eval status                # did the *current* config pass a full eval?
```

A case records the refs that were scanned and stable facts from its report — components and their current versions,
critical alerts, end-of-life flags, lower bounds on critical CVEs and builds — checked with "at least" semantics: new CVEs
never fail a case, a lost component or alert does. `mig status` warns when the config changed since the last passing eval.

## migration.yaml

```yaml
version: 1
project: acme
runner: {type: local, isolation: docker}
estate:
  - name: billing-api
    repo: https://github.com/acme/billing-api.git
    ref: main                         # branch, tag or commit = "what runs in production"
    token_env: GITHUB_TOKEN           # private repo / publishing PRs; omit for public ones
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
  packages: { apt: [openjdk-17-jdk, maven] }   # baked into the sandbox image
agents:
  model: auto                         # newest Opus-class model, or an exact model id
  max_iterations: 3                   # grader retries
  budget_usd: 25                      # optional per-run cap (API billing only)
schedule:                             # optional — omit for on-demand runs only
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

## What you get

Per scan: `impact-summary.md` (one page for approvers) · `impact-report.md` · `impact-report.json`
([schema 1.0](migration_control/resources/schemas/impact-report.schema.json), validated by the agent and the grader) ·
`impact-report.xlsx` (auditors). Per plan: `migration-plan.{md,json}`, a one-page summary, the proven wave's `.patch`
and its evidence logs. Per PR run: one `.patch` per module, `pr.json`, `pr-description.md`, gate logs.
`mig outputs <run>` copies everything into `./outputs/<run>/`.

## Commands

| | |
|---|---|
| `mig init [--example petclinic]` | write `migration.yaml` (interactive) or copy an example |
| `mig validate` | check the config, render prompts to `.mig/rendered/` |
| `mig doctor` | Docker / Claude auth / API key, tokens, repository access |
| `mig up` | local: build the sandbox image · managed: create/update the workspace objects |
| `mig scan` · `mig plan [--scan RUN]` | start runs (background; `--foreground` for cron/CI) |
| `mig pr <wave>` · `mig approve <run>` · `mig deny <run>` | prepare a wave's PR/MR · publish it · reject it |
| `mig stop <run>` · `mig resume <run>` | stop a local run · resume one paused by a Claude usage limit |
| `mig eval add\|check\|run\|status` | golden cases for the scanner |
| `mig status` · `mig outputs [RUN]` | runs, grader verdicts, cost, evals · copy outputs |
| `mig dashboard [--serve] [--offline]` | build / serve Migration Control |
| `mig schedule install\|remove` (local) · `pause\|unpause` + `mig run-now` (managed) | scheduling |
| `mig skill install [--project]` | install the `/migrate` Claude Code skill |

## Safety model

- Agents never push or open PRs: none of them gets a write credential. PRs/MRs are opened by `mig` on your machine, only
  after you approve the prepared diff, and never merged.
- Your keys and tokens are never written by `mig` — not to `.mig/`, prompts, logs or the dashboard page — and never appear
  on a command line (containers get them by variable name; git uses `GIT_ASKPASS`).
- The dashboard listens on `127.0.0.1` only, and every action needs a per-start secret embedded in the page it serves plus
  a same-origin request, so other websites cannot trigger approvals.
- Local runs use Claude Code's `bypassPermissions` mode: keep `isolation: docker` unless you accept the agent running
  builds and shell commands directly on your machine.
- Every version, CVE and end-of-life claim needs an official source or is tagged `UNVERIFIED` (the bundled
  `regulated-sourcing` skill). Still: these are agent findings for humans to review, not an authority.
- Runs are not free. A heavy estate (the petclinic example: 3 modules, ~180 components, real builds) took ~45 min and the
  equivalent of ~$20 at API list prices for a scan with one fix iteration, ~$5 for its plan and ~$2 for a PR. On a Claude
  subscription that is a large share of a usage window. `mig status` shows the cost of every run.

See [SECURITY.md](SECURITY.md) to report a vulnerability, [CONTRIBUTING.md](CONTRIBUTING.md) to hack on it,
[CHANGELOG.md](CHANGELOG.md) and [docs/ROADMAP.md](docs/ROADMAP.md).

## License

Apache-2.0
