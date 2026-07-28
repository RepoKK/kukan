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
# NOT YET BUILT. podman is not available in the dev container this was written
# in, so this file is unverified. Treat the first build as part of Stage 7 and
# expect to fix things — most likely the httpd module paths, which move between
# CentOS point releases.

FROM quay.io/centos/centos:stream9

# Python 3.12, matching .python-version. These two must not drift apart, or
# staging stops being a rehearsal of production. Available from AppStream on
# CentOS Stream 9 as of stage 5.
RUN dnf -y install --setopt=install_weak_deps=False \
        python3.12 python3.12-devel \
        httpd mod_ssl \
        sqlite \
        gcc \
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

# httpd's stock config also listens on 80 and would collide.
RUN sed -i 's/^Listen 80$/Listen 8080/' /etc/httpd/conf/httpd.conf \
    && sed -i 's/^Listen 443/Listen 8443/' /etc/httpd/conf.d/ssl.conf || true

EXPOSE 8443

# Refuses to start against an unscrubbed database; see the entrypoint.
ENTRYPOINT ["/usr/local/bin/staging-entrypoint.sh"]
