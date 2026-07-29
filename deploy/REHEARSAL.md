# Rehearsing the upgrade

How to run the whole upgraded stack — Python 3.12, Django 6.0, gunicorn behind
httpd, the HTMX/Alpine frontend — against a scrubbed copy of the real database,
in a container, without touching the live site.

**This document is self-contained.** Everything you need is here. When you are
finished, the live site is exactly as you left it.

The companion document is `deploy/UPGRADE.md`, which is the real thing. Do not
start it until this has passed.

---

## Contents

1. [What this is and what it proves](#1-what-this-is-and-what-it-proves)
2. [What it will not touch](#2-what-it-will-not-touch)
3. [Where to run it](#3-where-to-run-it)
4. [Prepare the box](#4-prepare-the-box-root-once)
5. [Get the code from GitHub](#5-get-the-code-from-github)
6. [Build the image](#6-build-the-image)
7. [Give it a database](#7-give-it-a-database)
8. [Run it](#8-run-it)
9. [Reach it from your machine](#9-reach-it-from-your-machine)
10. [What to check](#10-what-to-check)
11. [Rehearsing the nightly jobs](#11-rehearsing-the-nightly-jobs)
12. [When something fails](#12-when-something-fails)
13. [Teardown](#13-teardown)
14. [Sign-off checklist](#14-sign-off-checklist)

---

## 1. What this is and what it proves

A container that runs the **production settings module** (`kukansite.settings.prod`)
behind its own httpd and gunicorn, against a scrubbed copy of the production
database. It is the only place the production settings, the reverse proxy and
the TLS path get exercised before the live box.

It deliberately matches production where it matters and diverges where it does
not:

| | |
|---|---|
| CentOS Stream 9, so glibc 2.34 applies | same |
| Python 3.12 | same |
| httpd in front, gunicorn behind | same |
| `kukansite.settings.prod` | same |
| `deploy/gunicorn.conf.py` — same worker and thread counts | same |
| Certificate | **differs** — self-signed, not Let's Encrypt |
| Database | **differs** — a scrubbed copy, never the real one |
| Credentials | **differs** — `deploy/staging.env` supplies deliberate fakes |
| cron | **differs** — the image has none; nightly jobs are run by hand |
| systemd | **differs** — the entrypoint starts both processes directly |

The container refuses to start if the database has not been scrubbed, then runs
six checks on itself before it will serve. Those six are the cutover's real
failure modes:

1. httpd serves `/static` itself rather than proxying it
2. httpd serves `/.well-known` itself rather than proxying it
3. the ACME challenge is reachable over **plain HTTP**, which is how certbot
   fetches it
4. plain HTTP redirects to https, except the challenge
5. the application answers through the proxy
6. Django is told the request was HTTPS

Check 3 is the one that costs a certificate in production. If httpd proxies
`/.well-known/acme-challenge/` to Django instead of reading the file, certbot's
renewal fails silently every night until the certificate expires.

---

## 2. What it will not touch

Worth being explicit, because the recommended place to run this is the machine
that serves the site.

| | |
|---|---|
| `/home/fred/kukan` | read once, to snapshot the database. Never written |
| The live `db.sqlite3` | read via SQLite `.backup`, which is safe while the site is serving |
| `/etc/httpd`, `/etc/kukan`, systemd | not touched at all |
| Port 443, port 80 | not touched; the container publishes to loopback only |
| cron | the image has none, so no nightly job can fire from it |
| Dropbox, AnkiWeb, PSN, email | `deploy/staging.env` supplies fakes, so a job run by hand fails at login rather than reaching the real service |

The one genuinely shared resource is the box itself — CPU, RAM and disk. The
build is several minutes of CPU and about 2 GB of disk; do it at a quiet hour.
While serving, the container is one gunicorn worker plus an httpd, roughly
300 MB resident.

---

## 3. Where to run it

**On the production box, under a separate user account.** That is the
recommendation, and the reason is narrow and specific:

`pyproject.toml` pins `anki==24.11` because anki 25.02 and later ship
`manylinux_2_35` wheels, and CentOS Stream 9 has glibc **2.34**. No other
machine can answer whether that ceiling is right. Everything else in the
upgrade has been tested elsewhere; this has not.

Any machine with ordinary rootless podman and CentOS Stream 9 will do if you
have one. It will not build inside the project's own development container:
that sandbox confines every container it launches to a user namespace mapping
uid/gid 0 and nothing else, so `chown` to any other id returns `EINVAL`, and
httpd, mod_ssl, libutempter and util-linux all ship non-root-owned files. The
RPM transaction cannot complete. That is a property of the sandbox, not of
CentOS.

---

## 4. Prepare the box (root, once)

```bash
sudo dnf install -y podman git sqlite

sudo useradd -m -s /bin/bash kukanstage

# Rootless podman needs a delegated uid/gid range. useradd normally allocates
# one; if this prints nothing, allocate it by hand with the line below.
grep kukanstage /etc/subuid /etc/subgid
# sudo usermod --add-subuids 300000-365535 --add-subgids 300000-365535 kukanstage

# Without this, a rootless container is killed when the user's last session
# ends — including the ssh session you started it from.
sudo loginctl enable-linger kukanstage
```

Check there is room. The image is roughly 2 GB and rootless podman keeps it
under the user's home, not `/var`:

```bash
df -h /home /var/tmp
```

---

## 5. Get the code from GitHub

Rehearse from the **development branch**, not from `master`. `master` is the
released state; the branch is what you are about to release.

```bash
sudo -iu kukanstage

git clone https://github.com/RepoKK/kukan.git ~/kukan
cd ~/kukan
git checkout stage-10a-htmx-infra
git log --oneline -1
```

`stage-10a-htmx-infra` is the branch carrying the frontend rewrite. It sits on
top of the whole stage chain (0 through 8), so checking it out gives you every
stage at once — there is nothing else to merge in.

> **If the branch name has moved on.** List what is there and take the newest
> stage branch:
> ```bash
> git ls-remote --heads https://github.com/RepoKK/kukan.git
> ```
> The branches are named `stage-N-…` in order. The one you want is the one
> whose open pull request is the release candidate.

**Private repository.** If `git clone` prompts for credentials, use a token:

```bash
git clone https://<TOKEN>@github.com/RepoKK/kukan.git ~/kukan
```

Then remove the token from the remote so it is not left in
`.git/config` on the box:

```bash
cd ~/kukan
git remote set-url origin https://github.com/RepoKK/kukan.git
```

Anything you fetch later will prompt again, which is the intended trade.

**Check the branch is green before building anything.** The pull request runs
the suite, but confirm you have the commit you think you have:

```bash
git log --oneline -5
git status                      # must be clean
```

---

## 6. Build the image

```bash
cd ~/kukan
podman build -t kukan-staging -f Containerfile . 2>&1 | tee ~/build.log
```

Ten to twenty minutes, most of it `dnf` and `uv sync`. If it fails,
`~/build.log` has the whole transcript — keep it; the failing step and its
output are the useful part.

The build fails on a bad httpd config rather than letting you find out at run
time: the last layers run `httpd -t` and check that `ssl_module`,
`proxy_http_module` and `headers_module` are loaded.

**Then answer the anki question, before anything else.** The build proved the
wheel *installs*. This proves it *imports*, which is a different thing — a
glibc mismatch surfaces when the compiled extension is loaded, not when the
wheel is unpacked:

```bash
podman run --rm kukan-staging /opt/kukan/.venv/bin/python \
    -c 'import anki, anki.buildinfo; print(anki.buildinfo.version)'
```

`24.11` means the pinned ceiling is right. An `ImportError` mentioning GLIBC
means it is not, and that is the single most valuable result of this exercise —
stop here and fix `pyproject.toml` before going further.

---

## 7. Give it a database

The container gets a scrubbed **copy** on a bind mount. No database is baked
into the image, and `.containerignore` keeps the working one out of the build
context — it holds a live PSN npsso token and live session cookies, and an
image is a very easy thing to hand to somebody.

The best source is last night's Dropbox backup, because it involves the live
file not at all. Failing that, snapshot it. Use SQLite's `.backup`, which takes
a consistent copy while the site is serving; `cp` does not:

```bash
# as fred
sqlite3 /home/fred/kukan/db.sqlite3 ".backup /tmp/kukan-snapshot.sqlite3"

# as root: hand it over
sudo install -d -o kukanstage -g kukanstage -m 700 /home/kukanstage/kukan-data
sudo install -o kukanstage -g kukanstage -m 600 \
     /tmp/kukan-snapshot.sqlite3 /home/kukanstage/kukan-data/db.sqlite3
sudo rm /tmp/kukan-snapshot.sqlite3
```

Now scrub it, using the image's own virtualenv — nothing needs installing on
the host:

```bash
# as kukanstage
podman run --rm -v ~/kukan-data:/data:Z kukan-staging scrub
```

`:Z` is not optional if SELinux is enforcing, which it is on this box: without
it httpd inside the container cannot read the mount.

That runs migrations first (the copy's schema is whatever was last deployed,
and scrubbing goes through the ORM), then resets every password to `dev`,
replaces the PSN npsso token with the `__dummy__` sentinel, and deletes every
session. Confirm it:

```bash
sqlite3 ~/kukan-data/db.sqlite3 \
  'select count(*) from django_session; select distinct code from tempmon_psnapikey;'
# expect: 0, then __dummy__
```

The scrub prints the account names it reset, marking superusers with `*`. Note
them — they are whatever production happens to have, which is not necessarily
your shell username. To get the list again:

```bash
sqlite3 ~/kukan-data/db.sqlite3 'select username, is_superuser from auth_user'
```

The entrypoint rechecks both on every start and refuses to serve if either is
wrong, so a mistake here stops the container rather than exposing anything.
`scrub_local_db` additionally requires `DEBUG` to be on and refuses to run
against any path under `/home/fred/kukan`, `/srv/kukan` or `/var/www`. Those
are backstops, not a plan. Never point it at the live file.

---

## 8. Run it

```bash
podman run --rm --name kukan-staging \
    -p 127.0.0.1:18443:8443 \
    -v ~/kukan-data:/data:Z \
    kukan-staging
```

Two deliberate choices:

- **`127.0.0.1:` in front of the port.** Without it, podman publishes on all
  interfaces, and a staging instance — self-signed certificate, throwaway
  secrets, a copy of the real data — becomes reachable from the internet. This
  also means firewalld needs no change, since nothing arrives from outside.
- **No `--network=host`.** In the container's own network namespace gunicorn
  binds *its* `127.0.0.1:8000`. On the host network it would bind the box's,
  which is precisely the port the real cutover wants. Keep them separate.

`18443` is a suggestion; check with `ss -ltn | grep 18443` and use anything
free. The port inside the container stays 8443.

Expected output, in order, ending with the line that matters:

```
==> Checking the database at /data/db.sqlite3 has been scrubbed
==> Applying migrations
==> Collecting static files
==> Starting gunicorn on 127.0.0.1:8000
==> Waiting for gunicorn
==> Checking the httpd configuration
==> Starting httpd on 8080 and 8443
==> Waiting for httpd
==> Checking httpd serves /static itself, rather than proxying it
==> Checking httpd serves /.well-known itself, rather than proxying it
==> Checking the ACME challenge is reachable over plain HTTP
==> Checking plain HTTP redirects to https, except the challenge
==> Checking the application responds through the proxy
==> Checking Django was told the request was HTTPS
==> All staging checks passed. Serving on https://localhost:8443/
```

A `STAGING CHECK FAILED` line names which check stopped it.

The container also listens on 8080, standing in for production's `:80`.
Publishing it is optional — the ACME check runs inside the container — but
`-p 127.0.0.1:18080:8080` lets you try the redirect by hand.

---

## 9. Reach it from your machine

Do not open a firewall port. Tunnel over the SSH you already have:

```bash
ssh -N -L 8443:127.0.0.1:18443 fred@kukanjiten.com
```

Then browse **https://localhost:8443/** and accept the self-signed certificate.

**Keep the local end on 8443.** `deploy/staging.env` lists
`https://localhost:8443` in `DJANGO_CSRF_TRUSTED_ORIGINS`, and CSRF is checked
against the origin the *browser* sends, so the host-side port is irrelevant but
the local one is not. If you would rather hit some other port directly, pass
`--env DJANGO_CSRF_TRUSTED_ORIGINS=... --env DJANGO_ALLOWED_HOSTS=...` to
`podman run`; those two variables, and only those two, take an override.

Log in with one of the account names the scrub printed. The password is `dev`.

---

## 10. What to check

The container's own six checks cover the proxy and TLS. These cover the
application, roughly in order of how likely they are to find something.

### 10.1 Breadth first, from the shell

```bash
podman exec kukan-staging bash -c \
  'cd /opt/kukan && set -a && . deploy/staging.env && set +a &&
   DJANGO_SETTINGS_MODULE=kukansite.settings.prod .venv/bin/python manage.py smoke_urls'
```

`smoke_urls` GETs every no-arg URL as a superuser. It proves each view imports,
its template compiles and its queries run — against real data volumes, which
fixtures do not reproduce. Add `--username NAME` if the scrub reported no
superuser.

This is the cheapest net there is. Run it first.

### 10.2 The frontend rewrite, by hand through the tunnel

Every page below was rewritten. The automated tests assert the rendered markup,
but **nothing has exercised the JavaScript in a browser** — that is the specific
gap this rehearsal exists to close.

Open the browser console and keep it visible. A JavaScript error will be silent
otherwise: an Alpine component that throws just leaves the page inert.

**List pages** — `/kanji/list/`, `/yoji/list/`, `/kotowaza/list/`,
`/example/list/`, `/test_result/list/`, `/tempmon/session_list/`,
`/tempmon/game_list/`:

*Appearance first, because the whole page is wrong if this is:*

- **The background is white.** If it is black, `data-theme="light"` is not
  reaching `<html>` — Bulma 1.x has an automatic dark mode that Bulma 0.9.4
  did not, so this only shows up on a machine set to dark.
- The result count and `Q:` timing sit at the top right, opposite the title.
  After any filter or sort, `S:` and `T:` appear beside them.
- On `/kanji/list/` (310 pages) the pager reads `1 2 … 310` with `‹ ›`, not
  310 separate links.

*The filter bar — rebuilt in Phase 11 after the first version stacked every
widget inline and re-queried on every keystroke:*

- The page opens with **no filters showing**, just `ﾌｨﾙﾀｰ追加 ⊕`.
- Open it: a checkbox per available filter, and 適用. Tick two, press 適用 —
  two chips appear and the dropdown closes.
- Click a chip. Its widget opens in a dropdown with its own 適用. Type a
  value. **Nothing should happen until you press 適用** — no request in the
  Network tab while typing.
- Press 適用. The rows update, the chip turns coloured and reads
  `title: value`, and the URL gains that filter.
- Press Enter inside a filter widget — same as 適用.
- Press the `✕` on a chip. It disappears, its value is dropped from the URL,
  and the rows widen again. **Check the URL no longer carries that filter**;
  a removed filter that keeps filtering is the specific bug the disabled
  fieldset prevents.
- Add a filter, do not fill it in, then apply a different one. The empty chip
  must still be there afterwards — that is what `_show` in the URL is for.
- Copy a URL with filters applied into a new tab. The same chips come up
  filled in.
- Sort a column, then apply a filter. **The sort must survive.**

*Then the table itself:*

- Click a column header. It should sort, then reverse on a second click.
- Go to page 2, **then press the browser Back button.** It should return to
  page 1. This did not work before the rewrite and is the main thing to
  confirm.
- Apply a filter, then page forward. The filter must survive.
- Narrow the browser window until the table is wider than the page. It should
  scroll sideways inside its own box, not push the page sideways.

**`/kanji/<kanji>/`** (try a common kanji, so the tabs have content):

- The category tabs (例文 / 四字熟語 / 諺) switch.
- A tab with more than five rows shows pagination, and it works.
- Click the 属性 chevron; the attributes table opens.
- A kanji with a variant form (旧字体/許容字体) shows both, and clicking one
  switches the large glyph.
- **Look for a row labelled `None`** in the attributes table. There should not
  be one; that was a bug this release fixes.
- **Look for literal `&lt;a href=` text** anywhere. There should not be any;
  the model methods that emit HTML changed in this release.

**`/example/update/<id>/`** — the most complex page in the project:

- The 意味 button fetches a definition. If the word is ambiguous a modal of
  candidates appears; picking one fills the field.
- The 読み button fills the per-kanji reading selects.
- Change the word and tab out. The reading selects rebuild, and a notice about
  similar existing examples appears if there are any.
- Put the caret in the 例文 field, select part of it, press 振り仮名. The
  furigana is inserted **at the caret**, and the caret ends up after it.
- The 分離線 / 項目 / 例文の意味 buttons insert into 意味 at the caret.
- Change 種類 to 諺 and to 熟字訓, and watch the fields appear and disappear.
- Press 例文削除. A confirmation modal appears; cancel it, then confirm it on a
  throwaway example and check the example is gone.
- Save a real edit and confirm it persists.

**`/kotowaza/update/<id>/`** — the 振り仮名 button fills the field, and a bad
reading produces a red error under it on save.

**`/bustime/main`** (public, no login):

- The countdown ticks every second and the digits do not jitter.
- `?station=花園町` shows the realtime panel, which refreshes every ten
  seconds. Watch the Network tab: one request per ten seconds, no faster.
- It scrapes tobus.jp live, so it can legitimately show "該当なし".

**tempmon charts** — `/tempmon/playtime_monthly/`, `/tempmon/playtime_yearly/`,
and a session graph from `/tempmon/session_list/`:

- The charts render. They are ECharts now, served from `/static/vendor/`.
- On the session graph the coloured background bands line up with the games in
  the legend below. **Resize the window** — the bands must stay aligned. They
  were redrawn by hand in pixels before and are a `markArea` now.
- Hover for tooltips.

**`/tempmon/psn_npsso_update/1/`** — with the scrubbed `__dummy__` token this
should render with the header in red and days remaining as `N/A`. A 500 here
means the null-client path is broken.

**Anything with Japanese text**, looking for mojibake.

### 10.3 Confirm nothing is still loading the old stack

```bash
podman exec kukan-staging bash -c \
  'grep -ril "buefy\|node_modules\|vue.min.js" /opt/kukan --include="*.html" \
     --exclude-dir=node_modules || echo "clean"'
```

Expect `clean`. In the browser, the Network tab should show requests only to
`/static/vendor/` and `/static/images/`.

### 10.4 Watch the log throughout

```bash
podman logs -f kukan-staging
```

`database is locked` is the one finding that would argue against four threads.

Two things in that log are noise, not findings:

- `"-" 408 - "-" "-"` — httpd timing out a keep-alive connection the browser
  opened and did not use. Normal, and more frequent through an SSH tunnel.
- Timestamps in two zones. gunicorn's access log follows the container's TZ
  (UTC), httpd's follows the host's. Only staging logs both.

---

## 11. Rehearsing the nightly jobs

The container has no cron, so nothing fires on its own. `deploy/staging.env`
supplies fake credentials, so a job that reaches out fails at login rather than
touching the real service. That makes two of the three jobs only partly
rehearsable here — which is itself worth knowing before the real upgrade.

```bash
# Shorthand for the rest of this section.
alias stagemanage='podman exec kukan-staging bash -c "cd /opt/kukan && set -a && . deploy/staging.env && set +a && DJANGO_SETTINGS_MODULE=kukansite.settings.prod .venv/bin/python manage.py"'
```

**`backup_db`** — expect it to fail at the Dropbox upload with an
authentication error. What you are checking is that it gets that far: the
SQLite `.backup` and the bz2 compression happen before the upload, so reaching
the auth failure means those worked under the new Python.

```bash
stagemanage backup_db
```

**`sync_anki`** — expect it to fail at AnkiWeb login. Again, reaching that
point proves the anki 24.11 import, the export rendering and the collection
open all work.

```bash
stagemanage sync_anki --max_delete_count 0
```

**`vacuum_sqlite`** — not a cron job, but it needs no credentials, so it is the
one that runs end to end here:

```bash
stagemanage vacuum_sqlite
```

**Generate the crontab and read it, without installing it.** `set_cron` without
`--exec` prints what it would install:

```bash
stagemanage set_cron
```

Read that output now. It is three entries — `certbot renew` at 01:23,
`backup_db` at 03:03, `sync_anki` at 04:04 — each Django one prefixed with
`set -a; . /etc/kukan/kukan.env; set +a;` and a virtualenv activation, because
cron runs with a near-empty environment.

On the live box, `set_cron --exec` **replaces the entire crontab** via stdin —
there is no merge — and that is the single most destructive command in the
upgrade.

---

## 12. When something fails

**The build.** `~/build.log` has everything. The two failures seen before:

- `Bytecode timed out (60s) compiling .../janome/sysdic/connections1.py` —
  janome ships its dictionary as Python source, including a 5 MB literal that
  peaks at 865 MB resident to compile. The Containerfile compiles serially
  (`compileall -j 1`) for exactly this reason. If you see this, something has
  reintroduced `UV_COMPILE_BYTECODE=1`.
- `Cannot define multiple Listeners on the same IP:port` — the stock
  `conf.d/ssl.conf` and the project vhost both claiming a port. The
  Containerfile removes the stock file rather than rewriting it.

**A staging check.** The container prints which one and stops. Read the vhost
at `deploy/staging-httpd.conf`; the rule that matters is that `ProxyPass /`
must come **below** every `Alias`, each of which needs its own
`ProxyPass <path> !`. mod_proxy takes the first matching rule, so an alias
underneath the catch-all is dead.

**A page 500s.** Get the traceback:

```bash
podman logs kukan-staging | tail -50
```

**A page is inert but returns 200.** That is a JavaScript error. Look in the
browser console, not the server log.

Fix it on the branch, push, then rebuild:

```bash
cd ~/kukan && git pull && podman build -t kukan-staging -f Containerfile .
```

The database bind mount survives a rebuild; you do not need to re-scrub.

---

## 13. Teardown

```bash
podman stop kukan-staging          # or Ctrl-C
podman rmi kukan-staging
podman system prune -a             # reclaims the build cache
rm -rf ~/kukan-data ~/kukan        # the scrubbed copy and the clone
```

`sudo userdel -r kukanstage` if you do not want to keep the account — though
keeping it is convenient, and the next rebuild reuses nothing but the base
image layer.

---

## 14. Sign-off checklist

Do not start the real upgrade until every line here is ticked.

- [ ] `podman build` completed
- [ ] `import anki` printed `24.11`
- [ ] The scrub reported 0 sessions and a `__dummy__` token
- [ ] All fourteen entrypoint lines printed, ending in `All staging checks passed`
- [ ] `smoke_urls` reported no failures
- [ ] Every page has a **white** background
- [ ] Stats line shows 件 / Q, and S / T after a swap
- [ ] `/kanji/list/` pager elides (`1 2 … 310`), not 310 links
- [ ] Filters start hidden; ﾌｨﾙﾀｰ追加 adds chips; 適用 applies; ✕ removes
- [ ] Typing in a filter fires no request until 適用
- [ ] A removed filter leaves the URL, and stops filtering
- [ ] Sorting survives applying a filter
- [ ] Every list page filters, sorts and pages; **Back works**
- [ ] `kanji_detail` tabs switch and paginate; no `None` row; no literal `&lt;a`
- [ ] `example_update`: definition, readings, caret insertion, delete modal, save
- [ ] `kotowaza_update`: furigana button and validation errors
- [ ] `bustime`: countdown ticks, realtime panel polls at 10s
- [ ] Charts render; session-graph bands stay aligned after a resize
- [ ] No request to `node_modules` or any CDN in the Network tab
- [ ] No `database is locked` in the log
- [ ] `backup_db` reached the Dropbox auth failure
- [ ] `sync_anki` reached the AnkiWeb auth failure
- [ ] `set_cron` output read and understood
- [ ] Container torn down

---

## Driving this from Claude Code over SSH

It helps, and it is worth doing: a session can run `ssh fred@kukanjiten.com
'<command>'` per step, read the output and work out what a build failure means
— which is most of the value, because the failure modes here are things like a
wheel that will not build or an httpd module path that moved, where reading the
error is the whole job.

Three things to tell it:

1. **Each `ssh` call is a fresh shell.** No working directory, no environment
   and no `sudo -iu kukanstage` survives between calls. Use absolute paths and
   put each step in one compound command:
   `ssh box 'sudo -u kukanstage bash -lc "cd ~/kukan && podman build ..."'`
2. **Key-based authentication.** An interactive password or sudo prompt will
   hang, since there is no terminal to type into.
3. **It is a shell on the production box.** The unscrubbed database and the
   real secrets in `/etc/kukan/kukan.env` are both reachable from it. Tell it
   to stay out of `/home/fred/kukan` except for the one `.backup` command,
   never to read `/etc/kukan/kukan.env` (its contents would land in the
   transcript), and never to touch `httpd` or `systemctl` — this exercise needs
   none of them.

Run the build with `2>&1 | tee ~/build.log`, so that if a command is cut short
the output is still on the box.

**It cannot drive the browser.** Section 10.2 is yours.
