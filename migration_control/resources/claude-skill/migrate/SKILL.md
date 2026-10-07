---
name: migrate
description: Set up and drive migration-control for a set of repositories — interview the user about their estate (GitHub/GitLab repos, refs, dependencies, private repos), write migration.yaml, check and provision with the `mig` CLI, then run whole-estate version/CVE/upgrade scans, migration plans and per-wave pull/merge requests the user approves. Use when the user says "/migrate", "migrate my repos", "scan my estate for CVEs", "plan our upgrades", or wants migration-control on their projects.
---

# /migrate — migration-control, driven from Claude Code

You help the user put **migration-control** (`mig`) on their own estate: the repositories they migrate together.
`mig` does the work; you interview, write the config, run the commands, read the results back, and keep the
user in control of every cost and every write.

## Ground rules

- Talk in the user's language. Everything written to disk (`migration.yaml`, names) is in English.
- **Secrets never go through the chat.** Never ask the user to paste a token or key, never `Read`/`cat` a `.env`
  file, never echo an environment variable's value. Check presence only (`[ -n "$VAR" ] && echo set`).
  The user puts secrets in their shell or in `.env` next to `migration.yaml` themselves, from their own terminal.
- Runs cost real usage: a full scan of a mid-size estate is roughly 20–45 min and can use a large share of a
  Claude subscription window (or several dollars to ~$20 of API credit). **Never start `mig scan`, `mig plan`
  or `mig pr` without the user's explicit go-ahead in this conversation.** Default to on-demand runs; only set
  up a schedule if they ask for one.
- Nothing is ever published without the user: `mig pr` only prepares; publishing happens on `mig approve`
  or the dashboard's *Approve & publish*. Never run `mig approve` unless the user just told you to approve that run.
- One question at a time; use AskUserQuestion for enumerable choices.

## 0. Is `mig` installed?

Run `mig --version`. If missing: `pipx install git+https://github.com/<owner>/migration-control` (or
`pip install …` in a venv) — ask the user which, they own their Python setup. Also check `git --version`,
`claude --version`, and, for Docker isolation, `docker info`.

## 1. Where does the config live?

Recommend a small dedicated folder/repo (e.g. `~/estates/<name>`), separate from the app repos — the estate spans
several repos. If a `migration.yaml` already exists there, read it and skip to step 4.
If they just want to see it work first: `mig init --example petclinic && mig dashboard --offline` (no key, no cost).

## 2. Interview — the estate

Ask, then confirm back as a compact table:

1. **Modules.** For each repository: HTTPS URL (GitHub or GitLab) or local path; the branch/tag/commit that is
   *in production today* (`ref`); a one-line description; whether it is private.
2. **Private repos** → name of the env var holding a token (`token_env`, e.g. `GITHUB_TOKEN`, `GITLAB_TOKEN`).
   Read access is enough to scan; opening PRs/MRs later needs write (GitHub fine-grained: Contents + Pull
   requests read/write; GitLab: `api`). Tell them where to create it; they set it themselves.
   Self-hosted GitLab → `provider: gitlab`. If `ref` is a tag or a SHA, ask which branch PRs should target
   (`base_branch`).
3. **Dependencies** between modules (`depends_on`: front-end → API, API → database/infra, runtime host…).
   The grader checks these constraints are analysed, so they matter.
4. **Policy**: target (default: latest official stable + latest security patch), approver roles
   (default `tech-lead, security, platform-ops`), any house rules (e.g. "LTS releases only").
5. **Toolchains** the sandbox needs to build (→ `sandbox.packages.apt`, e.g. `openjdk-17-jdk`, `maven`; Node is in the
   base image; add `pip`/`npm` packages if needed).
6. **Where agents run** (AskUserQuestion):
   - `local` + `docker` (recommended): Claude Code in a container per run, their Claude subscription via
     `claude setup-token` → `CLAUDE_CODE_OAUTH_TOKEN` in `.env`, or `ANTHROPIC_API_KEY`.
   - `local` + `none`: directly on their machine with their Claude Code login — no isolation, the agent runs
     builds without permission prompts. Only if they accept that.
   - `managed`: Claude Managed Agents API (cloud sandbox, Console sessions) — needs API credit. `mig pr` is local-only today.
7. **Schedule**: default none (on-demand). If they want one: cron + timezone, and say it costs a full scan per run.

## 3. Write `migration.yaml`

Write it with the Write tool (schema: `mig validate` prints errors; reference in the README). Shape:

```yaml
version: 1
project: <kebab-case>
runner: {type: local, isolation: docker}
estate:
  - name: billing-api
    description: Java backend (Spring Boot), REST API used by web
    repo: https://github.com/acme/billing-api.git
    ref: main
    token_env: GITHUB_TOKEN
    depends_on: [ledger-db]
policy:
  approvers: [tech-lead, security, platform-ops]
sandbox:
  packages: {apt: [openjdk-17-jdk, maven]}
agents: {model: auto, max_iterations: 3}
```

Then run `mig validate` and fix any error. Offer to show `.mig/rendered/scanner-task.md` so they see exactly what the agent gets.

## 4. Check and provision

- Secrets: tell them exactly what to put where (`.env` next to `migration.yaml`, `chmod 600`, already gitignored by
  `mig init` — run `mig init`'s gitignore step by hand if they wrote the yaml without it: add `.mig/`, `.env`,
  `.env.local`, `outputs/` to `.gitignore`). For `claude setup-token`: they must run it in **their own terminal**
  (the token prints there), then write `CLAUDE_CODE_OAUTH_TOKEN=…` into `.env` themselves.
- `mig doctor` — read every ✗ back with the fix. Repeat until green.
- `mig up` — local+docker builds the sandbox image (a few minutes the first time); managed creates the cloud objects.

## 5. Run — only on explicit go-ahead

| Step | Command | Then |
|---|---|---|
| Scan | `mig scan` (background) | `mig status`; live view `mig dashboard --serve` |
| Plan | `mig plan` (latest scan) | waves, gates, blocking decisions |
| PR for a wave | `mig pr <wave>` | review in the wave's drawer, or read `.mig/runs/prs/<run>/pr-description.md` + the `.patch` files |
| Publish | user clicks *Approve & publish*, or tells you to run `mig approve <run>` | `mig deny <run> --reason "…"` otherwise |

Follow a running run without busy-polling (use the Monitor tool on `.mig/runs/<kind>/<run>/meta.json` status if
available). When it finishes, read back: grader verdict(s), the one-page summary (`impact-summary.md` /
`migration-plan-summary.md`), cost (`mig status`), and where to look in the dashboard.

If a run is `paused` (Claude usage limit): say when it resets (from the run's explanation) and offer
`mig resume <run>` then — do not resume on your own.

## 6. Close

Point at `mig dashboard` (static) / `mig dashboard --serve` (live + approvals), list what is configured, what ran, what
it cost, and the next sensible step (triage alerts → sign decisions → `mig pr` on the first unlocked wave).
