"""Golden cases for the scanner: catch regressions before trusting a changed config (prompts, rubric, model).

A case is derived from a scan you verified: the module refs it scanned + stable facts its report established
(components and their current versions, alerts, end-of-life flags, lower bounds on critical CVEs and builds).
Facts are checked with "at least" semantics — new CVEs or extra findings never fail a case; losing one does.

    evals/<case>.yaml        committed with migration.yaml (your golden set)
    mig eval add <case>      derive a case from a finished, satisfied scan
    mig eval check [RUN]     check a finished scan against every case (free)
    mig eval run [--case X]  re-scan each case with an isolated, empty memory and check it (costs a full scan per case)
"""
import json
import re
import shutil

import yaml

from . import local, render

EVALS_DIR = "evals"


def config_fingerprint(cfg):
    return render.scanner_fingerprint(cfg)


def cases_dir(cfg):
    return cfg.root / EVALS_DIR


def load_cases(cfg, only=None):
    d = cases_dir(cfg)
    cases = []
    for p in sorted(d.glob("*.yaml")) if d.exists() else []:
        c = yaml.safe_load(p.read_text())
        if not only or c["name"] in only:
            cases.append(c)
    if only and len(cases) != len(set(only)):
        missing = set(only) - {c["name"] for c in cases}
        raise RuntimeError(f"unknown eval case(s): {', '.join(sorted(missing))}")
    return cases


def _report(st, run):
    p = st.cache / "scans" / run / "impact-report.json"
    if not p.exists():
        raise RuntimeError(f"scan {run} has no impact-report.json")
    meta = json.loads((p.parent / "meta.json").read_text())
    return json.loads(p.read_text()), meta


def derive(cfg, st, name, run):
    """Build a case from a finished scan. Only keeps facts that should not drift for pinned refs."""
    if not re.match(r"^[a-z0-9][a-z0-9-]{1,47}$", name):
        raise RuntimeError("case names are kebab-case, e.g. petclinic-baseline")
    rep, meta = _report(st, run)
    if (meta.get("verdicts") or [None])[-1] != "satisfied":
        raise RuntimeError(f"scan {run} was not graded satisfied — derive cases only from runs you trust")
    prod = [c for c in rep["components"] if c.get("scope") == "production"]
    crit = len({v["id"] for c in prod for v in c.get("cves") or [] if v.get("severity") == "CRITICAL"})
    case = {
        "name": name,
        "created_from": run,
        "fingerprint": meta.get("config_fingerprint"),
        "refs": meta.get("refs") or current_refs(cfg),
        "expect": {
            "grader": "satisfied",
            "modules": sorted({c["module"] for c in rep["components"]}),
            "components": sorted(({"module": c["module"], "key": c["component_key"], "current": str(c["current"])} for c in prod),
                                 key=lambda x: (x["module"], x["key"])),
            "alerts": sorted({a["component_key"] for a in rep["alerts"] if a.get("severity") == "CRITICAL"}),   # stable ones only
            "eol": sorted({c["component_key"] for c in prod if c.get("eol")}),
            "min_critical_cves": int(crit * 0.9),          # dedup/scoring varies a little run to run
            "min_builds_attempted": rep["counts"].get("builds_attempted", 0),
        },
    }
    d = cases_dir(cfg)
    d.mkdir(exist_ok=True)
    path = d / f"{name}.yaml"
    path.write_text("# Golden case for `mig eval` — derived from a verified scan. Edit freely: remove facts you do not\n"
                    "# want to enforce, loosen bounds. Facts are checked with 'at least' semantics.\n"
                    + yaml.safe_dump(case, sort_keys=False, allow_unicode=True))
    return path, case


def _norm(v):
    return re.sub(r"\s+", " ", str(v)).strip().lower()


