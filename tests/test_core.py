import json
import re
import tarfile

import pytest
import yaml
from jsonschema import Draft202012Validator

from migration_control import RESOURCES, config, dashboard, estate, render
from migration_control.state import State

PETCLINIC = RESOURCES / "examples" / "petclinic"


def write_cfg(tmp_path, data):
    (tmp_path / "migration.yaml").write_text(yaml.safe_dump(data))
    return config.load(tmp_path)


def base(**over):
    d = {"version": 1, "project": "acme", "estate": [
        {"name": "api", "repo": "https://github.com/acme/api.git", "token_env": "GH_TOKEN", "depends_on": ["db"]},
        {"name": "web", "repo": "https://gitlab.com/acme/web", "token_env": "GL_TOKEN", "depends_on": ["api"]},
        {"name": "db", "repo": "https://github.com/acme/db"},
    ], "runner": {"type": "managed"}}
    d.update(over)
    return d


def test_fetch_modes(tmp_path):
    cfg = write_cfg(tmp_path, base())
    assert [m.fetch for m in cfg.modules] == ["mount", "upload", "clone"]
    d = base(); d.pop("runner")
    assert [m.fetch for m in write_cfg(tmp_path, d).modules] == ["local"] * 3   # local runner is the default
    assert [m.provider for m in cfg.modules] == ["github", "gitlab", "github"]


def test_validation_errors(tmp_path):
    bad = base()
    bad["estate"][0]["depends_on"] = ["nope"]
    bad["estate"].append({"name": "api", "path": "x"})
    errors = config.validate(bad)
    assert any("depends_on 'nope'" in e for e in errors)
    assert any("unique" in e for e in errors)
    assert config.validate({"version": 1, "project": "Bad Name", "estate": []})


def test_self_hosted_gitlab_needs_provider(tmp_path):
    d = base()
    d["estate"][2]["repo"] = "https://git.acme.internal/x/db"
    with pytest.raises(config.ConfigError, match="provider"):
        write_cfg(tmp_path, d)


def test_prompts_render_without_leftovers(tmp_path):
    cfg = write_cfg(tmp_path, base(schedule={"cron": "0 6 * * 1", "timezone": "UTC"}))
    task, rubric = render.scanner_task(cfg), render.scanner_rubric(cfg)
    for text in (task, rubric, render.planner_task(cfg, "sesn_x"), render.scanner_agent(cfg, "m", "s")["system"],
                 render.planner_agent(cfg, "m", "s")["system"]):
        assert not re.search(r"\$(?!schema|defs|ref)[a-z_]+", text)
    assert "api → db; web → api" in rubric
    assert "/workspace/web" in task and "git clone https://github.com/acme/db" in task
    render.check_no_literal_dates(task, rubric)


def test_schemas_get_module_enums(tmp_path):
    cfg = write_cfg(tmp_path, base())
    assert render.report_schema(cfg)["$defs"]["module"]["enum"] == ["api", "web", "db"]
    assert render.plan_schema(cfg)["$defs"]["approver"]["enum"] == ["tech-lead", "security", "platform-ops"]


def test_recorded_example_reports_validate_against_rendered_schema():
    cfg = config.load(PETCLINIC)
    v = Draft202012Validator(render.report_schema(cfg))
    reports = list((PETCLINIC / "recorded" / "scans").glob("*/impact-report.json"))
    assert reports
    for p in reports:
        assert not list(v.iter_errors(json.loads(p.read_text()))), p


def test_literal_date_guard():
    with pytest.raises(ValueError):
        render.check_no_literal_dates("scan as of 2026-10-06")


def test_snapshot_repacks_under_module_name(tmp_path):
    cfg = config.load(PETCLINIC)
    m = cfg.module("petclinic-infra")
    out, fp = estate.snapshot(cfg, m, tmp_path)
    names = tarfile.open(out).getnames()
    assert all(n == "petclinic-infra" or n.startswith("petclinic-infra/") for n in names)
    assert estate.snapshot(cfg, m, tmp_path)[1] == fp


def test_dashboard_builds_offline_from_example(tmp_path):
    cfg = config.load(PETCLINIC)
    st = State(tmp_path)
    import shutil
    shutil.copytree(PETCLINIC / "recorded", st.cache)
    data = dashboard.payload(cfg, st)
    assert len(data["scans"]) == 3 and len(data["plans"]) == 1
    assert [m["name"] for m in data["modules"]] == ["petclinic-rest", "petclinic-angular", "petclinic-infra"]
    assert data["rubrics"]["scanner"] and data["rubrics"]["planner"]
    page = dashboard.build(cfg, st, None, log=lambda *_: None).read_text()
    assert "/*__DATA__*/null" not in page
