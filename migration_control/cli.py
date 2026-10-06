"""mig — whole-estate version, CVE and upgrade migrations on Claude Managed Agents."""
import argparse
import os
import shutil
import subprocess
import sys
import time
import webbrowser
from pathlib import Path

from . import RESOURCES, __version__, config, dashboard, local, provision, render, runs
from .api import ApiError, Client, load_dotenv
from .state import State

EXAMPLES = RESOURCES / "examples"
GITIGNORE = ".mig/\n.env\n.env.local\noutputs/\n"


def _ctx(need_client=True):
    cfg = config.load()
    load_dotenv(cfg.root)
    st = State(cfg.root)
    return cfg, st, (Client() if need_client and not cfg.local else None)


def _say(msg=""):
    print(msg, flush=True)


# ── init ─────────────────────────────────────────────────────────────────────
def _ask(prompt, default=None):
    val = input(f"{prompt}{f' [{default}]' if default else ''}: ").strip()
    return val or default


def cmd_init(a):
    root = Path.cwd()
    if (root / config.CONFIG_NAME).exists() and not a.force:
        sys.exit(f"{config.CONFIG_NAME} already exists here (use --force to overwrite)")
    if a.example:
        src = EXAMPLES / a.example
        if not src.exists():
            sys.exit(f"unknown example {a.example!r} — available: {', '.join(p.name for p in EXAMPLES.iterdir() if p.is_dir())}")
        shutil.copy(src / config.CONFIG_NAME, root / config.CONFIG_NAME)
        for extra in src.iterdir():
            if extra.name not in (config.CONFIG_NAME, "recorded", "README.md") and not (root / extra.name).exists():
                (shutil.copytree if extra.is_dir() else shutil.copy)(extra, root / extra.name)
        st = State(root)
        if (src / "recorded").exists():
            shutil.copytree(src / "recorded", st.cache, dirs_exist_ok=True)
            st.set("example", value=a.example)
        _write_gitignore(root)
        _say(f"✓ {a.example} example copied. Look around with no API key at all:\n    mig dashboard --offline")
        _say("  When you want to run it for real: export ANTHROPIC_API_KEY, then `mig doctor && mig up && mig scan`.")
        return
    _say("Describe the estate: every repository you migrate together.\n")
    project = _ask("Project name (kebab-case)", root.name.lower().replace("_", "-").replace(" ", "-"))
    modules = []
    while True:
        _say(f"\nModule #{len(modules) + 1} (leave the URL empty to finish)")
        url = _ask("  GitHub/GitLab HTTPS URL or local path")
        if not url:
            if modules:
                break
            continue
        m = {"name": _ask("  Module name", Path(url.rstrip("/")).name.removesuffix(".git").lower())}
        if url.startswith("https://"):
            m["repo"] = url
            m["ref"] = _ask("  Branch, tag or commit deployed in production", "main")
            if _ask("  Private repository? (y/N)", "n").lower().startswith("y"):
                m["token_env"] = _ask("  Environment variable holding a read token", "GITLAB_TOKEN" if "gitlab" in url else "GITHUB_TOKEN")
        else:
            m["path"] = url
        desc = _ask("  One-line description (optional)", "")
        if desc:
            m["description"] = desc
        modules.append(m)
    if len(modules) > 1:
        names = [m["name"] for m in modules]
        _say(f"\nDependencies between modules ({', '.join(names)})")
        for m in modules:
            deps = _ask(f"  {m['name']} depends on (comma-separated, optional)", "")
            if deps:
                m["depends_on"] = [d.strip() for d in deps.split(",") if d.strip()]
    data = {"version": 1, "project": project, "estate": modules}
    cron = _ask("\nWeekly schedule? cron expression, or empty for manual runs only", "")
    if cron:
        data["schedule"] = {"cron": cron, "timezone": _ask("  Timezone", "UTC")}
    errors = config.validate(data)
    if errors:
        sys.exit("config is invalid:\n  - " + "\n  - ".join(errors))
    import yaml
    (root / config.CONFIG_NAME).write_text(yaml.safe_dump(data, sort_keys=False, allow_unicode=True))
    _write_gitignore(root)
    _say(f"\n✓ wrote {config.CONFIG_NAME}. Next: `mig doctor`, then `mig up`.")


