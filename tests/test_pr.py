"""PR flow: PR agent prepares (fake claude) → human approves → mig pushes a branch and opens the PR (local bare repo)."""
import json
import os
import stat
import subprocess

import pytest
import yaml

from migration_control import config, dashboard, local, publish
from migration_control.state import State

FAKE = r'''#!/usr/bin/env python3
import json, os, subprocess, sys
args = sys.argv[1:]
if args[:2] == ["auth", "status"]:
    print(json.dumps({"loggedIn": True, "authMethod": "claude.ai"})); sys.exit(0)
prompt = sys.stdin.read()
emit = lambda e: print(json.dumps(e), flush=True)
open(os.path.join(os.environ["FAKE_STATE"], "argv.log"), "a").write(" ".join(args) + "\n")
emit({"type": "system", "subtype": "init", "session_id": "s"})
if "--json-schema" in args:
    emit({"type": "result", "subtype": "success", "total_cost_usd": 0.01, "duration_ms": 10, "session_id": "g",
          "structured_output": {"criteria": [{"n": i, "met": True, "note": "ok"} for i in range(1, 6)], "summary": "ok"}})
    sys.exit(0)
outputs = args[args.index("--add-dir") + 1]
ws = os.getcwd()
f = os.path.join(ws, "infra", "requirements.txt")
open(f, "w").write("requests==2.32.3\n")
diff = subprocess.run(["git", "-C", os.path.join(ws, "infra"), "diff"], capture_output=True, text=True).stdout
open(os.path.join(outputs, "infra.patch"), "w").write(diff)
json.dump({"schema_version": "1.0", "wave": 2, "title": "Wave 2: requests 2.19 -> 2.32.3", "branch": "migration/wave-2-requests",
           "status": "READY", "blocked_reason": None,
           "modules": [{"module": "infra", "patch_file": "infra.patch", "commit_message": "Wave 2: bump requests to 2.32.3", "files": ["requirements.txt"]}],
           "gates": [{"id": "G1", "check": "pip install", "command": "pip install -r requirements.txt", "result": "PASS", "evidence": "Successfully installed"}],
           "to_run_at_rollout": []}, open(os.path.join(outputs, "pr.json"), "w"))
open(os.path.join(outputs, "pr-description.md"), "w").write("## Why\nrequests 2.19 has CVEs.\n\n- [ ] security\n\nDo not merge until every approver has signed off.\n")
emit({"type": "assistant", "message": {"content": [{"type": "tool_use", "id": "t1", "name": "Edit", "input": {"file_path": f}}]}})
emit({"type": "result", "subtype": "success", "total_cost_usd": 0.3, "duration_ms": 1000, "session_id": "a"})
'''

PLAN = {"schema_version": "1.0", "plan_date": "2026-10-07", "source_scan": {"scan_date": "2026-10-06", "report_schema_version": "1.0"},
        "waves": [{"wave": 2, "title": "requests", "component_keys": ["requests"], "modules": ["infra"], "depends_on": [],
                   "targets": [{"component_key": "requests", "from": "2.19.0", "to": "2.32.3"}], "intermediate_steps": [],
                   "changes": [{"description": "bump", "file": "requirements.txt", "line": 1, "impact_ref": "I1"}],
                   "entry_gates": [{"check": "a", "how": "b", "pass_criterion": "c"}], "exit_gates": [{"check": "a", "how": "b", "pass_criterion": "c"}],
                   "rollback": "revert", "approvers": ["security"], "risk": "low", "effort": "S", "evidence": [], "status": "PROVEN"}],
        "coverage": {"outdated_production_component_keys": ["requests"], "uncovered": [], "deferred": []},
        "blocking_decisions": [], "proof": {"wave": 2, "patch_file": "wave-2.patch", "base_refs": {}, "steps": [{"id": "P1", "command": "x", "result": "PASS", "output_excerpt": "ok"}]}}


def git(*a, cwd=None):
    return subprocess.run(["git", *a], cwd=cwd, check=True, capture_output=True, text=True).stdout.strip()


