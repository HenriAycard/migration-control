"""How each module's code reaches the agent's sandbox.

  clone   public repo → the agent runs `git clone` itself (fresh on every run)
  mount   private GitHub repo → `github_repository` session resource (fresh on every run)
  upload  private GitLab repo or local path → snapshot built here, uploaded with the Files API

Tokens are only used locally (upload) or handed to the API as the repository resource's
authorization token (mount). They never appear in prompts, logs or .mig/.
"""
import hashlib
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
    if m.fetch == "clone":
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


def _git(args, cwd=None, token=None):
    r = subprocess.run(["git", *args], cwd=cwd, capture_output=True, text=True)
    if r.returncode:
        raise RuntimeError(_redact(f"git {' '.join(args)} failed: {r.stderr.strip()[:400]}", token))
    return r.stdout.strip()


def _authed_url(m, token):
    u = urlparse(m["repo"])
    user = "oauth2" if m.provider == "gitlab" else "x-access-token"
    return urlunparse(u._replace(netloc=f"{user}:{token}@{u.hostname}" + (f":{u.port}" if u.port else "")))


def _tar(src_dir, name, out):
    def keep(ti):
        parts = Path(ti.name).parts
        return None if any(p in SKIP_DIRS for p in parts) else ti
    with tarfile.open(out, "w:gz") as tf:
        tf.add(src_dir, arcname=name, filter=keep)


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
                with tarfile.open(src) as tf:
                    tf.extractall(tmp)  # noqa: S202 — the user's own archive
                entries = [p for p in Path(tmp).iterdir()]
                root = entries[0] if len(entries) == 1 and entries[0].is_dir() else Path(tmp)
                _tar(root, m.name, out)
            return out, fp
        _tar(src, m.name, out)
        h = hashlib.sha256()
        for p in sorted(src.rglob("*")):
            if p.is_file() and not any(part in SKIP_DIRS for part in p.relative_to(src).parts):
                h.update(str(p.relative_to(src)).encode()); h.update(str(p.stat().st_mtime_ns).encode())
        return out, h.hexdigest()[:16]
    token = m.token()
    with tempfile.TemporaryDirectory() as tmp:
        dst = Path(tmp) / m.name
        if SHA_RE.match(m.ref):
            _git(["clone", "--quiet", _authed_url(m, token), str(dst)], token=token)
            _git(["checkout", "--quiet", m.ref], cwd=dst, token=token)
        else:
            _git(["clone", "--quiet", "--depth", "1", "--branch", m.ref, _authed_url(m, token), str(dst)], token=token)
        _git(["remote", "set-url", "origin", m["repo"]], cwd=dst)      # no token inside the archive
        head = _git(["rev-parse", "HEAD"], cwd=dst)
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
