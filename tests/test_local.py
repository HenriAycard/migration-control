"""Local runner: full agent → grader → fix loop against a fake `claude` binary (no cost, no network)."""
import json
import os
import stat

import yaml

from migration_control import config, dashboard, local, render
from migration_control.state import State

FAKE_CLAUDE = r'''#!/usr/bin/env python3
"""Fake Claude Code: agent writes outputs; grader fails criterion 2 on the first pass only."""
import json, os, sys
args = sys.argv[1:]
prompt = sys.stdin.read()
state = os.path.join(os.environ["FAKE_STATE"], "calls")
n = int(open(state).read()) if os.path.exists(state) else 0
open(state, "w").write(str(n + 1))
emit = lambda e: print(json.dumps(e), flush=True)
open(os.path.join(os.environ["FAKE_STATE"], "argv.log"), "a").write(" ".join(a for a in args if a.startswith("--")) + "\n")
emit({"type": "system", "subtype": "init", "session_id": "s"})
if os.environ.get("FAKE_LIMIT_AT") == str(n):
    emit({"type": "assistant", "message": {"content": [{"type": "text", "text": "working..."}]}})
    emit({"type": "result", "subtype": "success", "is_error": True, "result": "You've hit your session limit · resets 12:40am (UTC)",
          "total_cost_usd": 0.2, "duration_ms": 5000, "session_id": "a"})
    sys.exit(1)
if "--json-schema" in args:
    met = n >= 3   # calls: 0 agent, 1 grader (fail), 2 agent fix, 3 grader (pass)
    emit({"type": "result", "subtype": "success", "total_cost_usd": 0.01, "duration_ms": 1000, "session_id": "g",
          "structured_output": {"criteria": [{"n": 1, "met": True, "note": "inventory ok"}, {"n": 2, "met": met, "note": "cves ok" if met else "CVE-X has no link"}],
                                "summary": "graded"}})
    sys.exit(0)
out = [a for a in args if a.endswith("outputs")] or ["/mnt/session/outputs"]
odir = args[args.index("--add-dir") + 1] if "--add-dir" in args else "/mnt/session/outputs"
assert "/mnt/session" not in prompt, "paths must be rewritten in isolation none"
emit({"type": "assistant", "message": {"content": [{"type": "tool_use", "id": f"t{n}", "name": "Bash", "input": {"command": "curl -s https://api.osv.dev/v1/query"}}]}})
emit({"type": "user", "message": {"content": [{"type": "tool_result", "tool_use_id": f"t{n}", "is_error": False, "content": "{}"}]}})
emit({"type": "assistant", "message": {"content": [{"type": "tool_use", "id": f"w{n}", "name": "Write", "input": {"file_path": odir + "/impact-report.json"}}]}})
report = json.load(open(os.environ["FAKE_REPORT"]))
open(os.path.join(odir, "impact-report.json"), "w").write(json.dumps(report))
open(os.path.join(odir, "impact-summary.md"), "w").write("**Verdict:** fake\n")
open(os.path.join(odir, "impact-report.md"), "w").write("# report\n")
emit({"type": "assistant", "message": {"content": [{"type": "text", "text": "done"}]}})
emit({"type": "result", "subtype": "success", "total_cost_usd": 0.5, "duration_ms": 60000, "session_id": "a"})
'''


