My question to web-based Claude:
've developed a new version of our radio station's website in Jekyll. I did this primarily to free myself from a CMS. That being said, I want to offer some 'admin' functions. I figure updating and adding .md files is easily done via a github repo, but I also need functionality for adding long .mp3 files of news and public affairs programs. I was thinking of adding a service that would give me significant storage space and an interface or API that I could build upon.

It's easy to divide the concerns. If it's text, go to github, if it's audio, go to this service, but it would be great if I could offer one tool that a member could authenticate with and get any site update task done.

The split you've described (text → GitHub, audio → object storage) is exactly the right instinct, and the good news is you can hide that split behind a single front door. The trick is to think of the "admin tool" as a thin app that talks to two backends on the member's behalf, rather than trying to find one service that does both well.

For the audio side, I'd steer you toward plain object storage rather than a podcast-hosting service, since you're building your own interface anyway. Cloudflare R2 is the standout for this use case: S3-compatible API, cheap storage (around $0.015/GB/month), and crucially **zero egress fees** — which matters a lot when members are streaming hour-long public affairs programs. Backblaze B2 is the other strong option (even cheaper storage, and free egress through Cloudflare via the Bandwidth Alliance). Either gives you stable URLs with byte-range support, which you'll want for your podcast RSS feeds anyway. Long MP3s of a news program will blow past the limits of most "media library" add-ons in git-based CMSes, and you definitely don't want 100MB files committed to the repo itself.

For the unified tool, two paths depending on how much you want to build:

**Lower effort: a git-based CMS with a custom media backend.** Since Decap CMS was already on your radar for this migration, note that it (and its more actively maintained fork, Sveltia CMS) handles the markdown/GitHub side out of the box, including GitHub OAuth so members authenticate once with their GitHub account. The gap is that its media handling defaults to committing files to the repo. You can work around this with a custom media library integration or by adding a separate "upload audio" widget/page that talks to your storage. It's a bit of a seam, but members still experience one login and one interface.

**More control: a small custom admin app.** A single-page app hosted on Cloudflare Pages with a Worker behind it. The Worker handles auth (GitHub OAuth is convenient since members need repo access anyway, or you could use something like Auth0/Clerk if you don't want members to need GitHub accounts), commits markdown via the GitHub API, and issues presigned upload URLs for R2 so large files go straight from the member's browser to storage without passing through your server. When either kind of update lands, a GitHub Action rebuilds the Jekyll site. From the member's perspective: log in, click "add program," fill a form, drop in an MP3, done. They never know two systems exist.

The presigned-URL pattern is the key piece that makes this clean — the browser uploads directly to R2/B2, so you're never proxying gigabytes through anything, and your Worker just does the lightweight coordination: mint the upload URL, then commit a markdown file that references the final audio URL.

One design decision worth settling early: whether uploading an audio file should *automatically* create the corresponding markdown entry (episode page, RSS item) in the same action. I'd argue yes — a single "publish a program" form that takes title, description, air date, and the MP3, then does both the upload and the commit — because that's what makes it feel like one tool rather than two chores.

That's plenty to carry back to Claude Code. If you want, I can also sketch what the Worker's endpoints would look like, or how the RSS feed generation in Jekyll would consume the R2 URLs.

Here's both halves.

## The Worker

Conceptually it's four endpoints plus auth middleware. Something like:

```
POST /auth/login          → kicks off GitHub OAuth
GET  /auth/callback       → exchanges code for token, sets session cookie
POST /api/upload-url      → mints a presigned R2 upload URL
POST /api/publish         → commits the markdown episode file to GitHub
GET  /api/episodes        → (optional) lists recent episodes for an "edit" UI
```

The two interesting ones:

**`POST /api/upload-url`** — the browser sends metadata, gets back a URL it can PUT the MP3 to directly:

```js
// Request body: { filename: "morning-news-2026-07-16.mp3", contentType: "audio/mpeg" }

async function handleUploadUrl(request, env) {
  const session = await requireAuth(request, env); // 401 if no valid session
  const { filename, contentType } = await request.json();

  // Namespace by date to avoid collisions, sanitize the filename
  const key = `audio/${new Date().getFullYear()}/${sanitize(filename)}`;

  // R2 presigned PUT, valid for 1 hour — plenty for a big upload
  const url = await presignPut(env, {
    bucket: 'station-audio',
    key,
    contentType,
    expiresIn: 3600,
  });

  return Response.json({
    uploadUrl: url,
    publicUrl: `https://audio.thearopener.org/${key}`,
  });
}
```

(One wrinkle: R2's native Workers binding doesn't do presigned URLs directly — you either use the `aws4fetch` library to sign S3-style requests against R2's S3 API, or skip presigning entirely and have the browser PUT to the Worker itself, which streams to R2 via the binding. The streaming approach is simpler code but the file transits the Worker; for files under ~a few hundred MB either works fine.)

**`POST /api/publish`** — takes the form data plus the audio URL from the previous step, and commits a markdown file via GitHub's contents API:

```js
async function handlePublish(request, env) {
  const session = await requireAuth(request, env);
  const { title, description, airDate, durationSeconds, fileSizeBytes, audioUrl, program } = await request.json();

  const slug = slugify(`${airDate}-${title}`);
  const path = `_episodes/${slug}.md`;

  const frontmatter = [
    '---',
    `title: "${escapeYaml(title)}"`,
    `date: ${airDate}`,
    `program: ${program}`,
    `audio_url: ${audioUrl}`,
    `duration: ${durationSeconds}`,
    `file_size: ${fileSizeBytes}`,
    '---',
    '',
    description,
  ].join('\n');

  await fetch(`https://api.github.com/repos/yourorg/station-site/contents/${path}`, {
    method: 'PUT',
    headers: {
      Authorization: `Bearer ${env.GITHUB_APP_TOKEN}`,
      'User-Agent': 'station-admin',
      Accept: 'application/vnd.github+json',
    },
    body: JSON.stringify({
      message: `Add episode: ${title}`,
      content: btoa(unescape(encodeURIComponent(frontmatter))),
      committer: { name: session.userName, email: session.userEmail },
    }),
  });

  return Response.json({ ok: true, path });
}
```

That commit triggers your GitHub Action, Jekyll rebuilds, and the episode is live. Note `duration` and `file_size` in the frontmatter — capture those at upload time (the browser knows the file size; duration you can read client-side with an `<audio>` element before upload) because the RSS feed needs them and you don't want Jekyll fetching HEAD requests against R2 at build time.

A note on auth strategy: using a GitHub App installation token (as above) means members don't need GitHub accounts or repo write access at all — the Worker commits on their behalf and just records who did it in the committer field. That's friendlier for radio volunteers than requiring everyone to have GitHub OAuth-able accounts with repo permissions. You'd then handle login with magic links or a simple invite-based email/password system instead.

## Jekyll side

Episodes live as a collection. In `_config.yml`:

```yaml
collections:
  episodes:
    output: true
    permalink: /programs/:name/
