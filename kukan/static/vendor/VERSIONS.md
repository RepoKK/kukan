# Vendored frontend libraries

No build step, so these are the built/minified files straight from npm, fetched via
unpkg.com and committed as-is. No `package.json` here on purpose — that would imply a
build step that does not exist. Bump a version by re-running the matching `curl` below
and reviewing the diff.

| Library | Version | Source |
|---|---|---|
| htmx | 2.0.10 | `https://unpkg.com/htmx.org@2.0.10/dist/htmx.min.js` |
| Alpine.js | 3.15.12 | `https://unpkg.com/alpinejs@3.15.12/dist/cdn.min.js` |
| Bulma | 1.0.4 | `https://unpkg.com/bulma@1.0.4/css/bulma.min.css` |
| Apache ECharts | 5.6.0 | `https://unpkg.com/echarts@5.6.0/dist/echarts.min.js` |
| Material Design Icons (font) | 7.4.47 | `https://unpkg.com/@mdi/font@7.4.47/css/materialdesignicons.min.css` + `fonts/materialdesignicons-webfont.{woff2,woff,ttf,eot}` |

The MDI CSS was hand-edited after fetching: the stock file references four font formats
(`eot`, `woff2`, `woff`, `ttf`) for browsers back to IE9. Only `woff2` is vendored — every
browser this site needs to support has shipped it since 2020 — so the `@font-face` rule
was trimmed to the one `src` entry that matches, rather than shipping three files nothing
requests. Re-fetching the CSS from unpkg will restore the other three references; trim it
again the same way.

Bulma is the full `bulma.min.css` (677 KB) rather than a hand-picked subset of its Sass
modules, because picking a subset needs the Sass build step this project is deliberately
without. It is one cacheable file per user, not per request.

ECharts is the full `echarts.min.js` (1.0 MB) rather than a custom build with only the
bar/line charts this site draws, for the same reason as Bulma: a custom build is a build
step. It replaced two CDN `<script src="https://cdn.jsdelivr.net/...">` tags -- one for
ECharts on the playtime pages, one for Chart.js on the session graph -- neither of which
was pinned by SRI, and one of which (`chart.js` with no version at all) resolved to
whatever the CDN considered latest at page load.
