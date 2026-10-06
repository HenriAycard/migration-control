"""Start runs (scan, plan), follow them, and cache their outputs + condensed timelines in .mig/runs/."""
import json
import re
from datetime import datetime

from . import render
from .estate import resources, sync_uploads
from .provision import budget, memory_resource

SCAN_FILES = ("impact-report.json", "impact-summary.md", "impact-report.md", "impact-report.xlsx")
PLAN_FILES = ("migration-plan.json", "migration-plan-summary.md", "migration-plan.md")


def _need(st, *keys, hint="run `mig up` first"):
    v = st.get(*keys)
    if not v:
        raise RuntimeError(f"{'.'.join(keys)} missing — {hint}")
    return v


# ── start runs ───────────────────────────────────────────────────────────────
def start_scan(cfg, client, st, log=print):
    scanner = _need(st, "agents", "scanner")
    sync_uploads(cfg, st, client, log)
    body = {
        "agent": {"type": "agent", "id": scanner["id"], "version": scanner["version"]},
        "environment_id": _need(st, "environment", "id"),
        "title": "scan (manual)",
        "metadata": {"role": "scan", "tool": "migration-control"},
        "resources": [memory_resource(st), *resources(cfg, st)],
        "initial_events": [render.outcome_event(cfg, render.scanner_task(cfg), render.scanner_rubric(cfg))],
    }
    if budget(cfg):
        body["budget"] = budget(cfg)
    s = client.post("/sessions", body)
    st.set("last", "scan", value=s["id"])
    return s


def start_plan(cfg, client, st, scan_session=None, log=print):
    planner = _need(st, "agents", "planner", hint="enable agents.planner and run `mig up`")
    scan_session = scan_session or latest_scan_with_report(client, st, cfg)
    report = st.cache / "scans" / scan_session / "impact-report.json"
    if not report.exists():
        fetch_session(client, st, cfg, scan_session, "scans")
    if not report.exists():
        raise RuntimeError(f"scan {scan_session} has no impact-report.json")
    f = client.upload_file(report, "application/json")
    sync_uploads(cfg, st, client, log)
    body = {
        "agent": {"type": "agent", "id": planner["id"], "version": planner["version"]},
        "environment_id": _need(st, "environment", "id"),
        "title": f"plan from scan {scan_session}",
        "metadata": {"role": "plan", "scan_session": scan_session, "tool": "migration-control"},
        "resources": [{"type": "file", "file_id": f["id"], "mount_path": "/mnt/session/uploads/impact-report.json"},
                      *resources(cfg, st)],
        "initial_events": [render.outcome_event(cfg, render.planner_task(cfg, scan_session), render.planner_rubric(cfg))],
    }
    if budget(cfg):
        body["budget"] = budget(cfg)
    s = client.post("/sessions", body)
    st.set("last", "plan", value=s["id"])
    return s


def run_deployment_now(client, st):
    dep = _need(st, "deployment", "id", hint="add a schedule to migration.yaml and run `mig up`")
    return client.post(f"/deployments/{dep}/run", {}, params={"beta": "true"})


def latest_scan_with_report(client, st, cfg):
    refresh(client, st, cfg)
    scans = sorted((p for p in (st.cache / "scans").glob("*/impact-report.json")),
                   key=lambda p: json.loads((p.parent / "meta.json").read_text()).get("created_at") or "")
    if not scans:
        raise RuntimeError("no finished scan with an impact-report.json yet — run `mig scan` and wait for it")
    return scans[-1].parent.name


# ── status ───────────────────────────────────────────────────────────────────
def session_status(client, sid):
    d = client.get(f"/sessions/{sid}")
    u = d.get("usage") or {}
    return {"id": sid, "status": d.get("status"), "title": d.get("title"),
            "verdicts": [e.get("result") for e in d.get("outcome_evaluations", [])],
            "cost_usd": (u.get("list_cost") or 0) / 100 if u.get("list_cost") is not None else None,
            "active_min": round((u.get("active_seconds") or 0) / 60, 1)}


