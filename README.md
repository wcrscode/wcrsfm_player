# WCRS FM

Source for [wcrsfm.org](https://wcrsfm.org), the WCRS FM community radio station's website. A Jekyll static site deployed to DreamHost shared hosting via SFTP.

## Dependencies

**For building:**

- **Ruby** ≥ 2.7 (macOS ships with a compatible version; `brew install ruby` for the latest)
- **Bundler** — `gem install bundler`
- **Jekyll 4.3+** — installed via `bundle install`

**For deploying:**

- **lftp** — `brew install lftp` (macOS). Used by `deploy.sh` for SFTP mirroring.

**For the data-fetching scripts:**

- **Python 3.9+** (for `zoneinfo`)
- **PyYAML** — `pip3 install pyyaml` (used by `fetch_shows.py`)
- **BeautifulSoup 4** — `pip3 install beautifulsoup4` (used by the legacy import scripts)

## Local setup

```bash
git clone git@github.com:leonardpg/wcrsfm_player.git
cd wcrsfm_player
bundle install
bundle exec jekyll serve
```

The dev site runs at `http://localhost:4000`. The Matomo tracking snippet is production-gated, so it does NOT fire in local `jekyll serve` sessions.

Two files are not checked in and must be created locally to deploy:

- **`deploy.sh`** — contains the DreamHost SFTP host, user, password, and remote path. Ask an existing maintainer for the current values.
- **`mail_config.php`** — SMTP credentials for the contact form. Also maintainer-provided.

Both are listed in `.gitignore`.

## Building for production

```bash
JEKYLL_ENV=production bundle exec jekyll build
```

Output lands in `_site/`. The `JEKYLL_ENV=production` flag is required — it turns on the Matomo tracking include in `_layouts/default.html`.

## Deploying

```bash
./deploy.sh          # shows a dry-run diff first, prompts before uploading
./deploy.sh -y       # skip the confirmation prompt
```

`deploy.sh` uses `lftp` with `--reverse --only-newer --parallel=3` to mirror `_site/` to the DreamHost remote. Only files whose modification time is newer than the remote copy are transferred.

## Data-fetching scripts

Two scripts pull fresh data into the site. Both are idempotent — safe to re-run at any cadence, they only add or update what's changed.

### `getschedulejson.py` — weekly program schedule

Fetches the live broadcast schedule from `broadcast.wcrsfm.org` and writes `_data/schedule.json`. The schedule rotates weekly, so run this whenever the on-air lineup changes (a weekly cron or manual trigger both work).

```bash
python3 getschedulejson.py
```

Output feeds the `/schedule/` page and the "now playing" logic in the audio player. Timestamps are converted from UTC (source format) to America/New_York.

### `scripts/fetch_shows.py` — Mixcloud show archive

Pulls the latest uploads from one or more Mixcloud accounts (WCRS's main account plus DJ-owned accounts) and merges them into `_data/shows.yml`, sorted newest-first. New entries are added; existing entries are left alone so any manual edits (like a hand-written `description:` field) survive across runs.

```bash
python3 scripts/fetch_shows.py            # default: 20 most recent per account
LIMIT=50 python3 scripts/fetch_shows.py   # override
```

`_data/shows.yml` powers the "Recent Music Programs" section on the homepage and the full listing at `/archives/`. To add or remove a Mixcloud source, edit the `USERS` list at the top of `fetch_shows.py`.

## Legacy import scripts

Two additional scripts under `scripts/` were used to migrate content from the old Drupal site. They're kept in the repo for reference but shouldn't need to be re-run:

- **`scripts/fetch_programs.py`** — scraped `wcrsfm.org/local_programs` into `_programs/*.md`
- **`scripts/fetch_news.py`** — scraped station news and blogs into `_articles/*.html`, and downloaded referenced images into `assets/news/`

Both were incremental (safe to re-run) but are historical at this point.

## Directory layout

```
_articles/       Article/news collection (Jekyll `articles` collection)
_data/           Site data (nav, schedule.json, shows.yml)
_includes/       Shared partials (player.html)
_layouts/        Page templates (default, article, blog, program)
_programs/       Program collection (Jekyll `programs` collection)
archives/        "All Music Archives" listing page
assets/          CSS, JS, images
schedule/        Weekly schedule page
scripts/         Data-fetching and migration scripts
.htaccess        www → bare-hostname 301 redirect (Apache)
_config.yml      Jekyll config
Gemfile          Ruby dependencies
deploy.sh        SFTP deploy (gitignored — see Local setup)
mail_config.php  SMTP for contact form (gitignored — see Local setup)
```
