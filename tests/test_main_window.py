import time

import pytest
from fakes import FakeAudioOut, FakeSynth, wait_until
from PySide6.QtCore import Qt
from PySide6.QtGui import QKeySequence
from PySide6.QtWidgets import QFileDialog, QMessageBox

from leitorpdf.core.errors import LeitorError
from leitorpdf.core.pdf import MSG_INVALID
from leitorpdf.core.voices import DEFAULT_VOICE_KEY, Voice
from leitorpdf.playback.player import Player, PlayerState
from leitorpdf.ui import main_window
from leitorpdf.ui.main_window import MainWindow
from leitorpdf.ui.messages import MSG_NEED_VOICE, MSG_NO_TEXT

PLAY = "▶ Reproduzir"
PAUSE = "⏸ Pausar"
CONTINUE = "▶ Continuar"
LONG_AUDIO = b"\x00\x00" * 1000  # with out.free = 4 this lasts ~10 s per sentence


def add_voice(folder, key):
    (folder / f"{key}.onnx").write_bytes(b"model")
    (folder / f"{key}.onnx.json").write_bytes(b"{}")


@pytest.fixture
def voices_dir(tmp_path):
    folder = tmp_path / "voices"
    folder.mkdir()
    add_voice(folder, "pt_BR-fake-medium")
    return folder


@pytest.fixture
def notes():
    return []


@pytest.fixture
def out():
    return FakeAudioOut()


@pytest.fixture
def synth():
    return FakeSynth()


@pytest.fixture
def player(qapp, out):
    player = Player(out)
    yield player
    player.stop()


@pytest.fixture
def make_window(qapp, player, voices_dir, notes, synth):
    windows = []

    def build(**overrides):
        options = dict(
            player=player,
            voices_dir=voices_dir,
            notify=notes.append,
            synth_factory=lambda voice: synth,
            offer_download=False,
        )
        options.update(overrides)
        window = MainWindow(**options)
        windows.append(window)
        return window

    yield build
    for window in windows:
        window.close()


@pytest.fixture
def window(make_window):
    return make_window()


def open_and_wait(qapp, window, path):
    window.open_path(path)
    wait_until(qapp, lambda: window.play_button.isEnabled())


def start_long_playback(qapp, window, player, out, synth):
    out.free = 4
    synth.audio = LONG_AUDIO
    window.play_button.click()
    wait_until(qapp, lambda: player.state is PlayerState.PLAYING)


def test_starts_empty(window):
    assert window.windowTitle() == "LeitorPDF"
    assert not window.play_button.isEnabled()
    assert window.play_button.text() == PLAY
    assert window.text_view.toPlainText() == ""
    assert window.voice_combo.count() == 1
    assert window.voice_combo.itemText(0) == "Fake · pt_BR · medium"


def test_shortcuts_and_read_only_text(window):
    assert window.open_button.shortcut() == QKeySequence("Ctrl+O")
    assert window.play_button.shortcut() == QKeySequence(Qt.Key.Key_Space)
    assert window.text_view.isReadOnly()


def test_default_voice_is_preselected(make_window, voices_dir):
    add_voice(voices_dir, "en_US-amy-low")
    add_voice(voices_dir, DEFAULT_VOICE_KEY)
    window = make_window()
    assert window.voice_combo.count() == 3
    assert window.voice_combo.currentText() == "Faber · pt_BR · medium"


def test_open_pdf_shows_text_and_enables_play(window, qapp, make_pdf):
    open_and_wait(qapp, window, make_pdf(["Olá mundo. Tudo bem?", "Segunda página."]))
    assert window.text_view.toPlainText() == "Olá mundo. Tudo bem?\n\nSegunda página."
    assert window.statusBar().currentMessage() == "doc.pdf — 2 páginas"


def test_single_page_status_is_singular(window, qapp, make_pdf):
    open_and_wait(qapp, window, make_pdf(["Uma página só."]))
    assert window.statusBar().currentMessage() == "doc.pdf — 1 página"


def test_scanned_pdf_shows_notice(window, qapp, make_pdf, notes):
    window.open_path(make_pdf(["", ""]))
    wait_until(qapp, lambda: notes)
    assert notes == [MSG_NO_TEXT]
    assert not window.play_button.isEnabled()
    assert window.text_view.toPlainText() == ""


