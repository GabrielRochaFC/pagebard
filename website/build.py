#!/usr/bin/env python3
"""Build the Pagebard website into website/_site.

Standard library only. Each language in i18n/ becomes one page; the screenshots
and logo are copied from docs/images so the site and the README never drift.

    python3 website/build.py
    python3 -m http.server -d website/_site    # preview at http://localhost:8000
"""

from __future__ import annotations

import json
import re
import shutil
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
REPO = HERE.parent
SRC = HERE / "src"
I18N = HERE / "i18n"
IMAGES = REPO / "docs" / "images"
OUT = HERE / "_site"

BASE_URL = "https://gabrielrochafc.github.io/pagebard/"
REPO_URL = "https://github.com/GabrielRochaFC/pagebard"
DOWNLOAD_URL = REPO_URL + "/releases/latest/download/Pagebard.flatpak"

# (code, folder under the site root, label in the language switcher, Open Graph locale)
LANGUAGES = [
    ("en", "", "EN", "en_US"),
    ("pt-BR", "pt-br/", "PT", "pt_BR"),
    ("es", "es/", "ES", "es_ES"),
]

PLACEHOLDER = re.compile(r"\{\{\s*([a-z0-9_]+)\s*\}\}")


def load_strings() -> dict[str, dict[str, str]]:
    strings = {code: json.loads((I18N / f"{code}.json").read_text("utf-8")) for code, *_ in LANGUAGES}
    reference = set(strings["en"])
    for code, table in strings.items():
        missing, extra = reference - set(table), set(table) - reference
        if missing or extra:
            sys.exit(f"{code}.json: missing {sorted(missing)}, unexpected {sorted(extra)}")
    return strings


def render(template: str, context: dict[str, str]) -> str:
    def substitute(match: re.Match[str]) -> str:
        key = match.group(1)
        if key not in context:
            sys.exit(f"template uses {{{{ {key} }}}} but no value was given")
        return context[key]

    return PLACEHOLDER.sub(substitute, template)


def build() -> None:
    strings = load_strings()
    template = (SRC / "template.html").read_text("utf-8")

    if OUT.exists():
        shutil.rmtree(OUT)
    OUT.mkdir()
    for name in ("style.css", "site.js"):
        shutil.copy2(SRC / name, OUT / name)
    (OUT / "images").mkdir()
    for image in ("logo.svg", "reading.png", "selection.png", "voices.png"):
        shutil.copy2(IMAGES / image, OUT / "images" / image)

    hreflang = "\n".join(
        [f'<link rel="alternate" hreflang="{code}" href="{BASE_URL}{path}">' for code, path, *_ in LANGUAGES]
        + [f'<link rel="alternate" hreflang="x-default" href="{BASE_URL}">']
    )

    for code, path, _, og_locale in LANGUAGES:
        root = "../" * path.count("/")
        switch = "\n      ".join(
            f'<a href="{(root + other_path) or "./"}" hreflang="{other}" lang="{other}"'
            + (' aria-current="page"' if other == code else "")
            + f">{label}</a>"
            for other, other_path, label, _ in LANGUAGES
        )
        context = {
            **strings[code],
            "html_lang": code,
            "lang_code": code,
            "home": (root + path) or "./",
            "root": root,
            "base_url": BASE_URL,
            "page_url": BASE_URL + path,
            "og_locale": og_locale,
            "repo_url": REPO_URL,
            "download_url": DOWNLOAD_URL,
            "hreflang_links": hreflang,
            "lang_switch": switch,
        }
        target = OUT / path / "index.html"
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(render(template, context), "utf-8")
        print(f"built {target.relative_to(REPO)}")

    # GitHub Pages: serve files as they are, without Jekyll.
    (OUT / ".nojekyll").touch()


if __name__ == "__main__":
    build()
