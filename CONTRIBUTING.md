# Contributing to Pagebard

Thank you for helping! Bug reports, ideas, code and translations are all welcome.

## Reporting a problem

Open an [issue](https://github.com/GabrielRochaFC/pagebard/issues) and say:

- what you did, what you expected, and what happened instead;
- your distribution and how you installed Pagebard (Flatpak file or from source);
- if it is about a specific PDF and you can share it, attach the file — reading
  order and layout problems are almost impossible to reproduce without it.

## Setting up

```bash
git clone https://github.com/GabrielRochaFC/pagebard.git
cd pagebard
python3 -m venv .venv
.venv/bin/python -m pip install -e ".[dev]"
.venv/bin/python -m pagebard     # run the app
.venv/bin/python -m pytest       # run the tests (about a minute)
```

You need Python 3.11+ and, for the MP3 export tests, `ffmpeg`. The tests run
without a display (`QT_QPA_PLATFORM=offscreen` is set for you). A few tests use
the real sound device, but they only ever play silence.

## Making a change

- Write a test that fails first, then make it pass. The suite is the safety net
  of this project: a change without a test is hard to accept.
- Keep `pagebard/core` free of Qt. The interface lives in `pagebard/ui`.
- Read [docs/ARCHITECTURE.md](docs/ARCHITECTURE.md) before touching threads or
  the child process. In short: **worker threads never receive Qt objects**, and
  heavy PyMuPDF work happens in the child process.
- Texts shown to the user are written in English and wrapped in `_()`; see
  below.

## Translating

The texts are in English in the source. Each other language is one file in
`src/pagebard/locale/`: `pt_BR.po`, `es.po`. They are ordinary gettext
catalogs, read as they are — there is no compile step.

**To fix a translation**, edit the `msgstr` line in the `.po` file.

**To add a language**:

1. Copy `src/pagebard/locale/es.po` to, say, `fr.po`.
2. Change the `Language:` header and, if your language needs it, the
   `Plural-Forms:` line.
3. Translate every `msgstr`. Keep the `{placeholders}` exactly as they are.
4. Add your language to `_LANGUAGE_NAMES` in `src/pagebard/ui/main_window.py`
   (under its own name, e.g. `("fr", "Français")`) and to `TRANSLATED` in
   `tests/test_i18n.py`.
5. Run the tests: they check that no text is missing and that the placeholders
   match.

**When you add or change a text in the code**, add it to every `.po` file. The
test `test_catalog_is_complete_and_has_nothing_stale` tells you what is missing.

The Spanish translation and parts of the English wording were machine-assisted.
Corrections from native speakers are very welcome.

## Pull requests

Describe what the change does and how you tested it. Small, focused pull
requests are reviewed faster. By contributing you agree to license your work
under AGPL-3.0-or-later.