def test_scanned_pdf_replaces_previous_document(window, qapp, make_pdf, notes):
    open_and_wait(qapp, window, make_pdf(["Texto antigo."], name="antigo.pdf"))
    window.open_path(make_pdf([""], name="escaneado.pdf"))
    wait_until(qapp, lambda: notes)
    assert window.text_view.toPlainText() == ""
    assert not window.play_button.isEnabled()


def test_invalid_file_keeps_previous_document(window, qapp, make_pdf, notes, tmp_path):
    open_and_wait(qapp, window, make_pdf(["Texto bom."]))
    garbage = tmp_path / "lixo.pdf"
    garbage.write_bytes(b"isto nao e um pdf")
    window.open_path(garbage)
    wait_until(qapp, lambda: notes)
    assert notes == [MSG_INVALID]
    assert window.text_view.toPlainText() == "Texto bom."
    assert window.play_button.isEnabled()
    assert window.statusBar().currentMessage() == "doc.pdf — 1 página"


def test_last_opened_file_wins(window, qapp, make_pdf):
    first = make_pdf(["Primeiro."], name="a.pdf")
    second = make_pdf(["Segundo."], name="b.pdf")
    window.open_path(first)
    window.open_path(second)
    wait_until(qapp, lambda: window.text_view.toPlainText() == "Segundo.")
    deadline = time.monotonic() + 0.1
    while time.monotonic() < deadline:
        qapp.processEvents()
    assert window.text_view.toPlainText() == "Segundo."
    assert window.statusBar().currentMessage() == "b.pdf — 1 página"


def test_open_button_loads_the_chosen_file(window, qapp, make_pdf, monkeypatch):
    path = make_pdf(["Escolhido pelo diálogo."])
    monkeypatch.setattr(
        QFileDialog, "getOpenFileName", lambda *args, **kwargs: (str(path), "")
    )
    window.open_button.click()
    wait_until(qapp, lambda: window.play_button.isEnabled())
    assert window.text_view.toPlainText() == "Escolhido pelo diálogo."


def test_cancelled_open_dialog_changes_nothing(window, qapp, monkeypatch, notes):
    monkeypatch.setattr(QFileDialog, "getOpenFileName", lambda *args, **kwargs: ("", ""))
    window.open_button.click()
    qapp.processEvents()
    assert notes == []
    assert not window.play_button.isEnabled()


def test_reads_the_sentences_of_the_document(window, qapp, make_pdf, synth, out):
    open_and_wait(qapp, window, make_pdf(["Olá mundo. Tudo bem?", "Segunda página."]))
    window.play_button.click()
    wait_until(qapp, lambda: window.statusBar().currentMessage() == "Leitura concluída.")
    assert synth.spoken == ["Olá mundo.", "Tudo bem?", "Segunda página."]
    assert len(out.written) == 3 * len(synth.audio)
    assert out.started_rates == [22050]
    assert window.play_button.text() == PLAY


def test_play_pause_continue_cycle(window, qapp, make_pdf, player, out, synth):
    open_and_wait(qapp, window, make_pdf(["Olá mundo. Tudo bem?"]))
    start_long_playback(qapp, window, player, out, synth)
    assert window.play_button.text() == PAUSE
    assert window.statusBar().currentMessage() == "Lendo…"

    window.play_button.click()
    assert player.state is PlayerState.PAUSED
    assert window.play_button.text() == CONTINUE
    assert window.statusBar().currentMessage() == "Pausado"
    assert out.suspended

    window.play_button.click()
    assert player.state is PlayerState.PLAYING
    assert window.play_button.text() == PAUSE
    assert not out.suspended
    # Changing a button's text drops its shortcut unless it is set again.
    assert window.play_button.shortcut() == QKeySequence(Qt.Key.Key_Space)


def test_opening_another_pdf_stops_playback(window, qapp, make_pdf, player, out, synth):
    open_and_wait(qapp, window, make_pdf(["Primeiro documento."], name="a.pdf"))
    start_long_playback(qapp, window, player, out, synth)
    window.open_path(make_pdf(["Segundo documento."], name="b.pdf"))
    assert player.state is PlayerState.STOPPED
    wait_until(qapp, lambda: window.text_view.toPlainText() == "Segundo documento.")
    assert window.play_button.text() == PLAY
    assert out.stopped


