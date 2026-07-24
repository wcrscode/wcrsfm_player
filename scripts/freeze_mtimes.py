#!/usr/bin/env python3
"""Preserve mtimes on _site files whose content hasn't changed since the
last run. Jekyll rewrites every file on every build, so unchanged files
get fresh mtimes and confuse `lftp mirror --only-newer` into re-uploading
them. This script restores the previous mtime on any file whose SHA-256
matches the previous manifest.

Run this after `jekyll build` and before `deploy.sh`.

Manifest lives at .deploy_state/site_manifest.json (gitignored).
"""

from __future__ import annotations

import hashlib
import json
import os
import sys
from pathlib import Path

ROOT      = Path(__file__).resolve().parents[1]
SITE_DIR  = ROOT / "_site"
STATE_DIR = ROOT / ".deploy_state"
MANIFEST  = STATE_DIR / "site_manifest.json"


def sha256(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as f:
        for chunk in iter(lambda: f.read(65536), b""):
            h.update(chunk)
    return h.hexdigest()


def main() -> None:
    if not SITE_DIR.is_dir():
        sys.exit(f"No _site at {SITE_DIR}; run jekyll build first.")

    prev: dict[str, dict] = {}
    if MANIFEST.exists():
        prev = json.loads(MANIFEST.read_text())

    new: dict[str, dict] = {}
    frozen = 0
    changed = 0

    for path in SITE_DIR.rglob("*"):
        if not path.is_file():
            continue
        rel = path.relative_to(SITE_DIR).as_posix()
        digest = sha256(path)
        prev_entry = prev.get(rel)
        if prev_entry and prev_entry.get("hash") == digest:
            mtime = prev_entry["mtime"]
            os.utime(path, (mtime, mtime))
            new[rel] = prev_entry
            frozen += 1
        else:
            new[rel] = {"hash": digest, "mtime": path.stat().st_mtime}
            changed += 1

    STATE_DIR.mkdir(exist_ok=True)
    MANIFEST.write_text(json.dumps(new, sort_keys=True, indent=2))

    total = frozen + changed
    print(f"Froze mtimes on {frozen}/{total} unchanged files "
          f"({changed} new/changed).")


if __name__ == "__main__":
    main()
