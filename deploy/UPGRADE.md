# Upgrading the live site

The real thing, on kukanjiten.com. Merge to `master`, deploy from `master`,
verify, and know how to get back.

**This document is self-contained.** Everything you need is here.

**Do not start until the rehearsal has passed.** `deploy/REHEARSAL.md` runs the
whole upgraded stack in a container against a scrubbed copy of the real
database. It is where the expensive mistakes are cheap.

---

## Contents

1. [What changes](#1-what-changes)
2. [The four things with no undo](#2-the-four-things-with-no-undo)
3. [Before you begin](#3-before-you-begin)
4. [Merge to master on GitHub](#4-merge-to-master-on-github)
5. [Back up](#5-back-up)
6. [Stop cron](#6-stop-cron)
7. [Install the environment file](#7-install-the-environment-file)
8. [Deploy the code](#8-deploy-the-code)
9. [Install the systemd unit](#9-install-the-systemd-unit)
10. [Swap the Apache vhost](#10-swap-the-apache-vhost)
11. [Verify from outside](#11-verify-from-outside)
12. [Verify in a browser](#12-verify-in-a-browser)
13. [Restore cron](#13-restore-cron)
14. [The first Anki sync](#14-the-first-anki-sync)
15. [Rollback](#15-rollback)
16. [The week after](#16-the-week-after)
17. [Routine deploys from here on](#17-routine-deploys-from-here-on)

---

## 1. What changes

| | Before | After |
|---|---|---|
| Python | whatever `mod_wsgi.so` is linked against | 3.12 |
| Django | 4.2.7 | 6.0 |
| anki | 23.10.1 | 24.11 (ceiling — see below) |
| PSNAWP | 1.3.3 | 3.0.3 |
| Application process | inside httpd (mod_wsgi) | `kukan.service` (gunicorn) |
| Restarting the app | `systemctl restart httpd` | `systemctl reload kukan` |
| Concurrency | one request at a time | 1 worker × 4 threads |
| App logs | httpd `error_log` | `journalctl -u kukan` |
| Settings | `settings.py` + `settings_prod.py` | `kukansite.settings.prod` + `/etc/kukan/kukan.env` |
| Dependencies | pip / requirements | `uv sync --locked` |
| Frontend | Vue 2 + Buefy + axios + `node_modules/` | server-rendered HTML + HTMX + Alpine.js |

**What does not change:** the hostname, the certificate, the database file, the
URLs the site serves, and the temperature sensor's endpoint.

Apache keeps :443, TLS, `/static` and `/.well-known`. It no longer loads
Python; it proxies everything else to gunicorn on `127.0.0.1:8000`.

---

## 2. The four things with no undo

Everything else in this document is `git revert` plus a redeploy. These four
are not:

**1. `set_cron --exec` replaces the entire crontab.** Via stdin, with no merge.
Anything in that crontab which did not come from the project is gone. Section 6
takes a backup first; do not skip it.

**2. The `DJANGO_SECRET_KEY` rotation.** The key that was in git history is
burned and must be replaced. Rotating it invalidates every session unless the
old key is listed in `DJANGO_SECRET_KEY_FALLBACKS` for one deploy. Section 7.

**3. The Apache vhost.** Keep the old file. Section 10 saves it; section 15
puts it back.

**4. The first `sync_anki` after this upgrade.** It can delete notes, and this
release changes the content of a field on kanji notes, so it will want to
update many of them. Section 14 is the whole reason cron stays off for a cycle.

---

## 3. Before you begin

**Have a second SSH session open**, with the rollback commands from section 15
already typed into it. If the vhost swap goes wrong, you want to paste, not
compose.

**Pick a quiet hour.** Nothing here is fast except the parts you want to be
able to think about.

**Confirm what is running now**, so you can tell afterwards what changed:

```bash
ssh fred@kukanjiten.com

systemctl is-active httpd
crontab -l
ls -l /home/fred/kukan/db.sqlite3
df -h /home
```

**Confirm the prerequisites for gunicorn:**

```bash
httpd -M | grep -E 'proxy_module|proxy_http_module|headers_module|ssl_module'
```

All four must be present. They are enabled by default on CentOS Stream 9, but
check rather than assume — a missing `proxy_http_module` makes section 10 fail
with the site already swapped.

**Confirm `uv` is installed:**

```bash
which uv || curl -LsSf https://astral.sh/uv/install.sh | sh
```

---

## 4. Merge to master on GitHub

The upgrade deploys from `master`. Get the work there first.

`master` is currently 38 commits behind and **zero commits ahead** — every
stage branch was built on the one before it, so this is a fast-forward, not a
merge with conflicts.

### 4.1 Check the pull request

Open <https://github.com/RepoKK/kukan/pulls>. The release candidate is the pull
request from the newest `stage-*` branch. Confirm:

- Its checks are green.
- Its base branch. The stage pull requests chain onto each other, so the
  frontend one targets `stage-8-psnawp`, not `master`. **Retarget it to
  `master` before merging**, or merge the chain in order.

To retarget in the GitHub UI: *Edit* next to the title, then change the base
branch dropdown to `master`.

### 4.2 Verify it really is a fast-forward

From your machine, in a clone of the repository:

```bash
git fetch origin
git rev-list --count origin/master..origin/stage-10a-htmx-infra   # expect 38
git rev-list --count origin/stage-10a-htmx-infra..origin/master   # expect 0
```

If the second number is not 0, someone has committed to `master` since the
stage chain started, and this is a real merge. Stop and resolve it deliberately
rather than during a deploy.

### 4.3 Merge

In the GitHub UI, take the pull request out of draft (*Ready for review*), then
merge it. **Choose "Rebase and merge" or "Create a merge commit" — not
"Squash and merge".** The stage commits are the unit of rollback; squashing 38
of them into one means a bad stage can only be reverted by reverting all of
them.

Or from the command line:

```bash
git checkout master
git merge --ff-only origin/stage-10a-htmx-infra
git push origin master
```

`--ff-only` is the point: it refuses rather than silently creating a merge
commit if the assumption in 4.2 was wrong.

### 4.4 Tag the release

So that "what was running before" is a name, not a commit hash you have to go
looking for:

```bash
git checkout master && git pull
git tag -a pre-stage10 <SHA-OF-OLD-MASTER> -m 'Last commit before the Python 3.12 / Django 6 / HTMX upgrade'
git tag -a stage10 -m 'Python 3.12, Django 6.0, gunicorn, HTMX frontend'
git push origin pre-stage10 stage10
```

Get `<SHA-OF-OLD-MASTER>` before you merge:

```bash
git rev-parse origin/master
```

### 4.5 Close what this obsoletes

This release deletes `kukan/static/js/node_modules/` (505 files, 12 MB) along
with the `package.json` and lockfile beside it. The directory itself remains,
holding one small first-party script. The open Dependabot pull requests
against `/kukan/static/js` no longer apply —
close them, and expect most of the repository's Dependabot alerts to clear on
the next scan.

---

## 5. Back up

Three things, all cheap, all annoying to be without.

```bash
ssh fred@kukanjiten.com

# 1. The database. `.backup` is consistent while the site serves; `cp` is not.
sqlite3 /home/fred/kukan/db.sqlite3 \
    ".backup /home/fred/kukan-preupgrade-$(date +%F).sqlite3"
ls -lh /home/fred/kukan-preupgrade-*.sqlite3

# 2. The crontab. set_cron --exec will replace it wholesale.
crontab -l > /home/fred/crontab-preupgrade-$(date +%F).bak
cat /home/fred/crontab-preupgrade-*.bak

# 3. The Apache vhost.
sudo cp /etc/httpd/conf.d/kukan.conf /home/fred/kukan.conf.mod_wsgi.bak
```

Also confirm last night's Dropbox backup exists and is the size you expect.
That is the copy that survives the box itself.

---

## 6. Stop cron

Nothing should fire mid-upgrade, and `sync_anki` must not fire at all until
section 14.

```bash
crontab -r          # the backup from section 5 is how you get this back
crontab -l          # expect: "no crontab for fred"
```

---

## 7. Install the environment file

`kukansite/settings/prod.py` requires every variable and raises
`ImproperlyConfigured` if one is missing — the process refuses to start rather
than serving a debug page to the internet, which is what the arrangement it
replaced did.

```bash
sudo install -d -o root -g kukan -m 0750 /etc/kukan
sudo install -o root -g kukan -m 0640 \
     /home/fred/kukan/deploy/kukan.env.example /etc/kukan/kukan.env
sudo -e /etc/kukan/kukan.env
```

Fill in:

| Variable | |
|---|---|
| `DJANGO_SECRET_KEY` | **New.** Generate it, see below |
| `DJANGO_SECRET_KEY_FALLBACKS` | The old key, **for this deploy only** |
| `DJANGO_ALLOWED_HOSTS` | `kukanjiten.com,www.kukanjiten.com` |
| `DJANGO_CSRF_TRUSTED_ORIGINS` | `https://kukanjiten.com,https://www.kukanjiten.com` |
| `DROPBOX_TOKEN` | From the old `settings_prod.py` |
| `TEMPMON_API_KEY` | **From the old settings, unchanged.** See the warning below |
| `ANKI_*_USER` / `ANKI_*_PASSWORD` | Three accounts: ayumi, fred, test2 |
| `LETSENCRYPT_ROOT` | `/home/fred/letsencrypt` |
| `KUKAN_WEBROOT` | `/home/fred/kukan/` |

Generate the new secret key:

```bash
python3 -c 'from django.core.management.utils import get_random_secret_key as k; print(k())'
```

> **`TEMPMON_API_KEY` is a hardware contract.** The temperature sensor puts it
> in the JSON body as `API_KEY`. Its firmware is not in this repository and has
> **no retry buffer**, so any reading it fails to deliver is lost forever.
> Copy the existing value exactly. Only ever change it in step with reflashing
> the device.

The file syntax is plain `KEY=value` with no quoting and no expansion, so that
systemd's `EnvironmentFile`, `set -a; . file; set +a`, and the cron prefix all
read it identically. Do not add shell constructs.

**About the fallback key.** Listing the old key in
`DJANGO_SECRET_KEY_FALLBACKS` keeps sessions signed with it valid, so nobody is
logged out by the rotation. Empty it on the next deploy — leaving it there
means the burned key still works.

Check it loads before anything depends on it:

```bash
sudo -u fred bash -c 'set -a; . /etc/kukan/kukan.env; set +a; \
    cd /home/fred/kukan && .venv/bin/python manage.py check \
    --settings=kukansite.settings.prod'
```

That will fail until section 8 has built the virtualenv; run it again after.

---

## 8. Deploy the code

```bash
cd /home/fred/kukan
git fetch origin
git checkout master
git pull
git log --oneline -1        # confirm you have the merge from section 4

uv sync --locked
```

`--locked` fails rather than re-resolving if `uv.lock` is stale, so a forgotten
`uv lock` breaks the deploy instead of silently installing different versions.

**Compile the bytecode. One file at a time.**

```bash
.venv/bin/python -m compileall -q -j 1 .venv/lib/python3.12/site-packages
```

Several minutes. Both halves of that command matter:

- **Do it at all**, because otherwise it happens lazily inside the gunicorn
  worker at startup: a cold `Tokenizer()` costs 3.4s and a ~950 MB transient
  spike, against 0.3s and +50 MB warm.
- **`-j 1`**, because the constraint is memory. janome ships its dictionary as
  Python source — 113 MB of it, with a single 5 MB literal in
  `sysdic/connections1.py` that peaks at 865 MB resident to compile. Compiling
  in parallel puts several of those in flight at once and takes the box to
  swap. Never use `UV_COMPILE_BYTECODE=1` here.

**Migrate and collect static:**

```bash
set -a; . /etc/kukan/kukan.env; set +a
export DJANGO_SETTINGS_MODULE=kukansite.settings.prod

.venv/bin/python manage.py check --deploy
.venv/bin/python manage.py migrate
.venv/bin/python manage.py collectstatic --no-input
```

`collectstatic` matters more than usual this time: the frontend now serves
htmx, Alpine, Bulma, ECharts and the MDI webfont out of `static/vendor/`. If it
is skipped, every page loads with no styling and no JavaScript.

The site is still being served by mod_wsgi at this point. Nothing above has
touched it.

---

## 9. Install the systemd unit

```bash
sudo install -o root -g root -m 0644 \
     /home/fred/kukan/deploy/kukan.service /etc/systemd/system/kukan.service
sudo systemctl daemon-reload
sudo systemctl enable --now kukan.service
systemctl status kukan.service
```

Gunicorn is now running on loopback, serving nobody. Apache is still serving
the site through mod_wsgi. Check gunicorn directly:

```bash
curl -s -o /dev/null -w '%{http_code}\n' -H 'X-Forwarded-Proto: https' \
     http://127.0.0.1:8000/
```

**Expect 302** — production settings deny by default, so `/` redirects to
`/login`. A 500 means the app is up and broken; read the traceback:

```bash
journalctl -u kukan -n 50
```

If it will not start, **nothing has happened to the live site.** Fix it here.
The most likely cause is a missing variable in `/etc/kukan/kukan.env`, and the
journal will name it.

---

## 10. Swap the Apache vhost

This is the moment the live site changes.

```bash
sudo install -o root -g root -m 0644 \
     /home/fred/kukan/deploy/kukanjiten-httpd.conf /etc/httpd/conf.d/kukan.conf
sudo apachectl configtest        # must print "Syntax OK"
sudo systemctl reload httpd      # reload, NOT restart
```

**`reload`, not `restart`.** Reload finishes in-flight requests, and if the new
config is bad it leaves the old one running rather than leaving the site down.

Two things go wrong here, and both are already handled by the vhost in the
repository — this is what to look for if you have edited it:

**Losing the certificate.** `ProxyPass /` matches every URL and mod_proxy takes
the first matching rule. Put it above the `/.well-known` alias and Apache
proxies certbot's http-01 challenge to Django, which 404s it. Renewal then
fails silently at 01:23 every night until the certificate expires. The vhost
puts `ProxyPass /.well-known/ !` first; `kukansite/tests_deploy.py` asserts the
ordering.

**The redirect loop.** `prod.py` sets `SECURE_SSL_REDIRECT = True`. Without
`RequestHeader set X-Forwarded-Proto "https"`, Django sees plain http on every
proxied request and redirects to https forever. Both that header and
`SECURE_PROXY_SSL_HEADER` must be present; either alone is broken.

---

## 11. Verify from outside

From your own machine, not the box.

```bash
# 302 to /login
curl -sI https://kukanjiten.com/ | head -1

# The redirect must land on https, not http. http:// here is the redirect loop.
curl -sI -o /dev/null -w '%{redirect_url}\n' https://kukanjiten.com/

# Served by httpd, not proxied. 200.
curl -sI https://kukanjiten.com/static/vendor/htmx/htmx.min.js | head -1

# 403 or 404 from *Apache*. A Django 404 page means the proxy is shadowing the
# alias and certificate renewal will fail.
curl -s http://kukanjiten.com/.well-known/acme-challenge/ | head -5

# Public, no login, 200.
curl -sI https://kukanjiten.com/bustime/main | head -1
```

**Then the certificate renewal dry run.** This is the one check worth not
skipping — it is the difference between finding a problem now and finding it
when the certificate expires:

```bash
ssh fred@kukanjiten.com
sudo certbot renew --dry-run \
     --config-dir /home/fred/letsencrypt/config \
     --work-dir /home/fred/letsencrypt/work \
     --logs-dir /home/fred/letsencrypt/logs
```

**And the sensor endpoint**, which is the thing that loses data silently:

```bash
curl -s -X POST https://kukanjiten.com/tempmon/add_temp_point/ \
     -H 'Content-Type: application/json' \
     -d '{"API_KEY":"WRONG"}'
```

Expect `{"result": "Failure - wrong API_KEY"}` with **HTTP 200**. That endpoint
always returns 200, even on error, by design. Getting a 404, a 500 or a redirect
means the sensor is losing readings right now.

Then confirm real readings are arriving:

```bash
journalctl -u kukan -f | grep add_temp_point
```

The sensor posts roughly every 32 seconds. If nothing appears within two
minutes, stop and investigate before doing anything else.

---

## 12. Verify in a browser

The entire frontend was rewritten. Automated tests assert the rendered markup,
but the JavaScript is only exercised by a real browser — this is the same list
as the rehearsal, and it is worth walking again on real data.

Keep the browser console open. An Alpine component that throws leaves the page
inert with no server-side sign of it.

- **Every page: the background is white.** If it is black, `data-theme="light"`
  is not reaching `<html>`; Bulma 1.x has an automatic dark mode that Bulma
  0.9.4 did not, so it only shows on a machine set to dark.
- **List pages** (`/kanji/list/`, `/yoji/list/`, `/kotowaza/list/`,
  `/example/list/`, `/test_result/list/`, both tempmon lists): the page opens
  with no filters showing, just `ﾌｨﾙﾀｰ追加 ⊕`. Adding one puts up a chip;
  clicking the chip opens its widget; **nothing applies until 適用**; `✕`
  removes the filter and drops it from the URL. Sorting must survive applying
  a filter. On `/kanji/list/` the pager reads `1 2 … 310`, not 310 links. The
  count and `Q:` sit top right, with `S:`/`T:` appearing after a swap.
  **Press Back after paging** — it should return to the previous page.
- **`/kanji/<kanji>/`**: tabs switch, tabs with more than five rows paginate,
  the 属性 chevron opens the table, variant glyphs switch. No row labelled
  `None`; no literal `&lt;a href=` text.
- **`/example/update/<id>/`**: the 意味 and 読み buttons, the candidate modal,
  furigana insertion at the caret, the 分離線/項目/例文の意味 buttons, changing
  種類, and the delete confirmation. Save a real edit.
- **`/kotowaza/update/<id>/`**: the 振り仮名 button, and a validation error on a
  bad reading.
- **`/bustime/main`** and `?station=花園町`: the countdown ticks without the
  digits jittering; the realtime panel refreshes every ten seconds.
- **Charts**: `/tempmon/playtime_monthly/`, `/tempmon/playtime_yearly/`, and a
  session graph. Resize the window and confirm the coloured bands stay aligned
  with the legend.
- **Japanese text everywhere**, looking for mojibake.

In the Network tab, every asset should come from `/static/vendor/` or
`/static/images/`. A request to `node_modules` or to a CDN means something was
missed.

Watch the journal throughout:

```bash
journalctl -u kukan -f
```

`database is locked` would mean WAL, `busy_timeout` and
`transaction_mode=IMMEDIATE` are not enough for four threads, and the fix is
fewer threads, not more.

---

## 13. Restore cron

Generate the crontab and **read it before installing it**:

```bash
cd /home/fred/kukan
set -a; . /etc/kukan/kukan.env; set +a
export DJANGO_SETTINGS_MODULE=kukansite.settings.prod

.venv/bin/python manage.py set_cron
```

That prints the crontab it *would* install, wrapped in a `Generated cron:`
banner and a reminder about `--exec`. It generates exactly three entries, from
`CRON_CFG` in `kukansite/settings/prod.py`:

| When | What |
|---|---|
| 01:23 daily | `certbot renew --quiet`, with a post-hook restarting httpd |
| 03:03 daily | `backup_db` — SQLite `.backup`, bz2, upload to Dropbox |
| 04:04 daily | `sync_anki` |

Each Django entry is prefixed with `set -a; . /etc/kukan/kukan.env; set +a;`
and a virtualenv activation, because cron runs with a near-empty environment:
without it the jobs start with no `DJANGO_SECRET_KEY` and `prod.py` refuses to
load.

Put that side by side with the backup from section 5 and read both:

```bash
cat /home/fred/crontab-preupgrade-*.bak
```

**Anything in the backup that the generated version does not produce will be
lost.** `set_cron --exec` replaces the whole crontab through stdin, with no
merge. Read the two lists, do not diff them — the banner lines make a
mechanical diff noisy enough to hide a real difference.

**Install everything except the Anki sync.** The simplest way is to install the
generated crontab and then comment out the `sync_anki` line by hand:

```bash
.venv/bin/python manage.py set_cron --exec
crontab -e          # comment out the sync_anki line
crontab -l          # confirm
```

Leave it commented until section 14 has passed.

Then confirm the backup job actually works, by running it once by hand and
looking for the file in Dropbox:

```bash
.venv/bin/python manage.py backup_db
```

A file with today's date must appear in the Dropbox backup folder. This is the
job whose silent failure is worst, because you only discover it when you need
the backup.

---

## 14. The first Anki sync

`sync_anki` deletes notes. It is never exercised by the test suite, and **this
release changes the content of a field on kanji notes**, so the first run will
want to update a lot of them.

### Why this release in particular

Model methods that build HTML links were changed to escape their inputs, and
their `href` attributes are now quoted where they previously were not.
`Example.goo_link` and `Kanji.get_jukuji` both feed the `anki_Reading_Table`
field, so **every kanji note that has examples will show as modified**.

The change is additive — two characters per anchor, no note deleted — but it is
a bulk field update and it should be watched rather than discovered.

### The procedure

**1. Sync every device to AnkiWeb by hand, first.** Anything unsynced is at
risk.

**2. Copy the local collections**, so there is something to go back to:

```bash
cp -a ~/.local/share/Anki2 ~/Anki2-preupgrade-$(date +%F)
```

**3. Run it with deletion disabled, and watch:**

```bash
cd /home/fred/kukan
set -a; . /etc/kukan/kukan.env; set +a
export DJANGO_SETTINGS_MODULE=kukansite.settings.prod

.venv/bin/python manage.py sync_anki --max_delete_count 0
```

`--max_delete_count 0` makes it refuse rather than delete. The default is 5.

Read the added/updated/deleted counts it reports. Expect a large **updated**
count on the kanji profile — that is the field change above. Expect **added**
and **deleted** to be near zero. A large deleted count means it wants to remove
notes, and that is the thing to stop and understand.

**4. Open Anki and look at a few kanji notes.** The reading table should render
as it did before: the links work and no raw `<a href=...>` text is visible.

**5. Only then, restore the cron line:**

```bash
crontab -e          # uncomment sync_anki
crontab -l
```

Leave the copied collection directory in place for a week.

---

## 15. Rollback

**The vhost only** — if the site is broken but gunicorn is fine, or you simply
want the old stack back immediately:

```bash
sudo cp /home/fred/kukan.conf.mod_wsgi.bak /etc/httpd/conf.d/kukan.conf
sudo apachectl configtest && sudo systemctl reload httpd
sudo systemctl disable --now kukan.service
```

Apache goes back to running the application in-process. This is the fast one:
one file and a reload.

**Plus the code**, if the old vhost cannot serve the new checkout:

```bash
cd /home/fred/kukan
git checkout pre-stage10       # the tag from section 4.4
```

**Plus the database**, only if a migration did damage:

```bash
sudo systemctl stop httpd
cp /home/fred/kukan-preupgrade-*.sqlite3 /home/fred/kukan/db.sqlite3
sudo systemctl start httpd
```

**The crontab:**

```bash
crontab /home/fred/crontab-preupgrade-*.bak
crontab -l
```

**Keep the old virtualenv on disk for a week.** mod_wsgi is compiled against a
specific Python, and rebuilding it under time pressure is not something you
want to be doing.

**On GitHub**, if the release has to come out: `git revert` the merge commit
rather than force-pushing `master`. The stage commits were kept separate (§4.3)
precisely so a single bad stage can be reverted on its own.

---

## 16. The week after

**Check the certificate renewed.** The dry run in section 11 proved the path
works; this proves the real thing did. Renewal runs at 01:23:

```bash
ssh fred@kukanjiten.com
sudo certbot certificates --config-dir /home/fred/letsencrypt/config
```

**Check the nightly backup landed** in Dropbox, with today's date, every
morning for the first few days.

**Check the sensor never stopped:**

```bash
sqlite3 /home/fred/kukan/db.sqlite3 \
  'select max(end_time) from tempmon_playsession'
```

Readings are not rows: `DataPoint` is a dataclass and the readings live pickled
inside `PlaySession.data_points`, so the freshest session's `end_time` is the
signal. It should be within a few minutes of now while the PlayStation is on,
and otherwise from the last time it was.

A gap that starts at the upgrade is the failure mode this whole document is
most careful about.

**Watch memory.** One gunicorn worker, four threads, and a resident janome
tokenizer:

```bash
systemctl status kukan | grep Memory
```

Sustained growth in a process that never restarts is the one argument for
adding `max_requests` to `deploy/gunicorn.conf.py`, which is deliberately
absent for now.

**Stop any stray Janome daemon.** There was a resident tokenizer process that
Apache's many mod_wsgi instances talked to over `multiprocessing.connection`.
The script is gone and `prod.py` does not define `JANOME_PORT`, so the
application now tokenizes in-process. Check nothing is still listening and kill
it if so.

**Empty `DJANGO_SECRET_KEY_FALLBACKS`** on the next deploy:

```bash
sudo -e /etc/kukan/kukan.env      # set DJANGO_SECRET_KEY_FALLBACKS=
sudo systemctl reload kukan
```

Leaving it set means the key that was published in git history still signs
valid sessions.

---

## 17. Routine deploys from here on

Once this upgrade has settled, a deploy is:

```bash
cd /home/fred/kukan
git pull && uv sync --locked

# Only when uv sync actually installed something. Skipping it moves ~950 MB and
# several seconds into the first request instead.
.venv/bin/python -m compileall -q -j 1 .venv/lib/python3.12/site-packages

set -a; . /etc/kukan/kukan.env; set +a
export DJANGO_SETTINGS_MODULE=kukansite.settings.prod
.venv/bin/python manage.py migrate
.venv/bin/python manage.py collectstatic --no-input

sudo systemctl reload kukan          # not `restart httpd` any more
journalctl -u kukan -f
```

Things to watch for afterwards:

- **`database is locked`** in the journal — WAL, `busy_timeout` and
  `transaction_mode=IMMEDIATE` are not doing enough for four threads. The fix
  is fewer threads, not more.
- **`502` from Apache** — gunicorn is down. `systemctl status kukan`.
- **Sustained RSS growth** — see section 16.

After a dependency change, run `uv lock` and commit the result; CI uses
`--locked` and a forgotten lock fails the build.

After any dependency or template change, the cheapest breadth-first check is:

```bash
.venv/bin/python manage.py smoke_urls
```

It GETs every no-arg URL as a superuser, proving each view imports, its
template compiles and its queries run.
