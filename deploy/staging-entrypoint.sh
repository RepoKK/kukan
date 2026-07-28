#!/bin/bash
# Staging entrypoint: start gunicorn, then httpd in front of it.
#
# The database baked into this image is a copy of production. The guard below
# refuses to start if it has not been scrubbed, because a staging box holding
# live password hashes and a live PSN token is worse than no staging box.
set -euo pipefail

cd /opt/kukan

VENV=/opt/kukan/.venv/bin
DB=${KUKAN_DB_PATH:-/data/db.sqlite3}

# `podman run ... kukan-staging scrub` — prepare a mounted copy of production
# for use here, using this image's virtualenv rather than one on the host. On a
# box with no development environment that is the difference between a five
# minute rehearsal and installing Python, uv and a compiler first.
#
# It runs under dev settings on purpose: scrub_local_db refuses to run unless
# DEBUG is on, which is one of the three guards standing between it and the
# real database. Serving still uses prod settings, below.
if [ "${1:-}" = scrub ]; then
    [ -f "$DB" ] || { echo "ERROR: no database at $DB. Mount one: -v DIR:/data" >&2; exit 1; }
    echo "==> Scrubbing $DB"
    export DJANGO_SETTINGS_MODULE=kukansite.settings.dev
    # Migrations first: the copy comes from the box, whose schema is whatever
    # was last deployed there. Scrubbing goes through the ORM, so the schema
    # has to match the models before it can run.
    "$VENV/python" manage.py migrate --no-input
    exec "$VENV/python" manage.py scrub_local_db --yes-i-am-not-in-production
fi

# Staging runs the *production* settings module, not dev. That is the whole
# value of it: prod.py is the one that raises ImproperlyConfigured on a missing
# variable and turns on SSL redirect, HSTS and secure cookies, and none of that
# gets exercised anywhere else. deploy/staging.env supplies a complete set of
# deliberately fake values so it can start.
#
# `set -a` exports everything the file defines — the same mechanism systemd's
# EnvironmentFile and the cron prefix in set_cron.py use, so all three read the
# file identically.
set -a
# shellcheck disable=SC1091
. /opt/kukan/deploy/staging.env
set +a
export DJANGO_SETTINGS_MODULE=kukansite.settings.prod

echo "==> Checking the database at $DB has been scrubbed"
if [ ! -f "$DB" ]; then
    echo "ERROR: no database at $DB." >&2
    echo 'Mount a directory holding db.sqlite3 and scrub it first:' >&2
    echo '    podman run --rm -v DIR:/data:Z kukan-staging scrub' >&2
    exit 1
fi

# The scrubber sets every PSN token to the '__dummy__' sentinel. A real npsso
# token here means an unscrubbed copy of production.
if sqlite3 "$DB" \
        "select count(*) from tempmon_psnapikey where code != '__dummy__'" \
        | grep -qv '^0$'; then
    echo 'ERROR: the database contains a live PSN token.' >&2
    echo 'This looks like an unscrubbed copy of production. Run:' >&2
    echo '    podman run --rm -v DIR:/data:Z kukan-staging scrub' >&2
    exit 1
fi

if sqlite3 "$DB" "select count(*) from django_session" | grep -qv '^0$'; then
    echo 'ERROR: the database contains live sessions; scrub it first.' >&2
    exit 1
fi

echo '==> Applying migrations'
"$VENV/python" manage.py migrate --no-input

echo '==> Collecting static files'
"$VENV/python" manage.py collectstatic --no-input --clear

# The same config file production uses, so staging rehearses the real worker
# and thread counts rather than a guess at them. Flags here would defeat the
# point; anything staging-specific goes through the env vars the config reads.
echo '==> Starting gunicorn on 127.0.0.1:8000'
"$VENV/python" -m gunicorn \
    --config /opt/kukan/deploy/gunicorn.conf.py \
    kukansite.wsgi:application \
    &
