"""Publish an approved PR run: one branch + pull request (GitHub) / merge request (GitLab) per repository.

Runs on this machine only, after a human approved the prepared change set. The agent that prepared it never
had a write credential. Nothing is ever merged: humans review and merge.
"""
import json
import os
import subprocess
import tempfile
import urllib.error
import urllib.parse
import urllib.request
from datetime import datetime, timezone
from pathlib import Path
from urllib.parse import urlparse

from .estate import _git, _redact, base_branch, git_user

GITHUB_API = os.environ.get("MIG_GITHUB_API", "https://api.github.com")


def _now():
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")


def _repo_path(m):
    return urlparse(m["repo"]).path.strip("/").removesuffix(".git")


def _http(method, url, token, body, auth_header):
    req = urllib.request.Request(url, data=json.dumps(body).encode(), method=method,
                                 headers={"content-type": "application/json", "accept": "application/json",
                                          "user-agent": "migration-control", **auth_header(token)})
    try:
        with urllib.request.urlopen(req, timeout=60) as r:
            return json.loads(r.read().decode() or "{}")
    except urllib.error.HTTPError as e:
        raise RuntimeError(_redact(f"{method} {url} → HTTP {e.code}: {e.read().decode(errors='replace')[:400]}", token)) from None


def open_github_pr(m, token, branch, base, title, body):
    owner_repo = _repo_path(m)
    d = _http("POST", f"{GITHUB_API}/repos/{owner_repo}/pulls", token,
              {"title": title, "head": branch, "base": base, "body": body, "maintainer_can_modify": True},
              lambda t: {"authorization": f"Bearer {t}", "x-github-api-version": "2022-11-28"})
    return {"url": d["html_url"], "number": d["number"]}


def open_gitlab_mr(m, token, branch, base, title, body):
    u = urlparse(m["repo"])
    api = os.environ.get("MIG_GITLAB_API") or f"{u.scheme}://{u.netloc}/api/v4"
    project = urllib.parse.quote(_repo_path(m), safe="")
    d = _http("POST", f"{api}/projects/{project}/merge_requests", token,
              {"source_branch": branch, "target_branch": base, "title": title, "description": body, "remove_source_branch": False},
              lambda t: {"private-token": t})
    return {"url": d["web_url"], "number": d["iid"]}


OPENERS = {"github": open_github_pr, "gitlab": open_gitlab_mr}


def _identity():
    def cfg(key):
        r = subprocess.run(["git", "config", "--global", key], capture_output=True, text=True)
        return r.stdout.strip()
    return cfg("user.name") or "migration-control", cfg("user.email") or "migration-control@localhost"


def check(cfg, pr):
    """Per-module reasons a module will not get a PR/MR (empty dict = all publishable). See `blocking`."""
    problems = {}
    for entry in pr["modules"]:
        m = cfg.module(entry["module"])
        if "repo" not in m:
            problems[m.name] = "local path module — no remote to publish to; apply the patch yourself"
        elif not m.get("token_env"):
            problems[m.name] = "no token_env configured — patch only (e.g. an upstream repo you cannot write to)"
        elif not os.environ.get(m["token_env"]):
            problems[m.name] = f"needs a token with write access in {m['token_env']}"
        elif not base_branch(m):
            problems[m.name] = f"ref {m.ref} is not a branch — set base_branch for this module in migration.yaml"
    return problems


def blocking(cfg, problems):
    """Problems the user must fix before approving: a repo configured for publishing (token_env set) that cannot be
    published right now. Local paths and repos without token_env are simply patch-only."""
    return {k: v for k, v in problems.items() if "repo" in cfg.module(k) and cfg.module(k).get("token_env")}


