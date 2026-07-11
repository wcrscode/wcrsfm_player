#!/usr/bin/env python3
"""Scrape Station News and selected blogs from wcrsfm.org into _articles/.

Sources scraped:
- Station News:    https://wcrsfm.org/category/blog-type/station-news
- wesflexner blog: https://wcrsfm.org/blogs/wesflexner
- admin blog:      https://wcrsfm.org/blogs/admin

For each article we write _articles/<slug>.html with Jekyll front matter
(title, date, author, source_url, image, excerpt, categories) and the
body HTML preserved between {% raw %} ... {% endraw %} so Liquid leaves
it alone. Images referenced in the body are downloaded to
assets/news/ and the img srcs are rewritten to point at local copies.

Re-runs are incremental: an article whose slug already has a file in
_articles/ is skipped (and its categories list is merged if it now
shows up in additional listings).

Env vars:
    MAX_PAGES_PER_SOURCE=N   limit listing pages per source (default: all)
    FORCE=1                  re-fetch even if local file exists

Requires: beautifulsoup4   (`pip install beautifulsoup4`)
"""

from __future__ import annotations

import datetime as dt
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

BASE  = "https://wcrsfm.org"
UA    = "wcrs-jekyll/1.0 (+https://wcrsfm.org)"
DELAY = 0.4

SOURCES = [
    ("station-news", f"{BASE}/category/blog-type/station-news"),
    ("wesflexner",   f"{BASE}/blogs/wesflexner"),
    ("admin",        f"{BASE}/blogs/admin"),
]

# RSS feeds we paginate to harvest reliable pubDates. The blog feed
# covers every blog post; the station-news taxonomy feed mops up
# anything still missing.
DATE_FEEDS = [
    f"{BASE}/blog/feed",
    f"{BASE}/taxonomy/term/2011/0/feed",   # term 2011 = "Station News"
]

ROOT     = Path(__file__).resolve().parents[1]
ART_DIR  = ROOT / "_articles"
IMG_DIR  = ROOT / "assets" / "news"
IMG_URL  = "/assets/news/"

MAX_PAGES = os.environ.get("MAX_PAGES_PER_SOURCE")
MAX_PAGES = int(MAX_PAGES) if MAX_PAGES else None
FORCE     = bool(int(os.environ.get("FORCE", "0")))


# ---------- HTTP ---------------------------------------------------------

def http_get(url: str) -> bytes:
    req = urllib.request.Request(url, headers={"User-Agent": UA})
    with urllib.request.urlopen(req, timeout=30) as r:
        return r.read()


def html_get(url: str) -> BeautifulSoup:
    time.sleep(DELAY)
    return BeautifulSoup(http_get(url).decode("utf-8", "replace"), "html.parser")


# ---------- Listing pages ------------------------------------------------

def iter_listing(base_url: str):
    """Yield (slug, title, date_iso, is_sticky) for every article."""
    page = 0
    while True:
        if MAX_PAGES is not None and page >= MAX_PAGES:
            return
        url = base_url if page == 0 else f"{base_url}?page={page}"
        try:
            soup = html_get(url)
        except Exception as e:
            print(f"  ! listing fetch failed {url}: {e}")
            return

        seen = set()
        any_found = False
        for a in soup.select('a[href^="/content/"]'):
            href = a.get("href", "")
            m = re.match(r"^/content/([^/?#]+)", href)
            if not m:
                continue
            slug = m.group(1)
            if slug in seen:
                continue
            seen.add(slug)
            any_found = True
            title = (a.get("title") or a.get_text(strip=True) or "").strip()
            date_iso = _date_near(a)
            is_sticky = _is_sticky(a)
            yield (slug, title, date_iso, is_sticky)

        if not any_found or not soup.select_one("li.pager-next a"):
            return
        page += 1


def _is_sticky(a_tag):
    # Walk up to the enclosing <div id="node-*"> and check its classes.
    cur = a_tag
    for _ in range(8):
        if cur is None:
            return False
        if getattr(cur, "name", None) == "div":
            cid = cur.get("id", "")
            if cid.startswith("node-"):
                return "sticky" in (cur.get("class") or [])
        cur = cur.parent
    return False


def _date_near(a_tag):
    cur = a_tag
    for _ in range(6):
        if cur is None:
            break
        parent = cur.parent
        if parent is not None:
            created = parent.find(class_="views-field-created")
            if created:
                span = created.find(class_="field-content")
                if span:
                    return _parse_date(span.get_text())
        cur = cur.parent
    return None


def _parse_date(text):
    text = re.sub(r"\s+", " ", text or "").strip()
    for fmt in ("%m/%d/%Y - %I:%M%p", "%m/%d/%Y"):
        try:
            return dt.datetime.strptime(text, fmt).isoformat(sep=" ")
        except ValueError:
            pass
    return None


# ---------- RSS feed (for reliable dates) --------------------------------

