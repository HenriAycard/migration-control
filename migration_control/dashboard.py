"""Migration Control — the local dashboard.

`build()` normalises every cached run in .mig/runs/ into one JSON payload and writes a
static .mig/dashboard/index.html. `serve()` serves it on 127.0.0.1 with a live feed of
running sessions. The API key stays in this process; it is never written into the page.
"""
import hashlib
import html
import json
import re
import secrets
import threading
import urllib.parse
import time
from functools import partial
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer

from . import RESOURCES, local, publish, render, runs

TEMPLATE = RESOURCES / "dashboard" / "template.html"


# ── normalisation ────────────────────────────────────────────────────────────
def bucket(cvss):
    try:
        c = float(cvss)
    except (TypeError, ValueError):
        return "unscored"
    return "critical" if c >= 9 else "high" if c >= 7 else "medium" if c >= 4 else "low"


def build_status(result):
    r = (result or "").strip().upper()
    if r.startswith("PASS"):
        return "pass"
    if r.startswith("PARTIAL"):
        return "partial"
    if r.startswith(("NOT ATTEMPTED", "NOT_ATTEMPTED", "SKIP")):
        return "skipped"
    return "fail"


def text_of(item):
    if isinstance(item, str):
        return item
    if isinstance(item, dict):
        if "action" in item:
            return item["action"]
        head = item.get("title") or " · ".join(x for x in (item.get("module"), item.get("component")) if x)
        body = item.get("detail") or item.get("message") or ""
        return f"{head}: {body}" if head and body else head or body
    return str(item)


def _key(component_key):
    return hashlib.sha1(component_key.encode()).hexdigest()[:10]


def is_toolchain(c):
    return c.get("scope") in ("build_toolchain", "test")


def normalise_scan(d):
    """One cached scan (schema 1.0) → the shape the page expects."""
    meta = json.loads((d / "meta.json").read_text())
    if not (d / "impact-report.json").exists():
        return None
    rep = json.loads((d / "impact-report.json").read_text())
    summary = (d / "impact-summary.md").read_text() if (d / "impact-summary.md").exists() else ""

    prod, tool = {}, {}
    for c in rep.get("components", []):
        target = tool if is_toolchain(c) else prod
        for v in c.get("cves") or []:
            if v.get("id"):
                target.setdefault(v["id"], bucket(v.get("cvss")))
    sev = lambda m: {k: sum(1 for b in m.values() if b == k) for k in ("critical", "high", "medium", "low", "unscored")}

    builds = [{"module": b.get("module") or "", "what": b.get("what") or b.get("toolchain") or "",
               "status": build_status(b.get("result")), "result": (b.get("result") or "")[:140],
               "error": ((b.get("errors") or [""])[0] or "")[:220]} for b in rep.get("builds") or []]

    scope_of = {c.get("component_key"): c.get("scope") for c in rep.get("components", [])}
    alerts = [{"key": _key(a["component_key"]), "label": a["component_key"], "severity": (a.get("severity") or "").upper(),
               "component": a.get("component") or "", "message": re.sub(r"\*\*", "", a.get("message") or ""),
               "fix": re.sub(r"\*\*|\[[^\]]*\]\(#[^)]*\)", "", a.get("fix") or "").strip(),
               "source": " ; ".join(a.get("sources") or []), "scope": scope_of.get(a["component_key"], "production")}
              for a in rep.get("alerts", []) if a.get("component_key")]
    alert_by_key = {a["label"]: a for a in alerts}

    components = []
    for c in rep.get("components", []):
        cv = {k: 0 for k in ("critical", "high", "medium", "low", "unscored")}
        top = []
        for v in c.get("cves") or []:
            cv[bucket(v.get("cvss"))] += 1
            top.append({"id": v.get("id"), "cvss": v.get("cvss"), "url": v.get("url"), "fixed_in": v.get("fixed_in")})
        top.sort(key=lambda v: -(v["cvss"] if isinstance(v["cvss"], (int, float)) else -1))
        al = alert_by_key.get(c.get("component_key"))
        components.append({
            "key": c.get("component_key"), "name": re.sub(r"\s*\(.*?\)\s*", " ", c.get("name") or "").strip()[:90],
            "module": c.get("module") or "", "scope": c.get("scope") or "production",
            "current": str(c.get("current") or "")[:160], "latest": str(c.get("latest") or "")[:160],
            "patch": str(c.get("latest_security_patch") or "")[:220], "eol": bool(c.get("eol")),
            "outdated": c.get("outdated", True), "cves": cv, "top": top[:10],
            "alert": {k: al[k] for k in ("severity", "message", "fix", "source", "key")} if al else None,
        })
    tl = d / "timeline.json"
    return {
        "session": meta["id"], "title": meta.get("title"), "created_at": meta.get("created_at"), "trigger": meta.get("trigger"),
        "agent_version": meta.get("agent_version"), "grader": (meta.get("verdicts") or [None])[-1],
        "scan_date": rep.get("scan_date"), "baseline": bool(rep.get("baseline")),
        "verdict_line": re.sub(r"\*\*", "", rep.get("verdict") or ""),
        "prod_components": sum(1 for c in rep.get("components", []) if not is_toolchain(c)),
        "tool_components": sum(1 for c in rep.get("components", []) if is_toolchain(c)),
        "cves_prod": sev(prod), "cves_prod_total": len(prod), "cves_tool_total": len(tool),
        "alerts": alerts,
        "new_since": [text_of(x) for x in rep.get("new_since_last_scan", [])],
        "decisions": [text_of(x) for x in rep.get("decisions_needed", [])],
        "migration_order": [text_of(x) for x in rep.get("migration_order", [])],
        "builds": builds, "summary_html": md_to_html(summary), "components": components,
        "cross_module": [{"from": str(x.get("from", "")), "to": str(x.get("to", "")), "constraint": str(x.get("constraint", ""))[:300]}
                         for x in rep.get("cross_module", []) if isinstance(x, dict)],
        "timeline": json.loads(tl.read_text()) if tl.exists() else [],
        "active_seconds": meta.get("active_seconds"), "grader_text": meta.get("explanation", ""), "console": meta.get("console"),
    }