def check(case, rep, meta):
    """Deterministic checks of one report against one case → [{check, ok, detail}]."""
    e, out = case["expect"], []

    def add(name, ok, detail=""):
        out.append({"check": name, "ok": bool(ok), "detail": detail})

    verdict = (meta.get("verdicts") or [None])[-1]
    if e.get("grader"):
        add("grader verdict", verdict == e["grader"], f"{verdict} (expected {e['grader']})")
    mods = {c["module"] for c in rep.get("components", [])}
    missing = sorted(set(e.get("modules", [])) - mods)
    add("every module inventoried", not missing, f"missing: {', '.join(missing)}" if missing else f"{len(mods)} modules")
    have = {(c["module"], c["component_key"]): _norm(c.get("current")) for c in rep.get("components", [])}
    lost, changed = [], []
    for c in e.get("components", []):
        cur = have.get((c["module"], c["key"]))
        if cur is None:
            lost.append(f"{c['module']}/{c['key']}")
        elif _norm(c["current"]) not in cur and cur not in _norm(c["current"]):
            changed.append(f"{c['module']}/{c['key']}: {cur} ≠ {c['current']}")
    add("known components found", not lost, f"lost: {', '.join(lost[:8])}" + (" …" if len(lost) > 8 else "") if lost else f"{len(e.get('components', []))} found")
    add("current versions unchanged", not changed, "; ".join(changed[:5]) if changed else "all match")
    alerts = {a["component_key"] for a in rep.get("alerts", [])}
    miss = sorted(set(e.get("alerts", [])) - alerts)
    add("critical alerts raised", not miss, f"missing: {', '.join(miss)}" if miss else f"{len(e.get('alerts', []))} raised")
    eol = {c["component_key"] for c in rep.get("components", []) if c.get("eol")}
    miss = sorted(set(e.get("eol", [])) - eol)
    add("end-of-life flagged", not miss, f"missing: {', '.join(miss)}" if miss else f"{len(e.get('eol', []))} flagged")
    prod = [c for c in rep.get("components", []) if c.get("scope") == "production"]
    crit = len({v["id"] for c in prod for v in c.get("cves") or [] if v.get("severity") == "CRITICAL"})
    add("critical CVEs (lower bound)", crit >= e.get("min_critical_cves", 0), f"{crit} ≥ {e.get('min_critical_cves', 0)}")
    b = (rep.get("counts") or {}).get("builds_attempted", 0)
    add("builds attempted (lower bound)", b >= e.get("min_builds_attempted", 0), f"{b} ≥ {e.get('min_builds_attempted', 0)}")
    return out


def check_run(cfg, st, run, cases):
    rep, meta = _report(st, run)
    return [{"case": c["name"], "run": run, "results": check(c, rep, meta)} for c in cases]


def current_refs(cfg):
    return {m.name: (m.ref if "repo" in m else f"path:{m['path']}") for m in cfg.modules}


def refs_mismatch(cfg, case):
    now = current_refs(cfg)
    return {k: (v, now.get(k)) for k, v in case["refs"].items() if now.get(k) != v}


def start_case(cfg, st, case, log=print):
    """Scan the case's refs with an empty, isolated memory (production scan state stays untouched)."""
    diff = refs_mismatch(cfg, case)
    if diff:
        raise RuntimeError(f"case {case['name']} was recorded on other refs: "
                           + "; ".join(f"{k}: case {a} vs config {b}" for k, (a, b) in diff.items())
                           + " — re-derive the case or restore those refs")
    mem = st.dir / "evals" / "memory" / case["name"]
    if mem.exists():
        shutil.rmtree(mem)
    mem.mkdir(parents=True)
    rid = local.prepare(cfg, st, "scans", log=log, memory_dir=str(mem), eval_case=case["name"])
    return rid


def record(cfg, st, results, full):
    d = st.dir / "evals"
    d.mkdir(parents=True, exist_ok=True)
    fp = config_fingerprint(cfg)
    ok = all(r["ok"] for res in results for r in res["results"])
    entry = {"at": local.now_iso(), "fingerprint": fp, "passed": ok, "full": full, "results": results}
    hist = json.loads((d / "results.json").read_text()) if (d / "results.json").exists() else []
    hist.append(entry)
    (d / "results.json").write_text(json.dumps(hist, indent=2))
    return entry


def status(cfg, st):
    """(current fingerprint, last full eval entry for it or None)."""
    fp = config_fingerprint(cfg)
    p = st.dir / "evals" / "results.json"
    hist = json.loads(p.read_text()) if p.exists() else []
    mine = [h for h in hist if h["fingerprint"] == fp and h.get("full")]
    return fp, (mine[-1] if mine else None)
