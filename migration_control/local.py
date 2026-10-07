"""Local runner: the same scanner / planner / grader loop, run by Claude Code headless on this machine.

    runner: {type: local, isolation: docker}   one container per run (default, recommended)
    runner: {type: local, isolation: none}     directly on this machine

Each run gets a working dir .mig/work/<run>/ laid out like the managed sandbox:

    workspace/  → /workspace              the modules, checked out locally (tokens never leave this machine)
    outputs/    → /mnt/session/outputs    deliverables
    uploads/    → /mnt/session/uploads    inputs (the planner's impact-report.json)
    home/       → $HOME in the container  Claude Code config + the regulated-sourcing skill
    .mig/memory → /mnt/memory             persistent across runs (the "memory store")

With docker the prompts are used verbatim; with isolation none the paths are rewritten to the host dirs.
Auth: docker needs CLAUDE_CODE_OAUTH_TOKEN (`claude setup-token`, Claude subscription) or ANTHROPIC_API_KEY
in the environment / .env; isolation none uses your normal Claude Code login.
"""
import json
import os
import shutil
import signal
import subprocess
import sys
import time
import uuid
from datetime import datetime, timezone
from pathlib import Path

from . import RESOURCES, render
from .estate import materialize
from .runs import PLAN_FILES, SCAN_FILES, phase_of, tool_label

PR_FILES = ("pr.json", "pr-description.md")

AUTH_VARS = ("CLAUDE_CODE_OAUTH_TOKEN", "ANTHROPIC_API_KEY")
DEFAULT_IMAGE = "node:22-bookworm"
SANDBOX_PATHS = {  # container path → run-dir subfolder (longest first for rewriting)
    "/mnt/session/outputs": "outputs",
    "/mnt/session/uploads": "uploads",
    "/mnt/memory": None,          # → .mig/memory
    "/workspace": "workspace",
}
TOOL_NAMES = {"Bash": "bash", "Read": "read", "Write": "write", "Edit": "edit", "MultiEdit": "edit", "Glob": "glob",
              "Grep": "grep", "WebSearch": "web_search", "WebFetch": "web_fetch", "NotebookEdit": "edit"}
GRADER_SYSTEM = (
    "You are an independent grader. You did not write these outputs. Read the real files and check every rubric "
    "criterion strictly; a criterion is met only if the evidence is in the files. Never modify any file. "
    "Return one entry per rubric criterion, numbered as in the rubric.")
GRADER_SCHEMA = {
    "type": "object", "additionalProperties": False, "required": ["criteria", "summary"],
    "properties": {
        "criteria": {"type": "array", "items": {"type": "object", "additionalProperties": False, "required": ["n", "met", "note"],
                     "properties": {"n": {"type": "integer"}, "met": {"type": "boolean"}, "note": {"type": "string"}}}},
        "summary": {"type": "string"},
    },
}


def now_iso():
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")


def model_of(cfg):
    m = cfg["agents"]["model"]
    return "opus" if m == "auto" else m


# ── image (docker isolation) ─────────────────────────────────────────────────
def dockerfile(cfg):
    pk = cfg["sandbox"].get("packages") or {}
    apt = ["git", "curl", "ca-certificates", "python3", "python3-pip", "python3-venv", "jq", "unzip", *pk.get("apt", [])]
    lines = [f"FROM {cfg['runner'].get('image') or DEFAULT_IMAGE}",
             "ENV DEBIAN_FRONTEND=noninteractive PIP_BREAK_SYSTEM_PACKAGES=1",
             f"RUN apt-get update && apt-get install -y --no-install-recommends {' '.join(sorted(set(apt)))} && rm -rf /var/lib/apt/lists/*",
             f"RUN npm install -g @anthropic-ai/claude-code {' '.join(pk.get('npm', []))}".rstrip(),
             f"RUN pip3 install --no-cache-dir jsonschema openpyxl {' '.join(pk.get('pip', []))}".rstrip(),
             "RUN mkdir -p /workspace /mnt/session/outputs /mnt/session/uploads /mnt/memory /mnt/home && chmod 777 /workspace /mnt/session/outputs /mnt/session/uploads /mnt/memory /mnt/home",
             "WORKDIR /workspace"]
    return "\n".join(lines) + "\n"