def normalise_plan(d, href_prefix):
    meta = json.loads((d / "meta.json").read_text())
    if not (d / "migration-plan.json").exists():
        return None
    plan = json.loads((d / "migration-plan.json").read_text())
    tl = d / "timeline.json"
    return {
        "session": meta["id"], "created_at": meta.get("created_at"), "scan_session": meta.get("scan_session"),
        "grader": (meta.get("verdicts") or [None])[-1], "plan_date": plan.get("plan_date"), "console": meta.get("console"),
        "waves": [{k: w.get(k) for k in ("wave", "title", "component_keys", "modules", "depends_on", "targets", "intermediate_steps",
                                         "changes", "entry_gates", "exit_gates", "rollback", "approvers", "risk", "effort", "evidence", "status")}
                  for w in plan.get("waves", [])],
        "coverage": plan.get("coverage", {}), "blocking_decisions": plan.get("blocking_decisions", []),
        "proof": {"wave": (plan.get("proof") or {}).get("wave"),
                  "steps": [{k: s.get(k) for k in ("id", "command", "result")} for s in (plan.get("proof") or {}).get("steps", [])]},
        "patches": [f"{href_prefix}/{meta['id']}/{p.name}" for p in sorted(d.glob("wave-*.patch"))],
        "timeline": json.loads(tl.read_text()) if tl.exists() else [],
        "active_seconds": meta.get("active_seconds"), "grader_text": meta.get("explanation", ""),
    }


def load_pr_run(st):
    """Recorded PR-agent run (ships with the petclinic example; the PR agent itself arrives in v1)."""
    base = st.cache / "pr"
    dirs = sorted(p for p in base.iterdir() if (p / "timeline.json").exists()) if base.exists() else []
    if not dirs:
        return None, []
    d = dirs[-1]
    tl, calls, meta = (json.loads((d / n).read_text()) for n in ("timeline.json", "calls.json", "meta.json"))
    decided = {x["tool_use_id"]: x for x in tl if x["k"] == "confirm"}
    run = {"session": meta["id"], "created_at": meta.get("created_at"), "active_seconds": meta.get("active_seconds"), "wave": meta.get("wave"),
           "grader": (meta.get("verdicts") or [None])[-1], "grader_text": meta.get("explanation", ""), "timeline": tl,
           "original_url": meta.get("pr_url"), "console": meta.get("console"),
           "calls": [{"id": c["id"], "tool": c["tool"],
                      "summary": {k: v for k, v in c["input"].items() if k in ("owner", "repo", "branch", "from_branch", "head", "base", "title", "message", "pullNumber")},
                      "files": [{"path": f.get("path"), "size": len(f.get("content", ""))} for f in c["input"].get("files", [])] if isinstance(c["input"].get("files"), list) else [],
                      "body": (c["input"].get("body") or "")[:4000],
                      "decision": (decided.get(c["id"]) or {}).get("result"),
                      "deny_message": (decided.get(c["id"]) or {}).get("text", "")} for c in calls]}
    prs = [{"url": meta["pr_url"], "number": meta["pr_url"].rstrip("/").split("/")[-1], "wave": meta.get("wave"),
            "session": meta["id"], "report": False}] if meta.get("pr_url") else []
    return run, prs


