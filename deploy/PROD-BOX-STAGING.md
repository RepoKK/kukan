# Running the staging container on the production box

This is a rehearsal, not a deployment. When you are finished, the live site is
still Apache/mod_wsgi on :443 and nothing about it has changed. What runs
alongside it is a container: its own httpd, its own gunicorn, its own copy of
the database, under a different user account and a different port.

`deploy/STAGE7-CUTOVER.md` is the separate document for the real cutover. Do
not start it until this has passed.

## Why on that box, of all places

Everything in this project has been tested on a development machine except the
one thing that machine cannot reproduce: **CentOS Stream 9 and glibc 2.34**.

`pyproject.toml` pins `anki==24.11` because 25.02 and later ship
`manylinux_2_35` wheels, and 2.35 > 2.34. If that ceiling is wrong — if 24.11
also fails to install there — the Anki sync pipeline does not work on the new
Python and it is better to find out now. Nothing else can answer that question.

Still unverified, in the order the build will hit them:

1. The `dnf` layer completing at all. It has never run to completion; the
   development container confines every container it launches to a user
   namespace mapping uid 0 only, so `dnf` cannot install an RPM that sets
   non-root file ownership, and `httpd` is one. See the `Containerfile` header.
   On a box with ordinary rootless podman this does not apply.
2. `uv sync --locked` on Python 3.12 against glibc 2.34 — the anki question.
3. httpd module paths, which move between CentOS point releases.
4. The four cutover checks the entrypoint runs on itself.
5. Django 6.0, PSNAWP 3.0.3 and the rest against real data volumes rather than
   fixtures.

Expect the first build to fail on something. That is what it is for.

## What it will not touch

Worth being explicit, because it is running on the machine that serves the
site:

| | |
|---|---|
| `/home/fred/kukan` | read once, to snapshot the database. Never written |
| The live `db.sqlite3` | read via `.backup`, which is safe while the site runs |
| `/etc/httpd`, `/etc/kukan`, systemd | not touched at all |
| Port 443, port 80 | not touched; the container publishes to loopback only |
| cron | the image has none, so no nightly job can fire from it |
| Dropbox, AnkiWeb, PSN, email | `deploy/staging.env` supplies fakes, so a job run by hand fails at login rather than reaching the real service |

The one genuinely shared resource is the box itself — CPU, RAM and disk. See
"Cost to the live site" at the end.

## 1. Prepare the box (root, once)

```bash
sudo dnf install -y podman git sqlite

sudo useradd -m -s /bin/bash kukanstage

# Rootless podman needs a delegated uid/gid range. useradd normally allocates
# one; if these print nothing, allocate it by hand.
grep kukanstage /etc/subuid /etc/subgid
# sudo usermod --add-subuids 300000-365535 --add-subgids 300000-365535 kukanstage

# Without this, a rootless container is killed when the user's last session
# ends — including the ssh session you started it from.
sudo loginctl enable-linger kukanstage
```

Check there is room before building. The image is roughly 2 GB and rootless
podman keeps it under the user's home, not `/var`:

```bash
df -h /home /var/tmp
```

## 2. Build (as kukanstage)

```bash
sudo -iu kukanstage

git clone -b stage-8-psnawp https://github.com/RepoKK/kukan.git ~/kukan
cd ~/kukan
podman build -t kukan-staging -f Containerfile . 2>&1 | tee ~/build.log
```

`stage-8-psnawp` is the right branch: it sits on top of `stage-7-gunicorn`, so
it carries every stage from 0 to 8.

Ten to twenty minutes, most of it `dnf` and `uv sync`. If it fails, `~/build.log`
has the whole transcript — keep it, the failing step and its output are the
useful part.

Then answer the anki question directly, before anything else:

```bash
podman run --rm kukan-staging /opt/kukan/.venv/bin/python \
    -c 'import anki, anki.buildinfo; print(anki.buildinfo.version)'
```

`24.11` means the pinned ceiling was right. An `ImportError` mentioning GLIBC
means it was not, and that is the single most valuable result of this exercise.

## 3. Give it a database

The container gets a scrubbed **copy**, on a bind mount. No database is baked
into the image, and `.containerignore` keeps the working one out of the build
context, so there is no image here that contains production data.

The best source is last night's Dropbox backup, because it involves the live
file not at all. Failing that, snapshot it — `.backup` takes a consistent copy
while the site is serving, which `cp` does not:

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
the host for this:

```bash
# as kukanstage
podman run --rm -v ~/kukan-data:/data:Z kukan-staging scrub
```

`:Z` is not optional on this box: SELinux is enforcing, and without it httpd
inside the container cannot read the mount.

That resets every password to `dev`, replaces the PSN npsso token with the
`__dummy__` sentinel, and deletes every session. Confirm it:

```bash
sqlite3 ~/kukan-data/db.sqlite3 \
  'select count(*) from django_session; select distinct code from tempmon_psnapikey;'
# expect: 0, then __dummy__
```

The entrypoint checks both again on every start and refuses to serve if either
is wrong, so a mistake here stops the container rather than exposing anything.
`scrub_local_db` additionally refuses to run against any path under
`/home/fred/kukan` — that is a backstop, not a plan. Never point it at the live
file.

