import pytest
from fakes import wait_until
from PySide6.QtCore import Qt
from PySide6.QtWidgets import QMessageBox

from leitorpdf.core.voices import (
    MSG_CATALOG,
    MSG_DOWNLOAD,
    CatalogVoice,
    Voice,
    VoiceDownloadError,
    installed_voices,
)
from leitorpdf.ui.voice_manager import VoiceManagerDialog

CATALOG = [
    CatalogVoice("pt_BR-cadu-medium", "pt_BR", "cadu", "medium", 63_000_000),
    CatalogVoice("pt_BR-faber-medium", "pt_BR", "faber", "medium", 63_221_984),
    CatalogVoice("de_DE-thorsten-high", "de_DE", "thorsten", "high", 110_400_000),
    CatalogVoice("en_US-amy-low", "en_US", "amy", "low", 60_000_000),
]


def add_voice(folder, key):
    (folder / f"{key}.onnx").write_bytes(b"model")
    (folder / f"{key}.onnx.json").write_bytes(b"{}")


@pytest.fixture
def voices_dir(tmp_path):
    folder = tmp_path / "voices"
    folder.mkdir()
    add_voice(folder, "pt_BR-faber-medium")
    return folder


@pytest.fixture
def notes():
    return []


@pytest.fixture
def downloads():
    return []


@pytest.fixture
def make_dialog(qapp, voices_dir, tmp_path, notes, downloads):
    dialogs = []

    def fake_download(key, folder, progress=None, cancel=None):
        downloads.append((key, folder))
        add_voice(folder, key)
        return Voice(key, folder / f"{key}.onnx")

    def build(fetch=lambda cache_file: list(CATALOG), download=fake_download, wait=True):
        dialog = VoiceManagerDialog(
            voices_dir,
            tmp_path / "voices.json",
            fetch=fetch,
            download=download,
            notify=notes.append,
        )
        dialogs.append(dialog)
        if wait:
            wait_until(qapp, lambda: dialog.status_label.text() != "Carregando lista de vozes…")
        return dialog

    yield build
    for dialog in dialogs:
        dialog.close()


def rows(dialog):
    table = dialog.table
    return [
        tuple(table.item(row, column).text() for column in range(table.columnCount()))
        for row in range(table.rowCount())
    ]


def keys(dialog):
    return [
        dialog.table.item(row, 0).data(Qt.ItemDataRole.UserRole)
        for row in range(dialog.table.rowCount())
    ]


def select(dialog, key):
    dialog.table.selectRow(keys(dialog).index(key))


def choose_language(dialog, text):
    dialog.language_combo.setCurrentIndex(dialog.language_combo.findText(text))


def answer(monkeypatch, button):
    asked = []

    def question(parent, title, text, *args, **kwargs):
        asked.append(text)
        return button

    monkeypatch.setattr(QMessageBox, "question", question)
    return asked


def test_starts_on_brazilian_portuguese(make_dialog):
    dialog = make_dialog()
    assert dialog.language_combo.currentText() == "Português (Brasil)"
    assert rows(dialog) == [
        ("Cadu", "Português (Brasil)", "média", "63 MB", "Disponível"),
        ("Faber", "Português (Brasil)", "média", "63 MB", "Instalada"),
    ]
    assert dialog.status_label.text() == ""
    assert not dialog.changed


def test_language_filter(make_dialog):
    dialog = make_dialog()
    languages = [
        dialog.language_combo.itemText(i) for i in range(dialog.language_combo.count())
    ]
    assert languages == ["Todos os idiomas", "Português (Brasil)", "Alemão", "Inglês (EUA)"]
    choose_language(dialog, "Todos os idiomas")
    assert keys(dialog) == [voice.key for voice in CATALOG]
    choose_language(dialog, "Alemão")
    assert rows(dialog) == [("Thorsten", "Alemão", "alta", "110 MB", "Disponível")]


def test_shows_installed_voices_while_the_list_loads(make_dialog):
    import threading

    gate = threading.Event()

    def slow_fetch(cache_file):
        gate.wait(3.0)
        return list(CATALOG)

    dialog = make_dialog(fetch=slow_fetch, wait=False)
    assert dialog.status_label.text() == "Carregando lista de vozes…"
    assert keys(dialog) == ["pt_BR-faber-medium"]
    gate.set()