# ── cache: outputs + timelines ───────────────────────────────────────────────
EVENT_TYPES = ["agent.tool_use", "agent.tool_result", "agent.message", "span.outcome_evaluation_start",
               "span.outcome_evaluation_end", "session.status_idle", "session.status_running",
               "agent.mcp_tool_use", "agent.mcp_tool_result", "user.tool_confirmation"]
PHASES = [  # (phase, regex on "tool label") — first match wins
    ("skill", r"/skills/[A-Za-z0-9_-]+/"),
    ("memory", r"/mnt/memory"),
    ("setup", r"git clone|git -C .* checkout|tar -?x|/mnt/session/uploads"),
    ("build", r"\bmvn\b|mvnw|gradle|javac|npm (ci|install|run)|yarn|pnpm|\bng (build|update|test)|npx|pip install|venv|pytest|go (build|test)|cargo|dotnet|bundle|w\d_gate|/logs?/\S*(build|baseline|B\d)|\bbuild\S*\.log"),
    ("research", r"^web_(search|fetch)|curl -s|osv\.dev|nvd\.nist|registry\.npmjs|pypi\.org|maven|endoflife|adoptium|nodejs\.org|github\.com/advisories|/data/raw|cpu(jan|apr|jul|oct)\d{4}|\.html\b"),
    ("report", r"^write\b|/mnt/session/outputs|impact-report|impact-summary|migration-plan|jsonschema|\.patch"),
    ("code", r"/workspace/|grep -r|cat -n|sed -n"),
]


def tool_label(e):
    i = e.get("input") or {}
    raw = i.get("command") or i.get("query") or i.get("url") or i.get("file_path") or i.get("pattern") or i.get("path") or ""
    lines = [l.strip() for l in str(raw).splitlines() if l.strip() and not l.strip().startswith("#")]
    first = next((l for l in lines if "/skills/" in l), lines[0] if lines else "")
    if "/skills/" in first and len(first) > 160:
        k = first.index("/skills/"); first = first[max(0, k - 40):]
    return first[:160]


def phase_of(tool, label):
    s = f"{tool} {label}"
    for ph, rx in PHASES:
        if re.search(rx, s, re.I):
            return ph
    return "analysis"


def session_timeline(client, sid, max_events=4000):
    """Condensed, replayable event list: [{t, k, tool, label, phase, err, text, result}] (t = seconds from start)."""
    items, errs, start, n = [], {}, None, 0
    params = [("limit", "100")] + [("types[]", t) for t in EVENT_TYPES]
    for e in client.paged(f"/sessions/{sid}/events", params):
        n += 1
        try:
            t = datetime.fromisoformat((e.get("processed_at") or "").replace("Z", "+00:00")).timestamp()
        except ValueError:
            continue
        start = start if start is not None else t
        rt, k = round(t - start, 1), e["type"]
        if k == "agent.tool_use":
            label = tool_label(e)
            ph = phase_of(e.get("name"), label)
            item = {"t": rt, "k": "tool", "id": e.get("id"), "tool": e.get("name"), "label": label, "phase": ph}
            if ph == "skill":
                item["skill"] = re.search(r"/skills/([A-Za-z0-9_-]+)/", label).group(1)
            items.append(item)
        elif k in ("agent.tool_result", "agent.mcp_tool_result"):
            errs[e.get("tool_use_id") or e.get("mcp_tool_use_id")] = str(e.get("is_error")).lower() == "true"
        elif k == "agent.message":
            txt = " ".join(c.get("text", "") for c in (e.get("content") or []) if isinstance(c, dict))
            if txt.strip():
                items.append({"t": rt, "k": "msg", "text": txt.strip()[:220]})
        elif k == "span.outcome_evaluation_start":
            items.append({"t": rt, "k": "eval_start", "iteration": e.get("iteration")})
        elif k == "span.outcome_evaluation_end":
            items.append({"t": rt, "k": "eval_end", "result": e.get("result"), "text": (e.get("explanation") or "")[:400]})
        elif k == "session.status_idle":
            sr = e.get("stop_reason") or {}
            items.append({"t": rt, "k": "await", "ids": sr.get("event_ids") or []} if sr.get("type") == "requires_action" else {"t": rt, "k": "idle"})
        if n >= max_events:
            break
    for it in items:
        if it["k"] == "tool":
            it["err"] = errs.get(it.pop("id"), False)
    return items


