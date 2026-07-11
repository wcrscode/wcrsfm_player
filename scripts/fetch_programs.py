#!/usr/bin/env python3
"""Scrape wcrsfm.org/local_programs and save each program as Jekyll markdown.

Reads the listing at /local_programs (program name + quick description +
link), follows each program page, and extracts:
  - Genre (structured field)
  - Homepage URL (structured field)
  - DJs (structured field)
  - Free-text description prose

Skipped everywhere: the "Listen on WCRS On The Air at:" schedule block
(the site already carries schedule.json), any <iframe> embeds, any links
to audio files (.mp3, /audio/, podcast feeds, mixcloud / soundcloud show
playlists), any [audio-player] placeholders, and trailing "Podcast Feed"
/ "Program archives with audio ..." boilerplate.

Output: _programs/<slug>.md   (Jekyll collection)
Re-run to pick up new or edited programs (FORCE=1 to re-fetch existing).

Requires: beautifulsoup4  (`pip install beautifulsoup4`)
"""

from __future__ import annotations

import os
import re
import sys
import time
import urllib.parse
import urllib.request
from pathlib import Path

try:
    from bs4 import BeautifulSoup
except ImportError:
    sys.exit("beautifulsoup4 required: pip install beautifulsoup4")

BASE    = "https://www.wcrsfm.org"
LISTING = f"{BASE}/local_programs"
UA      = "wcrs-jekyll/1.0 (+https://wcrsfm.org)"
DELAY   = 0.4

ROOT    = Path(__file__).resolve().parents[1]
OUT_DIR = ROOT / "_programs"
FORCE   = bool(int(os.environ.get("FORCE", "0")))


# ---------- HTTP ---------------------------------------------------------

def http_get(url: str) -> bytes:
    req = urllib.request.Request(url, headers={"User-Agent": UA})
    with urllib.request.urlopen(req, timeout=30) as r:
        return r.read()


def html_get(url: str) -> BeautifulSoup:
    time.sleep(DELAY)
    return BeautifulSoup(http_get(url).decode("utf-8", "replace"), "html.parser")


def slugify(text: str) -> str:
    # URL-decode first so percent-encoded slugs from the source (e.g. %E2%80%99
    # for a curly apostrophe) collapse instead of leaking into the filename.
    text = urllib.parse.unquote(text or "")
    # Strip any non-ASCII noise (curly quotes, em-dashes, etc.).
    text = text.encode("ascii", "ignore").decode("ascii").lower()
    text = re.sub(r"[^a-z0-9\s_-]", "", text)
    text = re.sub(r"[\s_-]+", "-", text).strip("-")
    return text or "program"


# ---------- Listing page ------------------------------------------------

def fetch_listing():
    soup = html_get(LISTING)
    out = []
    seen = set()
    for row in soup.select("table.views-table tbody tr"):
        title_a = row.select_one("td.views-field-title a")
        desc_td = row.select_one("td.views-field-field-quick-description-value")
        if not title_a:
            continue
        title = title_a.get_text(strip=True)
        href  = title_a.get("href", "").strip()
        quick = desc_td.get_text(" ", strip=True) if desc_td else ""
        if not href:
            continue
        if not href.startswith("http"):
            href = urllib.parse.urljoin(BASE + "/", href)

        m = re.search(r"/programs/([^/?#]+)", href)
        # Even URL-derived slugs get run through slugify() so percent-encoded
        # characters (%E2%80%99, etc.) don't end up in filenames.
        slug = slugify(m.group(1)) if m else slugify(title)

        # De-dupe slug — Drupal has a couple duplicates (e.g. two Virtual
        # Vortex entries).
        base_slug = slug
        i = 2
        while slug in seen:
            slug = f"{base_slug}-{i}"
            i += 1
        seen.add(slug)

        out.append({"slug": slug, "title": title, "quick": quick, "url": href})
    return out


# ---------- Program page ------------------------------------------------

# Anything matching this URL pattern gets its <a> stripped from the body:
# audio files, podcast feeds, per-show playlist / archive URLs.
SKIP_URL_RE = re.compile(
    r"(?:\.mp3(?:$|[?#])|/audio/|/files/audio|mixcloud\.com|soundcloud\.com"
    r"|open\.spotify\.com|/feed$|/feed[?#]|/rss(?:$|[?#])|podcast"
    r"|/playlist|/user/login)",
    re.IGNORECASE,
)
PODCAST_IMG_RE = re.compile(r"podcast[_-]?icon", re.IGNORECASE)

BAD_PARAGRAPH_TEXTS = {
    "Program archives with audio, text descriptions and photos",
    "Podcast Feed",
    "Podcast",
    "Show Links:",
    "Show Links",
    "Website",
    "Audio Archives",
    "Playlists",
}

# Paragraphs whose plain text matches any of these are dropped — they're
# the leftovers from stripped embeds ("Is the embed not appearing…") or
# episode-listing chatter.
BAD_PARAGRAPH_RE = re.compile(
    r"(embed not appearing|listen to this show directly"
    r"|program archive[s]?:?\s*$)",
    re.IGNORECASE,
)

BAD_HEADING_RE = re.compile(
    r"^(program archive|show links|podcast|listen)",
    re.IGNORECASE,
)

PLACEHOLDER_RE = re.compile(r"\[(?:audio-player|audio-tag-[^\]]+)\]")