def load_pr_runs(cfg, st):
    """Local PR runs: prepared change sets awaiting (or past) human review, with their diffs."""
    base = st.cache / "prs"
    out = []
    for mp in sorted(base.glob("*/meta.json")) if base.exists() else []:
        d, meta = mp.parent, json.loads(mp.read_text())
        pr = json.loads((d / "pr.json").read_text()) if (d / "pr.json").exists() else None
        patches = {}
        for e in (pr or {}).get("modules", []):
            f = d / e["patch_file"]
            if f.exists():
                txt = f.read_text(errors="replace")
                patches[e["module"]] = txt[:150_000] + ("\n… (truncated)" if len(txt) > 150_000 else "")
        problems = publish.check(cfg, pr) if pr else {}
        out.append({"run": meta["id"], "wave": meta.get("wave"), "plan_run": meta.get("plan_run"), "status": meta.get("status"),
                    "created_at": meta.get("created_at"), "grader": (meta.get("verdicts") or [None])[-1],
                    "grader_text": meta.get("explanation", ""), "review": meta.get("review") or {}, "pr": pr, "patches": patches,
                    "publishable": {m: (m not in problems) for m in patches}, "problems": problems,
                    "description_html": md_to_html((d / "pr-description.md").read_text()) if (d / "pr-description.md").exists() else "",
                    "timeline": json.loads((d / "timeline.json").read_text()) if (d / "timeline.json").exists() else [],
                    "active_seconds": meta.get("active_seconds")})
    return out


def parse_rubric(text):
    out = []
    for line in text.splitlines():
        m = re.match(r"^(\d+)\.\s+\*\*(.+?)\*\*\s*(.*)$", line.strip())
        if m:
            out.append({"n": int(m.group(1)), "title": m.group(2).rstrip("."), "text": re.sub(r"`", "", m.group(3))})
    return out


def schedule_label(cfg, dep):
    s = cfg.get("schedule")
    if not s:
        return "manual runs only"
    if cfg.local:
        return f"cron {s['cron']} · " + ("crontab" if local.schedule_installed(cfg) else "not installed")
    return f"cron {s['cron']} · {s['timezone']}" + ("" if dep.get("id") else " (not deployed)")


def md_to_html(md):
    def inline(s):
        s = html.escape(s)
        s = re.sub(r"`([^`]+)`", r"<code>\1</code>", s)
        s = re.sub(r"\*\*([^*]+)\*\*", r"<strong>\1</strong>", s)
        s = re.sub(r"\[([^\]]+)\]\(([^)]+)\)", lambda m: f'<a href="{m.group(2) if m.group(2).startswith("http") else "#"}">{m.group(1)}</a>', s)
        return s
    out, lst, tbl = [], None, []

    def flush():
        nonlocal lst, tbl
        if lst:
            out.append(f"</{lst}>"); lst = None
        if tbl:
            rows = [r for r in tbl if not re.match(r"^\|\s*-", r)]
            cells = lambda r: [c.strip() for c in r.strip().strip("|").split("|")]
            out.append('<div class="scroll"><table><thead><tr>' + "".join(f"<th>{inline(c)}</th>" for c in cells(rows[0])) + "</tr></thead><tbody>"
                       + "".join("<tr>" + "".join(f"<td>{inline(c)}</td>" for c in cells(r)) + "</tr>" for r in rows[1:]) + "</tbody></table></div>")
            tbl = []
    for line in (md or "").splitlines():
        if line.startswith("|"):
            if lst:
                out.append(f"</{lst}>"); lst = None
            tbl.append(line); continue
        if tbl:
            flush()
        m = re.match(r"^(#{1,3})\s+(.*)", line)
        if m:
            flush(); lvl = len(m.group(1)) + 1
            out.append(f"<h{lvl}>{inline(m.group(2))}</h{lvl}>"); continue
        m = re.match(r"^\s*([-*]|\d+\.)\s+(.*)", line)
        if m:
            kind = "ol" if m.group(1)[0].isdigit() else "ul"
            if lst != kind:
                flush(); out.append(f"<{kind}>"); lst = kind
            out.append(f"<li>{inline(m.group(2))}</li>"); continue
        flush()
        if line.strip():
            out.append(f"<p>{inline(line)}</p>")
    flush()
    return "\n".join(out)


