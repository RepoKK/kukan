# Stage 7 — Apache/mod_wsgi → Apache + gunicorn

What changes: Apache stops loading Python. It keeps :443, TLS, `/static` and
`/.well-known`, and proxies everything else to gunicorn on `127.0.0.1:8000`,
managed by systemd.

What does not change: the hostname, the certificate, the database, the cron
jobs, and every URL the site serves.

| | Before | After |
|---|---|---|
| Application process | inside httpd (mod_wsgi) | `kukan.service` (gunicorn) |
| Restarting the app | `systemctl restart httpd` | `systemctl reload kukan` |
| Concurrency | one request at a time | 1 worker × 4 threads |
| App logs | httpd error_log | `journalctl -u kukan` |
| Config | `WSGIDaemonProcess` in the vhost | `deploy/gunicorn.conf.py` |

Files added by this stage:

- `deploy/gunicorn.conf.py` — worker sizing, shared by production and staging
- `deploy/kukan.service` — the systemd unit
- `deploy/kukanjiten-httpd.conf` — the replacement vhost
- `deploy/staging.env` — fake credentials so staging can run `prod.py`
- `kukansite/tests_deploy.py` — asserts the two mistakes below cannot recur

## The two things that actually go wrong

**1. Losing the certificate.** `ProxyPass /` matches every URL, and mod_proxy
takes the first matching rule. Put it above the `/.well-known` alias and Apache
proxies certbot's http-01 challenge to Django, which 404s it — `static()` in
`kukansite/urls.py` is `DEBUG`-only and serves nothing in production. Renewal
then fails silently at 01:23 every night until the certificate expires.

The vhost puts `ProxyPass /.well-known/ !` first. `kukansite/tests_deploy.py`
asserts the ordering, and the staging container writes a token into the webroot
and fetches it back over HTTP before it will finish starting.

**2. The redirect loop.** `prod.py` sets `SECURE_SSL_REDIRECT = True`. Without
`RequestHeader set X-Forwarded-Proto "https"`, Django sees plain http on every
proxied request, redirects to https, Apache proxies the new request, and the
whole site loops. Both the header and `SECURE_PROXY_SSL_HEADER` must be
present; either alone is broken.

## Prerequisites

Stage 4's environment file must already be installed and working, or gunicorn
will not start at all — `prod.py` raises `ImproperlyConfigured` on a missing
variable, by design.

```bash
ls -l /etc/kukan/kukan.env          # root:kukan 0640
sudo -u fred bash -c 'set -a; . /etc/kukan/kukan.env; set +a; \
    cd /home/fred/kukan && .venv/bin/python manage.py check \
    --settings=kukansite.settings.prod'
httpd -M | grep -E 'proxy_module|proxy_http_module|headers_module'
```

## Rehearse in the staging container

The point of the container is that this cutover otherwise gets performed for
the first time on the live site.

```bash
podman build -t kukan-staging -f Containerfile .

# A scrubbed *copy*, on a bind mount. No database is baked into the image, and
# .containerignore keeps the working one out of the build context — it holds a
# live npsso token and live sessions.
mkdir -p ~/kukan-staging-data
cp /path/to/backup.sqlite3 ~/kukan-staging-data/db.sqlite3
podman run --rm -v ~/kukan-staging-data:/data:Z kukan-staging scrub

podman run --rm -p 127.0.0.1:8443:8443 -v ~/kukan-staging-data:/data:Z \
    --name kukan-staging kukan-staging
```

**This has not run to completion yet.** The dev container confines every
container it launches to a user namespace mapping uid 0 only, so `dnf` cannot
install any RPM that sets non-root file ownership — `httpd` among them. The
header of `Containerfile` has the detail. Run the build somewhere with ordinary
rootless podman before trusting any of what follows; everything past the `dnf`
step, including whether the anki 24.11 wheel installs against glibc 2.34, is
still unverified.

**`deploy/PROD-BOX-STAGING.md` is how to do that on the production box** — a
separate user account, a loopback-only port, reached over an SSH tunnel. It is
the recommended way, because CentOS Stream 9 and glibc 2.34 are exactly what
cannot be reproduced elsewhere, and the anki wheel ceiling depends on them.

The entrypoint refuses to start on an unscrubbed database, then runs the
rehearsal checks itself: `/static` and `/.well-known` served by httpd rather
than proxied, the app reachable through the proxy, and the redirect landing on
`https://`. Any of them failing stops the container with the reason.