def extract_program(html):
    soup = BeautifulSoup(html, "html.parser")
    node = soup.select_one('div[id^="node-"].node')
    if not node:
        return None
    content = node.find("div", class_="content")
    if not content:
        return None

    # -- pull out structured fields we care about --------------------------
    genre  = _field_text(content, "field-field-station-program-genre")
    hp_url = _field_link(content, "field-field-station-program-link")
    djs    = _field_list(content, "field-field-station-program-dj")

    # -- yank subtrees we don't want in the description --------------------
    for cls in (
        "field-field-station-program-genre",
        "field-field-station-program-link",
        "field-field-station-program-dj",
        "field-field-show",       # embedded audio player + episode metadata
    ):
        for el in content.select(f".{cls}"):
            el.decompose()

    for form in content.select(".form-item"):
        # These wrap the "Listen on WCRS On The Air at: ..." schedule block.
        form.decompose()

    for iframe in content.find_all("iframe"):
        iframe.decompose()

    for img in content.find_all("img"):
        if PODCAST_IMG_RE.search(img.get("src") or ""):
            img.decompose()

    for a in list(content.find_all("a")):
        if SKIP_URL_RE.search(a.get("href") or ""):
            a.decompose()

    # Replace literal shortcode placeholders left in the text.
    for tn in list(content.find_all(string=True)):
        replaced = PLACEHOLDER_RE.sub("", tn)
        if replaced != tn:
            tn.replace_with(replaced)

    # Boilerplate paragraphs.
    for p in list(content.find_all("p")):
        t = p.get_text(" ", strip=True)
        if t in BAD_PARAGRAPH_TEXTS or BAD_PARAGRAPH_RE.search(t):
            p.decompose()

    # Boilerplate headings ("Program Archive:", etc).
    for h in list(content.find_all(["h1", "h2", "h3", "h4", "h5", "h6"])):
        t = h.get_text(" ", strip=True)
        if BAD_HEADING_RE.match(t):
            h.decompose()

    # Kill the "Login to post comments" links block if it's inside content.
    for ul in content.select("ul.links"):
        ul.decompose()

    # Drupal wraps the whole content in a single <p>, which is invalid
    # once it contains block-level children (<div>, nested <p>, headings).
    # Unwrap those outer <p>s so the emitted markup is valid.
    for outer_p in list(content.find_all("p")):
        if outer_p.find(["p", "div", "h1", "h2", "h3", "h4", "h5", "h6", "ul", "ol"]):
            outer_p.unwrap()

    # Prune empty leftovers in a couple of passes.
    for _ in range(3):
        removed = 0
        for tag in list(content.find_all(True)):
            if tag.name == "br":
                continue
            if not tag.get_text(strip=True) and not tag.find(["img"]):
                tag.decompose()
                removed += 1
        if not removed:
            break

    body_html = content.decode_contents().strip()
    # collapse runs of whitespace between tags
    body_html = re.sub(r"\n\s*\n\s*\n+", "\n\n", body_html)

    return {
        "genre":  genre,
        "hp_url": hp_url,
        "djs":    djs,
        "body":   body_html,
    }


def _field_text(root, cls):
    div = root.find("div", class_=cls)
    if not div:
        return ""
    items = div.find("div", class_="field-items")
    return items.get_text(" ", strip=True) if items else ""


def _field_link(root, cls):
    div = root.find("div", class_=cls)
    if not div:
        return ""
    items = div.find("div", class_="field-items")
    if not items:
        return ""
    a = items.find("a")
    if a and a.get("href"):
        return a["href"].strip()
    return items.get_text(" ", strip=True)


def _field_list(root, cls):
    div = root.find("div", class_=cls)
    if not div:
        return []
    items = div.find("div", class_="field-items")
    if not items:
        return []
    out = []
    for it in items.find_all("div", class_="field-item"):
        v = it.get_text(" ", strip=True)
        if v:
            out.append(v)
    if not out:
        v = items.get_text(" ", strip=True)
        if v:
            out.append(v)
    return out


# ---------- Output -------------------------------------------------------

def _q(v):
    if v is None:
        return '""'
    s = str(v).replace("\\", "\\\\").replace('"', '\\"')
    return f'"{s}"'


def write_program(entry, prog):
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    slug = entry["slug"]
    path = OUT_DIR / f"{slug}.md"

    lines = [
        "---",
        "layout: program",
        f"title: {_q(entry['title'])}",
        f"slug: {_q(slug)}",
        f"source_url: {_q(entry['url'])}",
    ]
    if entry.get("quick"):
        lines.append(f"quick_description: {_q(entry['quick'])}")
    if prog.get("genre"):
        lines.append(f"genre: {_q(prog['genre'])}")
    if prog.get("hp_url"):
        lines.append(f"homepage_url: {_q(prog['hp_url'])}")
    if prog.get("djs"):
        lines.append("djs:")
        for d in prog["djs"]:
            lines.append(f"  - {_q(d)}")
    lines.append("---")

    body = (prog.get("body") or "").strip()
    if body:
        lines += ["{% raw %}", body, "{% endraw %}"]

    path.write_text("\n".join(lines) + "\n", encoding="utf-8")


# ---------- Main ---------------------------------------------------------

def main():
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    print("== listing programs ==")
    programs = fetch_listing()
    print(f"  {len(programs)} in listing")

    saved = skipped = failed = 0
    for entry in programs:
        slug = entry["slug"]
        path = OUT_DIR / f"{slug}.md"
        if path.exists() and not FORCE:
            skipped += 1
            continue
        print(f"  · {slug}  ({entry['url']})")
        try:
            html = http_get(entry["url"]).decode("utf-8", "replace")
        except Exception as e:
            print(f"    ! fetch failed: {e}")
            failed += 1
            continue
        time.sleep(DELAY)
        prog = extract_program(html)
        if not prog:
            print(f"    ! could not parse")
            failed += 1
            continue
        write_program(entry, prog)
        saved += 1

    total = len(list(OUT_DIR.glob("*.md")))
    print(f"\nDone. {saved} new, {skipped} skipped (exists), "
          f"{failed} failed. Total on disk: {total}.")


if __name__ == "__main__":
    main()
