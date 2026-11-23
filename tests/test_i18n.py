import ast
import os
import re
import subprocess
import sys
from pathlib import Path

import pytest

from pagebard.core import i18n

SOURCE = Path(i18n.__file__).resolve().parent.parent
TRANSLATED = ["es", "pt_BR"]


@pytest.fixture
def switch():
    """Change the language for one test and put Portuguese back afterwards."""
    yield i18n.set_language
    i18n.set_language("pt_BR")


def source_messages():
    """Every text marked for translation in the source: (singular, plural or None)."""
    found = set()
    for path in SOURCE.rglob("*.py"):
        for node in ast.walk(ast.parse(path.read_text(encoding="utf-8"))):
            if not isinstance(node, ast.Call) or not isinstance(node.func, ast.Name):
                continue
            if node.func.id in ("_", "N_"):
                [argument] = node.args
                if isinstance(argument, ast.Constant):
                    found.add((argument.value, None))
                else:  # a text looked up at run time must have been marked with N_
                    assert node.func.id == "_", f"{path}:{node.lineno}"
            elif node.func.id == "ngettext":
                singular, plural = node.args[0], node.args[1]
                assert isinstance(singular, ast.Constant) and isinstance(plural, ast.Constant)
                found.add((singular.value, plural.value))
    return found


def placeholders(text):
    return sorted(re.findall(r"\{[a-z_]*\}", text))


def test_available_languages():
    assert i18n.available_languages() == ["en", "es", "pt_BR"]


def test_match_language():
    assert i18n.match_language("pt_BR") == "pt_BR"
    assert i18n.match_language("pt_PT.UTF-8") == "pt_BR"
    assert i18n.match_language("pt") == "pt_BR"
    assert i18n.match_language("es_MX.UTF-8") == "es"
    assert i18n.match_language("es-AR") == "es"
    assert i18n.match_language("en_GB") == "en"
    assert i18n.match_language("fr_FR.UTF-8") is None
    assert i18n.match_language("C") is None
    assert i18n.match_language("") is None
    assert i18n.match_language(None) is None


def test_system_language_reads_the_environment(monkeypatch):
    for name in ("LANGUAGE", "LC_ALL", "LC_MESSAGES", "LANG"):
        monkeypatch.delenv(name, raising=False)
    assert i18n.system_language() == "en"
    monkeypatch.setenv("LANG", "pt_BR.UTF-8")
    assert i18n.system_language() == "pt_BR"
    monkeypatch.setenv("LC_MESSAGES", "es_ES.UTF-8")
    assert i18n.system_language() == "es"
    monkeypatch.setenv("LANGUAGE", "fr:en_GB:pt")  # first one that exists
    assert i18n.system_language() == "en"


def test_explicit_choice_then_variable_then_system(monkeypatch, switch):
    monkeypatch.setenv("LANG", "es_ES.UTF-8")
    monkeypatch.setenv("PAGEBARD_LANGUAGE", "pt_BR")
    assert switch("en") == "en"
    assert switch() == "pt_BR"
    monkeypatch.delenv("PAGEBARD_LANGUAGE")
    assert switch() == "es"
    assert switch("klingon") == "es"  # unknown: falls through
    assert i18n.language() == "es"


def test_translates_and_falls_back(switch):
    switch("pt_BR")
    assert i18n._("Cancel") == "Cancelar"
    assert i18n._("texto que não existe no catálogo") == "texto que não existe no catálogo"
    switch("es")
    assert i18n._("Cancel") == "Cancelar"
    switch("en")
    assert i18n._("Cancel") == "Cancel"


def test_plurals(switch):
    singular, plural = "{name} — {count} page", "{name} — {count} pages"
    expected = {
        "en": ["a.pdf — 1 page", "a.pdf — 2 pages"],
        "pt_BR": ["a.pdf — 1 página", "a.pdf — 2 páginas"],
        "es": ["a.pdf — 1 página", "a.pdf — 2 páginas"],
    }
    for code, texts in expected.items():
        switch(code)
        got = [
            i18n.ngettext(singular, plural, count).format(name="a.pdf", count=count)
            for count in (1, 2)
        ]
        assert got == texts


