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
uv run manage.py test                # 529 tests, ~14 s
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
.venv/bin/python -m compileall -q -j 1 .venv/lib/python3.12/site-packages
.venv/bin/python manage.py migrate
.venv/bin/python manage.py collectstatic --no-input
sudo systemctl reload kukan          # not `restart httpd` any more
journalctl -u kukan -f
```

**`compileall -j 1`, never `UV_COMPILE_BYTECODE=1`.** janome ships its
dictionary as Python source; compiling `sysdic/connections1.py` alone peaks at
865 MB resident. Compiling site-packages in parallel puts several of those in
flight at once and takes the box to swap. Skipping it entirely is the other
failure: a cold `Tokenizer()` costs 3.4s and ~950 MB inside the gunicorn worker
at startup, against 0.3s and +50 MB warm.

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
before the live box. The database arrives on a bind mount at `/data` and is scrubbed by the
image itself (`podman run ... kukan-staging scrub`), so no image ever contains one.
`deploy/PROD-BOX-STAGING.md` runs it on the production box under a separate account — the only
way to test the `anki==24.11` ceiling, which exists because of that box's glibc 2.34.

`smoke_urls` is the cheap breadth-first net: it proves each view imports, its template compiles
and its queries run. Use it after any dependency or template change.

A development database goes at `db.sqlite3` in this directory (gitignored via `*sqlite*`). Get one
from the nightly Dropbox backup rather than building it from fixtures — several views only show
their interesting behaviour with real data. That copy carries real password hashes, a live PSN
token and live sessions, so strip them before using it anywhere but your own machine:

```bash
uv run manage.py scrub_local_db --yes-i-am-not-in-production
```

## PlayStation Network

`tempmon/psn.py` owns it. `get_psn()` builds the client on first use and keeps it for the life
of the process; `reset_psn(client)` replaces it, which is both how a new npsso token takes
effect and how tests install a fake. It always returns something — a `NullPsnClient` when there
is no usable token — so no caller checks for None.

**`get_current_game()` never raises.** The sensor firmware has no retry buffer, so a
temperature reading `add_temp_point` fails to store is gone. PSN being unreachable costs the
game attribution for those minutes and nothing else.

**PSNAWP is pinned exactly.** 3.x paces requests with `pyrate_limiter`, whose `try_acquire`
blocks indefinitely rather than failing — a drained bucket stalls every sensor POST until the
window rolls. Two defences: `PRESENCE_TTL` (25s, just under the measured 32s sensor interval,
so it collapses bursts without blurring ordinary readings) and `FAILURE_COOLDOWN` (300s, so an
outage does not make every POST pay a network timeout). The token expires every few months;
`/tempmon/psn_npsso_update/` shows the days remaining.

## Frontend

Server-rendered HTML plus HTMX + Alpine.js and Bulma 1.x. **Vue 2, Buefy, axios and
`node_modules/` are gone** — Stage 10 replaced them page by page (see PLAN.md); there is no
JavaScript build step and no `package.json` anywhere in the repo.

- **`kukan/templates/base.html`** is the one base template: links the vendored files below,
  includes `ui/toasts.html`, and offers `{% block navbar %}`, `{% block extra_head %}` and
  `{% block body %}`. `base_ext.html` adds the fixed navbar and a container;
  `tempmon/base.html` adds the PSN-status hero and its own favicons.
- **`kukan/static/vendor/`** holds htmx, Alpine.js, Bulma, ECharts and the MDI webfont as
  fetched, minified files. `kukan/static/vendor/VERSIONS.md` has exact versions and the
  `curl` to bump one. `kukan/tests_templates.py` fails the build if a template ever links a
  CDN again.
- **`kukan/listview.py: FilteredListView`** serves all seven list pages: one response, either
  the full page or (when `request.htmx`) just `ui/_table.html`'s results fragment.
  `TableData` and `FFilter.add_to_query()` are reused unchanged. `kukan/templates/ui/filters/`
  has one template per `FFilter.kind` (`string`, `checkbox`, `yomi-simple`, `min-max`, `yomi`,
  `bushu`, `daterange`), dispatched by `{% render_filter %}` — adding a filter type to a page
  means adding a row to `FILTER_TEMPLATES` in `kukan/templatetags/util_tags.py`, not editing
  that page's template.
- **Two table partials, on purpose.** `ui/_table.html` is the list-view one and owns
  `#results`, the hx-get sort links and `page_obj`. `ui/_static_table.html` is for pages
  holding several small tables at once (kanji_detail's tabs) and has none of that.
- **`kukan/forms.py: BulmaModelForm`** gives every field a Bulma class, a placeholder (its
  own label, prefixed `（任意）` when optional) and `x-model`. Rendered through
  `{% render_single_field %}` → `ui/_field.html`. A `<select>` gets neither class nor
  placeholder: Bulma styles the wrapping `div.select`, which `ui/_field_control.html` adds.
- **`window.toast(message, type)`** is the client-side toast API; it shares
  `ui/toasts.html`'s region with Django's `messages`. `MESSAGE_TAGS` in `settings/base.py`
  maps message levels onto Bulma's colours (`error` → `is-danger`; Bulma has no `.error`).
- **`kukan/middleware.py: HtmxLoginRedirectMiddleware`** turns a `LoginRequiredMiddleware`
  redirect into an `HX-Redirect` header for htmx requests — otherwise htmx swaps the login
  page's HTML into whatever element made the request instead of navigating the browser
  there. Must sit after `django_htmx.middleware.HtmxMiddleware` and after
  `LoginRequiredMiddleware` in `MIDDLEWARE`.
- **`example_update.html` is a client-side component, deliberately.** Its five ajax endpoints
  return *values* — a definition for a textarea, reading options for a select, furigana to
  insert at the caret — not markup, and htmx swaps markup. It is Alpine + `fetch`, near-1:1
  with the Vue it replaced, and `/ajax/…` stays JSON. `kotowaza_update.html` is the small
  version of the same thing.
- **`{% load icons %}{% icon 'check' %}`** renders a Bulma `.icon` span around an MDI glyph.

### Template gotchas that have bitten more than once

- **`{# ... #}` is single-line only.** Django matches the comment token without `DOTALL`, so
  a `{#` whose `#}` is on a later line is not a comment: every line renders as page text.
  Silent — the page still loads. Use `{% comment %}`. `kukan/tests_templates.py` fails the
  build on it, after three separate occurrences.
- **`{{ value|default:True }}` substitutes on any falsy value**, including an explicit
  `False`, so it cannot express a boolean default. Default in Python at the call site.
- **Explanatory comments about the old stack belong in `{% comment %}`, not `//`.** A JS
  comment ships, and `test_no_vue_or_buefy_remains` checks rendered bytes.
- **Model methods that emit HTML return `SafeString`** (`format_html`, or `join_html` in
  `kukan/models.py` for joining already-safe fragments). `'、'.join()` over SafeStrings
  returns a plain `str`, which the template then escapes — the anchors render as visible
  tags.

## Things that will bite you
- **`add_temp_point` is a hardware contract.** The sensor firmware is not in this repo and has no
  retry buffer. Never change its URL, method, the `API_KEY` body key, the `{'result':'OK'}`
  response, `@csrf_exempt`, or the fact that it *always* returns 200 — even on error.
- **`PlaySession.data_points` is a pickled dict in a `BinaryField`.** Do not "clean it up".
- **Model methods that emit HTML must keep using `format_html`.** `Kanji.basic_info2`,
  `Reading.get_list_ex2`, `Example.goo_link` and friends build anchors that
  `kanji_detail.html` and `AnkiReadTable.html` render. They used string concatenation and
  returned plain `str`, which was invisible while Vue's `v-html` was the only consumer.
- **`kukan/fixtures/`** holds a 26 MB and a 12 MB JSON fixture. Do not regenerate them — several
  tests assert against their exact contents.

## Tests

Plain `django.test.TestCase` with fixtures, `override_settings` and `Client`. No pytest.
`tempmon.tests.TestPsn` is a live contract test against the PlayStation Network and is skipped
unless the `psn_token` environment variable is set.

Each app's original tests live in `tests.py`; the characterisation tests added before the
dependency upgrades are in `tests_<topic>.py` alongside them (Django's default `test*.py`
discovery picks both up). Coverage is 91%; measure it with:

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
