#!/bin/bash
# Staging entrypoint: start gunicorn, then httpd in front of it.
#
# The database baked into this image is a copy of production. The guard below
# refuses to start if it has not been scrubbed, because a staging box holding
# live password hashes and a live PSN token is worse than no staging box.
set -euo pipefail

cd /opt/kukan

VENV=/opt/kukan/.venv/bin

echo '==> Checking the database has been scrubbed'
if [ ! -f db.sqlite3 ]; then
    echo 'ERROR: no db.sqlite3 in the image.' >&2
    echo 'Copy a scrubbed database into the build context first:' >&2
    echo '    manage.py scrub_local_db --yes-i-am-not-in-production' >&2
    exit 1
fi

# The scrubber sets every PSN token to the '__dummy__' sentinel. A real npsso
# token here means an unscrubbed copy of production.
if sqlite3 db.sqlite3 \
        "select count(*) from tempmon_psnapikey where code != '__dummy__'" \
        | grep -qv '^0$'; then
    echo 'ERROR: the database contains a live PSN token.' >&2
    echo 'This looks like an unscrubbed copy of production. Run:' >&2
    echo '    manage.py scrub_local_db --yes-i-am-not-in-production' >&2
    exit 1
fi

if sqlite3 db.sqlite3 "select count(*) from django_session" | grep -qv '^0$'; then
    echo 'ERROR: the database contains live sessions; scrub it first.' >&2
    exit 1
fi

echo '==> Applying migrations'
"$VENV/python" manage.py migrate --no-input

echo '==> Collecting static files'
"$VENV/python" manage.py collectstatic --no-input --clear

echo '==> Starting gunicorn on 127.0.0.1:8000'
"$VENV/python" -m gunicorn kukansite.wsgi:application \
    --bind 127.0.0.1:8000 \
    --workers 3 \
    --access-logfile - \
    --error-logfile - \
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

echo '==> Starting httpd in the foreground on 8443'
exec httpd -DFOREGROUND
