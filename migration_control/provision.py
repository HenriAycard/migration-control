"""`mig up`: create or update everything in the Anthropic workspace, idempotently.

environment → custom skill → memory store → scanner (+ planner) agent → module snapshots → deployment
Each object's ID lands in .mig/state.json; re-running only creates what is missing and
versions what changed.
"""
from . import render
from .api import BETA_MEMORY, ApiError
from .estate import resources, sync_uploads
from . import RESOURCES

SKILL_DIR = RESOURCES / "skills" / "regulated-sourcing"


def pick_model(cfg, client, st, log):
    want = cfg["agents"]["model"]
    if want != "auto":
        st.set("model", value=want)
        return want
    if st.get("model"):
        return st.get("model")
    ids = [m["id"] for m in client.get("/models", params={"limit": 100}, beta=None).get("data", [])]
    opus = [i for i in ids if "opus" in i]
    model = (opus or ids)[0]
    st.set("model", value=model)
    log(f"  model: {model} (newest Opus-class — pin it with agents.model in migration.yaml)")
    return model


def ensure_environment(cfg, client, st, log):
    body = render.environment(cfg)
    fp = render.fingerprint(body)
    if st.get("environment", "id") and st.get("environment", "fingerprint") == fp:
        log(f"  environment: {st.get('environment', 'id')} (unchanged)")
        return st.get("environment", "id")
    if st.get("environment", "id"):
        # environments are not versioned: create a fresh one with a suffixed name
        body["name"] = f"{body['name']}-{fp[:6]}"
    env = client.post("/environments", body)
    st.set("environment", value={"id": env["id"], "fingerprint": fp})
    log(f"  environment: {env['id']} (created)")
    return env["id"]


def ensure_skill(cfg, client, st, log):
    if st.get("skill", "id"):
        log(f"  skill regulated-sourcing: {st.get('skill', 'id')} (exists)")
        return st.get("skill", "id")
    files = [(f"regulated-sourcing/{p.name}", p.read_bytes()) for p in sorted(SKILL_DIR.iterdir()) if p.is_file()]
    skill = client.upload_skill(f"regulated-sourcing ({cfg['project']})", files)
    st.set("skill", value={"id": skill["id"]})
    log(f"  skill regulated-sourcing: {skill['id']} (uploaded)")
    return skill["id"]


def ensure_memory(cfg, client, st, log):
    if st.get("memory_store_id"):
        log(f"  memory store: {st.get('memory_store_id')} (exists)")
        return st.get("memory_store_id")
    ms = client.post("/memory_stores", {
        "name": f"{cfg['project']}-scan-history",
        "description": "State of the previous whole-estate scan (component_key, version, latest version, CVE IDs), used to build the New since last scan section.",
    }, beta=BETA_MEMORY)
    st.set("memory_store_id", value=ms["id"])
    log(f"  memory store: {ms['id']} (created)")
    return ms["id"]


def ensure_agent(role, body, client, st, log):
    fp = render.fingerprint(body)
    cur = st.get("agents", role) or {}
    if cur.get("id") and cur.get("fingerprint") == fp:
        log(f"  {role} agent: {cur['id']} v{cur['version']} (unchanged)")
        return cur
    if cur.get("id"):
        upd = dict(body, version=cur["version"])
        a = client.post(f"/agents/{cur['id']}", upd)
        log(f"  {role} agent: {a['id']} v{cur['version']} → v{a['version']} (config changed — re-run your evals before trusting it)")
    else:
        a = client.post("/agents", body)
        log(f"  {role} agent: {a['id']} v{a['version']} (created)")
    cur = {"id": a["id"], "version": a["version"], "fingerprint": fp}
    st.set("agents", role, value=cur)
    return cur


def memory_resource(st):
    return {"type": "memory_store", "memory_store_id": st.get("memory_store_id"), "access": "read_write",
            "instructions": "Previous scan state. Read before writing the report; overwrite after."}


def budget(cfg):
    usd = cfg["agents"].get("budget_usd")
    return {"type": "limit", "max_list_cost": {"amount": str(int(usd * 100)), "currency": "USD"}} if usd else None


def deployment_body(cfg, st, env_id):
    scanner = st.get("agents", "scanner")
    task, rubric = render.scanner_task(cfg), render.scanner_rubric(cfg)
    render.check_no_literal_dates(task, rubric)
    body = {
        "name": f"{cfg['project']} — scheduled whole-estate scan",
        "agent": {"type": "agent", "id": scanner["id"], "version": scanner["version"]},
        "environment_id": env_id,
        "resources": [memory_resource(st), *resources(cfg, st)],
        "initial_events": [render.outcome_event(cfg, task, rubric)],
        "schedule": {"type": "cron", "expression": cfg["schedule"]["cron"], "timezone": cfg["schedule"]["timezone"]},
    }
    if budget(cfg):
        body["budget"] = budget(cfg)
    return body


def ensure_deployment(cfg, client, st, env_id, log):
    dep_id = st.get("deployment", "id")
    if not cfg.get("schedule"):
        if dep_id:
            log(f"  deployment: {dep_id} still exists but migration.yaml has no schedule — `mig schedule pause` to stop it")
        return None
    body = deployment_body(cfg, st, env_id)
    fp = render.fingerprint({k: v for k, v in body.items() if k != "resources"} | {"res": [r.get("file_id") or r.get("url") or r.get("memory_store_id") for r in body["resources"]]})
    if dep_id and st.get("deployment", "fingerprint") == fp:
        log(f"  deployment: {dep_id} (unchanged)")
        return dep_id
    if dep_id:
        # initial_events / agent / resources are snapshots: push the full new set
        d = client.post(f"/deployments/{dep_id}", {k: body[k] for k in ("agent", "resources", "initial_events", "schedule")}, params={"beta": "true"})
        log(f"  deployment: {dep_id} (updated)")
    else:
        d = client.post("/deployments", body, params={"beta": "true"})
        log(f"  deployment: {d['id']} (created)")
    st.set("deployment", value={"id": d["id"], "fingerprint": fp})
    nxt = ((d.get("schedule") or {}).get("upcoming_runs_at") or [None])[0]
    if nxt:
        log(f"  next scheduled run: {nxt}")
    if any(m.fetch == "upload" for m in cfg.modules):
        log("  note: uploaded modules are snapshots — scheduled runs scan the snapshot taken by the last `mig up`.\n"
            "        Re-run `mig up` (e.g. from CI) to refresh them, or make those repos reachable by clone/mount.")
    return d["id"]


def up(cfg, client, st, log=print):
    log("▶ model");        model = pick_model(cfg, client, st, log)
    log("▶ environment");  env_id = ensure_environment(cfg, client, st, log)
    log("▶ skill");        skill_id = ensure_skill(cfg, client, st, log)
    log("▶ memory");       ensure_memory(cfg, client, st, log)
    log("▶ agents")
    ensure_agent("scanner", render.scanner_agent(cfg, model, skill_id), client, st, log)
    if cfg["agents"]["planner"]:
        ensure_agent("planner", render.planner_agent(cfg, model, skill_id), client, st, log)
    log("▶ module snapshots")
    if not sync_uploads(cfg, st, client, log) and not any(m.fetch == "upload" for m in cfg.modules):
        log("  nothing to upload (every module is cloned or mounted at run time)")
    log("▶ deployment")
    try:
        ensure_deployment(cfg, client, st, env_id, log)
    except ApiError as e:
        log(f"  deployment failed: {e}")
        raise
    return st