def _write_gitignore(root):
    gi = root / ".gitignore"
    have = gi.read_text() if gi.exists() else ""
    missing = [l for l in GITIGNORE.splitlines() if l not in have.splitlines()]
    if missing:
        gi.write_text(have + ("" if have.endswith("\n") or not have else "\n") + "\n".join(missing) + "\n")


# ── checks ───────────────────────────────────────────────────────────────────
def cmd_validate(a):
    cfg, st, _ = _ctx(need_client=False)
    out = render.write_preview(cfg, st)
    _say(f"✓ {config.CONFIG_NAME} is valid — {len(cfg.modules)} modules")
    for m in cfg.modules:
        _say(f"  {m.name:<24} {m.fetch:<7} {m.get('repo') or m.get('path')}" + (f" @ {m.ref}" if 'repo' in m else ""))
    _say(f"Rendered prompts, rubrics and agents → {out}/")


def cmd_doctor(a):
    ok = True

    def check(label, fn):
        nonlocal ok
        try:
            detail = fn()
            _say(f"  ✓ {label}" + (f" — {detail}" if detail else ""))
        except Exception as e:  # noqa: BLE001 — doctor reports, never raises
            ok = False
            _say(f"  ✗ {label} — {e}")

    try:
        cfg = config.load()
    except config.ConfigError as e:
        sys.exit(f"  ✗ {e}")
    load_dotenv(cfg.root)
    _say(f"✓ {config.CONFIG_NAME} — project {cfg['project']}, {len(cfg.modules)} modules")
    check("git installed", lambda: subprocess.run(["git", "--version"], capture_output=True, text=True, check=True).stdout.strip())
    if cfg.local:
        _say(f"  runner: local · isolation {cfg['runner']['isolation']}")
        if cfg["runner"]["isolation"] == "docker":
            check("Docker daemon", local.docker_ok)
        check("Claude Code auth", lambda: local.auth_status(cfg))
    else:
        _say("  runner: managed (Claude Managed Agents API)")
        check("ANTHROPIC_API_KEY", lambda: "set" if os.environ.get("ANTHROPIC_API_KEY") else (_ for _ in ()).throw(RuntimeError("not set — export it or put it in .env (never commit it)")))
        if os.environ.get("ANTHROPIC_API_KEY"):
            check("API reachable", lambda: f"{len(Client().get('/models', beta=None, params={'limit': 100}).get('data', []))} models visible")
    for m in cfg.modules:
        def reach(m=m):
            if "path" in m:
                return "local path" + ("" if cfg.local else ", snapshot uploaded by `mig up`")
            from .estate import _authed_url, _redact
            url = _authed_url(m, m.token()) if m.get("token_env") else m["repo"]
            r = subprocess.run(["git", "ls-remote", "--exit-code", url, m.ref], capture_output=True, text=True, timeout=60,
                               env={**os.environ, "GIT_TERMINAL_PROMPT": "0"})
            if r.returncode == 2 and len(m.ref) == 40:
                pass  # a commit SHA is not a ref name; reachability was still proven
            elif r.returncode:
                raise RuntimeError(_redact(r.stderr.strip()[:200] or f"ref {m.ref} not found", m.token() if m.get("token_env") else None))
            return {"local": "checked out locally for each run", "clone": "public, cloned by the agent", "mount": "private GitHub, mounted per run",
                    "upload": "private, snapshot uploaded by `mig up`"}[m.fetch]
        check(f"module {m.name}", reach)
    if cfg.get("schedule") and not cfg.local:
        check("schedule kickoff has no literal dates", lambda: render.check_no_literal_dates(render.scanner_task(cfg), render.scanner_rubric(cfg)))
    _say("\nAll good — next: `mig up`" if ok else "\nFix the ✗ above, then re-run `mig doctor`.")
    sys.exit(0 if ok else 1)