## 4. Run it

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

`18443` is only a suggestion; check with `ss -ltn | grep 18443` and use
anything free. The port inside the container stays 8443.

Expected output, in order, ending with the line that matters:

```
==> Checking the database at /data/db.sqlite3 has been scrubbed
==> Applying migrations
==> Collecting static files
==> Starting gunicorn on 127.0.0.1:8000
==> Starting httpd on 8443
==> Checking httpd serves /static itself, rather than proxying it
==> Checking httpd serves /.well-known itself, rather than proxying it
==> Checking the application responds through the proxy
==> Checking Django was told the request was HTTPS
==> All staging checks passed. Serving on https://localhost:8443/
```

Those four checks are the cutover's real failure modes, rehearsed. A
`STAGING CHECK FAILED` line names which one and stops the container. In
particular, `/.well-known/ returned 404` is the one that costs a certificate in
production, and finding it here is the entire point of this container existing.

## 5. Look at it from your machine

Do not open a firewall port. Tunnel over the SSH you already have:

```powershell
ssh -N -L 8443:127.0.0.1:18443 fred@kukanjiten.com
```

Then browse **https://localhost:8443/** and accept the self-signed certificate.

Keeping the local end on 8443 matters: `deploy/staging.env` lists
`https://localhost:8443` in `DJANGO_CSRF_TRUSTED_ORIGINS`, and CSRF is checked
against the origin the *browser* sends. The tunnel makes the host-side port
irrelevant. If you would rather hit some other port directly, pass
`--env DJANGO_CSRF_TRUSTED_ORIGINS=... --env DJANGO_ALLOWED_HOSTS=...` to
`podman run`; those two variables, and only those two, take an override.

Log in as any real username with the password `dev`.

## 6. What to check

The automated checks cover the proxy. These cover the application, and they are
roughly in order of how likely they are to find something.

```bash
# Breadth first: every no-arg URL, as a superuser. Proves each view imports,
# its template compiles and its queries run against real data.
podman exec kukan-staging bash -c \
  'cd /opt/kukan && set -a && . deploy/staging.env && set +a &&
   DJANGO_SETTINGS_MODULE=kukansite.settings.prod .venv/bin/python manage.py smoke_urls'
```

Then by hand, through the tunnel:

- `/bustime/` without logging in — public, 200, and it scrapes tobus.jp live.
- Log in. A kanji list with a filter applied, and an example detail page. These
  are the pages where Django 6.0 template or ORM changes would show, and they
  are the ones fixtures do not exercise at real size.
- A tempmon session graph. Real `PlaySession.data_points` pickles, unpickled by
  Python 3.12 — the fixtures are small and recent, the real ones are not.
- `/tempmon/psn_npsso_update/`. With the scrubbed `__dummy__` token this should
  render with PSN shown as unavailable and days remaining as `N/A`. A 500 here
  means `NullPsnClient` is not doing its job.
- Anything with Japanese text on it, looking for mojibake — the PSNAWP upgrade
  changed how the `Accept-Language`/`Country` headers are passed.

Watch `podman logs -f kukan-staging` throughout. `database is locked` would be
the one finding that argues against four threads.

## 7. Cost to the live site, and teardown

The build is the expensive part: several minutes of CPU and ~2 GB of disk. Do
it at a quiet hour. While serving, the container is one gunicorn worker plus an
httpd — call it 300 MB resident, which is roughly what mod_wsgi is already
using next door.

```bash
podman stop kukan-staging          # or Ctrl-C
podman rmi kukan-staging
podman system prune -a             # reclaims the build cache
rm -rf ~/kukan-data ~/kukan        # the scrubbed copy and the clone
```

`sudo userdel -r kukanstage` if you do not want to keep it — though keeping it
is convenient, and the next rebuild reuses nothing but the base image layer.

## Driving this from Claude Code over SSH

It helps, and it is worth doing. A Claude Code session on Windows can run
`ssh fred@kukanjiten.com '<command>'` per step, read the output, and work out
what a build failure means — which is most of the value, because the failure
modes here are things like a wheel that does not build or an httpd module path
that moved, where reading the error is the whole job.

Point that session at this file and at `Containerfile`. Three things to tell it:

1. **Each `ssh` call is a fresh shell.** No working directory, no environment
   and no `sudo -iu kukanstage` survives between calls. Use absolute paths, and
   put each step in one compound command:
   `ssh box 'sudo -u kukanstage bash -lc "cd ~/kukan && podman build ..."'`
2. **Key-based authentication.** An interactive password or sudo prompt will
   hang, since there is no terminal to type into.
3. **It is a shell on the production box.** The unscrubbed database and the
   real secrets in `/etc/kukan/kukan.env` are both reachable from it. Tell it
   to stay out of `/home/fred/kukan` except for the one `.backup` command, never
   to read `/etc/kukan/kukan.env` (its contents would land in the transcript),
   and never to touch `httpd` or `systemctl` — this exercise needs none of
   them.

Run the build with `2>&1 | tee ~/build.log` as above, so that if a command is
cut short the output is still on the box to look at.
