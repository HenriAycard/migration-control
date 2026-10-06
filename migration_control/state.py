"""Project state in .mig/: IDs of everything created in the Anthropic workspace + the run cache.

Everything in .mig/ is re-creatable and is gitignored. Secrets never land here.
"""
import json
from pathlib import Path

STATE_DIR = ".mig"


class State:
    def __init__(self, root):
        self.dir = Path(root) / STATE_DIR
        self.path = self.dir / "state.json"
        self.data = json.loads(self.path.read_text()) if self.path.exists() else {}

    def get(self, *keys, default=None):
        cur = self.data
        for k in keys:
            if not isinstance(cur, dict) or k not in cur:
                return default
            cur = cur[k]
        return cur

    def set(self, *keys, value):
        cur = self.data
        for k in keys[:-1]:
            cur = cur.setdefault(k, {})
        cur[keys[-1]] = value
        self.save()

    def save(self):
        self.dir.mkdir(exist_ok=True)
        (self.dir / ".gitignore").write_text("*\n")
        self.path.write_text(json.dumps(self.data, indent=2) + "\n")

    @property
    def cache(self):
        """Dashboard / outputs cache: .mig/runs/{scans,plans}/<session>/"""
        return self.dir / "runs"