def test_buttons_follow_the_selected_voice(make_dialog):
    dialog = make_dialog()
    assert not dialog.download_button.isEnabled() and not dialog.remove_button.isEnabled()
    select(dialog, "pt_BR-cadu-medium")
    assert dialog.download_button.isEnabled() and not dialog.remove_button.isEnabled()
    select(dialog, "pt_BR-faber-medium")
    assert not dialog.download_button.isEnabled() and dialog.remove_button.isEnabled()


def test_download_installs_the_voice(make_dialog, voices_dir, downloads):
    dialog = make_dialog()
    select(dialog, "pt_BR-cadu-medium")
    dialog.download_button.click()
    assert downloads == [("pt_BR-cadu-medium", voices_dir)]
    assert rows(dialog)[0][-1] == "Instalada"
    assert dialog.changed
    assert dialog.remove_button.isEnabled() and not dialog.download_button.isEnabled()
    assert [v.key for v in installed_voices(voices_dir)] == [
        "pt_BR-cadu-medium",
        "pt_BR-faber-medium",
    ]


def test_download_failure_is_reported(make_dialog, notes):
    def failing(key, folder, progress=None, cancel=None):
        raise VoiceDownloadError(MSG_DOWNLOAD)

    dialog = make_dialog(download=failing)
    select(dialog, "pt_BR-cadu-medium")
    dialog.download_button.click()
    assert notes == [MSG_DOWNLOAD]
    assert rows(dialog)[0][-1] == "Disponível"
    assert not dialog.changed


def test_remove_after_confirmation(make_dialog, voices_dir, monkeypatch):
    asked = answer(monkeypatch, QMessageBox.StandardButton.Yes)
    dialog = make_dialog()
    select(dialog, "pt_BR-faber-medium")
    dialog.remove_button.click()
    assert asked == ["Remover a voz Faber · Português (Brasil) · média?"]
    assert installed_voices(voices_dir) == []
    assert rows(dialog)[1][-1] == "Disponível"
    assert dialog.changed


def test_remove_declined(make_dialog, voices_dir, monkeypatch):
    answer(monkeypatch, QMessageBox.StandardButton.No)
    dialog = make_dialog()
    select(dialog, "pt_BR-faber-medium")
    dialog.remove_button.click()
    assert len(installed_voices(voices_dir)) == 1
    assert not dialog.changed


def test_offline_shows_only_installed_voices_and_says_why(make_dialog):
    def offline(cache_file):
        raise VoiceDownloadError(MSG_CATALOG)

    dialog = make_dialog(fetch=offline)
    assert dialog.status_label.text() == MSG_CATALOG
    assert rows(dialog) == [("Faber", "Português (Brasil)", "média", "—", "Instalada")]


def test_installed_voice_missing_from_the_list_is_still_shown(make_dialog, voices_dir):
    add_voice(voices_dir, "pt_BR-antiga-low")
    dialog = make_dialog()
    assert ("Antiga", "Português (Brasil)", "baixa", "—", "Instalada") in rows(dialog)


def test_without_brazilian_voices_all_languages_are_shown(qapp, tmp_path, notes):
    empty = tmp_path / "sem-vozes"
    empty.mkdir()
    foreign = [voice for voice in CATALOG if voice.language != "pt_BR"]
    dialog = VoiceManagerDialog(
        empty, tmp_path / "voices.json", fetch=lambda cache_file: foreign, notify=notes.append
    )
    wait_until(qapp, lambda: dialog.table.rowCount() > 0)
    assert dialog.language_combo.currentText() == "Todos os idiomas"
    assert len(rows(dialog)) == 2
    dialog.close()


def test_remove_still_works_if_the_list_arrives_during_the_question(
    make_dialog, voices_dir, monkeypatch
):
    def slow_fetch(cache_file):
        raise VoiceDownloadError(MSG_CATALOG)  # nothing yet; it "arrives" below

    dialog = make_dialog(fetch=slow_fetch)
    select(dialog, "pt_BR-faber-medium")

    def question(parent, title, text, *args, **kwargs):
        dialog._on_catalog(list(CATALOG))  # the table is rebuilt under the question
        return QMessageBox.StandardButton.Yes

    monkeypatch.setattr(QMessageBox, "question", question)
    dialog.remove_button.click()
    assert installed_voices(voices_dir) == []
    assert dialog.changed