```bash
curl -k -I https://localhost:8443/          # 302 -> https://.../login
curl -k    https://localhost:8443/bustime/  # public, 200
podman logs kukan-staging
```

## Cutover

Roughly fifteen minutes, with a rollback that is one file move.

**1. Install the unit.**

```bash
sudo install -o root -g root -m 0644 deploy/kukan.service \
     /etc/systemd/system/kukan.service
sudo systemctl daemon-reload
sudo systemctl enable --now kukan.service
systemctl status kukan.service
```

Apache is still serving the site through mod_wsgi at this point. Gunicorn is
running alongside it on loopback, serving nobody. Check it directly:

```bash
curl -s -o /dev/null -w '%{http_code}\n' -H 'X-Forwarded-Proto: https' \
     http://127.0.0.1:8000/          # 302
```

If it does not come up, nothing has happened to the live site. Read
`journalctl -u kukan -n 50` and fix it before going on.

**2. Swap the vhost.**

```bash
sudo cp /etc/httpd/conf.d/kukan.conf ~/kukan.conf.mod_wsgi.bak   # keep this
sudo install -o root -g root -m 0644 deploy/kukanjiten-httpd.conf \
     /etc/httpd/conf.d/kukan.conf
sudo apachectl configtest        # must say "Syntax OK"
sudo systemctl reload httpd      # reload, not restart
```

`reload` finishes in-flight requests. `restart` drops them and, if the new
config is bad, leaves the site down instead of leaving the old config running.

**3. Verify, from outside the box.**

```bash
curl -sI https://kukanjiten.com/ | head -1              # 302 to /login
curl -s  https://kukanjiten.com/static/js/... | head -1 # served by httpd
curl -sI http://kukanjiten.com/.well-known/acme-challenge/ | head -1
    # 403 or 404 from *Apache* — not a Django page. A Django 404 means the
    # proxy is shadowing the alias and renewal will fail.
sudo certbot renew --dry-run --config-dir /home/fred/letsencrypt/config \
     --work-dir /home/fred/letsencrypt/work --logs-dir /home/fred/letsencrypt/logs
```

The dry run is the one check worth not skipping: it is the difference between
finding this out now and finding out when the certificate expires.

Then log in and load a kanji list, an example detail page, `/bustime/`, and a
tempmon session graph. `journalctl -u kukan -f` alongside.

## Rollback

```bash
sudo cp ~/kukan.conf.mod_wsgi.bak /etc/httpd/conf.d/kukan.conf
sudo apachectl configtest && sudo systemctl reload httpd
sudo systemctl disable --now kukan.service
```

Apache goes back to running the application in-process. Keep the old virtualenv
on disk for a week — mod_wsgi is compiled against a specific Python and
rebuilding it under time pressure is not a thing you want to do.

## Afterwards

**Stop the Janome daemon, if it is running.** `utilskanji/janome_daemon.py` was
a resident tokenizer process that `kukan/jautils.py` talked to over
`multiprocessing.connection`, so that Apache's many mod_wsgi instances did not
each build their own. Stage 2 deleted the script (it imported a `settings_prod`
module that no longer exists) and Stage 4's `prod.py` does not define
`JANOME_PORT`, so `jautils.py` now takes its in-process branch. Measured, that
costs +50 MB RSS and 0.3s at startup, once, for the single gunicorn worker —
cheaper than the process it replaces. Check for a stray daemon still listening
and stop it.

The `hasattr(settings, 'JANOME_PORT')` branch is left in place deliberately: if
the worker count ever has to rise, defining `JANOME_PORT` and `JANOME_KEY` is
the way back.

**Deploys become:**

```bash
git pull && uv sync --locked
.venv/bin/python manage.py migrate
.venv/bin/python manage.py collectstatic --no-input
sudo systemctl reload kukan          # not restart httpd
```

**Watch for.** `database is locked` in the journal means WAL, `busy_timeout` or
`transaction_mode=IMMEDIATE` (all three in `kukansite/settings/base.py`) are not
doing enough, and the fix is fewer threads, not more. `502` from Apache means
gunicorn is down. Sustained RSS growth in a process that never restarts is the
one argument for adding `max_requests` to `gunicorn.conf.py`, which is
deliberately absent for now.