def image_tag(cfg):
    return f"mig-{cfg['project']}:{render.fingerprint(dockerfile(cfg))[:12]}"


DOCKER_DESKTOP_BIN = "/Applications/Docker.app/Contents/Resources/bin"


def _docker_path():
    """Docker Desktop's credential helper is often missing from PATH when the docker CLI comes from Homebrew."""
    path = os.environ.get("PATH", "")
    if os.path.isdir(DOCKER_DESKTOP_BIN) and DOCKER_DESKTOP_BIN not in path.split(os.pathsep):
        os.environ["PATH"] = path + os.pathsep + DOCKER_DESKTOP_BIN


def docker_ok():
    _docker_path()
    try:
        r = subprocess.run(["docker", "info", "--format", "{{.ServerVersion}}"], capture_output=True, text=True, timeout=20)
    except FileNotFoundError:
        raise RuntimeError("docker is not installed — install Docker, or set runner.isolation: none")
    if r.returncode:
        raise RuntimeError("the Docker daemon is not running — start Docker Desktop / dockerd, or set runner.isolation: none")
    return r.stdout.strip()


def build_image(cfg, st, log=print):
    docker_ok()
    tag = image_tag(cfg)
    if subprocess.run(["docker", "image", "inspect", tag], capture_output=True).returncode == 0:
        log(f"  image {tag} (exists)")
        return tag
    unsupported = set(cfg["sandbox"].get("packages") or {}) - {"apt", "npm", "pip"}
    if unsupported:
        log(f"  note: sandbox.packages {sorted(unsupported)} are not installed by the local image (apt/npm/pip only)")
    ctx = st.dir / "image"
    ctx.mkdir(parents=True, exist_ok=True)
    (ctx / "Dockerfile").write_text(dockerfile(cfg))
    log(f"  building image {tag} (first time only, a few minutes)…")
    r = subprocess.run(["docker", "build", "-t", tag, str(ctx)], capture_output=True, text=True)
    if r.returncode:
        raise RuntimeError("docker build failed:\n" + r.stderr[-1500:])
    log(f"  image {tag} (built)")
    return tag


# ── auth ─────────────────────────────────────────────────────────────────────
def auth_status(cfg):
    if cfg["runner"]["isolation"] == "docker":
        have = [v for v in AUTH_VARS if os.environ.get(v)]
        if not have:
            raise RuntimeError("set CLAUDE_CODE_OAUTH_TOKEN (run `claude setup-token`, Claude subscription) or ANTHROPIC_API_KEY "
                               "in your environment or .env — the container cannot read your local Claude Code login")
        return f"{have[0]} set"
    if not shutil.which("claude"):
        raise RuntimeError("claude (Claude Code) is not on PATH — https://docs.claude.com/en/docs/claude-code")
    try:
        r = subprocess.run(["claude", "auth", "status"], capture_output=True, text=True, timeout=30, stdin=subprocess.DEVNULL)
    except subprocess.TimeoutExpired:
        raise RuntimeError("`claude auth status` did not answer within 30 s — check that Claude Code runs (`claude --version`)")
    try:
        d = json.loads(r.stdout)
    except ValueError:
        d = {}
    if not d.get("loggedIn") and not os.environ.get("ANTHROPIC_API_KEY"):
        raise RuntimeError("Claude Code is not logged in — run `claude` once and log in, or set ANTHROPIC_API_KEY")
    return f"Claude Code logged in ({d.get('authMethod', 'api key')})"