```

The RSS feed is just a Liquid template, `feed-news.xml` in the site root:

```xml
---
layout: null
permalink: /feeds/news.xml
---
<?xml version="1.0" encoding="UTF-8"?>
<rss version="2.0" xmlns:itunes="http://www.itunes.com/dtds/podcast-1.0.dtd">
<channel>
  <title>{{ site.title }} — News &amp; Public Affairs</title>
  <link>{{ site.url }}</link>
  <description>{{ site.description }}</description>
  {% assign eps = site.episodes | where: "program", "news" | sort: "date" | reverse %}
  {% for ep in eps limit: 50 %}
  <item>
    <title>{{ ep.title | xml_escape }}</title>
    <pubDate>{{ ep.date | date_to_rfc822 }}</pubDate>
    <guid isPermaLink="false">{{ ep.audio_url }}</guid>
    <enclosure url="{{ ep.audio_url }}"
               length="{{ ep.file_size }}"
               type="audio/mpeg"/>
    <itunes:duration>{{ ep.duration }}</itunes:duration>
    <description>{{ ep.content | strip_html | xml_escape | truncate: 500 }}</description>
  </item>
  {% endfor %}
</channel>
</rss>
```

The key detail for your URL-preservation concern from the Drupal migration: since `permalink` is under your control per-episode (you can override it in frontmatter), old podcast URLs can be preserved exactly, and the `<guid>` staying stable means podcast apps won't re-download episodes as duplicates. If your old Drupal feed used specific GUIDs, carry those over in frontmatter as a `guid:` field and use it in the template instead of the audio URL.

Point `audio.wcrsfm.org` at the R2 bucket as a custom domain (Cloudflare makes this a checkbox) and you get free egress, HTTP range requests for seeking, and URLs that survive even if you ever swap storage providers — you'd just repoint the CNAME rather than rewriting every enclosure URL in every feed.

The one-form flow ties it together: member fills in title/description/program/date, picks the MP3 → browser reads duration, requests upload URL, PUTs the file, then calls `/api/publish` with everything → site rebuilds in a couple minutes. One login, one form, both backends updated.