# ── page ─────────────────────────────────────────────────────────────────────
def out_dir(st):
    return st.dir / "dashboard"


def payload(cfg, st):
    cache = st.cache
    scans = [s for s in (normalise_scan(p) for p in (cache / "scans").glob("*") if (p / "meta.json").exists()) if s] if (cache / "scans").exists() else []
    scans.sort(key=lambda s: s["created_at"] or "")
    plans = [p for p in (normalise_plan(d, "runs/plans") for d in (cache / "plans").glob("*") if (d / "meta.json").exists()) if p] if (cache / "plans").exists() else []
    plans.sort(key=lambda p: p["created_at"] or "")
    dep = json.loads((cache / "deployment.json").read_text()) if (cache / "deployment.json").exists() else {}
    pr_run, prs = load_pr_run(st)
    pr_runs = load_pr_runs(cfg, st) if cfg.local else []
    for r in pr_runs:   # published PRs/MRs feed the flow's PR node
        for res in (r["review"].get("published") or []):
            if res.get("url"):
                prs.append({"url": res["url"], "number": res["number"], "wave": r["wave"], "session": r["run"], "report": False})
    rubrics = {"scanner": parse_rubric(render.scanner_rubric(cfg))}
    if cfg["agents"]["planner"]:
        rubrics["planner"] = parse_rubric(render.planner_rubric(cfg))
    if (cache / "pr" / "rubric.md").exists():
        rubrics["pr"] = parse_rubric((cache / "pr" / "rubric.md").read_text())
    elif cfg.local:
        rubrics["pr"] = parse_rubric(render.pr_rubric(cfg))
    agents = json.loads((cache / "agents.json").read_text()) if (cache / "agents.json").exists() else {}
    return {
        "project": cfg["project"], "workspace": cfg["console_workspace"],
        "modules": [{"name": m.name, "label": m.name, "description": m.get("description", ""),
                     "icon": m.get("icon") or "📦", "depends_on": m.get("depends_on", [])} for m in cfg.modules],
        "approvers": cfg["policy"]["approvers"], "schedule_label": schedule_label(cfg, dep),
        "agent_id": st.get("agents", "scanner", "id"), "deployment": dep,
        "scans": scans, "plans": plans, "prs": prs, "pr_run": pr_run, "pr_runs": pr_runs, "rubrics": rubrics, "agents": agents,
        "local": cfg.local,
        "demo": bool(st.get("example")) and pr_run is not None, "demo_repo": st.get("example_demo_repo"),
    }


def cache_agents(client, st):
    """Attached skills per agent role (live config), cached for offline rebuilds."""
    out = {}
    skill_id = st.get("skill", "id")
    for role in ("scanner", "planner"):
        a = st.get("agents", role)
        if not a:
            continue
        live = client.get(f"/agents/{a['id']}")
        out[role] = {"id": live["id"], "name": live.get("name"), "version": live.get("version"),
                     "skills": [{"type": s.get("type"), "id": s.get("skill_id"), "version": s.get("version"),
                                 "name": "regulated-sourcing" if s.get("skill_id") == skill_id else s.get("skill_id")}
                                for s in live.get("skills", [])]}
    st.cache.mkdir(parents=True, exist_ok=True)
    (st.cache / "agents.json").write_text(json.dumps(out, indent=2))


def build(cfg, st, client=None, log=print):
    if client is not None and not cfg.local:
        log("fetching finished runs…")
        runs.refresh(client, st, cfg, log)
        cache_agents(client, st)
    data = payload(cfg, st)
    out = out_dir(st)
    out.mkdir(parents=True, exist_ok=True)
    blob = json.dumps(data).replace("</", "<\\/")
    (out / "index.html").write_text(TEMPLATE.read_text().replace("/*__DATA__*/null", blob))
    # patches are linked from the Journey view
    link = out / "runs"
    if link.is_symlink() and not link.exists():
        link.unlink()
    if not link.exists():
        link.symlink_to(st.cache.resolve(), target_is_directory=True)
    log(f"wrote {out / 'index.html'} — {len(data['scans'])} scan(s), {len(data['plans'])} plan(s)")
    return out / "index.html"