# ── up ───────────────────────────────────────────────────────────────────────
def up(cfg, st, log=print):
    log(f"▶ runner: local · isolation {cfg['runner']['isolation']} · model {model_of(cfg)}")
    log(f"  auth: {auth_status(cfg)}")
    if cfg["runner"]["isolation"] == "docker":
        st.set("local", "image", value=build_image(cfg, st, log))
    else:
        log("  ⚠ isolation none: the agent runs shell commands and builds directly on this machine, without permission prompts.")
    (st.dir / "memory").mkdir(parents=True, exist_ok=True)
    st.cache.mkdir(parents=True, exist_ok=True)
    roles = ["scanner"] + (["planner"] if cfg["agents"]["planner"] else [])
    (st.cache / "agents.json").write_text(json.dumps({r: {"id": f"local-{r}", "name": f"{cfg['project']}-{r}", "version": None,
        "skills": [{"type": "custom", "id": "regulated-sourcing", "version": "local", "name": "regulated-sourcing"}]} for r in roles}, indent=2))
    if cfg.get("schedule"):
        log(f"  schedule {cfg['schedule']['cron']} is not installed automatically — run `mig schedule install` (cron)")


# ── runs ─────────────────────────────────────────────────────────────────────
def new_run_id():
    return datetime.now().strftime("run-%Y%m%d-%H%M%S-") + uuid.uuid4().hex[:4]


def _kind_dir(st, kind):
    return st.cache / kind


def prepare(cfg, st, kind, scan_session=None, log=print, plan_run=None, wave=None):
    """Create the run dir, check out every module, write meta.json (status queued). Returns run id."""
    rid = new_run_id()
    work = st.dir / "work" / rid
    for sub in ("workspace", "outputs", "uploads", "home"):
        (work / sub).mkdir(parents=True, exist_ok=True)
    (st.dir / "memory").mkdir(parents=True, exist_ok=True)
    for m in cfg.modules:
        log(f"  {m.name}: {materialize(cfg, m, work / 'workspace')}")
    skill_dst = work / "home" / ".claude" / "skills" / "regulated-sourcing"
    shutil.copytree(RESOURCES / "skills" / "regulated-sourcing", skill_dst)
    if cfg["runner"]["isolation"] == "none":   # project-level skill for a host run (cwd = workspace)
        shutil.copytree(RESOURCES / "skills" / "regulated-sourcing", work / "workspace" / ".claude" / "skills" / "regulated-sourcing")
    if kind == "plans":
        src = _kind_dir(st, "scans") / scan_session / "impact-report.json"
        if not src.exists():
            raise RuntimeError(f"scan {scan_session} has no impact-report.json")
        shutil.copy(src, work / "uploads" / "impact-report.json")
    if kind == "prs":
        plan_dir = _kind_dir(st, "plans") / plan_run
        if not (plan_dir / "migration-plan.json").exists():
            raise RuntimeError(f"plan {plan_run} has no migration-plan.json")
        waves = [w["wave"] for w in json.loads((plan_dir / "migration-plan.json").read_text()).get("waves", [])]
        if wave not in waves:
            raise RuntimeError(f"plan {plan_run} has no wave {wave} (waves: {waves})")
        shutil.copy(plan_dir / "migration-plan.json", work / "uploads" / "migration-plan.json")
        if (plan_dir / f"wave-{wave}.patch").exists():
            shutil.copy(plan_dir / f"wave-{wave}.patch", work / "uploads" / "wave.patch")
        if (plan_dir / "outputs" / "evidence").exists():
            shutil.copytree(plan_dir / "outputs" / "evidence", work / "uploads" / "plan-evidence")
    d = _kind_dir(st, kind) / rid
    d.mkdir(parents=True, exist_ok=True)
    title = f"PR · wave {wave} (local)" if kind == "prs" else f"{kind[:-1]} (local)"
    meta = {"id": rid, "title": title, "created_at": now_iso(), "status": "queued", "runner": "local",
            "trigger": os.environ.get("MIG_TRIGGER", "manual"), "scan_session": scan_session, "agent_version": None,
            "plan_run": plan_run, "wave": wave, "review": {"state": "pending"} if kind == "prs" else None,
            "verdicts": [], "explanation": "", "active_seconds": 0, "list_cost_cents": None, "console": ""}
    (d / "meta.json").write_text(json.dumps(meta, indent=2))
    st.set("last", {"scans": "scan", "plans": "plan", "prs": "pr"}[kind], value=rid)
    return rid


