"""Load and validate migration.yaml, and fill in defaults."""
import json
import os
from pathlib import Path
from urllib.parse import urlparse

import yaml
from jsonschema import Draft202012Validator

from . import RESOURCES

CONFIG_NAME = "migration.yaml"
SCHEMA = json.loads((RESOURCES / "schemas" / "migration-config.schema.json").read_text())

DEFAULTS = {
    "policy": {
        "target": "latest official stable version and latest security patch for every component",
        "rules": [],
        "approvers": ["tech-lead", "security", "platform-ops"],
        "include_toolchain": True,
    },
    "sandbox": {"packages": {}},
    "agents": {"model": "auto", "max_iterations": 3, "planner": True, "xlsx": True},
    "console_workspace": "default",
    "runner": {"type": "local", "isolation": "docker"},
}


class ConfigError(Exception):
    pass


class Module(dict):
    """One estate entry, with derived fields: provider and fetch mode."""

    @property
    def name(self):
        return self["name"]

    @property
    def provider(self):
        if "repo" not in self:
            return None
        if self.get("provider"):
            return self["provider"]
        host = urlparse(self["repo"]).hostname or ""
        if host == "github.com":
            return "github"
        if "gitlab" in host:
            return "gitlab"
        raise ConfigError(f"module {self.name}: cannot tell GitHub from GitLab for {host} — set `provider:`")

    @property
    def ref(self):
        return self.get("ref", "main")

    @property
    def fetch(self):
        if self.get("_local"):
            return "local"
        return self.managed_fetch

    @property
    def managed_fetch(self):
        """How the code reaches the sandbox.

        clone   public repo: the agent clones it at run time (always fresh, also on scheduled runs)
        mount   private GitHub repo: `github_repository` session resource (fresh on every run)
        upload  private GitLab repo or local path: `mig` snapshots it locally and uploads it (Files API)
        """
        if "path" in self:
            return "upload"
        if not self.get("token_env"):
            return "clone"
        return "mount" if self.provider == "github" else "upload"

    def token(self):
        var = self.get("token_env")
        if not var:
            return None
        val = os.environ.get(var)
        if not val:
            raise ConfigError(f"module {self.name}: environment variable {var} is not set")
        return val


class Config(dict):
    def __init__(self, data, root):
        super().__init__(data)
        self.root = Path(root)

    @property
    def local(self):
        return self["runner"]["type"] == "local"

    @property
    def modules(self):
        return [Module(m, _local=True) if self.local else Module(m) for m in self["estate"]]

    def module(self, name):
        for m in self.modules:
            if m.name == name:
                return m
        raise KeyError(name)


def _merge(defaults, data):
    out = dict(defaults)
    for k, v in data.items():
        out[k] = _merge(defaults[k], v) if isinstance(v, dict) and isinstance(defaults.get(k), dict) else v
    return out


def validate(data):
    errors = sorted(Draft202012Validator(SCHEMA).iter_errors(data), key=lambda e: list(e.path))
    msgs = [f"{'/'.join(str(p) for p in e.path) or '(root)'}: {e.message}" for e in errors]
    names = [m.get("name") for m in data.get("estate", []) if isinstance(m, dict)]
    if len(names) != len(set(names)):
        msgs.append("estate: module names must be unique")
    for m in data.get("estate", []) if isinstance(data.get("estate"), list) else []:
        for dep in m.get("depends_on", []) if isinstance(m, dict) else []:
            if dep not in names:
                msgs.append(f"estate/{m.get('name')}: depends_on '{dep}' is not a module of the estate")
    return msgs


def find_root(start=None):
    p = Path(start or Path.cwd()).resolve()
    for d in (p, *p.parents):
        if (d / CONFIG_NAME).exists():
            return d
    raise ConfigError(f"no {CONFIG_NAME} here or in a parent directory — run `mig init` first")


def load(root=None):
    root = find_root(root)
    raw = yaml.safe_load((root / CONFIG_NAME).read_text()) or {}
    errors = validate(raw)
    if errors:
        raise ConfigError(f"{CONFIG_NAME} is invalid:\n  - " + "\n  - ".join(errors))
    cfg = Config(_merge(DEFAULTS, raw), root)
    for m in cfg.modules:
        m.provider  # surfaces host errors early
        if "path" in m and not (root / m["path"]).exists():
            raise ConfigError(f"module {m.name}: path {m['path']} does not exist")
    return cfg
