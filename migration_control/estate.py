"""How each module's code reaches the agent's sandbox.

  clone   public repo → the agent runs `git clone` itself (fresh on every run)
  mount   private GitHub repo → `github_repository` session resource (fresh on every run)
  upload  private GitLab repo or local path → snapshot built here, uploaded with the Files API

Tokens are only used locally (upload) or handed to the API as the repository resource's
authorization token (mount). They never appear in prompts, logs or .mig/.
"""
import hashlib
import os
import re
import shutil
import subprocess
import tarfile
import tempfile
from pathlib import Path
from urllib.parse import urlparse, urlunparse

SKIP_DIRS = {"node_modules", "target", "build", "dist", ".venv", "venv", "__pycache__", ".gradle", ".idea", ".mig"}
SHA_RE = re.compile(r"^[0-9a-f]{40}$")


def workspace(m):
    return f"/workspace/{m.name}"


def setup_line(m, i):
    """One numbered setup instruction for the task prompt."""
    head = f"{i}. {m.name}" + (f" — {m['description']}" if m.get("description") else "")
    if m.get("depends_on"):
        head += f" (depends on: {', '.join(m['depends_on'])})"
    if m.fetch == "local":
        ref = f" (ref {m.ref})" if "repo" in m else ""
        body = f"   Already checked out at {workspace(m)}{ref}. Leave it as is; experiment on throwaway copies."
    elif m.fetch == "clone":
        body = f"   git clone {m['repo']} {workspace(m)} && git -C {workspace(m)} checkout {m.ref}"
    elif m.fetch == "mount":
        body = f"   Already mounted at {workspace(m)} (ref {m.ref}). Do not push from it."
    else:
        body = (f"   Uploaded as {m.name}.tar.gz under /mnt/session/uploads/ — extract it so the code lands in {workspace(m)}:\n"
                f"   mkdir -p /workspace && tar -xzf /mnt/session/uploads/{m.name}.tar.gz -C /workspace")
    return head + "\n" + body


def setup_text(modules):
    return "\n".join(setup_line(m, i) for i, m in enumerate(modules, 1))


def _redact(text, token):
    return text.replace(token, "***") if token else text


def _git(args, cwd=None, token=None, user=None):
    """Run git. With a token, auth goes through GIT_ASKPASS reading an env var — never through argv or the URL."""
    env = {**os.environ, "GIT_TERMINAL_PROMPT": "0"}
    askpass = None
    if token:
        fd, askpass = tempfile.mkstemp(prefix="mig-askpass-", suffix=".sh")
        with os.fdopen(fd, "w") as f:
            f.write('#!/bin/sh\ncase "$1" in Username*) echo "$MIG_GIT_USER";; *) echo "$MIG_GIT_TOKEN";; esac\n')
        os.chmod(askpass, 0o700)
        env.update(GIT_ASKPASS=askpass, MIG_GIT_TOKEN=token, MIG_GIT_USER=user or "x-access-token")
    try:
        r = subprocess.run(["git", *args], cwd=cwd, capture_output=True, text=True, env=env)
    finally:
        if askpass:
            os.unlink(askpass)
    if r.returncode:
        raise RuntimeError(_redact(f"git {' '.join(args)} failed: {r.stderr.strip()[:400]}", token))
    return r.stdout.strip()


def git_user(m):
    return "oauth2" if m.provider == "gitlab" else "x-access-token"


def _authed_url(m, token):
    """Only used by `mig doctor` for ls-remote reachability; clones and pushes use askpass."""
    u = urlparse(m["repo"])
    return urlunparse(u._replace(netloc=f"{git_user(m)}:{token}@{u.hostname}" + (f":{u.port}" if u.port else "")))


def base_branch(m):
    if m.get("base_branch"):
        return m["base_branch"]
    if SHA_RE.match(m.ref) or re.match(r"^v?\d+(\.\d+)*", m.ref):
        return None   # a commit or a version tag: we cannot guess the branch to target
    return m.ref


def _tar(src_dir, name, out):
    def keep(ti):
        parts = Path(ti.name).parts
        return None if any(p in SKIP_DIRS for p in parts) else ti
    with tarfile.open(out, "w:gz") as tf:
        tf.add(src_dir, arcname=name, filter=keep)


def _clone(m, dst):
    """Clone a repo module at its ref into dst (token used for the clone only, then removed from the remote)."""
    token, user = m.token(), git_user(m)
    if SHA_RE.match(m.ref):
        _git(["clone", "--quiet", m["repo"], str(dst)], token=token, user=user)
        _git(["checkout", "--quiet", m.ref], cwd=dst)
    else:
        _git(["clone", "--quiet", "--depth", "1", "--branch", m.ref, m["repo"], str(dst)], token=token, user=user)
    return _git(["rev-parse", "HEAD"], cwd=dst)


