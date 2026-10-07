# Contributing

Thanks for helping. migration-control is small on purpose: a stdlib-first Python CLI (`mig`), prompts and JSON
Schemas as data, and one self-contained dashboard page.

## Set up

```bash
git clone https://github.com/HenriAycard/migration-control && cd migration-control
python3 -m venv .venv && .venv/bin/pip install -e '.[dev]'
.venv/bin/ruff check . && .venv/bin/pytest -q
```

Tests never call a model or a Git host: they drive the full local loop (agent → grader → fix, pause/resume, PR
prepare → approve → push) against a fake `claude` binary, a local bare repository and a stubbed PR API.

## Try changes without spending anything

```bash
mkdir -p sandbox/demo && cd sandbox/demo        # sandbox/ is gitignored
../../.venv/bin/mig init --example petclinic
../../.venv/bin/mig validate                     # renders every prompt/rubric to .mig/rendered/
../../.venv/bin/mig dashboard --offline          # the recorded example runs
```

## Where things live

| Path | What |
|---|---|
| `migration_control/cli.py` | the `mig` commands |
| `config.py` · `resources/schemas/migration-config.schema.json` | `migration.yaml` |
| `render.py` · `resources/prompts/` | everything an agent sees, rendered from the config |
| `resources/schemas/` | the contracts: impact report, migration plan, PR |
| `local.py` | local runner (Claude Code headless, Docker or host), grader loop, pause/resume |
| `provision.py` · `runs.py` · `api.py` | managed runner (Claude Managed Agents API) |
| `publish.py` | approved PR runs → branch + GitHub PR / GitLab MR |
| `evals.py` | golden cases |
| `dashboard.py` · `resources/dashboard/template.html` | Migration Control (data injected at build time) |
| `resources/claude-skill/migrate/` | the `/migrate` Claude Code skill |

## Rules of the road

- **Contracts change deliberately.** A schema change bumps `schema_version` and keeps the dashboard able to read older
  reports. Prompt and rubric changes alter the scanner fingerprint — run `mig eval` on a real estate before relying on them.
- **Secrets never move.** No token or key in prompts, logs, `.mig/`, argv, URLs or the page. Agents never get a write
  credential; publishing stays a human decision.
- **Recorded examples are anonymized** with `scripts/anonymize_recording.py` before they are committed.
- Keep dependencies at `pyyaml` + `jsonschema`; Python ≥ 3.9.
