"""Minimal Claude Managed Agents client (stdlib only).

The key is read from ANTHROPIC_API_KEY (environment, or a .env / .env.local file next to
migration.yaml that *you* create). It is never written anywhere by this tool.
"""
import json
import mimetypes
import os
import time
import urllib.error
import urllib.parse
import urllib.request
import uuid
from pathlib import Path

BASE = os.environ.get("ANTHROPIC_BASE_URL", "https://api.anthropic.com").rstrip("/") + "/v1"
BETA_AGENTS = "managed-agents-2026-04-01"
BETA_MEMORY = "agent-memory-2026-07-22"   # replaces (never joins) the agents beta on /memory_stores


class ApiError(Exception):
    def __init__(self, status, body, path):
        self.status, self.body, self.path = status, body, path
        super().__init__(f"HTTP {status} on {path}: {body[:500]}")


def load_dotenv(root):
    """Read KEY=VALUE lines from .env / .env.local into os.environ (existing variables win)."""
    for name in (".env", ".env.local"):
        p = Path(root) / name
        if not p.exists():
            continue
        for line in p.read_text().splitlines():
            line = line.strip()
            if not line or line.startswith("#") or "=" not in line:
                continue
            k, v = line.split("=", 1)
            k = k.strip().removeprefix("export ").strip()
            os.environ.setdefault(k, v.strip().strip('"').strip("'"))


class Client:
    def __init__(self, key=None):
        self.key = key or os.environ.get("ANTHROPIC_API_KEY")
        if not self.key:
            raise ApiError(0, "ANTHROPIC_API_KEY is not set — export it, or put it in .env next to migration.yaml", "-")

    def _headers(self, beta=BETA_AGENTS, ctype="application/json"):
        h = {"x-api-key": self.key, "anthropic-version": "2023-06-01"}
        if beta:
            h["anthropic-beta"] = beta
        if ctype:
            h["content-type"] = ctype
        return h

    def request(self, method, path, body=None, *, beta=BETA_AGENTS, raw=False, data=None, ctype="application/json", params=None):
        url = BASE + path
        if params:
            url += ("&" if "?" in url else "?") + urllib.parse.urlencode(params, doseq=True)
        payload = data if data is not None else (json.dumps(body).encode() if body is not None else None)
        if method == "POST" and payload is None:
            payload = b"{}"
        req = urllib.request.Request(url, data=payload, method=method, headers=self._headers(beta, ctype))
        for attempt in range(4):
            try:
                with urllib.request.urlopen(req, timeout=120) as r:
                    out = r.read()
                break
            except urllib.error.HTTPError as e:
                text = e.read().decode(errors="replace")
                if e.code in (429, 500, 502, 503, 529) and attempt < 3:
                    time.sleep(2 ** attempt * 2)
                    continue
                raise ApiError(e.code, text, path) from None
        if raw:
            return out
        return json.JSONDecoder(strict=False).decode(out.decode()) if out else {}

    get = lambda self, path, **kw: self.request("GET", path, **kw)
    post = lambda self, path, body=None, **kw: self.request("POST", path, body, **kw)

    # ── helpers ──────────────────────────────────────────────────────────────
    def paged(self, path, params=None, key="data"):
        """Follow both pagination styles used by the API (after_id/has_more and next_page)."""
        base = list(params.items()) if isinstance(params, dict) else list(params or [])   # list form allows repeated keys
        cursor = []
        while True:
            d = self.get(path, params=base + cursor)
            yield from d.get(key, [])
            if d.get("next_page"):
                cursor = [("page", d["next_page"])]
            elif d.get("has_more") and d.get("last_id"):
                cursor = [("after_id", d["last_id"])]
            else:
                return

    def upload_file(self, path, mime=None):
        path = Path(path)
        mime = mime or mimetypes.guess_type(path.name)[0] or "application/octet-stream"
        boundary = uuid.uuid4().hex
        body = (f"--{boundary}\r\nContent-Disposition: form-data; name=\"file\"; filename=\"{path.name}\"\r\n"
                f"Content-Type: {mime}\r\n\r\n").encode() + path.read_bytes() + f"\r\n--{boundary}--\r\n".encode()
        return self.request("POST", "/files", data=body, ctype=f"multipart/form-data; boundary={boundary}")

    def upload_skill(self, title, files):
        """files: [(path_in_skill e.g. 'regulated-sourcing/SKILL.md', bytes)] → skill object. No beta header on /skills."""
        boundary = uuid.uuid4().hex
        parts = [f"--{boundary}\r\nContent-Disposition: form-data; name=\"display_title\"\r\n\r\n{title}\r\n".encode()]
        for name, content in files:
            parts.append((f"--{boundary}\r\nContent-Disposition: form-data; name=\"files[]\"; filename=\"{name}\"\r\n"
                          "Content-Type: text/markdown\r\n\r\n").encode() + content + b"\r\n")
        parts.append(f"--{boundary}--\r\n".encode())
        return self.request("POST", "/skills", data=b"".join(parts), beta=None, ctype=f"multipart/form-data; boundary={boundary}")

    def output_files(self, session_id):
        return list(self.paged("/files", {"scope_id": session_id, "limit": 100}))

    def download(self, file_id):
        return self.get(f"/files/{file_id}/content", raw=True)
