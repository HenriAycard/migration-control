"""Render the agents, kickoff tasks, rubrics and report schemas from migration.yaml.

Everything an agent sees is derived from the config, so two projects never share
hand-edited prompts. Rendered files are written to .mig/rendered/ for review.
"""
import copy
import hashlib
import json
import re
from string import Template

from . import RESOURCES
from .estate import setup_text

PROMPTS = RESOURCES / "prompts"
LITERAL_DATE = re.compile(r"\b20\d{2}-\d{2}-\d{2}\b")


def _tpl(name, **values):
    return Template((PROMPTS / name).read_text()).substitute(**values)


def _rules(cfg):
    rules = cfg["policy"].get("rules") or []
    return "".join(f"- {r}\n" for r in rules)


def report_schema(cfg):
    s = json.loads((RESOURCES / "schemas" / "impact-report.schema.json").read_text())
    s["$defs"]["module"]["enum"] = [m.name for m in cfg.modules]
    return s


def plan_schema(cfg):
    s = json.loads((RESOURCES / "schemas" / "migration-plan.schema.json").read_text())
    s["$defs"]["module"]["enum"] = [m.name for m in cfg.modules]
    s["$defs"]["approver"]["enum"] = list(cfg["policy"]["approvers"])
    return s


def _dumps_schema(s):
    return json.dumps(s, indent=2, ensure_ascii=False)


# ── scanner ──────────────────────────────────────────────────────────────────
def scanner_agent(cfg, model, skill_id):
    xlsx = cfg["agents"]["xlsx"]
    system = _tpl("scanner-system.md",
                  agent_name=f"{cfg['project']}-scanner", project=cfg["project"], target=cfg["policy"]["target"],
                  xlsx_skill_line=(" Produce the Excel workbook with openpyxl (`pip install openpyxl`)." if cfg.local else
                                   " Use the xlsx skill to produce the Excel workbook.") if xlsx else "",
                  xlsx_output=" and /mnt/session/outputs/impact-report.xlsx (for security and auditors)" if xlsx else "",
                  extra_rules=_rules(cfg))
    skills = [{"type": "custom", "skill_id": skill_id, "version": "latest"}]
    if xlsx:
        skills.append({"type": "anthropic", "skill_id": "xlsx"})
    return {"name": f"{cfg['project']}-scanner", "model": model,
            "description": "Whole-estate version, security-patch and CVE scan with a code-level upgrade impact report.",
            "system": system, "tools": [{"type": "agent_toolset_20260401"}], "skills": skills,
            "metadata": {"project": cfg["project"], "role": "scanner", "tool": "migration-control"}}


def scanner_task(cfg):
    mods = cfg.modules
    xlsx = cfg["agents"]["xlsx"]
    return _tpl("scanner-task.md",
                module_count=len(mods), module_setup=setup_text(mods),
                xlsx_deliverable=(f"\n- impact-report.xlsx — Excel workbook for security and auditors ({'openpyxl' if cfg.local else 'use the xlsx skill'}), sheets in this order: "
                                  "Summary (verdict + severity counts), Alerts, Inventory (module, component_key, current, latest, latest security patch, "
                                  "EOL, source), CVEs (component_key, CVE ID, CVSS, severity, fixed in, link, verified). Header row frozen, autofilter on, "
                                  "same data as impact-report.json.") if xlsx else "",
                toolchain_note=("" if cfg["policy"]["include_toolchain"] else
                                " Report production components only (scope \"production\"); leave test and build toolchain components out."),
                schema=_dumps_schema(report_schema(cfg)))


def scanner_rubric(cfg):
    mods = cfg.modules
    deps = [f"{m.name} → {d}" for m in mods for d in m.get("depends_on", [])]
    xlsx = cfg["agents"]["xlsx"]
    deliverables = "impact-summary.md, impact-report.md, impact-report.json" + (", impact-report.xlsx" if xlsx else "")
    return _tpl("scanner-rubric.md",
                deliverables=deliverables, module_list=", ".join(m.name for m in mods),
                dependency_minimum=(f" — at minimum {'; '.join(deps)}" if deps else ""),
                xlsx_criterion=("8. **Audit workbook.** impact-report.xlsx opens, has the sheets Summary, Alerts, Inventory and CVEs in that order "
                                "with a frozen header row and autofilter, and its alerts, components and CVE IDs match impact-report.json.\n") if xlsx else "")