# ── live server ──────────────────────────────────────────────────────────────
def serve(cfg, st, client, port=8765, log=print):
    cache = {"live": (0, None)}
    lock = threading.Lock()

    def live():
        now = time.time()
        with lock:
            ts, val = cache["live"]
            if val is not None and now - ts < 5:
                return val
        if cfg.local:
            return {"now": now, "running": local.running_runs(st), "deployment": None}
        dep = None
        if st.get("deployment", "id"):
            d = client.get(f"/deployments/{st.get('deployment', 'id')}", params={"beta": "true"})
            dep = {"status": d.get("status"), "schedule": d.get("schedule")}
        val = {"now": now, "running": runs.running_sessions(client, st, cfg), "deployment": dep}
        with lock:
            cache["live"] = (now, val)
        return val

    secret = secrets.token_urlsafe(24)
    origins = {f"http://127.0.0.1:{port}", f"http://localhost:{port}"}

    class Handler(SimpleHTTPRequestHandler):
        def _json(self, code, obj):
            body = json.dumps(obj).encode()
            self.send_response(code)
            self.send_header("content-type", "application/json")
            self.send_header("cache-control", "no-store")
            self.send_header("content-length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)

        def _page(self):
            # the page gets this server's secret; POSTs must echo it (blocks cross-site requests to 127.0.0.1)
            html_ = (out_dir(st) / "index.html").read_text().replace("<script>\nconst DATA =", f"<script>\nwindow.__MIG_TOKEN = {json.dumps(secret)};\nconst DATA =", 1)
            body = html_.encode()
            self.send_response(200)
            self.send_header("content-type", "text/html; charset=utf-8")
            self.send_header("cache-control", "no-store")
            self.send_header("content-length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)

        def do_GET(self):
            path = self.path.split("?")[0]
            if path in ("/", "/index.html"):
                return self._page()
            if path.startswith("/api/live"):
                try:
                    return self._json(200, live())
                except Exception as e:  # network hiccup: keep the page alive
                    return self._json(502, {"error": str(e)[:200]})
            if path.startswith("/api/demo/"):
                return self._json(200, {"error": "live GitHub replay is not part of migration-control — the demo plays without it"})
            return super().do_GET()

        def do_POST(self):
            origin = self.headers.get("origin")
            if self.headers.get("x-mig-token") != secret or (origin and origin not in origins):
                return self._json(403, {"ok": False, "error": "forbidden — reload the page served by `mig dashboard --serve`"})
            path, _, query = self.path.partition("?")
            q = urllib.parse.parse_qs(query)
            try:
                if path == "/api/refresh":
                    build(cfg, st, client, log=lambda *_: None)
                    return self._json(200, {"ok": True})
                if path == "/api/pr/start" and cfg.local:
                    plans = [m for m in local.list_runs(st, "plans") if (st.cache / "plans" / m["id"] / "migration-plan.json").exists()]
                    if not plans:
                        return self._json(400, {"ok": False, "error": "no finished plan"})
                    wave = int(q["wave"][0])
                    rid = local.prepare(cfg, st, "prs", None, log=lambda *_: None, plan_run=plans[-1]["id"], wave=wave)
                    local.start(cfg, st, "prs", rid)
                    return self._json(200, {"ok": True, "run": rid})
                parts = path.strip("/").split("/")   # api/pr/<run>/<approve|deny>
                if len(parts) == 4 and parts[:2] == ["api", "pr"] and parts[3] in ("approve", "deny"):
                    length = int(self.headers.get("content-length") or 0)
                    body = json.loads(self.rfile.read(length) or b"{}") if length else {}
                    logs = []
                    review = publish.decide(cfg, st, parts[2], parts[3] == "approve", body.get("reason", ""), log=logs.append)
                    build(cfg, st, None, log=lambda *_: None)
                    return self._json(200, {"ok": True, "review": review, "log": logs})
            except Exception as e:
                return self._json(500, {"ok": False, "error": str(e)[:800]})
            if path.startswith("/api/demo/"):
                return self._json(200, {"ok": False, "error": "live GitHub replay is not part of migration-control"})
            self.send_error(404)

        def log_message(self, fmt, *args):
            if "/api/live" not in (args[0] if args else ""):
                super().log_message(fmt, *args)

    srv = ThreadingHTTPServer(("127.0.0.1", port), partial(Handler, directory=str(out_dir(st))))
    log(f"Migration Control → http://127.0.0.1:{port}  (live feed on; Ctrl-C to stop)")
    try:
        srv.serve_forever()
    except KeyboardInterrupt:
        pass
