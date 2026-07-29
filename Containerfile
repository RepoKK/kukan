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
#   podman build -t kukan-staging -f Containerfile .
#
#   # A copy of the database, scrubbed using this image's own virtualenv, so
#   # that running staging needs nothing on the host but podman.
#   mkdir -p ~/kukan-staging-data
#   cp /path/to/backup.sqlite3 ~/kukan-staging-data/db.sqlite3
#   podman run --rm -v ~/kukan-staging-data:/data:Z kukan-staging scrub
#
#   podman run --rm -p 127.0.0.1:8443:8443 -v ~/kukan-staging-data:/data:Z \
#       --name kukan-staging kukan-staging
#   # then: https://localhost:8443/  (accept the self-signed certificate)
#
# The database is a bind mount, not baked in. Three reasons: rebuilding the
# image after a code change does not mean re-copying data; the working
# db.sqlite3 cannot end up in an image even by accident; and the scrub can run
# inside the container, which is what makes this practical on a box that has no
# development environment. See deploy/PROD-BOX-STAGING.md.
#
# BUILD HISTORY, because it is short and each entry cost something to learn.
#
# It cannot be built in the development container at all: every container that
# sandbox can launch is confined to a user namespace mapping uid/gid 0 and
# nothing else, so `chown` to any other id returns EINVAL, and httpd, mod_ssl,
# libutempter and util-linux all ship non-root-owned files. The RPM transaction
# therefore cannot complete. (`ignore_chown_errors` does not help — it covers
# the storage library applying layer diffs, not a live chown(2) from rpm inside
# a RUN step.) That is a property of the sandbox, not of CentOS or of this
# file; ordinary rootless podman is fine.
#
#   attempt 1, dev container: dnf refused the transaction — curl-minimal in the
#       base image conflicts with curl. Fixed, see --allowerasing.
#   attempt 2, dev container: the uid-0 namespace wall above. Went no further.
#   attempt 3, production box: dnf completed. anki 24.11 downloaded and
#       installed, which is the answer to the question this container was
#       mainly built to ask — the glibc 2.34 ceiling in pyproject.toml holds.
#       Died in `uv sync` on a bytecode compile timeout; see the compileall
#       step below, which is the fix.
#
# So everything up to and including `uv sync` is now known to work on the real
# target. Everything after it — httpd module paths especially, which move
# between CentOS point releases — is still unproven.

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

# No UV_COMPILE_BYTECODE here — see the compileall step below, which does the
# same job serially. uv compiles site-packages across all cores at once, and
# janome cannot afford that.
ENV UV_PYTHON=python3.12 \
    UV_PROJECT_ENVIRONMENT=/opt/kukan/.venv \
    UV_LINK_MODE=copy \
    PYTHONUNBUFFERED=1

WORKDIR /opt/kukan

# Dependencies first, so a source-only change does not re-resolve them.
COPY pyproject.toml uv.lock .python-version ./
RUN uv sync --locked --no-dev --no-install-project

COPY . .
RUN uv sync --locked --no-dev

# Bytecode, compiled ONE FILE AT A TIME. `-j 1` is the entire point of this
# step existing as its own line rather than as UV_COMPILE_BYTECODE=1.
#
# janome ships its dictionary as Python source: 113 MB of it, including a
# single 5 MB literal in sysdic/connections1.py. Measured, compiling that one
# file peaks at 865 MB resident. uv compiles site-packages across every core
# simultaneously, so on an 8-core box that is several gigabytes at once — which
# is how the first real build of this image died, with uv's 60s-per-file
# compile timeout firing on a machine that had gone to swap.
#
# Doing it here rather than leaving it to lazy import-time compilation is
# deliberate: the alternative is that the first Tokenizer() in a fresh
# container pays 3.4s and a ~950 MB transient spike, in-process, inside the
# gunicorn worker. Warm, that same construction is 0.3s and +50 MB.
RUN /opt/kukan/.venv/bin/python -m compileall -q -j 1 \
        /opt/kukan/.venv/lib/python3.12/site-packages

# The database lives on a bind mount at /data, and no database is baked into
# the image at all. .containerignore excludes the working copy from the build
# context as well — it holds a live PSN npsso token and live session cookies,
# and an image is a very easy thing to hand to somebody.
#
# `podman run ... kukan-staging scrub` scrubs whatever is mounted there, using
# this image's virtualenv. The entrypoint checks the result on every start and
# refuses to serve if the token or the sessions are still present.
ENV KUKAN_DB_PATH=/data/db.sqlite3
RUN mkdir -p /data

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