def publish(cfg, run_dir, log=print, results=None):
    """Push one branch per publishable module and open its PR/MR, appending to `results` as it goes
    ([{module, url, number} | {module, patch_only}]). Modules already in `results` (a previous partial attempt) are skipped."""
    pr = json.loads((run_dir / "pr.json").read_text())
    if pr["status"] != "READY":
        raise RuntimeError(f"the PR agent marked this wave BLOCKED: {pr.get('blocked_reason')}")
    body = (run_dir / "pr-description.md").read_text()
    problems = check(cfg, pr)
    fix = blocking(cfg, problems)
    if fix:
        raise RuntimeError("cannot publish yet — " + "; ".join(f"{k}: {v}" for k, v in fix.items()))
    name, email = _identity()
    results = [] if results is None else results
    done = {r["module"] for r in results if r.get("url")}
    for entry in pr["modules"]:
        m = cfg.module(entry["module"])
        if m.name in done:
            log(f"  {m.name}: already published")
            continue
        results[:] = [r for r in results if r["module"] != m.name]
        patch = run_dir / entry["patch_file"]
        if m.name in problems:
            log(f"  {m.name}: not published — {problems[m.name]} ({patch})")
            results.append({"module": m.name, "patch_only": str(patch), "reason": problems[m.name]})
            continue
        token, base = os.environ[m["token_env"]], base_branch(m)
        with tempfile.TemporaryDirectory() as tmp:
            repo = Path(tmp) / m.name
            _git(["clone", "--quiet", "--branch", base, m["repo"], str(repo)], token=token, user=git_user(m))
            _git(["checkout", "--quiet", "-b", pr["branch"]], cwd=repo)
            _git(["apply", "--index", str(patch.resolve())], cwd=repo)
            _git(["-c", f"user.name={name}", "-c", f"user.email={email}", "commit", "--quiet", "--no-gpg-sign",
                  "-m", entry["commit_message"]], cwd=repo)
            _git(["push", "--quiet", "origin", f"HEAD:refs/heads/{pr['branch']}"], cwd=repo, token=token, user=git_user(m))
        others = [e["module"] for e in pr["modules"] if e["module"] != m.name]
        head = (f"> Prepared by migration-control (wave {pr['wave']}), approved before publishing."
                + (f" Same wave also changes: {', '.join(others)}." if others else "") + "\n\n")
        opened = OPENERS[m.provider](m, token, pr["branch"], base, pr["title"], head + body)
        log(f"  {m.name}: {'PR' if m.provider == 'github' else 'MR'} #{opened['number']} → {opened['url']}")
        results.append({"module": m.name, **opened})
    return results


def decide(cfg, st, rid, approve, reason="", log=print):
    """Record the human decision on a prepared PR run; publish on approval."""
    d = st.cache / "prs" / rid
    mp = d / "meta.json"
    if not mp.exists():
        raise RuntimeError(f"no PR run {rid}")
    meta = json.loads(mp.read_text())
    if meta.get("status") != "idle":
        raise RuntimeError(f"{rid} is {meta.get('status')} — wait until the PR agent and its grader finish")
    if (meta.get("review") or {}).get("state") not in ("pending", "failed"):
        raise RuntimeError(f"{rid} was already {meta['review']['state']}")
    who = _identity()[0]
    if not approve:
        meta["review"] = {"state": "denied", "by": who, "at": _now(), "reason": reason}
        mp.write_text(json.dumps(meta, indent=2))
        log(f"✓ {rid} denied — nothing was published")
        return meta["review"]
    results = list((meta.get("review") or {}).get("published") or [])   # resume a partial publish
    meta["review"] = {"state": "publishing", "by": who, "at": _now(), "published": results}
    mp.write_text(json.dumps(meta, indent=2))
    try:
        publish(cfg, d, log, results)
    except Exception as e:
        meta["review"] = {"state": "failed", "by": who, "at": _now(), "error": str(e)[:600], "published": results}
        mp.write_text(json.dumps(meta, indent=2))
        raise
    meta["review"] = {"state": "approved", "by": who, "at": _now(), "published": results}
    mp.write_text(json.dumps(meta, indent=2))
    return meta["review"]
