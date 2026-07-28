# kukan

Django site behind [kukanjiten.com](https://kukanjiten.com/) — Japanese kanji study material for
the Kanken exam, plus an Anki sync pipeline and two bolted-on utilities (`bustime`, `tempmon`).
Single self-hosted CentOS Stream 9 box, Apache in front of gunicorn, SQLite.
Python 3.12, Django 6.0.

## Apps

| App | What it is |
|---|---|
| `kukan` | The site proper: kanji, 四字熟語, 諺, example sentences, export to Anki |
| `tempmon` | PlayStation session/temperature logger fed by a hardware sensor POSTing to `add_temp_point` |
| `bustime` | Scrapes tobus.jp for the next bus; public, no login |
| `utils_django` | Reusable bits: `FBaseCommand` (locking + logging for cron commands), Dropbox helper |

## Running it

Dependencies are managed by [uv](https://docs.astral.sh/uv/). `pyproject.toml` lists the direct
ones, `uv.lock` pins the full transitive set and is committed — there is no `requirements.txt`.
`uv sync` builds `.venv/`; `uv run` uses it without an activate step.

```bash
uv sync                              # or `uv sync --locked` to fail on a stale lock
uv run manage.py check
uv run manage.py test                # 465 tests, ~14 s
uv run manage.py test --shuffle      # randomised order; what CI runs
uv run manage.py smoke_urls          # GETs every no-arg URL as a superuser
uv run manage.py runserver
uv run ruff check .                  # and `--fix` to apply
```

## Settings

`kukansite/settings/` is a package, and `DJANGO_SETTINGS_MODULE` picks one:

| Module | Used by | Notes |
|---|---|---|
| `base` | imported by the others | shared only; no `DEBUG`, no `SECRET_KEY` |
| `dev` | `manage.py` default | throwaway credentials, works with no env at all |
| `test` | `manage.py test` (auto) | blocks outbound sockets, MD5 hasher |
| `prod` | `wsgi.py` default | every secret required; raises if one is missing |

`prod` reads `/etc/kukan/kukan.env` (root:kukan 0640) — see `deploy/kukan.env.example`.
For dev, put real values in an uncommitted `.env` and use `uv run --env-file .env manage.py …`.

**Every view requires a login unless it says otherwise.** `LoginRequiredMiddleware` denies by
default; the entire public surface is the five `@login_not_required` markers (`add_temp_point`,
both bustime views, `LoginView`, `LogoutView`). This replaced opting in per view, which had
silently failed twice — see `kukan/tests_access_control.py`.

**`prod` has no fallbacks by design.** It replaced a `try: from settings_prod import * except
ImportError: pass` sitting under a checked-in `DEBUG = True`, which meant any import error inside
that file served full Django debug pages to the internet. If a variable is missing, the process
must not start.

`test` blocks AF_INET/AF_INET6 sockets, so any un-mocked HTTP call fails loudly instead of
silently depending on a third-party site. The two live contract tests are opt-in:

```bash
psn_token=... uv run manage.py test tempmon.tests.TestPsn
KUKAN_LIVE_WEB_TESTS=1 uv run manage.py test kukan.tests.TestDefinitionReal
```

After editing `pyproject.toml`, run `uv lock` and commit the result. CI uses `--locked`, so a
forgotten lock fails the build rather than silently resolving to different versions.

## Deployment

Apache owns :443, TLS, `/static` and `/.well-known`, and proxies everything else to gunicorn on
`127.0.0.1:8000` under systemd. It no longer loads Python. Everything needed is in `deploy/`,
and `deploy/STAGE7-CUTOVER.md` is the runbook.

| File | Installs as |
|---|---|
| `deploy/kukan.service` | `/etc/systemd/system/kukan.service` |
| `deploy/kukanjiten-httpd.conf` | `/etc/httpd/conf.d/kukan.conf` |
| `deploy/kukan.env.example` | `/etc/kukan/kukan.env` (root:kukan 0640) |
| `deploy/gunicorn.conf.py` | read in place from the checkout |

```bash
git pull && uv sync --locked
.venv/bin/python manage.py migrate
.venv/bin/python manage.py collectstatic --no-input
sudo systemctl reload kukan          # not `restart httpd` any more
journalctl -u kukan -f
```

**`ProxyPass /` must stay below every `Alias`**, each of which needs its own
`ProxyPass <path> !`. mod_proxy takes the first matching rule, so an alias underneath the
catch-all is dead — and for `/.well-known` that means certbot's challenge gets proxied to
Django, 404s, and renewal fails silently until the certificate expires.
`kukansite/tests_deploy.py` asserts the ordering; the staging container proves it at runtime.

**One worker, four threads.** One writer for one SQLite file, and one resident Janome
`Tokenizer` (+50 MB). `DATABASES['OPTIONS']` therefore carries WAL, `busy_timeout` and
`transaction_mode=IMMEDIATE` — four threads on one file need all three.

The staging container (`Containerfile`) runs `kukansite.settings.prod` against
`deploy/staging.env` and a scrubbed database, and refuses to start until its own checks pass.
It is the only place the production settings module, the proxy and the TLS path get exercised
before the live box.

`smoke_urls` is the cheap breadth-first net: it proves each view imports, its template compiles
and its queries run. Use it after any dependency or template change.

A development database goes at `db.sqlite3` in this directory (gitignored via `*db*`). Get one
from the nightly Dropbox backup rather than building it from fixtures — several views only show
their interesting behaviour with real data. That copy carries real password hashes, a live PSN
token and live sessions, so strip them before using it anywhere but your own machine:

```bash
uv run manage.py scrub_local_db --yes-i-am-not-in-production
```

## Things that will bite you
- **`tempmon/views.py` runs a DB query and a PSN network login at import time.** With no
  `db.sqlite3` present every command logs `OperationalError: no such table: tempmon_psnapikey`.
  It is caught and harmless, but it is why the module is hard to test.
- **`add_temp_point` is a hardware contract.** The sensor firmware is not in this repo and has no
  retry buffer. Never change its URL, method, the `API_KEY` body key, the `{'result':'OK'}`
  response, `@csrf_exempt`, or the fact that it *always* returns 200 — even on error.
- **`PlaySession.data_points` is a pickled dict in a `BinaryField`.** Do not "clean it up".
- **Model `__str__`-style methods emit raw HTML** without `mark_safe` (`kukan/models.py`). This is
  invisible today because templates render through Vue's `v-html`; it becomes visible escaping the
  moment a page is server-rendered.
- **`kukan/fixtures/`** holds a 26 MB and a 12 MB JSON fixture. Do not regenerate them — several
  tests assert against their exact contents.

## Tests

Plain `django.test.TestCase` with fixtures, `override_settings` and `Client`. No pytest.
`tempmon.tests.TestPsn` is a live contract test against the PlayStation Network and is skipped
unless the `psn_token` environment variable is set.

Each app's original tests live in `tests.py`; the characterisation tests added before the
dependency upgrades are in `tests_<topic>.py` alongside them (Django's default `test*.py`
discovery picks both up). Coverage is 92%; measure it with:

```bash
uv run coverage run manage.py test && uv run coverage report
```

Two conventions worth keeping:

- **Known-defect tests** assert the buggy behaviour and say so in the docstring, so the suite
  stays green while the defect stays visible. Fixing the defect is meant to turn them red.
  Currently: empty numeric filter values (`kukan/tests_filters.py`) and the tempmon duration
  filter (`tempmon/tests_views.py`).
- **Recorded web pages** for the scrapers go under `fixtures/Web/` as raw HTML. The older
  `FixWebKukan` helper pickles a `requests.Response`, which stops loading when `requests` is
  upgraded — don't add new fixtures in that format.

## Conventions

Follow what is already in the file you are editing. Broadly: 4-space indent, single quotes,
~100 column lines, `logging.getLogger(__name__)` per module, class-based views.
