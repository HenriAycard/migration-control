#!/usr/bin/env python3
"""Anonymize a recorded runs folder before shipping it as an example.

Replaces every Anthropic object ID (sessions, agents, deployments, files, skills, events...)
with a stable fake one, renames session folders accordingly, swaps GitHub owners for
`example-org`, points PR links at a non-resolvable host and drops Console links.

    python3 scripts/anonymize_recording.py <recorded-dir> --owner YourGitHubName [--owner other]
"""
import argparse
import json
import re
from pathlib import Path

ID_RE = re.compile(r"\b(sesn|agent|depl|deplrun|file|skill|memstore|mem|vlt|vcrd|cred|env|sevt|evt|msg|toolu|mcptoolu|srvtoolu)_[0-9A-Za-z]{12,}\b")
FAKE_HOST = "https://example.invalid"


def main():
    p = argparse.ArgumentParser()
    p.add_argument("root", type=Path)
    p.add_argument("--owner", action="append", default=[], help="GitHub user/org to replace with example-org")
    a = p.parse_args()
    files = [f for f in a.root.rglob("*") if f.is_file()]

    mapping, counters = {}, {}
    for f in files:
        for m in ID_RE.finditer(f.read_text(errors="ignore") + " " + str(f.relative_to(a.root))):
            if m.group(0) not in mapping:
                pre = m.group(1)
                counters[pre] = counters.get(pre, 0) + 1
                mapping[m.group(0)] = f"{pre}_example{counters[pre]:04d}"

    def scrub(text):
        text = ID_RE.sub(lambda m: mapping[m.group(0)], text)
        for owner in a.owner:
            text = re.sub(rf"https://github\.com/{re.escape(owner)}/", f"{FAKE_HOST}/example-org/", text, flags=re.I)
            text = re.sub(rf"\b{re.escape(owner)}\b", "example-org", text, flags=re.I)
        return text

    for f in files:
        f.write_text(scrub(f.read_text()))
        if f.name == "meta.json":
            meta = json.loads(f.read_text())
            meta["console"] = ""
            f.write_text(json.dumps(meta, indent=2))
    for d in sorted((d for d in a.root.rglob("*") if d.is_dir()), key=lambda d: -len(d.parts)):
        if d.name in mapping:
            d.rename(d.with_name(mapping[d.name]))

    left = [str(f) for f in a.root.rglob("*") if f.is_file() and (ID_RE.search(f.read_text()) or any(o.lower() in f.read_text().lower() for o in a.owner))]
    print(f"replaced {len(mapping)} ids; {len(left)} files still matching" + (": " + ", ".join(left) if left else ""))


if __name__ == "__main__":
    main()