ITEM_RE = re.compile(r"<item>(.*?)</item>", re.DOTALL)
LINK_RE = re.compile(r"<link>([^<]+)</link>")
DATE_RE = re.compile(r"<pubDate>([^<]+)</pubDate>")

def build_date_map():
    """Return {slug: 'YYYY-MM-DD HH:MM:SS'} harvested from RSS feeds."""
    dates = {}
    for feed in DATE_FEEDS:
        page = 0
        while True:
            url = feed if page == 0 else f"{feed}?page={page}"
            try:
                time.sleep(DELAY)
                xml = http_get(url).decode("utf-8", "replace")
            except Exception as e:
                print(f"  ! feed fetch failed {url}: {e}")
                break
            items = ITEM_RE.findall(xml)
            if not items:
                break
            added = 0
            for item in items:
                lm, dm = LINK_RE.search(item), DATE_RE.search(item)
                if not (lm and dm):
                    continue
                link = lm.group(1).strip()
                m = re.search(r"/content/([^/?#]+)", link)
                if not m:
                    continue
                slug = m.group(1)
                if slug in dates:
                    continue
                try:
                    d = dt.datetime.strptime(
                        dm.group(1).strip(), "%a, %d %b %Y %H:%M:%S %z"
                    )
                except ValueError:
                    continue
                dates[slug] = d.strftime("%Y-%m-%d %H:%M:%S")
                added += 1
            print(f"  feed {feed.split('/')[-2]}/page {page}: +{added} dates "
                  f"(total: {len(dates)})")
            if added == 0:
                break
            page += 1
    return dates


def patch_date(slug, date_str):
    path = ART_DIR / f"{slug}.html"
    text = path.read_text(encoding="utf-8")
    if re.search(r"^date: ", text, flags=re.M):
        return False
    # Insert after the layout line for tidy ordering.
    text = re.sub(r"^(layout: article\n)",
                  rf"\1date: {_q(date_str)}\n", text, count=1, flags=re.M)
    path.write_text(text, encoding="utf-8")
    return True


# ---------- Article pages ------------------------------------------------

def parse_article(html):
    soup = BeautifulSoup(html, "html.parser")
    title_el = soup.select_one("h1.title#page-title")
    title = title_el.get_text(strip=True) if title_el else None

    node = soup.select_one('div[id^="node-"].node')
    if not node:
        return None
    body_div = node.find("div", class_="content")
    if not body_div:
        return None

    author = None
    blog_li = node.select_one("li.blog_usernames_blog a")
    if blog_li:
        m = re.search(r"/blogs/([^/?#]+)", blog_li.get("href", ""))
        if m:
            author = m.group(1)

    tagged_news = bool(
        node.select_one('a[href$="/category/blog-type/station-news"]')
    )

    return {
        "title": title,
        "body_div": body_div,
        "author": author,
        "tagged_news": tagged_news,
    }


def download_image(abs_url, slug, idx):
    try:
        data = http_get(abs_url)
    except Exception as e:
        print(f"    ! image fail {abs_url}: {e}")
        return None
    ext = os.path.splitext(urllib.parse.urlparse(abs_url).path)[1].lower()
    if ext not in (".jpg", ".jpeg", ".png", ".gif", ".webp", ".svg"):
        ext = ".jpg"
    name = f"{slug}-{idx}{ext}"
    (IMG_DIR / name).write_bytes(data)
    return IMG_URL + name


def rewrite_images(body_div, slug):
    first = None
    for i, img in enumerate(body_div.find_all("img"), start=1):
        src = img.get("src")
        if not src or src.startswith("data:"):
            continue
        abs_url = urllib.parse.urljoin(BASE + "/", src)
        local = download_image(abs_url, slug, i)
        if local:
            img["src"] = local
            img.attrs.pop("srcset", None)
            if first is None:
                first = local
    return first


def excerpt_from(body_div, length=255):
    text = " ".join(body_div.get_text(" ").split())
    if len(text) <= length:
        return text
    return text[:length].rstrip() + "…"


# ---------- Output files -------------------------------------------------

def _q(value):
    if value is None:
        return '""'
    s = str(value).replace("\\", "\\\\").replace('"', '\\"')
    return f'"{s}"'


def write_article(slug, fields, body_html):
    ART_DIR.mkdir(parents=True, exist_ok=True)
    out = ART_DIR / f"{slug}.html"
    lines = ["---", "layout: article"]
    for k in ("title", "date", "author", "source_url", "image", "excerpt"):
        v = fields.get(k)
        if v in (None, ""):
            continue
        lines.append(f"{k}: {_q(v)}")
    if fields.get("order") is not None:
        lines.append(f"order: {fields['order']}")
    cats = fields.get("categories") or []
    if cats:
        lines.append("categories:")
        for c in cats:
            lines.append(f"  - {c}")
    lines += ["---", "{% raw %}", body_html.strip(), "{% endraw %}"]
    out.write_text("\n".join(lines) + "\n", encoding="utf-8")