def test_local_loop_end_to_end(tmp_path, monkeypatch):
    from migration_control import RESOURCES
    pet = RESOURCES / "examples" / "petclinic"
    report = next((pet / "recorded" / "scans").glob("*/impact-report.json"))
    bindir = tmp_path / "bin"; bindir.mkdir()
    fake = bindir / "claude"; fake.write_text(FAKE_CLAUDE); fake.chmod(fake.stat().st_mode | stat.S_IEXEC)
    monkeypatch.setenv("PATH", f"{bindir}{os.pathsep}{os.environ['PATH']}")
    monkeypatch.setenv("FAKE_STATE", str(tmp_path)); monkeypatch.setenv("FAKE_REPORT", str(report))

    proj = tmp_path / "proj"; (proj / "infra").mkdir(parents=True)
    (proj / "infra" / "requirements.txt").write_text("requests==2.19.0\n")
    (proj / "migration.yaml").write_text(yaml.safe_dump({
        "version": 1, "project": "demo", "runner": {"type": "local", "isolation": "none"},
        "estate": [{"name": "petclinic-infra", "path": "infra"}], "agents": {"max_iterations": 3, "planner": False}}))
    cfg = config.load(proj); st = State(proj)
    rid = local.prepare(cfg, st, "scans", log=lambda *_: None)
    verdict = local.work(cfg, st, "scans", rid)

    d = st.cache / "scans" / rid
    meta = json.loads((d / "meta.json").read_text())
    assert verdict == "satisfied" and meta["verdicts"] == ["needs_revision", "satisfied"]
    assert meta["status"] == "idle" and meta["list_cost_cents"] == 102
    assert "(2) cves ok" in meta["explanation"]
    tl = json.loads((d / "timeline.json").read_text())
    kinds = [i["k"] for i in tl]
    assert kinds.count("eval_end") == 2 and kinds[-1] == "idle"
    assert {i["phase"] for i in tl if i["k"] == "tool"} >= {"research", "report"}
    assert (d / "impact-report.json").exists() and (d / "outputs" / "impact-summary.md").exists()
    assert not (st.dir / "work" / rid / "workspace").exists()          # cleaned after the run
    page = dashboard.payload(cfg, st)
    assert len(page["scans"]) == 1 and page["scans"][0]["grader"] == "satisfied"


def test_local_prompts_use_checked_out_modules(tmp_path):
    (tmp_path / "migration.yaml").write_text(yaml.safe_dump({"version": 1, "project": "x",
        "estate": [{"name": "api", "repo": "https://github.com/acme/api", "ref": "v1"}]}))
    cfg = config.load(tmp_path)
    task = render.scanner_task(cfg)
    assert "Already checked out at /workspace/api (ref v1)" in task and "git clone" not in task
    assert "openpyxl" in render.scanner_agent(cfg, "-", "-")["system"]


def test_timeline_maps_claude_code_events(tmp_path):
    tl = local.Timeline(tmp_path / "t.json", 0)
    tl.event({"type": "assistant", "message": {"content": [
        {"type": "tool_use", "id": "a", "name": "WebSearch", "input": {"query": "spring boot latest"}},
        {"type": "tool_use", "id": "b", "name": "Skill", "input": {"skill": "regulated-sourcing"}}]}})
    tl.event({"type": "user", "message": {"content": [{"type": "tool_result", "tool_use_id": "a", "is_error": True}]}})
    tl.flush(force=True)
    items = json.loads((tmp_path / "t.json").read_text())
    assert items[0]["tool"] == "web_search" and items[0]["phase"] == "research" and items[0]["err"] is True
    assert items[1]["phase"] == "skill" and items[1]["skill"] == "regulated-sourcing"


def test_usage_limit_pauses_then_resume_finishes(tmp_path, monkeypatch):
    from migration_control import RESOURCES
    pet = RESOURCES / "examples" / "petclinic"
    report = next((pet / "recorded" / "scans").glob("*/impact-report.json"))
    bindir = tmp_path / "bin"; bindir.mkdir()
    fake = bindir / "claude"; fake.write_text(FAKE_CLAUDE); fake.chmod(fake.stat().st_mode | stat.S_IEXEC)
    monkeypatch.setenv("PATH", f"{bindir}{os.pathsep}{os.environ['PATH']}")
    monkeypatch.setenv("FAKE_STATE", str(tmp_path)); monkeypatch.setenv("FAKE_REPORT", str(report))
    monkeypatch.setenv("FAKE_LIMIT_AT", "0")       # the very first agent call hits the limit
    proj = tmp_path / "proj"; (proj / "infra").mkdir(parents=True)
    (proj / "infra" / "requirements.txt").write_text("requests==2.19.0\n")
    (proj / "migration.yaml").write_text(yaml.safe_dump({
        "version": 1, "project": "demo", "runner": {"type": "local", "isolation": "none"},
        "estate": [{"name": "petclinic-infra", "path": "infra"}], "agents": {"max_iterations": 3, "planner": False}}))
    cfg = config.load(proj); st = State(proj)
    rid = local.prepare(cfg, st, "scans", log=lambda *_: None)

    assert local.work(cfg, st, "scans", rid) == "paused"
    d = st.cache / "scans" / rid
    meta = json.loads((d / "meta.json").read_text())
    assert meta["status"] == "paused" and meta["progress"]["started"] and f"mig resume {rid}" in meta["explanation"]
    assert (st.dir / "work" / rid / "workspace").exists()            # kept for the resume

    monkeypatch.delenv("FAKE_LIMIT_AT")
    assert local.work(cfg, st, "scans", rid) == "satisfied"
    meta = json.loads((d / "meta.json").read_text())
    assert meta["status"] == "idle" and meta["progress"] is None
    assert meta["verdicts"] == ["needs_revision", "satisfied"] and meta["list_cost_cents"] == 122
    argv = (tmp_path / "argv.log").read_text().splitlines()
    assert "--session-id" in argv[0] and "--resume" in argv[1]       # same conversation continued
    msgs = [i["text"] for i in json.loads((d / "timeline.json").read_text()) if i["k"] == "msg"]
    assert any("paused" in m for m in msgs) and any("resumed" in m for m in msgs)
    assert not (st.dir / "work" / rid / "workspace").exists()