def start(cfg, st, kind, rid, foreground=False):
    """Run the worker for a prepared run — inline, or detached so the CLI returns immediately."""
    if foreground:
        return work(cfg, st, kind, rid)
    log = open(st.dir / "work" / rid / "worker.log", "w")
    p = subprocess.Popen([sys.executable, "-m", "migration_control", "_worker", kind, rid], cwd=cfg.root,
                         stdout=log, stderr=subprocess.STDOUT, stdin=subprocess.DEVNULL, start_new_session=True)
    _update_meta(st, kind, rid, pid=p.pid)
    return p.pid


def _update_meta(st, kind, rid, **kw):
    p = _kind_dir(st, kind) / rid / "meta.json"
    meta = json.loads(p.read_text())
    meta.update(kw)
    p.write_text(json.dumps(meta, indent=2))
    return meta


class Timeline:
    """Turns Claude Code stream-json events into the dashboard's timeline items, flushed for the live view."""

    def __init__(self, path, t0, unmap=None):
        self.path, self.t0, self.items, self.errs, self.last_flush = path, t0, [], {}, 0
        self.unmap = sorted((unmap or {}).items(), key=lambda kv: -len(kv[0]))   # host path → sandbox path
        if path.exists():   # resuming a paused run: continue its timeline
            try:
                self.items = json.loads(path.read_text())
            except ValueError:
                self.items = []

    def _sandbox_paths(self, obj):
        s = json.dumps(obj)
        for host, box in self.unmap:
            s = s.replace(host, box)
        return json.loads(s)

    def t(self):
        return round(time.time() - self.t0, 1)

    def add(self, item, force=False):
        self.items.append(item)
        self.flush(force)

    def event(self, e):
        k = e.get("type")
        if k == "assistant":
            for c in (e.get("message") or {}).get("content") or []:
                if c.get("type") == "tool_use":
                    name = c.get("name") or ""
                    inp = self._sandbox_paths(c.get("input") or {})
                    if name == "Skill":
                        label, tool = f"/skills/{inp.get('skill') or inp.get('command') or 'skill'}/", "read"
                    else:
                        tool = TOOL_NAMES.get(name, name.lower())
                        label = tool_label({"input": inp})
                    ph = phase_of(tool, label)
                    item = {"t": self.t(), "k": "tool", "id": c.get("id"), "tool": tool, "label": label, "phase": ph}
                    if ph == "skill":
                        item["skill"] = label.split("/skills/")[1].split("/")[0]
                    self.items.append(item)
                elif c.get("type") == "text" and (c.get("text") or "").strip():
                    self.items.append({"t": self.t(), "k": "msg", "text": c["text"].strip()[:220]})
        elif k == "user":
            for c in (e.get("message") or {}).get("content") or []:
                if isinstance(c, dict) and c.get("type") == "tool_result":
                    self.errs[c.get("tool_use_id")] = bool(c.get("is_error"))
        self.flush()

    def flush(self, force=False):
        if not force and time.time() - self.last_flush < 3:
            return
        out = []
        for it in self.items:
            it = dict(it)
            if it["k"] == "tool" and "id" in it:
                it["err"] = self.errs.get(it.pop("id"), False)
            out.append(it)
        self.path.write_text(json.dumps(out))
        self.last_flush = time.time()


def _paths(cfg, st, rid):
    work = st.dir / "work" / rid
    host = {"/mnt/session/outputs": work / "outputs", "/mnt/session/uploads": work / "uploads",
            "/mnt/memory": st.dir / "memory", "/workspace": work / "workspace"}
    return work, host


