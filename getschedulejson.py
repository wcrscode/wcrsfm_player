#!/usr/bin/env python3
"""Fetch the live program schedule from broadcast.wcrsfm.org and write
a Jekyll-friendly data file at _data/schedule.json.

Output shape:
    {
      "fetched_at": "2026-06-28T16:30:00",
      "days": {
        "SUN": [{"name": ..., "start": "00:00", "end": "01:00", ...}, ...],
        "MON": [...],
        ...
      }
    }

The broadcast schedule rotates weekly, so re-run on a cadence (weekly
cron, GitHub Action, or by hand) to keep the site in sync.
"""

import datetime as dt
import json
import re
import urllib.request
from pathlib import Path
from zoneinfo import ZoneInfo

URL  = "http://broadcast.wcrsfm.org/embed/weekly-program"
ROOT = Path(__file__).resolve().parent
OUT  = ROOT / "_data" / "schedule.json"
PROG_DIR = ROOT / "_programs"

# The broadcast.wcrsfm.org feed returns naive timestamps in UTC.
SRC_TZ = ZoneInfo("UTC")
LOCAL  = ZoneInfo("America/New_York")

# Index matches datetime.weekday(): 0=Mon … 6=Sun
DAY_NAMES = ["MON", "TUE", "WED", "THU", "FRI", "SAT", "SUN"]

# Schedule show names that don't match a program title cleanly enough for
# fuzzy matching. Keys are normalized via _norm_title() so add lowercase,
# apostrophe-free, single-spaced entries.
ALIASES = {
    "crazy mommas radio":              "crazy-mamas-radio",
    "dawg day radio local love":       "dawg-day-radio",
    "supermex and co":                 "latino-music-dj-supermex",
    "wes flexners rock and roll show": "wes-flexners-rock-n-roll-show",
    "maximumrocknroll":                "maximum-rock-and-roll",
    "capitalism race democracy":       "capitalism-race-democracy",
}


def fetch_raw():
    with urllib.request.urlopen(URL, timeout=30) as r:
        html = r.read().decode("utf-8")
    m = re.search(r"var\s+schedule_data\s*=\s*(\{.*?\});", html, re.DOTALL)
    if not m:
        raise SystemExit("schedule_data not found on remote page")
    return json.loads(m.group(1))


def _norm_title(s: str) -> str:
    s = (s or "").lower()
    s = re.sub(r"[‘’']", "", s)          # curly + straight apostrophes
    s = re.sub(r"[^a-z0-9]+", " ", s).strip()
    s = re.sub(r"^the\s+", "", s)                  # drop leading "The "
    return re.sub(r"\s+", " ", s)


def load_program_index():
    """Return three dicts:
      exact  = { normalized_title: slug }
      spaced = { normalized_title_no_spaces: slug }
      titles = { slug: original_title }
    for every program markdown file on disk. Empty maps if _programs/ is
    absent.
    """
    exact, spaced, titles = {}, {}, {}
    if not PROG_DIR.exists():
        return exact, spaced, titles
    for p in PROG_DIR.glob("*.md"):
        text = p.read_text(encoding="utf-8", errors="replace")
        m = re.search(r'^title:\s*"([^"]+)"', text, flags=re.M)
        if not m:
            continue
        title = m.group(1)
        titles[p.stem] = title
        key = _norm_title(title)
        if key and key not in exact:
            exact[key] = p.stem
        collapsed = key.replace(" ", "")
        if collapsed and collapsed not in spaced:
            spaced[collapsed] = p.stem
    return exact, spaced, titles


def match_program(name: str, exact: dict, spaced: dict):
    """Best-effort title match. Returns slug or None. Consults ALIASES for
    known name-variance cases first, then tries exact normalized match,
    substring containment, and a space-collapsed fallback."""
    key = _norm_title(name)
    if not key:
        return None
    if key in ALIASES:
        return ALIASES[key]
    if key in exact:
        return exact[key]

    subs = {v for k, v in exact.items() if k in key or key in k}
    if len(subs) == 1:
        return next(iter(subs))

    ck = key.replace(" ", "")
    if ck in spaced:
        return spaced[ck]
    csubs = {v for k, v in spaced.items() if ck and (k in ck or ck in k)}
    if len(csubs) == 1:
        return next(iter(csubs))
    return None


def group_by_day(raw, prog_exact, prog_spaced):
    # The remote feed returns two weeks of instances, so a given slot
    # (Sun 8pm "Steam Room") shows up twice. Dedupe by (day, start, name).
    days = {d: [] for d in DAY_NAMES}
    seen = set()
    unmatched = set()
    for s in raw.get("shows", []):
        try:
            start = dt.datetime.fromisoformat(s["start_timestamp"]).replace(tzinfo=SRC_TZ).astimezone(LOCAL)
            end   = dt.datetime.fromisoformat(s["end_timestamp"]).replace(tzinfo=SRC_TZ).astimezone(LOCAL)
        except (KeyError, ValueError):
            continue
        dow = DAY_NAMES[start.weekday()]
        name = s.get("name") or ""
        # Normalize the name in the dedup key so casing variance across
        # weeks (e.g. "Cafe International" vs "Cafe international")
        # collapses to a single entry instead of two.
        key = (dow, start.strftime("%H:%M"), _norm_title(name))
        if key in seen:
            continue
        seen.add(key)
        slug = match_program(name, prog_exact, prog_spaced) if name else None
        if name and slug is None:
            unmatched.add(name)
        days[dow].append({
            "name":          name,
            "description":   (s.get("description") or "").strip(),
            "start":         start.strftime("%H:%M"),
            "end":           end.strftime("%H:%M"),
            "start_display": start.strftime("%-I:%M %p").lower(),
            "end_display":   end.strftime("%-I:%M %p").lower(),
            "url":           s.get("url") or "",
            "program_slug":  slug or "",
        })
    for d in DAY_NAMES:
        days[d].sort(key=lambda x: x["start"])
    apply_local_overrides(days)
    merge_split_shows(days)
    return days, unmatched