# ── provisioning & runs ──────────────────────────────────────────────────────
def cmd_up(a):
    cfg, st, client = _ctx()
    if cfg.local:
        local.up(cfg, st, log=_say)
    else:
        provision.up(cfg, client, st, log=_say)
    render.write_preview(cfg, st)
    _say("\n✓ up to date. Start a scan with `mig scan`" + (" (or `mig run-now` to fire the deployment)" if cfg.get("schedule") and not cfg.local else ""))


def _wait(client, sid, every=30):
    last = None
    while True:
        s = runs.session_status(client, sid)
        line = f"  {s['status']} · {s['active_min']} min active · grader {s['verdicts'] or '—'}"
        if line != last:
            _say(line); last = line
        if s["status"] in ("idle", "terminated"):
            return s
        time.sleep(every)


def cmd_scan(a):
    cfg, st, client = _ctx()
    if cfg.local:
        return _local_start(cfg, st, "scans", None, a)
    s = runs.start_scan(cfg, client, st, log=_say)
    _say(f"▶ scan started: {s['id']}\n  console: https://platform.claude.com/workspaces/{cfg['console_workspace']}/sessions/{s['id']}")
    _say("  follow it live: `mig dashboard --serve`  ·  status: `mig status`")
    if a.wait:
        _wait(client, s["id"])
        runs.fetch_session(client, st, cfg, s["id"], "scans")
        _say("✓ outputs cached — `mig dashboard` to open them")


def cmd_plan(a):
    cfg, st, client = _ctx()
    if cfg.local:
        scans = [m for m in local.list_runs(st, "scans") if (st.cache / "scans" / m["id"] / "impact-report.json").exists()]
        scan = a.scan or (scans[-1]["id"] if scans else None)
        if not scan:
            sys.exit("no finished scan with an impact-report.json yet — run `mig scan` first")
        return _local_start(cfg, st, "plans", scan, a)
    s = runs.start_plan(cfg, client, st, a.scan, log=_say)
    _say(f"▶ plan started: {s['id']} (from scan {s.get('metadata', {}).get('scan_session') or a.scan or 'latest'})")
    if a.wait:
        _wait(client, s["id"])
        runs.fetch_session(client, st, cfg, s["id"], "plans")
        _say("✓ plan cached — `mig dashboard` to open it")


def _local_start(cfg, st, kind, scan, a):
    if cfg["runner"]["isolation"] == "docker" and not st.get("local", "image"):
        sys.exit("no image yet — run `mig up` first")
    local.auth_status(cfg)
    _say(f"▶ preparing {kind[:-1]} (local · {cfg['runner']['isolation']})" + (f" from scan {scan}" if scan else ""))
    rid = local.prepare(cfg, st, kind, scan, log=_say)
    if a.wait or getattr(a, "foreground", False):
        _say(f"▶ {rid} running in the foreground…")
        verdict = local.start(cfg, st, kind, rid, foreground=True)
        _say(f"✓ {rid} finished · grader {verdict} — `mig dashboard` to open it")
    else:
        pid = local.start(cfg, st, kind, rid)
        _say(f"▶ {rid} started in the background (pid {pid})\n  follow it live: `mig dashboard --serve` · status: `mig status` · stop: `mig stop {rid}`")


def cmd_worker(a):
    cfg, st, _ = _ctx(need_client=False)
    local.work(cfg, st, a.kind, a.run)


def cmd_stop(a):
    cfg, st, _ = _ctx(need_client=False)
    if not cfg.local:
        sys.exit("managed runner: interrupt or archive the session from the Console")
    local.stop_run(st, a.run)
    _say(f"✓ {a.run} stopped")


