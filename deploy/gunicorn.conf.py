"""Gunicorn configuration for kukanjiten.com.

Used by both production (deploy/kukan.service) and the staging container
(deploy/staging-entrypoint.sh), so that staging rehearses the real thing rather
than an approximation of it.

    gunicorn -c deploy/gunicorn.conf.py kukansite.wsgi:application

Apache stays in front on :443 doing TLS, /static and /.well-known; this process
only ever sees plain HTTP on loopback. See deploy/kukanjiten-httpd.conf.
"""

import os

# Loopback only. Nothing outside the box may reach gunicorn directly: it has no
# TLS, and SECURE_SSL_REDIRECT trusts an X-Forwarded-Proto header that only
# Apache is supposed to be able to set.
bind = os.environ.get('GUNICORN_BIND', '127.0.0.1:8000')

# ONE worker, on purpose. Two reasons, both specific to this site:
#
#  1. SQLite. The database is a single file with one writer. A second worker
#     process doubles the contention that WAL and busy_timeout exist to absorb,
#     for a site whose traffic is one household.
#  2. Janome. `kukan.jautils` constructs a `Tokenizer` at import time. Measured
#     on Python 3.12: +50 MB RSS and 0.3s, paid per worker with no sharing.
#     That is what the (now deleted) utilskanji/janome_daemon.py existed to
#     avoid back when Apache ran many mod_wsgi instances — see
#     deploy/STAGE7-CUTOVER.md. At one worker it is not worth a second process.
#
# Concurrency comes from threads instead. Four is enough to keep a slow
# request — an Anki export, a kanjipedia scrape — from blocking the whole site,
# which is the one thing mod_wsgi's single in-process handler could not do.
workers = int(os.environ.get('GUNICORN_WORKERS', 1))
threads = int(os.environ.get('GUNICORN_THREADS', 4))
worker_class = 'gthread'

# The default is 30s, which is shorter than a cold Anki export or a kanjipedia
# fetch and would show up as a worker killed mid-request.
timeout = 120
graceful_timeout = 30

# Apache's own keep-alive is what browsers talk to; this only needs to outlive
# the proxy connection.
keepalive = 5

# No max_requests. With a single worker, recycling it means a window where the
# site has no worker at all, and there is no evidence of a leak to trade that
# against. If RSS is seen to climb, add it then — the restart itself is cheap
# (~0.3s of Janome, plus the Django import).

# stdout/stderr, so journald owns the logs in production and `podman logs`
# does in staging. Django's own file handler (settings.LOGGING) is unaffected.
accesslog = '-'
errorlog = '-'
loglevel = os.environ.get('GUNICORN_LOGLEVEL', 'info')

# Apache sets X-Forwarded-For; without this the access log records 127.0.0.1
# for every request.
access_log_format = '%({x-forwarded-for}i)s %(t)s "%(r)s" %(s)s %(b)s %(D)sus'

# Only trust proxy headers from loopback, which is the only thing that can
# reach `bind` anyway.
forwarded_allow_ips = '127.0.0.1'

proc_name = 'kukan'