def test_eval_add_check_and_isolated_run(tmp_path, monkeypatch):
    """Golden case from a satisfied scan; free check; eval re-run uses an empty memory and leaves production memory alone."""
    from migration_control import RESOURCES, evals
    pet = RESOURCES / "examples" / "petclinic"
    report = next((pet / "recorded" / "scans").glob("*/impact-report.json"))
    bindir = tmp_path / "bin"; bindir.mkdir()
    fake = bindir / "claude"; fake.write_text(FAKE_CLAUDE); fake.chmod(fake.stat().st_mode | stat.S_IEXEC)
    monkeypatch.setenv("PATH", f"{bindir}{os.pathsep}{os.environ['PATH']}")
    monkeypatch.setenv("FAKE_STATE", str(tmp_path)); monkeypatch.setenv("FAKE_REPORT", str(report))
    proj = tmp_path / "proj"; (proj / "infra").mkdir(parents=True)
    (proj / "infra" / "requirements.txt").write_text("requests==2.19.0\n")
    (proj / "migration.yaml").write_text(yaml.safe_dump({
        "version": 1, "project": "demo", "runner": {"type": "local", "isolation": "none"},
        "estate": [{"name": "petclinic-infra", "path": "infra"}], "agents": {"max_iterations": 3, "planner": False}}))
    cfg = config.load(proj); st = State(proj)
    (st.dir / "memory").mkdir(parents=True); (st.dir / "memory" / "scan-state.json").write_text('{"prod": true}')

    rid = local.prepare(cfg, st, "scans", log=lambda *_: None)
    local.work(cfg, st, "scans", rid)
    path, case = evals.derive(cfg, st, "baseline", rid)
    assert case["refs"] == {"petclinic-infra": "path:infra"} and case["fingerprint"] == render.scanner_fingerprint(cfg)
    assert all(r["ok"] for r in evals.check_run(cfg, st, rid, [case])[0]["results"])

    # a report that lost a component and an alert fails the case
    rep = json.loads(report.read_text()); rep["components"] = rep["components"][1:]; rep["alerts"] = []
    bad = evals.check(case, rep, {"verdicts": ["satisfied"]})
    assert {r["check"] for r in bad if not r["ok"]} >= {"known components found", "critical alerts raised"}

    erid = evals.start_case(cfg, st, case, log=lambda *_: None)
    local.work(cfg, st, "scans", erid)
    meta = json.loads((st.cache / "scans" / erid / "meta.json").read_text())
    assert meta["eval_case"] == "baseline" and meta["memory_dir"].endswith("evals/memory/baseline")
    assert (st.dir / "memory" / "scan-state.json").read_text() == '{"prod": true}'      # production memory untouched
    assert st.get("last", "scan") == rid                                                # eval runs never become "the latest scan"
    assert all(s["session"] != erid for s in dashboard.payload(cfg, st)["scans"])        # nor show in the estate history
    entry = evals.record(cfg, st, evals.check_run(cfg, st, erid, [case]), full=True)
    assert entry["passed"] and evals.status(cfg, st)[1]["at"] == entry["at"]