def cmd_run_now(a):
    cfg, st, client = _ctx()
    r = runs.run_deployment_now(client, st)
    _say(f"▶ deployment fired: session {r.get('session_id')} ({r.get('status')})")


def cmd_status(a):
    cfg, st, client = _ctx()
    if cfg.local:
        _say(f"project {cfg['project']} · runner local ({cfg['runner']['isolation']}) · model {local.model_of(cfg)}")
        if cfg.get("schedule"):
            _say(f"  schedule {cfg['schedule']['cron']} · " + ("installed in crontab" if local.schedule_installed(cfg) else "not installed (`mig schedule install`)"))
        for kind in ("scans", "plans"):
            for m in local.list_runs(st, kind)[-5:]:
                cost = f" · ${m['list_cost_cents'] / 100:.2f}" if m.get("list_cost_cents") is not None else ""
                _say(f"  {kind[:-1]:<4} {m['id']} · {m['status']} · {round((m.get('active_seconds') or 0) / 60, 1)} min{cost} · grader {m.get('verdicts') or '—'}")
        return
    _say(f"project {cfg['project']} · model {st.get('model') or '—'}")
    for role in ("scanner", "planner"):
        ag = st.get("agents", role)
        _say(f"  {role:<8} {ag['id'] + ' v' + str(ag['version']) if ag else '— (run `mig up`)'}")
    if st.get("deployment", "id"):
        d = client.get(f"/deployments/{st.get('deployment', 'id')}", params={"beta": "true"})
        nxt = ((d.get("schedule") or {}).get("upcoming_runs_at") or ["—"])[0]
        _say(f"  deployment {d['id']} · {d.get('status')} · next run {nxt}")
    for kind in ("scan", "plan"):
        sid = st.get("last", kind)
        if sid:
            s = runs.session_status(client, sid)
            cost = f" · ${s['cost_usd']:.2f}" if s["cost_usd"] is not None else ""
            _say(f"  last {kind}: {sid} · {s['status']} · {s['active_min']} min{cost} · grader {s['verdicts'] or '—'}")


def cmd_outputs(a):
    cfg, st, client = _ctx()
    sid = a.session or st.get("last", "scan")
    if not sid:
        sys.exit("no session given and no scan started yet")
    if cfg.local:
        src = next((st.cache / k / sid / "outputs" for k in ("scans", "plans") if (st.cache / k / sid / "outputs").exists()), None)
        if not src:
            sys.exit(f"no outputs for {sid} yet")
        dst = cfg.root / "outputs" / sid
        shutil.copytree(src, dst, dirs_exist_ok=True)
        _say(f"✓ {dst}")
        return
    dst = cfg.root / "outputs" / sid
    dst.mkdir(parents=True, exist_ok=True)
    for f in client.output_files(sid):
        rel = f["filename"].removeprefix("/mnt/session/outputs/")
        (dst / rel).parent.mkdir(parents=True, exist_ok=True)
        (dst / rel).write_bytes(client.download(f["id"]))
        _say(f"  got {rel}")
    _say(f"✓ {dst}")


def cmd_schedule(a):
    cfg, st, client = _ctx()
    if cfg.local:
        if a.action == "install":
            _say(f"✓ crontab entry:\n  {local.schedule_install(cfg, st)}")
            _say(f"  note: cron uses this machine's timezone ({time.strftime('%Z')}); migration.yaml says {cfg['schedule']['timezone']}")
        elif a.action == "remove":
            local.schedule_remove(cfg); _say("✓ crontab entry removed")
        else:
            sys.exit("local runner: use `mig schedule install` / `mig schedule remove`")
        return
    if a.action not in ("pause", "unpause"):
        sys.exit("managed runner: use `mig schedule pause` / `mig schedule unpause` (the deployment carries the schedule)")
    dep = st.get("deployment", "id") or sys.exit("no deployment — add `schedule:` to migration.yaml and run `mig up`")
    client.post(f"/deployments/{dep}/{a.action}", {}, params={"beta": "true"})
    _say(f"✓ deployment {dep} {a.action}d")