def _localize(text, host):
    for k in SANDBOX_PATHS:  # longest container paths first
        text = text.replace(k, str(host[k].resolve()))
    return text


def _claude_cmd(cfg, st, rid, args, host):
    """Full argv for one claude invocation (inside docker or on the host)."""
    _docker_path()
    if cfg["runner"]["isolation"] == "none":
        adds = [a for k in ("/mnt/session/outputs", "/mnt/session/uploads", "/mnt/memory") for a in ("--add-dir", str(host[k].resolve()))]
        return ["claude", *args, *adds], str(host["/workspace"].resolve())
    work = st.dir / "work" / rid
    vols = []
    for cpath, hpath in (("/workspace", host["/workspace"]), ("/mnt/session/outputs", host["/mnt/session/outputs"]),
                         ("/mnt/session/uploads", host["/mnt/session/uploads"]), ("/mnt/memory", host["/mnt/memory"]),
                         ("/mnt/home", work / "home")):
        vols += ["-v", f"{hpath.resolve()}:{cpath}"]
    envs = [x for v in AUTH_VARS if os.environ.get(v) for x in ("-e", v)]   # values come from our env, never argv
    # Linux: run as the host uid so bind-mounted files stay yours; Docker Desktop maps ownership itself → image's `node` user
    user = ["--user", f"{os.getuid()}:{os.getgid()}"] if sys.platform.startswith("linux") else ["--user", "node"]
    image = st.get("local", "image") or image_tag(cfg)
    return ["docker", "run", "--rm", "-i", "--name", f"mig-{rid}-{uuid.uuid4().hex[:4]}", *user, *vols, *envs,
            "-e", "HOME=/mnt/home", "-w", "/workspace", image, "claude", *args], None


