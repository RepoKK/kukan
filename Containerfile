# Staging container: a throwaway stand-in for the production box.
#
# The point of this file is Stage 7 (the Apache/mod_wsgi -> gunicorn cutover).
# There is no staging environment, so that cutover would otherwise be rehearsed
# for the first time on the live site. This gives it somewhere to fail.
#
# It deliberately matches production where it matters and diverges where it
# does not:
#   same    - CentOS Stream 9, so glibc 2.34 and the anki wheel ceiling apply
#   same    - httpd in front, gunicorn behind, systemd-less
#   differs - self-signed certificate instead of Let's Encrypt
#   differs - a scrubbed copy of the database, never the real one
#   differs - no cron; the nightly jobs are run by hand when being tested
#
# BUILD AND RUN
#
#   # from the repo root, with a scrubbed database at ./db.sqlite3
#   podman build -t kukan-staging -f Containerfile .
#   podman run --rm -p 8443:8443 --name kukan-staging kukan-staging
#   # then: https://localhost:8443/  (accept the self-signed certificate)
#
# STILL UNVERIFIED — and now for a known reason. Stage 7 installed podman 5.8.3
# in the dev container and attempted the build. It gets as far as the `dnf`
# step below, which found and fixed one real bug (the curl-minimal conflict,
# see --allowerasing) and then hit a wall that is not this file's fault:
#
#   Every container this dev container can launch is confined to a user
#   namespace that maps uid/gid 0 and nothing else — there is no usable
#   /etc/subuid delegation and the outer sandbox has no CAP_SYS_ADMIN. `chown`
#   to any non-root id returns EINVAL. httpd, mod_ssl, libutempter and
#   util-linux all ship files owned by apache:apache or setgid tty, so the RPM
#   transaction cannot complete. storage.conf's `ignore_chown_errors` does not
#   help: it covers the storage library applying layer diffs, not a live
#   chown(2) from rpm inside a RUN step.
#
# That is a property of the development sandbox, not of CentOS or of this
# Containerfile. On an ordinary machine with rootless podman — or as root on
# the production box — the build should proceed past this point. Everything
# from `uv sync` onwards, including whether the anki 24.11 wheel installs
# against glibc 2.34, is therefore still untested.
#
# Expect to fix things on the first successful build, most likely the httpd
# module paths, which move between CentOS point releases.

FROM quay.io/centos/centos:stream9

# Python 3.12, matching .python-version. These two must not drift apart, or
# staging stops being a rehearsal of production. Available from AppStream on
# CentOS Stream 9 as of stage 5.
#
# --allowerasing: the base image ships curl-minimal, which conflicts with the
# full curl package below (they both provide /usr/bin/curl). Without it dnf
# just refuses the whole transaction; this lets it swap curl-minimal out.
RUN dnf -y install --setopt=install_weak_deps=False --allowerasing \
        python3.12 python3.12-devel \
        httpd mod_ssl \
        sqlite \
        gcc \
        curl \
    && dnf clean all \
    && rm -rf /var/cache/dnf

# uv, matching the version the project is developed against.
COPY --from=ghcr.io/astral-sh/uv:latest /uv /usr/local/bin/uv

ENV UV_PYTHON=python3.12 \
    UV_PROJECT_ENVIRONMENT=/opt/kukan/.venv \
    UV_COMPILE_BYTECODE=1 \
    UV_LINK_MODE=copy \
    PYTHONUNBUFFERED=1

WORKDIR /opt/kukan

# Dependencies first, so a source-only change does not re-resolve them.
COPY pyproject.toml uv.lock .python-version ./
RUN uv sync --locked --no-dev --no-install-project

COPY . .
RUN uv sync --locked --no-dev

# The database, from an explicit path rather than whatever ./db.sqlite3 happens
# to be. .containerignore excludes the working development copy outright: it
# holds a live PSN npsso token and live session cookies, and an image is a very
# easy thing to hand to somebody.
#
#   cp ~/nightly-backup.sqlite3 deploy/staging-db.sqlite3
#   KUKAN_DB_PATH=deploy/staging-db.sqlite3 \
#       uv run manage.py scrub_local_db --yes-i-am-not-in-production
#
# The entrypoint checks the result anyway and refuses to start if the token or
# the sessions are still there.
COPY deploy/staging-db.sqlite3 /opt/kukan/db.sqlite3

# A self-signed certificate. Staging is not reachable from outside the host, so
# the only thing this needs to do is exercise the same TLS code path as prod.
RUN openssl req -x509 -nodes -newkey rsa:2048 -days 365 \
        -keyout /etc/pki/tls/private/kukan-staging.key \
        -out /etc/pki/tls/certs/kukan-staging.crt \
        -subj '/CN=localhost' \
    && chmod 600 /etc/pki/tls/private/kukan-staging.key

COPY deploy/staging-httpd.conf /etc/httpd/conf.d/kukan.conf
COPY deploy/staging-entrypoint.sh /usr/local/bin/staging-entrypoint.sh
RUN chmod +x /usr/local/bin/staging-entrypoint.sh

# The ACME webroot. Empty in staging — there is no certificate to renew here —
# but it has to exist for the Alias to resolve, and the entrypoint writes a
# marker into it to prove httpd serves it rather than proxying it.
RUN mkdir -p /opt/kukan/.well-known/acme-challenge /opt/kukan/static

# httpd's stock config also listens on 80 and would collide.
RUN sed -i 's/^Listen 80$/Listen 8080/' /etc/httpd/conf/httpd.conf \
    && sed -i 's/^Listen 443/Listen 8443/' /etc/httpd/conf.d/ssl.conf || true

EXPOSE 8443

# Refuses to start against an unscrubbed database; see the entrypoint.
ENTRYPOINT ["/usr/local/bin/staging-entrypoint.sh"]