def test_decimal_separator(switch):
    switch("pt_BR")
    assert i18n.decimal(1.5) == "1,5"
    switch("es")
    assert i18n.decimal(1.0) == "1,0"
    switch("en")
    assert i18n.decimal(1.5) == "1.5"


def test_po_reader(tmp_path):
    po = tmp_path / "xx.po"
    po.write_text(
        '# a comment\n'
        'msgid ""\n'
        'msgstr ""\n'
        '"Language: xx\\n"\n'
        '"Plural-Forms: nplurals=2; plural=(n > 1);\\n"\n'
        '\n'
        '#: somewhere.py:3\n'
        'msgid "one "\n'
        '"line"\n'
        'msgstr "uma \\"linha\\"\\n"\n'
        '"só"\n'
        '\n'
        'msgid "{count} page"\n'
        'msgid_plural "{count} pages"\n'
        'msgstr[0] "{count} página"\n'
        'msgstr[1] "{count} páginas"\n'
        '\n'
        'msgid "untranslated"\n'
        'msgstr ""\n',
        encoding="utf-8",
    )
    messages, plurals = i18n.read_po(po)
    assert messages["one line"] == 'uma "linha"\nsó'
    assert "Plural-Forms: nplurals=2; plural=(n > 1);" in messages[""]
    assert plurals == {"{count} page": ["{count} página", "{count} páginas"]}
    assert "untranslated" not in messages


@pytest.mark.parametrize("code", TRANSLATED)
def test_catalog_is_complete_and_has_nothing_stale(code):
    messages, plurals = i18n.read_po(i18n.LOCALE_DIR / f"{code}.po")
    in_source = source_messages()
    wanted_plain = {singular for singular, plural in in_source if plural is None}
    wanted_plural = {singular for singular, plural in in_source if plural is not None}
    assert wanted_plain - set(messages) == set(), "missing translations"
    assert wanted_plural - set(plurals) == set(), "missing plural translations"
    assert set(messages) - wanted_plain - {""} == set(), "translations of texts no longer used"
    assert set(plurals) - wanted_plural == set(), "plural translations no longer used"


@pytest.mark.parametrize("code", TRANSLATED)
def test_translations_keep_the_placeholders(code):
    messages, plurals = i18n.read_po(i18n.LOCALE_DIR / f"{code}.po")
    for msgid, msgstr in messages.items():
        if msgid:
            assert placeholders(msgstr) == placeholders(msgid), msgid
            assert msgstr.strip(), msgid
    for msgid, forms in plurals.items():
        assert len(forms) == 2
        for form in forms:
            assert placeholders(form) == placeholders(msgid), msgid


def run_fresh(code, language_variable=None, **environment):
    """Run a snippet in a new interpreter, as the program would start."""
    env = {k: v for k, v in os.environ.items() if k not in ("LANGUAGE", "LC_ALL", "LC_MESSAGES")}
    env.pop("PAGEBARD_LANGUAGE", None)
    env.update(environment)
    if language_variable:
        env["PAGEBARD_LANGUAGE"] = language_variable
    result = subprocess.run([sys.executable, "-c", code], env=env, capture_output=True, text=True)
    assert result.returncode == 0, result.stderr
    return result.stdout.strip().splitlines()


SNIPPET = (
    "from pagebard.core import i18n, voices, ocr\n"
    "from pagebard.ui import messages\n"
    "print(i18n.language())\n"
    "print(messages.MSG_NO_TEXT)\n"
    "print(voices.DEFAULT_VOICE_KEY)\n"
    "print(voices.language_label('pt_BR'), '|', voices.quality_label('medium'))\n"
    "print(ocr.language_for('sw_CD'))\n"
)