def test_changing_voice_stops_playback_and_uses_new_voice(
    make_window, qapp, make_pdf, player, out, synth, voices_dir
):
    add_voice(voices_dir, "pt_BR-outra-medium")
    made = []

    def factory(voice):
        made.append(voice.key)
        return synth

    window = make_window(synth_factory=factory)
    open_and_wait(qapp, window, make_pdf(["Olá mundo."]))
    start_long_playback(qapp, window, player, out, synth)
    window.voice_combo.setCurrentIndex(1)
    assert player.state is PlayerState.STOPPED
    assert window.play_button.text() == PLAY
    window.play_button.click()
    assert made == ["pt_BR-fake-medium", "pt_BR-outra-medium"]


def test_synthesizer_is_reused_while_the_voice_is_the_same(
    make_window, qapp, make_pdf, synth
):
    made = []

    def factory(voice):
        made.append(voice.key)
        return synth

    window = make_window(synth_factory=factory)
    open_and_wait(qapp, window, make_pdf(["Olá mundo."]))
    for _ in range(2):
        window.play_button.click()
        wait_until(
            qapp, lambda: window.statusBar().currentMessage() == "Leitura concluída."
        )
    assert made == ["pt_BR-fake-medium"]
    assert synth.spoken == ["Olá mundo.", "Olá mundo."]


def test_synthesis_error_is_shown(window, qapp, make_pdf, notes, synth, player):
    synth.error = LeitorError("Falhou.")
    open_and_wait(qapp, window, make_pdf(["Olá mundo."]))
    window.play_button.click()
    wait_until(qapp, lambda: notes)
    assert notes == ["Falhou."]
    assert player.state is PlayerState.STOPPED
    assert window.play_button.text() == PLAY


def test_no_voice_and_download_declined(
    make_window, qapp, make_pdf, tmp_path, monkeypatch, player, out
):
    asked = []

    def question(parent, title, text, *args, **kwargs):
        asked.append(text)
        return QMessageBox.StandardButton.No

    monkeypatch.setattr(QMessageBox, "question", question)
    empty = tmp_path / "sem-vozes"
    empty.mkdir()
    window = make_window(voices_dir=empty)
    assert window.voice_combo.count() == 0
    open_and_wait(qapp, window, make_pdf(["Olá mundo."]))
    window.play_button.click()
    assert asked == [MSG_NEED_VOICE]
    assert player.state is PlayerState.STOPPED
    assert out.started_rates == []


def test_no_voice_download_accepted_then_reads(
    make_window, qapp, make_pdf, tmp_path, monkeypatch, synth
):
    empty = tmp_path / "sem-vozes"
    empty.mkdir()

    def fake_download(parent, voices_dir, **kwargs):
        add_voice(voices_dir, DEFAULT_VOICE_KEY)
        return Voice(DEFAULT_VOICE_KEY, voices_dir / f"{DEFAULT_VOICE_KEY}.onnx")

    monkeypatch.setattr(
        QMessageBox, "question", lambda *args, **kwargs: QMessageBox.StandardButton.Yes
    )
    monkeypatch.setattr(main_window, "download_default_voice", fake_download)
    window = make_window(voices_dir=empty)
    open_and_wait(qapp, window, make_pdf(["Olá mundo."]))
    window.play_button.click()
    assert window.voice_combo.count() == 1
    assert window.voice_combo.currentText() == "Faber · pt_BR · medium"
    wait_until(qapp, lambda: window.statusBar().currentMessage() == "Leitura concluída.")
    assert synth.spoken == ["Olá mundo."]


def test_offers_download_at_startup_when_there_is_no_voice(
    make_window, qapp, tmp_path, monkeypatch
):
    asked = []

    def question(parent, title, text, *args, **kwargs):
        asked.append(text)
        return QMessageBox.StandardButton.No

    monkeypatch.setattr(QMessageBox, "question", question)
    empty = tmp_path / "sem-vozes"
    empty.mkdir()
    make_window(voices_dir=empty, offer_download=True)
    wait_until(qapp, lambda: asked)
    assert asked == [MSG_NEED_VOICE]


def test_does_not_offer_download_when_a_voice_exists(make_window, qapp, monkeypatch):
    asked = []
    monkeypatch.setattr(
        QMessageBox, "question", lambda *args, **kwargs: asked.append(1)
    )
    make_window(offer_download=True)
    deadline = time.monotonic() + 0.1
    while time.monotonic() < deadline:
        qapp.processEvents()
    assert asked == []


def test_closing_the_window_stops_playback(window, qapp, make_pdf, player, out, synth):
    open_and_wait(qapp, window, make_pdf(["Olá mundo."]))
    start_long_playback(qapp, window, player, out, synth)
    window.close()
    assert player.state is PlayerState.STOPPED