def patch_order(slug, order):
    path = ART_DIR / f"{slug}.html"
    text = path.read_text(encoding="utf-8")
    if re.search(r"^order: ", text, flags=re.M):
        text = re.sub(r"^order: .+\n", f"order: {order}\n", text,
                      count=1, flags=re.M)
    else:
        text = re.sub(r"^(layout: article\n)",
                      rf"\1order: {order}\n", text, count=1, flags=re.M)
    path.write_text(text, encoding="utf-8")


def load_existing_slugs():
    if not ART_DIR.exists():
        return set()
    return {p.stem for p in ART_DIR.glob("*.html")}


def load_existing_categories(slug):
    path = ART_DIR / f"{slug}.html"
    if not path.exists():
        return []
    text = path.read_text(encoding="utf-8")
    m = re.search(r"^categories:\n((?:  - .+\n)+)", text, flags=re.M)
    if not m:
        return []
    return re.findall(r"  - (.+)", m.group(1))


def patch_categories(slug, cats):
    path = ART_DIR / f"{slug}.html"
    text = path.read_text(encoding="utf-8")
    new_block = "categories:\n" + "".join(f"  - {c}\n" for c in cats)
    if re.search(r"^categories:\n", text, flags=re.M):
        text = re.sub(r"^categories:\n(?:  - .+\n)+", new_block, text,
                      count=1, flags=re.M)
    else:
        text = text.replace("---\n", "---\n" + new_block, 1)
    path.write_text(text, encoding="utf-8")


# ---------- Main ---------------------------------------------------------

def main():
    IMG_DIR.mkdir(parents=True, exist_ok=True)
    ART_DIR.mkdir(parents=True, exist_ok=True)

    print("== building date map from RSS feeds ==")
    date_map = build_date_map()

    # `order` = global discovery sequence; lower = more recently posted.
    # Drupal lists each source newest-first; sticky items appear pinned at
    # the top regardless of date, so we defer them to the end of each
    # source's order range — that way they don't masquerade as recent.
    discovered = {}
    next_order = 0
    for source_id, base_url in SOURCES:
        print(f"\n== listing {source_id} ==")
        regular, sticky = [], []
        for slug, title, date_iso, is_sticky in iter_listing(base_url):
            (sticky if is_sticky else regular).append((slug, title, date_iso))
        for slug, title, date_iso in regular + sticky:
            if slug not in discovered:
                discovered[slug] = {
                    "title": title, "date": date_iso,
                    "categories": set(), "order": next_order,
                }
                next_order += 1
            entry = discovered[slug]
            entry["categories"].add(source_id)
            if not entry.get("date") and date_iso:
                entry["date"] = date_iso
            if not entry.get("title") and title:
                entry["title"] = title
        print(f"  {len(regular)} regular + {len(sticky)} sticky "
              f"(unique so far: {len(discovered)})")

    existing = load_existing_slugs()
    print(f"\n{len(existing)} on disk; {len(discovered)} discovered")

    # Patch missing dates on already-saved articles using the feed map,
    # and update `order` so previously-saved files participate in sorts.
    date_patched = order_patched = 0
    for slug in existing:
        if slug in date_map:
            if patch_date(slug, date_map[slug]):
                date_patched += 1
        if slug in discovered:
            patch_order(slug, discovered[slug]["order"])
            order_patched += 1
    if date_patched or order_patched:
        print(f"Patched dates on {date_patched}, order on {order_patched} "
              f"existing article(s).\n")

    new = updated = 0
    for slug, info in discovered.items():
        path = ART_DIR / f"{slug}.html"
        if path.exists() and not FORCE:
            current = set(load_existing_categories(slug))
            if info["categories"] - current:
                patch_categories(slug, sorted(current | info["categories"]))
                updated += 1
            continue

        source_url = f"{BASE}/content/{slug}"
        try:
            html = http_get(source_url).decode("utf-8", "replace")
        except Exception as e:
            print(f"  ! fetch fail {slug}: {e}")
            continue
        time.sleep(DELAY)
        article = parse_article(html)
        if not article:
            print(f"  ! could not parse {slug}")
            continue

        body_div = article["body_div"]
        first_img = rewrite_images(body_div, slug)
        excerpt = excerpt_from(body_div, 255)
        body_html = body_div.decode_contents().strip()

        cats = set(info["categories"])
        if article["author"]:
            cats.add(article["author"])
        if article["tagged_news"]:
            cats.add("station-news")

        date = info.get("date") or date_map.get(slug) or ""
        write_article(slug, {
            "title": article["title"] or info.get("title"),
            "date": date,
            "author": article["author"] or "",
            "source_url": source_url,
            "image": first_img or "",
            "excerpt": excerpt,
            "order": info.get("order"),
            "categories": sorted(cats),
        }, body_html)
        new += 1
        print(f"  + {slug}")

    print(f"\nDone. {new} new, {updated} re-categorized. "
          f"On disk: {len(load_existing_slugs())}.")


if __name__ == "__main__":
    main()
