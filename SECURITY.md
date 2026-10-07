# Security

## Reporting a vulnerability

Please **do not open a public issue**. Use GitHub's private vulnerability reporting on this repository
(Security → Report a vulnerability). Include what an attacker could do, the affected commands or files, and the
smallest reproduction you have. You will get an acknowledgement within a week.

## Security model (what we defend)

| Asset | Protection |
|---|---|
| Your Claude credentials (`CLAUDE_CODE_OAUTH_TOKEN`, `ANTHROPIC_API_KEY`) | Read from your environment or `.env` only; passed to containers by variable name (`docker run -e VAR`), never on a command line, never written by `mig` |
| Git tokens (`token_env`) | Used only on your machine, through `GIT_ASKPASS` (never in argv or URLs); redacted from errors; never given to an agent (local runner). Managed runner: private GitHub repos are mounted with the token as the repository resource's authorization |
| Your repositories | Agents run with no write credential. Pull/merge requests are opened by `mig` only after a human approves the prepared diff, on a `migration/…` branch, and are never merged |
| Your machine | Default isolation is one Docker container per run. `runner.isolation: none` runs the agent on the host without permission prompts — opt-in, documented as such |
| The dashboard | Listens on `127.0.0.1` only; every POST needs a per-start secret embedded in the served page and a same-origin request |

Out of scope: the security of Claude Code, Docker, GitHub/GitLab or the Anthropic API themselves; what an agent reads on
the public web during research (treat findings as claims to verify — the bundled sourcing rules require official sources).