def _git_baseline(dst):
    """Give a copied (non-git) module a baseline commit so agents can produce `git diff` patches."""
    if (dst / ".git").exists():
        return
    _git(["init", "--quiet"], cwd=dst)
    _git(["add", "-A"], cwd=dst)
    _git(["-c", "user.name=migration-control", "-c", "user.email=migration-control@localhost", "commit", "--quiet",
          "--no-gpg-sign", "-m", "production baseline"], cwd=dst)


def _extract_single_root(archive, tmp):
    with tarfile.open(archive) as tf:
        tf.extractall(tmp)  # noqa: S202 — the user's own archive
    entries = list(Path(tmp).iterdir())
    return entries[0] if len(entries) == 1 and entries[0].is_dir() else Path(tmp)


def materialize(cfg, m, workspace_dir):
    """Put module m at <workspace_dir>/<name> for a local run. Returns a short description of what was placed."""
    dst = Path(workspace_dir) / m.name
    if "path" in m:
        src = (cfg.root / m["path"]).resolve()
        if src.is_file():
            with tempfile.TemporaryDirectory() as tmp:
                shutil.copytree(_extract_single_root(src, tmp), dst, ignore=shutil.ignore_patterns(*SKIP_DIRS))
        else:
            shutil.copytree(src, dst, ignore=shutil.ignore_patterns(*SKIP_DIRS))
        _git_baseline(dst)
        return f"copied from {m['path']}"
    return f"cloned at {_clone(m, dst)[:12]}"


def snapshot(cfg, m, out_dir):
    """Build <out_dir>/<name>.tar.gz for an `upload` module. Returns (path, fingerprint)."""
    out_dir = Path(out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    out = out_dir / f"{m.name}.tar.gz"
    if "path" in m:
        src = (cfg.root / m["path"]).resolve()
        if src.is_file():
            # re-pack so the code always lands in /workspace/<module name>, whatever the archive's top folder
            fp = hashlib.sha256(src.read_bytes()).hexdigest()[:16]
            with tempfile.TemporaryDirectory() as tmp:
                _tar(_extract_single_root(src, tmp), m.name, out)
            return out, fp
        _tar(src, m.name, out)
        h = hashlib.sha256()
        for p in sorted(src.rglob("*")):
            if p.is_file() and not any(part in SKIP_DIRS for part in p.relative_to(src).parts):
                h.update(str(p.relative_to(src)).encode()); h.update(str(p.stat().st_mtime_ns).encode())
        return out, h.hexdigest()[:16]
    with tempfile.TemporaryDirectory() as tmp:
        dst = Path(tmp) / m.name
        head = _clone(m, dst)
        _tar(dst, m.name, out)
    return out, head[:16]


def resources(cfg, st, *, include_uploads=True):
    """Session resources for every module (mount + upload kinds)."""
    res = []
    for m in cfg.modules:
        if m.fetch == "mount":
            checkout = {"type": "commit", "sha": m.ref} if SHA_RE.match(m.ref) else {"type": "branch", "name": m.ref}
            res.append({"type": "github_repository", "url": m["repo"].removesuffix(".git"), "mount_path": workspace(m),
                        "checkout": checkout, "authorization_token": m.token()})
        elif m.fetch == "upload" and include_uploads:
            fid = st.get("uploads", m.name, "file_id")
            if not fid:
                raise RuntimeError(f"module {m.name} has no uploaded snapshot — run `mig up`")
            res.append({"type": "file", "file_id": fid, "mount_path": f"/mnt/session/uploads/{m.name}.tar.gz"})
    return res


def sync_uploads(cfg, st, client, log=print):
    """Snapshot + upload every `upload` module whose content changed. Returns True if anything was re-uploaded."""
    changed = False
    for m in cfg.modules:
        if m.fetch != "upload":
            continue
        path, fp = snapshot(cfg, m, st.dir / "snapshots")
        if st.get("uploads", m.name, "fingerprint") == fp and st.get("uploads", m.name, "file_id"):
            log(f"  {m.name}: snapshot unchanged ({fp})")
            continue
        f = client.upload_file(path, "application/gzip")
        st.set("uploads", m.name, value={"file_id": f["id"], "fingerprint": fp})
        log(f"  {m.name}: uploaded snapshot {fp} → {f['id']}")
        changed = True
    return changed