def apply_local_overrides(days):
    """Post-process the raw broadcast feed to correct local edits that
    the upstream schedule doesn't reflect yet.
      - Drop "Morning PSAs" (a 1-minute filler at 08:59-09:00; was
        previously named "Morning Weather" upstream)
      - Extend the 08:00 Democracy Now slot to run the full hour ending
        at 09:00 (was 08:00-08:59 because Morning PSAs occupied that
        last minute)
    """
    for d in DAY_NAMES:
        days[d] = [s for s in days[d] if _norm_title(s["name"]) != "morning psas"]
        for s in days[d]:
            n = _norm_title(s["name"])
            if s["start"] == "08:00" and ("democracy now" in n or "democracynow" in n):
                s["end"] = "09:00"
                s["end_display"] = "9:00 am"


_HOUR_HALF_RE = re.compile(
    r"^(?P<base>.+?),\s*hour\s*(?P<half>[12])(?P<tag>\s*\(.*\))?\s*$", re.I)
_FIRST_SECOND_HALF_RE = re.compile(
    r"^(?P<base>.+?)\s*[-–—]\s*(?P<half>first|second)\s+half\s*$", re.I)

# Canonical display name overrides for merged shows, keyed by
# _norm_title(base) so casing variance in the upstream feed doesn't leak
# through (e.g. "Cafe international" one week, "Cafe International" the
# next).
_MERGED_NAME_OVERRIDES = {
    "cafe international": "Cafe International",
}


def _split_half_key(name: str):
    """If `name` looks like one half of a split show, return
    (base, tag, half) where half is 1 or 2. Else None."""
    m = _HOUR_HALF_RE.match(name)
    if m:
        return (m.group("base").strip(),
                m.group("tag") or "",
                int(m.group("half")))
    m = _FIRST_SECOND_HALF_RE.match(name)
    if m:
        return (m.group("base").strip(),
                "",
                1 if m.group("half").lower() == "first" else 2)
    return None


def merge_split_shows(days):
    """Merge adjacent slots that represent halves of the same show into a
    single entry. Handles the "X, hour 1" + "X, hour 2" pattern (with an
    optional trailing tag like "(rerun)") and the "X - first half" +
    "X - second half" pattern."""
    for d in DAY_NAMES:
        slots = days[d]
        out = []
        i = 0
        while i < len(slots):
            cur = slots[i]
            nxt = slots[i + 1] if i + 1 < len(slots) else None
            merged = None
            if nxt and cur["end"] == nxt["start"]:
                a = _split_half_key(cur["name"])
                b = _split_half_key(nxt["name"])
                if (a and b
                        and a[2] == 1 and b[2] == 2
                        and a[0].lower() == b[0].lower()
                        and a[1] == b[1]):
                    base, tag = a[0], a[1]
                    canonical = _MERGED_NAME_OVERRIDES.get(_norm_title(base))
                    display_base = canonical or base
                    merged = dict(cur)
                    merged["name"] = f"{display_base}{tag}".strip()
                    merged["end"] = nxt["end"]
                    merged["end_display"] = nxt["end_display"]
                    merged["description"] = cur["description"] or nxt["description"]
                    merged["url"] = cur["url"] or nxt["url"]
                    merged["program_slug"] = cur["program_slug"] or nxt["program_slug"]
            if merged is not None:
                out.append(merged)
                i += 2
            else:
                out.append(cur)
                i += 1
        days[d] = out


def main():
    prog_exact, prog_spaced, prog_titles = load_program_index()
    print(f"Loaded {len(prog_titles)} program(s) from {PROG_DIR}.")
    raw = fetch_raw()
    days, unmatched = group_by_day(raw, prog_exact, prog_spaced)
    OUT.parent.mkdir(parents=True, exist_ok=True)
    OUT.write_text(json.dumps({
        "fetched_at": dt.datetime.now().isoformat(timespec="seconds"),
        "days": days,
    }, indent=2), encoding="utf-8")
    total = sum(len(v) for v in days.values())
    filled = sum(1 for v in days.values() if v)
    matched = sum(1 for d in days.values() for s in d if s["program_slug"])
    print(f"Wrote {OUT} ({total} shows across {filled}/7 days; "
          f"{matched} linked to program pages).")
    if unmatched:
        print(f"\n{len(unmatched)} show name(s) with no matching program page "
              f"(likely syndicated):")
        for name in sorted(unmatched):
            print(f"  - {name}")

    # Reverse audit: program pages that never showed up in the schedule
    # (candidates for retirement).
    scheduled_slugs = {s["program_slug"] for d in days.values() for s in d
                       if s["program_slug"]}
    dormant = [(prog_titles[slug], slug) for slug in prog_titles
               if slug not in scheduled_slugs]
    if dormant:
        print(f"\n{len(dormant)} program page(s) with no scheduled airing "
              f"(candidates to retire):")
        for title, slug in sorted(dormant, key=lambda t: t[0].lower()):
            print(f"  - {title}   ({slug})")


if __name__ == "__main__":
    main()