def cmd_dashboard(a):
    offline = a.offline
    cfg, st, client = _ctx(need_client=not offline)
    page = dashboard.build(cfg, st, client, log=_say)
    if a.serve:
        if offline and not cfg.local:
            sys.exit("--serve needs the API (live feed) — drop --offline")
        if not a.no_open:
            webbrowser.open(f"http://127.0.0.1:{a.port}")
        dashboard.serve(cfg, st, client, a.port, log=_say)
    elif not a.no_open:
        webbrowser.open(page.as_uri())


# ── entry point ──────────────────────────────────────────────────────────────
def main(argv=None):
    p = argparse.ArgumentParser(prog="mig", description=__doc__)
    p.add_argument("--version", action="version", version=f"migration-control {__version__}")
    sub = p.add_subparsers(dest="cmd", required=True)

    s = sub.add_parser("init", help="create migration.yaml (interactive) or copy an example")
    s.add_argument("--example", help="copy a bundled example, e.g. petclinic")
    s.add_argument("--force", action="store_true")
    s.set_defaults(fn=cmd_init)
    sub.add_parser("validate", help="validate migration.yaml and render prompts to .mig/rendered/").set_defaults(fn=cmd_validate)
    sub.add_parser("doctor", help="check key, API, tokens and repository access").set_defaults(fn=cmd_doctor)
    sub.add_parser("up", help="create/update environment, skill, memory, agents, snapshots and deployment").set_defaults(fn=cmd_up)
    s = sub.add_parser("scan", help="start a whole-estate scan now")
    s.add_argument("--wait", action="store_true", help="block until it finishes and cache its outputs")
    s.add_argument("--foreground", action="store_true", help="local runner: run in this process (cron, CI)")
    s.set_defaults(fn=cmd_scan)
    s = sub.add_parser("plan", help="build a migration plan from a finished scan")
    s.add_argument("--scan", help="scan session id (default: latest scan with a report)")
    s.add_argument("--wait", action="store_true")
    s.add_argument("--foreground", action="store_true")
    s.set_defaults(fn=cmd_plan)
    s = sub.add_parser("stop", help="local runner: stop a running scan or plan")
    s.add_argument("run")
    s.set_defaults(fn=cmd_stop)
    s = sub.add_parser("_worker")  # internal: detached local run
    s.add_argument("kind", choices=["scans", "plans"])
    s.add_argument("run")
    s.set_defaults(fn=cmd_worker)
    sub.add_parser("run-now", help="fire the scheduled deployment once, now").set_defaults(fn=cmd_run_now)
    sub.add_parser("status", help="agents, deployment and last runs").set_defaults(fn=cmd_status)
    s = sub.add_parser("outputs", help="download every output file of a session to ./outputs/<session>/")
    s.add_argument("session", nargs="?")
    s.set_defaults(fn=cmd_outputs)
    s = sub.add_parser("schedule", help="pause or unpause the deployment")
    s.add_argument("action", choices=["install", "remove", "pause", "unpause"])
    s.set_defaults(fn=cmd_schedule)
    s = sub.add_parser("dashboard", help="build (and open) the Migration Control dashboard")
    s.add_argument("--serve", action="store_true", help="serve on 127.0.0.1 with a live feed of running sessions")
    s.add_argument("--offline", action="store_true", help="rebuild from the local cache only (no API key needed)")
    s.add_argument("--port", type=int, default=8765)
    s.add_argument("--no-open", action="store_true")
    s.set_defaults(fn=cmd_dashboard)

    a = p.parse_args(argv)
    try:
        a.fn(a)
    except (config.ConfigError, ApiError, RuntimeError, ValueError) as e:
        sys.exit(f"✗ {e}")
    except KeyboardInterrupt:
        sys.exit(130)


if __name__ == "__main__":
    main()