def fetch_session(client, st, cfg, sid, kind, trigger=None):
    """Cache one finished session: meta.json, timeline.json and its wanted output files."""
    d = st.cache / kind / sid
    d.mkdir(parents=True, exist_ok=True)
    full = client.get(f"/sessions/{sid}")
    evals = full.get("outcome_evaluations") or []
    meta = {"id": sid, "title": full.get("title") or "", "created_at": full.get("created_at"), "status": full.get("status"),
            "agent_version": (full.get("agent") or {}).get("version"),
            "trigger": trigger or ("deployment" if full.get("deployment_id") else "manual"),
            "scan_session": (full.get("metadata") or {}).get("scan_session"),
            "verdicts": [e.get("result") for e in evals],
            "explanation": (evals[-1] if evals else {}).get("explanation", ""),
            "active_seconds": (full.get("usage") or {}).get("active_seconds"),
            "list_cost_cents": (full.get("usage") or {}).get("list_cost"),
            "console": f"https://platform.claude.com/workspaces/{cfg['console_workspace']}/sessions/{sid}"}
    (d / "meta.json").write_text(json.dumps(meta, indent=2))
    if full.get("status") not in ("idle", "terminated"):
        return meta
    if not (d / "timeline.json").exists():
        (d / "timeline.json").write_text(json.dumps(session_timeline(client, sid)))
    wanted = SCAN_FILES if kind == "scans" else PLAN_FILES
    have = {p.name for p in d.iterdir()}
    if all(w in have for w in wanted[:3]):
        return meta
    for f in client.output_files(sid):
        name = f["filename"].rsplit("/", 1)[-1]
        if name in have:
            continue
        if name in wanted or (kind == "plans" and name.startswith("wave-") and name.endswith(".patch")):
            (d / name).write_bytes(client.download(f["id"]))
    return meta


def refresh(client, st, cfg, log=lambda *_: None):
    """Cache every finished scan and plan session of this project's agents."""
    triggers = {}
    dep = st.get("deployment", "id")
    if dep:
        for r in client.paged("/deployment_runs", {"deployment_id": dep, "beta": "true", "limit": 100}):
            triggers[r.get("session_id")] = "deployment · " + ((r.get("trigger_context") or {}).get("type") or "scheduled")
        d = client.get(f"/deployments/{dep}", params={"beta": "true"})
        (st.cache).mkdir(parents=True, exist_ok=True)
        (st.cache / "deployment.json").write_text(json.dumps({k: d.get(k) for k in ("id", "status", "schedule", "name")}, indent=2))
    for role, kind in (("scanner", "scans"), ("planner", "plans")):
        agent = st.get("agents", role, "id")
        if not agent:
            continue
        for s in client.paged("/sessions", {"agent_id": agent, "include_archived": "true", "limit": 100}):
            if s.get("status") in ("running", "rescheduling") or (s.get("title") or "").startswith("eval "):
                continue
            meta_p = st.cache / kind / s["id"] / "meta.json"
            if meta_p.exists() and (st.cache / kind / s["id"] / "timeline.json").exists():
                continue
            fetch_session(client, st, cfg, s["id"], kind, triggers.get(s["id"]))
            log(f"  cached {kind[:-1]} {s['id']}")


def running_sessions(client, st, cfg):
    out = []
    for role in ("scanner", "planner"):
        agent = st.get("agents", role, "id")
        if not agent:
            continue
        for s in client.get("/sessions", params={"agent_id": agent, "limit": 10}).get("data", []):
            if s.get("status") not in ("running", "rescheduling"):
                continue
            full = client.get(f"/sessions/{s['id']}")
            out.append({"role": role, "session": s["id"], "title": s.get("title"), "status": s.get("status"),
                        "created_at": s.get("created_at"),
                        "active_seconds": (full.get("usage") or {}).get("active_seconds"),
                        "evaluations": [e.get("result") for e in full.get("outcome_evaluations", [])],
                        "timeline": session_timeline(client, s["id"]),
                        "console": f"https://platform.claude.com/workspaces/{cfg['console_workspace']}/sessions/{s['id']}"})
    return out