GUNICORN_PID=$!

# If gunicorn dies, take the container down with it rather than leaving httpd
# serving 502s and the container looking healthy.
trap 'kill "$GUNICORN_PID" 2>/dev/null || true' EXIT

echo '==> Waiting for gunicorn'
for _ in $(seq 1 30); do
    if (echo > /dev/tcp/127.0.0.1/8000) >/dev/null 2>&1; then
        break
    fi
    if ! kill -0 "$GUNICORN_PID" 2>/dev/null; then
        echo 'ERROR: gunicorn exited during startup.' >&2
        exit 1
    fi
    sleep 1
done

echo '==> Starting httpd on 8443'
httpd -DFOREGROUND &
HTTPD_PID=$!
trap 'kill "$GUNICORN_PID" "$HTTPD_PID" 2>/dev/null || true' EXIT

echo '==> Waiting for httpd'
for _ in $(seq 1 30); do
    if (echo > /dev/tcp/127.0.0.1/8443) >/dev/null 2>&1; then
        break
    fi
    if ! kill -0 "$HTTPD_PID" 2>/dev/null; then
        echo 'ERROR: httpd exited during startup.' >&2
        exit 1
    fi
    sleep 1
done

# --- Rehearsal checks ---------------------------------------------------------
# The reason this container exists. Each of these is a cutover mistake that is
# cheap here and expensive on the box.
CURL='curl --insecure --silent --show-error --output /dev/null --write-out %{http_code}'

fail() { echo "STAGING CHECK FAILED: $*" >&2; exit 1; }

echo '==> Checking httpd serves /static itself, rather than proxying it'
# A marker file rather than a real asset: this asserts the Alias wins over the
# catch-all ProxyPass. Django has no /static/ route in production, so if the
# proxy wins this is a 404.
echo staging > /opt/kukan/static/.staging-marker
code=$($CURL "https://127.0.0.1:8443/static/.staging-marker")
[ "$code" = 200 ] || fail "/static/ returned $code; the ProxyPass is shadowing the Alias"

echo '==> Checking httpd serves /.well-known itself, rather than proxying it'
# This is the one that costs a certificate in production: certbot writes the
# challenge token to the webroot, and if httpd proxies the URL to gunicorn
# instead of reading the file, renewal fails silently until the cert expires.
mkdir -p /opt/kukan/.well-known/acme-challenge
echo staging > /opt/kukan/.well-known/acme-challenge/.staging-marker
code=$($CURL "https://127.0.0.1:8443/.well-known/acme-challenge/.staging-marker")
[ "$code" = 200 ] || fail "/.well-known/ returned $code; certbot renewal would fail"

echo '==> Checking the application responds through the proxy'
# 302 to /login, not 200: prod settings deny by default via
# LoginRequiredMiddleware. A 500 here means the app is up but broken; a 502
# means gunicorn is not reachable.
code=$($CURL "https://127.0.0.1:8443/")
case "$code" in
    302) ;;
    502) fail '/ returned 502; httpd cannot reach gunicorn' ;;
    *)   fail "/ returned $code; expected a 302 to /login" ;;
esac

echo '==> Checking Django was told the request was HTTPS'
# Without RequestHeader set X-Forwarded-Proto, SECURE_SSL_REDIRECT sends the
# browser to https, httpd proxies it, Django sees http again, and the site is
# an infinite redirect loop. The tell is a Location on http://.
location=$(curl --insecure --silent --output /dev/null \
    --write-out '%{redirect_url}' "https://127.0.0.1:8443/")
case "$location" in
    https://*) ;;
    http://*)  fail "redirect went to $location; X-Forwarded-Proto is not reaching Django" ;;
esac

echo '==> All staging checks passed. Serving on https://localhost:8443/'

# Exit when either process does, so the container does not sit there healthy
# with half of it dead.
wait -n
echo 'A service exited; shutting down.' >&2
exit 1
