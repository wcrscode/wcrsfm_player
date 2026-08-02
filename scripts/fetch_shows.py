#!/usr/bin/env python3
"""Fetch latest shows from one or more Mixcloud accounts and merge them
into _data/shows.yml, sorted newest-first.

The main WCRS account is `wcrs`. Additional entries in USERS pull from
DJs who host on WCRS but keep their own Mixcloud profiles — their shows
appear inline with everything else, ordered by upload date. To add or
remove a source, edit the USERS list below.

Re-running only pulls new shows (keyed by Mixcloud `key`); existing
entries are kept untouched so manual edits survive.

Usage:
    python3 scripts/fetch_shows.py            # default LIMIT=20 per account
    LIMIT=50 python3 scripts/fetch_shows.py   # override

Requires: pyyaml  (`pip install pyyaml`)
"""

from __future__ import annotations

import json
import os
import sys
import time
import urllib.request
from pathlib import Path

try:
    import yaml
except ImportError:
    sys.exit("pyyaml required: pip install pyyaml")

# Mixcloud usernames to pull from. Add or remove entries here; the rest
# of the script iterates over the list. Names are case-sensitive and must
# match the profile URL segment (mixcloud.com/<name>/).
USERS = [
    "wcrs",
    "Yesterdays_Wine",
    "BigBeefProductions",
    "beatreats",
    "Cultural_Popcorn",
]

LIMIT      = int(os.environ.get("LIMIT", "20"))
PIC_SIZE   = "extra_large"        # 600x600; fallbacks below if missing
UA         = "wcrs-jekyll/1.0 (+https://wcrsfm.org)"

ROOT       = Path(__file__).resolve().parents[1]
DATA_FILE  = ROOT / "_data" / "shows.yml"
IMG_DIR    = ROOT / "assets" / "shows"
IMG_URL    = "/assets/shows/"     # site-root-relative path written into YAML


def http_get(url: str) -> bytes:
    req = urllib.request.Request(url, headers={"User-Agent": UA})
    with urllib.request.urlopen(req, timeout=30) as r:
        return r.read()


def get_json(url: str) -> dict:
    return json.loads(http_get(url).decode("utf-8"))


def pick_picture(pictures: dict) -> str | None:
    for k in (PIC_SIZE, "large", "medium", "medium_mobile", "thumbnail"):
        if pictures.get(k):
            return pictures[k]
    return None


def download_image(url: str, slug: str) -> str | None:
    if not url:
        return None
    path = IMG_DIR / f"{slug}.jpg"
    if not path.exists():
        path.write_bytes(http_get(url))
    return IMG_URL + path.name


def load_existing() -> list[dict]:
    if not DATA_FILE.exists():
        return []
    with DATA_FILE.open() as f:
        return yaml.safe_load(f) or []


def save(shows: list[dict]) -> None:
    DATA_FILE.parent.mkdir(parents=True, exist_ok=True)
    with DATA_FILE.open("w") as f:
        yaml.safe_dump(
            shows, f,
            sort_keys=False, allow_unicode=True,
            default_flow_style=False, width=4096,
        )


def fetch_user(user: str, known: set[str]) -> list[dict]:
    """Return new shows for `user`, skipping any Mixcloud key already in
    `known`. Image slugs are prefixed with the account so two users with
    an identical slug don't clobber each other's cover art."""
    try:
        listing = get_json(f"https://api.mixcloud.com/{user}/cloudcasts/?limit={LIMIT}")
    except Exception as e:
        print(f"  ! {user}: fetch failed ({e}) — skipping")
        return []

    items = listing.get("data", [])
    out = []
    for item in items:
        key = item["key"]
        if key in known:
            continue
        known.add(key)  # guard against dupes within this run too

        try:
            detail = get_json(f"https://api.mixcloud.com{key}")
        except Exception as e:
            print(f"  ! detail fetch failed for {key} ({e})")
            detail = {}

        raw_slug = item.get("slug") or key.strip("/").split("/")[-1]
        # Prefix non-primary accounts so image filenames stay unique.
        img_slug = raw_slug if user == USERS[0] else f"{user.lower()}-{raw_slug}"
        pic = pick_picture(item.get("pictures") or {})
        local_img = download_image(pic, img_slug)

        out.append({
            "key": key,
            "name": item["name"],
            "url": item["url"],
            "image": local_img,
            "description": (detail.get("description") or "").strip(),
            "created_time": item["created_time"],
            "host": (item.get("user") or {}).get("name"),
            "account": user,
        })
        print(f"  + {item['name']}")
        time.sleep(0.2)  # be polite to the API
    return out


def main() -> None:
    IMG_DIR.mkdir(parents=True, exist_ok=True)
    existing = load_existing()
    known = {s["key"] for s in existing}

    all_new: list[dict] = []
    for user in USERS:
        print(f"== {user} ==")
        all_new.extend(fetch_user(user, known))

    if not all_new:
        print("\nNo new shows.")
        return

    combined = sorted(
        existing + all_new,
        key=lambda s: s["created_time"],
        reverse=True,
    )
    save(combined)
    print(f"\nSaved {len(all_new)} new show(s) across {len(USERS)} account(s). "
          f"Total: {len(combined)}.")


if __name__ == "__main__":
    main()