def test_program_starts_in_the_language_of_the_system():
    assert run_fresh(SNIPPET, LANG="en_US.UTF-8") == [
        "en",
        "This PDF has no text to read.",
        "en_US-lessac-medium",
        "Portuguese (Brazil) | medium",
        "eng",
    ]
    assert run_fresh(SNIPPET, LANG="es_AR.UTF-8") == [
        "es",
        "Este PDF no tiene texto para leer.",
        "es_ES-davefx-medium",
        "Portugués (Brasil) | media",
        "spa",
    ]
    assert run_fresh(SNIPPET, LANG="pt_PT.UTF-8") == [
        "pt_BR",
        "Este PDF não tem texto para ler.",
        "pt_BR-faber-medium",
        "Português (Brasil) | média",
        "por",
    ]


def test_unsupported_system_language_gives_english():
    assert run_fresh(SNIPPET, LANG="ja_JP.UTF-8")[0] == "en"
    assert run_fresh(SNIPPET, LANG="C")[0] == "en"


def test_variable_overrides_the_system():
    assert run_fresh(SNIPPET, language_variable="es", LANG="pt_BR.UTF-8")[0] == "es"


WINDOW_SNIPPET = """
import os, tempfile
os.environ["QT_QPA_PLATFORM"] = "offscreen"
from PySide6.QtCore import QCoreApplication
from PySide6.QtWidgets import QApplication
app = QApplication([])
from pagebard.app import install_translations
from pagebard.playback.player import Player
from pagebard.ui.main_window import MainWindow
from pagebard.ui.shortcuts_dialog import SHORTCUTS


class Silent:
    def start(self, rate): pass
    def bytes_free(self): return 0
    def write(self, data): return 0
    def suspend(self): pass
    def resume(self): pass
    def stop(self): pass
    def is_idle(self): return True


from pathlib import Path
window = MainWindow(
    player=Player(Silent()), voices_dir=Path(tempfile.mkdtemp()), offer_download=False
)
print(window.open_button.text(), "|", window.play_button.text(), "|", window.stop_button.text())
print([action.text() for action in window.menuBar().actions()])
print(window.speed_label.text(), "|", window.fit_button.text())
print(SHORTCUTS[3])
print(install_translations(app), "|", QCoreApplication.translate("QPlatformTheme", "Cancel"))
window.close()
"""


def test_window_in_english():
    assert run_fresh(WINDOW_SNIPPET, LANG="en_US.UTF-8") == [
        "Open PDF… | ▶ Play | ⏹ Stop",
        "['&File', '&Reading', '&View', '&Help']",
        "1.0× | Fit width",
        "('Space', 'Play, pause or resume reading')",
        "True | Cancel",
    ]


def test_window_in_spanish():
    assert run_fresh(WINDOW_SNIPPET, LANG="es_ES.UTF-8") == [
        "Abrir PDF… | ▶ Reproducir | ⏹ Detener",
        "['&Archivo', '&Lectura', '&Ver', 'A&yuda']",
        "1,0× | Ajustar al ancho",
        "('Espacio', 'Reproducir, pausar o continuar la lectura')",
        "True | Cancelar",
    ]


def test_no_portuguese_left_in_the_english_window():
    # Portuguese has letters English text never needs: any of them means a
    # text that escaped translation.
    snippet = WINDOW_SNIPPET + """
from PySide6.QtWidgets import QWidget
texts = set()
for widget in window.findChildren(QWidget) + [window]:
    for getter in ("text", "toolTip", "accessibleName", "title", "placeholderText"):
        value = getattr(widget, getter, None)
        if callable(value):
            try:
                texts.add(str(value()))
            except TypeError:
                pass
for action in window.findChildren(type(window.open_action)):
    texts.add(action.text())
print("LEFT:", sorted(t for t in texts if any(c in t for c in "ãõçáéíóúâêô") and t != "Português (Brasil)" and t != "Español"))
"""
    assert run_fresh(snippet, LANG="en_US.UTF-8")[-1] == "LEFT: []"