def _run_claude(cfg, st, rid, args, prompt, host, on_event=None):
    cmd, cwd = _claude_cmd(cfg, st, rid, args, host)
    p = subprocess.Popen(cmd, cwd=cwd, stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
    p.stdin.write(prompt)
    p.stdin.close()
    result = None
    for line in p.stdout:
        try:
            e = json.loads(line)
        except ValueError:
            continue
        if e.get("type") == "result":
            result = e
        if on_event:
            on_event(e)
    p.wait()
    if result is None:
        err = p.stderr.read()[-800:]
        if _is_limit(err):
            raise UsageLimit(err.strip())
        raise RuntimeError(f"claude exited with code {p.returncode}: {err}")
    if result.get("is_error"):
        text = str(result.get("result") or result.get("subtype") or "")
        if _is_limit(text) or result.get("api_error_status") == 429:
            raise UsageLimit(text.strip(), result)
        raise RuntimeError(f"claude reported an error: {text[:500]}")
    return result


class UsageLimit(Exception):
    """Claude subscription / rate limit reached — the run is paused and can be resumed."""

    def __init__(self, message, result=None):
        super().__init__(message)
        self.result = result or {}


def _is_limit(text):
    t = (text or "").lower()
    return any(k in t for k in ("usage limit", "session limit", "hit your limit", "rate limit", "rate_limit", "resets "))


def _grade(cfg, st, rid, host, task, rubric, loc):
    prompt = (f"Grade this run against the rubric below.\n\n# Rubric\n{rubric}\n\n# The task the agent was given\n{task}\n\n"
              "Deliverables are in /mnt/session/outputs/ and the code in /workspace/. Read the real files "
              "(you may run read-only commands, e.g. validate JSON with python3 and jsonschema). Do not modify anything.")
    args = ["-p", "--output-format", "stream-json", "--verbose", "--model", model_of(cfg), "--permission-mode", "bypassPermissions",
            "--disallowedTools", "Write", "Edit", "NotebookEdit", "--no-session-persistence",
            "--append-system-prompt", GRADER_SYSTEM, "--json-schema", json.dumps(GRADER_SCHEMA)]
    res = _run_claude(cfg, st, rid, args, loc(prompt), host)
    g = res.get("structured_output")
    if not isinstance(g, dict):
        try:
            g = json.loads(res.get("result") or "")
        except ValueError:
            raise RuntimeError("the grader returned no structured verdict")
    return g, res


def work(cfg, st, kind, rid):
    """Agent → grader → (fix → grader)… up to max_iterations. Writes meta/timeline/outputs into the cache.

    Progress (session, iteration, phase, next prompt, cost) is checkpointed in meta.json, so a run cut by a
    usage limit is left `paused` with its workspace intact and `mig resume <run>` picks it up where it stopped.
    """
    d = _kind_dir(st, kind) / rid
    meta = json.loads((d / "meta.json").read_text())
    work_dir, host = _paths(cfg, st, rid)
    loc = (lambda s: _localize(s, host)) if cfg["runner"]["isolation"] == "none" else (lambda s: s)
    if kind == "scans":
        system, task, rubric = (render.scanner_agent(cfg, "-", "-")["system"], render.scanner_task(cfg), render.scanner_rubric(cfg))
    elif kind == "plans":
        system, task, rubric = (render.planner_agent(cfg, "-", "-")["system"], render.planner_task(cfg, meta["scan_session"]),
                                render.planner_rubric(cfg))
    else:
        system, task, rubric = (render.pr_system(cfg),
                                render.pr_task(cfg, meta["plan_run"], meta["wave"], (work_dir / "uploads" / "wave.patch").exists()),
                                render.pr_rubric(cfg))
    resuming = bool(meta.get("progress"))
    if resuming and not (work_dir / "workspace").exists():
        raise RuntimeError(f"{rid} cannot be resumed: its workspace is gone — start a new run")
    p = meta.get("progress") or {"sid": str(uuid.uuid4()), "it": 1, "phase": "agent", "prompt": loc(task),
                                  "started": False, "cost": 0.0, "active": 0.0, "verdicts": []}
    t0 = time.time() if not meta.get("started_at") else datetime.fromisoformat(meta["started_at"].replace("Z", "+00:00")).timestamp()
    unmap = {str(v.resolve()): k for k, v in host.items()} if cfg["runner"]["isolation"] == "none" else {}
    tl = Timeline(d / "timeline.json", t0, unmap)
    if resuming:
        tl.add({"t": tl.t(), "k": "msg", "text": "▶ resumed after the usage limit"}, force=True)
    _update_meta(st, kind, rid, status="running", pid=os.getpid(), progress=p, **({} if resuming else {"started_at": now_iso()}))
    max_it = cfg["agents"]["max_iterations"]
    budget = cfg["agents"].get("budget_usd")
    base = ["-p", "--output-format", "stream-json", "--verbose", "--model", model_of(cfg), "--permission-mode", "bypassPermissions",
            "--append-system-prompt", loc(system)]

    def save(**kw):
        p.update(kw)
        return _update_meta(st, kind, rid, progress=p, verdicts=p["verdicts"], active_seconds=round(p["active"], 1),
                            list_cost_cents=round(p["cost"] * 100))

    def stop(sig, _frm):
        _update_meta(st, kind, rid, status="terminated", explanation="stopped by user")
        tl.flush(force=True)
        sys.exit(130)
    signal.signal(signal.SIGTERM, stop)

    def on_event(e):
        if e.get("type") == "assistant" and not p["started"]:
            save(started=True)          # the conversation is on disk: from now on we resume it
        tl.event(e)

    try:
        while True:
            if p["phase"] == "agent":
                args = base + (["--resume", p["sid"]] if p["started"] else ["--session-id", p["sid"]])
                if budget:
                    args += ["--max-budget-usd", f"{max(0.5, budget - p['cost']):.2f}"]
                res = _run_claude(cfg, st, rid, args, p["prompt"], host, on_event=on_event)
                save(cost=p["cost"] + (res.get("total_cost_usd") or 0), active=p["active"] + (res.get("duration_ms") or 0) / 1000,
                     phase="grade")
            tl.add({"t": tl.t(), "k": "eval_start", "iteration": p["it"]}, force=True)
            g, gres = _grade(cfg, st, rid, host, task, rubric, loc)
            failed = [c for c in g.get("criteria", []) if not c.get("met")]
            last = p["it"] >= max_it
            result = "satisfied" if not failed else ("max_iterations_reached" if last else "needs_revision")
            explanation = ("An independent grader " + ("found all criteria met: " if not failed else f"found {len(failed)} criteria not met: ")
                           + " ".join(f"({c['n']}) {c['note']}" for c in sorted(g.get("criteria", []), key=lambda c: c["n"]))
                           + (f" Summary: {g.get('summary')}" if g.get("summary") else ""))
            tl.add({"t": tl.t(), "k": "eval_end", "result": result, "text": explanation[:400]}, force=True)
            save(cost=p["cost"] + (gres.get("total_cost_usd") or 0), active=p["active"] + (gres.get("duration_ms") or 0) / 1000,
                 verdicts=p["verdicts"] + [result])
            _update_meta(st, kind, rid, explanation=explanation)
            if not failed or last:
                break
            save(it=p["it"] + 1, phase="agent",
                 prompt=loc("An independent grader checked your outputs against the rubric. These criteria are NOT met:\n"
                            + "\n".join(f"- ({c['n']}) {c['note']}" for c in failed)
                            + "\n\nFix every one of them in /mnt/session/outputs/ (re-check the code and sources as needed), then finish."))
        tl.add({"t": tl.t(), "k": "idle"}, force=True)
        _collect(kind, work_dir, d)
        _update_meta(st, kind, rid, status="idle", finished_at=now_iso(), progress=None)
    except UsageLimit as e:
        p["cost"] += e.result.get("total_cost_usd") or 0           # the interrupted call still counts
        p["active"] += (e.result.get("duration_ms") or 0) / 1000
        if p["phase"] == "agent" and p["started"]:
            p["prompt"] = "You were interrupted by a usage limit. Continue the task exactly where you stopped and finish it."
        elif p["phase"] == "agent":
            p["sid"] = str(uuid.uuid4())   # nothing was recorded: start the conversation afresh on resume
        tl.add({"t": tl.t(), "k": "msg", "text": f"⏸ paused: Claude usage limit ({str(e)[:120]})"}, force=True)
        _update_meta(st, kind, rid, status="paused", progress=p, list_cost_cents=round(p["cost"] * 100),
                     active_seconds=round(p["active"], 1),
                     explanation=f"Claude usage limit reached ({str(e)[:200]}). Run `mig resume {rid}` once it resets.")
        return "paused"
    except Exception as e:  # keep a readable trace in the dashboard
        tl.flush(force=True)
        _update_meta(st, kind, rid, status="terminated", explanation=f"run failed: {e}"[:2000])
        _cleanup(work_dir)
        raise
    _cleanup(work_dir)
    return p["verdicts"][-1] if p["verdicts"] else None


def _cleanup(work_dir):
    for sub in ("workspace", "home"):
        shutil.rmtree(work_dir / sub, ignore_errors=True)


def resume(cfg, st, rid, foreground=False):
    for kind in ("scans", "plans", "prs"):
        mp = _kind_dir(st, kind) / rid / "meta.json"
        if mp.exists():
            m = json.loads(mp.read_text())
            if m.get("status") != "paused":
                raise RuntimeError(f"{rid} is {m.get('status')}, not paused")
            return kind, start(cfg, st, kind, rid, foreground=foreground)
    raise RuntimeError(f"no local run {rid}")


def _collect(kind, work_dir, d):
    out = work_dir / "outputs"
    shutil.copytree(out, d / "outputs", dirs_exist_ok=True)
    wanted = {"scans": SCAN_FILES, "plans": PLAN_FILES, "prs": PR_FILES}[kind]
    for f in out.iterdir():
        if f.is_file() and (f.name in wanted or (kind in ("plans", "prs") and f.name.endswith(".patch"))):
            shutil.copy(f, d / f.name)


# ── status / live ────────────────────────────────────────────────────────────
def _alive(pid):
    try:
        os.kill(pid, 0)
        return True
    except (OSError, TypeError):
        return False


def list_runs(st, kind):
    base = _kind_dir(st, kind)
    out = []
    for p in sorted(base.glob("*/meta.json")) if base.exists() else []:
        m = json.loads(p.read_text())
        if m.get("status") in ("running", "queued") and m.get("pid") and not _alive(m["pid"]):
            m = _update_meta(st, kind, m["id"], status="terminated",
                             explanation=m.get("explanation") or "worker exited unexpectedly — see .mig/work/<run>/worker.log")
        out.append(m)
    return sorted(out, key=lambda m: m.get("created_at") or "")


def running_runs(st):
    out = []
    for kind, role in (("scans", "scanner"), ("plans", "planner"), ("prs", "pr")):
        for m in list_runs(st, kind):
            if m.get("status") not in ("running", "queued"):
                continue
            tl = _kind_dir(st, kind) / m["id"] / "timeline.json"
            out.append({"role": role, "session": m["id"], "title": m.get("title"), "status": "running", "created_at": m.get("created_at"),
                        "active_seconds": round(time.time() - datetime.fromisoformat(m["created_at"].replace("Z", "+00:00")).timestamp()),
                        "evaluations": m.get("verdicts") or [], "timeline": json.loads(tl.read_text()) if tl.exists() else [], "console": ""})
    return out


def stop_run(st, rid):
    for kind in ("scans", "plans", "prs"):
        p = _kind_dir(st, kind) / rid / "meta.json"
        if p.exists():
            m = json.loads(p.read_text())
            if m.get("pid") and _alive(m["pid"]):
                os.killpg(os.getpgid(m["pid"]), signal.SIGTERM)
            for cid in subprocess.run(["docker", "ps", "-q", "--filter", f"name=mig-{rid}"], capture_output=True, text=True).stdout.split():
                subprocess.run(["docker", "kill", cid], capture_output=True)
            return _update_meta(st, kind, rid, status="terminated", explanation="stopped by user")
    raise RuntimeError(f"no local run {rid}")


# ── schedule (cron) ──────────────────────────────────────────────────────────
MARK = "# migration-control:"


def _crontab():
    r = subprocess.run(["crontab", "-l"], capture_output=True, text=True)
    return r.stdout if r.returncode == 0 else ""


def schedule_install(cfg, st):
    if not cfg.get("schedule"):
        raise RuntimeError("add `schedule:` to migration.yaml first")
    mig = shutil.which("mig") or f"{sys.executable} -m migration_control"
    tag = f"{MARK}{cfg.root}"
    line = (f"{cfg['schedule']['cron']} cd '{cfg.root}' && PATH='{os.environ.get('PATH', '')}' MIG_TRIGGER=schedule "
            f"{mig} scan --foreground >> '{st.dir / 'cron.log'}' 2>&1 {tag}")
    lines = [l for l in _crontab().splitlines() if tag not in l]
    subprocess.run(["crontab", "-"], input="\n".join(lines + [line]) + "\n", text=True, check=True)
    return line


def schedule_remove(cfg):
    tag = f"{MARK}{cfg.root}"
    lines = [l for l in _crontab().splitlines() if tag not in l]
    subprocess.run(["crontab", "-"], input="\n".join(lines) + ("\n" if lines else ""), text=True, check=True)


def schedule_installed(cfg):
    return any(f"{MARK}{cfg.root}" in l for l in _crontab().splitlines())