@pytest.fixture
def project(tmp_path, monkeypatch):
    # "remote" = a local bare repo that git transparently uses for https://github.com/acme/infra.git
    seed, bare = tmp_path / "seed", tmp_path / "infra.git"
    seed.mkdir()
    (seed / "requirements.txt").write_text("requests==2.19.0\n")
    git("init", "-q", "-b", "main", cwd=seed); git("add", "-A", cwd=seed)
    git("-c", "user.name=t", "-c", "user.email=t@t", "commit", "-qm", "init", cwd=seed)
    git("clone", "-q", "--bare", str(seed), str(bare))
    for k, v in {"GIT_CONFIG_COUNT": "1", "GIT_CONFIG_KEY_0": f"url.{bare.as_uri()}.insteadOf",
                 "GIT_CONFIG_VALUE_0": "https://github.com/acme/infra.git", "GIT_ALLOW_PROTOCOL": "file:https"}.items():
        monkeypatch.setenv(k, v)
    monkeypatch.setenv("INFRA_TOKEN", "tok-SECRET-123")
    bindir = tmp_path / "bin"; bindir.mkdir()
    fake = bindir / "claude"; fake.write_text(FAKE); fake.chmod(fake.stat().st_mode | stat.S_IEXEC)
    monkeypatch.setenv("PATH", f"{bindir}{os.pathsep}{os.environ['PATH']}")
    monkeypatch.setenv("FAKE_STATE", str(tmp_path))
    proj = tmp_path / "proj"; proj.mkdir()
    (proj / "migration.yaml").write_text(yaml.safe_dump({
        "version": 1, "project": "demo", "runner": {"type": "local", "isolation": "none"},
        "estate": [{"name": "infra", "repo": "https://github.com/acme/infra.git", "ref": "main", "token_env": "INFRA_TOKEN"}],
        "agents": {"max_iterations": 1}}))
    cfg, st = config.load(proj), State(proj)
    pd = st.cache / "plans" / "plan-1"; pd.mkdir(parents=True)
    (pd / "migration-plan.json").write_text(json.dumps(PLAN))
    (pd / "meta.json").write_text(json.dumps({"id": "plan-1", "status": "idle", "created_at": "2026-10-07T00:00:00Z"}))
    opened = []
    monkeypatch.setitem(publish.OPENERS, "github", lambda m, tok, br, base, title, body: opened.append((br, base, title, body, tok)) or
                        {"url": "https://github.com/acme/infra/pull/7", "number": 7})
    return cfg, st, bare, opened, tmp_path


def test_prepare_then_approve_publishes_branch_and_pr(project):
    cfg, st, bare, opened, tmp = project
    rid = local.prepare(cfg, st, "prs", log=lambda *_: None, plan_run="plan-1", wave=2)
    assert local.work(cfg, st, "prs", rid) == "satisfied"
    d = st.cache / "prs" / rid
    assert (d / "pr.json").exists() and (d / "infra.patch").exists()
    assert json.loads((d / "meta.json").read_text())["review"] == {"state": "pending"}

    page = dashboard.payload(cfg, st)
    run = page["pr_runs"][0]
    assert run["publishable"] == {"infra": True} and "+requests==2.32.3" in run["patches"]["infra"]

    review = publish.decide(cfg, st, rid, True, log=lambda *_: None)
    assert review["state"] == "approved" and review["published"][0]["number"] == 7
    assert git("--git-dir", str(bare), "show", "migration/wave-2-requests:requirements.txt") == "requests==2.32.3"
    assert git("--git-dir", str(bare), "show", "main:requirements.txt") == "requests==2.19.0"     # main untouched
    br, base, title, body, tok = opened[0]
    assert (br, base) == ("migration/wave-2-requests", "main") and "approved before publishing" in body
    assert "tok-SECRET-123" not in (tmp / "argv.log").read_text()                                 # the agent never saw it
    assert dashboard.payload(cfg, st)["prs"][0]["url"].endswith("/pull/7")
    with pytest.raises(RuntimeError, match="already approved"):
        publish.decide(cfg, st, rid, True, log=lambda *_: None)


def test_deny_publishes_nothing(project):
    cfg, st, bare, opened, _ = project
    rid = local.prepare(cfg, st, "prs", log=lambda *_: None, plan_run="plan-1", wave=2)
    local.work(cfg, st, "prs", rid)
    review = publish.decide(cfg, st, rid, False, "not this sprint", log=lambda *_: None)
    assert review["state"] == "denied" and not opened
    assert "migration/wave-2-requests" not in git("--git-dir", str(bare), "branch")


def test_missing_token_blocks_approval_until_fixed(project, monkeypatch):
    cfg, st, bare, opened, _ = project
    rid = local.prepare(cfg, st, "prs", log=lambda *_: None, plan_run="plan-1", wave=2)
    local.work(cfg, st, "prs", rid)
    monkeypatch.delenv("INFRA_TOKEN")
    with pytest.raises(RuntimeError, match="cannot publish yet — infra: needs a token"):
        publish.decide(cfg, st, rid, True, log=lambda *_: None)
    assert json.loads((st.cache / "prs" / rid / "meta.json").read_text())["review"]["state"] == "failed" and not opened
    monkeypatch.setenv("INFRA_TOKEN", "tok-SECRET-123")                      # fixed → approve again
    assert publish.decide(cfg, st, rid, True, log=lambda *_: None)["state"] == "approved" and len(opened) == 1


def test_unknown_wave_is_rejected(project):
    cfg, st, *_ = project
    with pytest.raises(RuntimeError, match="no wave 9"):
        local.prepare(cfg, st, "prs", log=lambda *_: None, plan_run="plan-1", wave=9)


def test_repo_without_token_env_is_patch_only_not_blocking(project, monkeypatch, tmp_path):
    cfg, st, bare, opened, _ = project
    cfg["estate"][0].pop("token_env")
    pr = {"modules": [{"module": "infra"}]}
    problems = publish.check(cfg, pr)
    assert "patch only" in problems["infra"] and publish.blocking(cfg, problems) == {}