# ── planner ──────────────────────────────────────────────────────────────────
def planner_agent(cfg, model, skill_id):
    approvers = ", ".join(cfg["policy"]["approvers"])
    system = _tpl("planner-system.md", agent_name=f"{cfg['project']}-planner", project=cfg["project"],
                  approver_list=approvers, extra_rules=_rules(cfg))
    return {"name": f"{cfg['project']}-planner", "model": model,
            "description": "Turns a validated impact report into an ordered, gated, provable migration plan (waves) and proves the first code wave.",
            "system": system, "tools": [{"type": "agent_toolset_20260401"}],
            "skills": [{"type": "custom", "skill_id": skill_id, "version": "latest"}],
            "metadata": {"project": cfg["project"], "role": "planner", "tool": "migration-control"}}


def planner_task(cfg, scan_session):
    return _tpl("planner-task.md", scan_session=scan_session, module_setup=setup_text(cfg.modules),
                schema=_dumps_schema(plan_schema(cfg)))


def planner_rubric(cfg):
    return (PROMPTS / "planner-rubric.md").read_text()


# ── PR agent ─────────────────────────────────────────────────────────────────
def pr_schema(cfg):
    s = json.loads((RESOURCES / "schemas" / "pr.schema.json").read_text())
    s["$defs"]["module"]["enum"] = [m.name for m in cfg.modules]
    return s


def pr_system(cfg):
    return _tpl("pr-system.md", agent_name=f"{cfg['project']}-pr", project=cfg["project"],
                approver_list=", ".join(cfg["policy"]["approvers"]), extra_rules=_rules(cfg))


def pr_task(cfg, plan_run, wave, has_patch):
    return _tpl("pr-task.md", plan_run=plan_run, wave=wave, module_setup=setup_text(cfg.modules),
                patch_line=("/mnt/session/uploads/wave.patch — the planner's proven patch for this wave (paths prefixed by the module name; "
                            "apply it from /workspace)." if has_patch else
                            "No proven patch exists for this wave: implement its `changes` from the plan yourself."),
                schema=_dumps_schema(pr_schema(cfg)))


def pr_rubric(cfg):
    return (PROMPTS / "pr-rubric.md").read_text()


# ── shared ───────────────────────────────────────────────────────────────────
def outcome_event(cfg, task, rubric):
    return {"type": "user.define_outcome", "description": task,
            "rubric": {"type": "text", "content": rubric}, "max_iterations": cfg["agents"]["max_iterations"]}


def environment(cfg):
    return {"name": f"{cfg['project']}-env",
            "config": {"type": "cloud", "networking": {"type": "unrestricted"},
                       "packages": copy.deepcopy(cfg["sandbox"].get("packages") or {})}}


def fingerprint(obj):
    return hashlib.sha256(json.dumps(obj, sort_keys=True).encode()).hexdigest()[:16]


def check_no_literal_dates(*texts):
    """Deployment kickoffs are replayed verbatim on every run — a literal date would freeze 'today'."""
    for t in texts:
        m = LITERAL_DATE.search(t)
        if m:
            raise ValueError(f"literal date {m.group(0)} in a scheduled kickoff — use relative wording ('as of today')")


def write_preview(cfg, st, scan_session="<scan session>"):
    out = st.dir / "rendered"
    out.mkdir(parents=True, exist_ok=True)
    files = {
        "scanner-agent.json": json.dumps(scanner_agent(cfg, "<model>", "<skill id>"), indent=2),
        "scanner-task.md": scanner_task(cfg), "scanner-rubric.md": scanner_rubric(cfg),
        "planner-agent.json": json.dumps(planner_agent(cfg, "<model>", "<skill id>"), indent=2),
        "planner-task.md": planner_task(cfg, scan_session), "planner-rubric.md": planner_rubric(cfg),
        "environment.json": json.dumps(environment(cfg), indent=2),
    }
    for name, text in files.items():
        (out / name).write_text(text)
    return out
