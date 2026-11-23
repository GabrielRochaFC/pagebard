# Pagebard website

The project page published at <https://gabrielrochafc.github.io/pagebard/>.

A plain static site with no framework and no dependencies beyond Python's standard
library. It loads no third-party fonts or scripts and does no tracking.

| Path | What it is |
|---|---|
| `src/template.html` | The page, with `{{ placeholders }}` for every piece of text |
| `src/style.css`, `src/site.js` | Styles (light and dark) and a little script: language memory, copy buttons |
| `i18n/*.json` | The text in each language — every file must have the same keys |
| `build.py` | Fills the template once per language into `_site/` |

Screenshots and the logo come from `docs/images/`, the same files the README uses.

## Preview

```bash
python3 website/build.py
python3 -m http.server -d website/_site
```

Then open <http://localhost:8000>.

## Publish

`.github/workflows/pages.yml` builds and deploys the site on every push to `main`
that touches `website/` or `docs/images/`. One-time setup: in the repository's
*Settings → Pages*, set **Source** to **GitHub Actions**.

## Add a language

1. Copy `i18n/en.json` to `i18n/<code>.json` and translate the values.
2. Add the language to `LANGUAGES` in `build.py`.
