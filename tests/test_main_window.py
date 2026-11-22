import threading
import time

import pytest
from fakes import FakeAudioOut, FakeSynth, wait_until
from PySide6.QtCore import Qt
from PySide6.QtGui import QKeySequence
from PySide6.QtTest import QTest
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
LEFT = Qt.MouseButton.LeftButton
LONG_AUDIO = b"\x00\x00" * 1000  # with out.free = 4 this lasts ~10 s per sentence
SHORT_AUDIO = b"\x00\x00" * 20  # with out.free = 4: ~0.2 s per sentence


def add_voice(folder, key):
    (folder / f"{key}.onnx").write_bytes(b"model")
    (folder / f"{key}.onnx.json").write_bytes(b"{}")


def threads_named(name):
    return [t for t in threading.enumerate() if t.name == name]


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
    player.shutdown()


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
    deadline = time.monotonic() + 2.0
    while threads_named("leitorpdf-render") and time.monotonic() < deadline:
        time.sleep(0.005)
    assert threads_named("leitorpdf-render") == []


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


def status(window):
    return window.statusBar().currentMessage()


def show_active(qapp, window):
    window.show()
    window.activateWindow()
    assert QTest.qWaitForWindowActive(window, 2000)


# ---- start-up -------------------------------------------------------------


def test_starts_empty(window):
    assert window.windowTitle() == "LeitorPDF"
    assert window.reading is None
    assert window.pdf_view.reading is None
    assert not window.play_button.isEnabled()
    assert window.play_button.text() == PLAY
    assert not window.stop_button.isEnabled()
    assert window.page_label.text() == ""
    assert window.voice_combo.count() == 1
    assert window.voice_combo.itemText(0) == "Fake · pt_BR · medium"


def test_open_shortcut(window):
    assert window.open_button.shortcut() == QKeySequence("Ctrl+O")


def test_default_voice_is_preselected(make_window, voices_dir):
    add_voice(voices_dir, "en_US-amy-low")
    add_voice(voices_dir, DEFAULT_VOICE_KEY)
    window = make_window()
    assert window.voice_combo.count() == 3
    assert window.voice_combo.currentText() == "Faber · pt_BR · medium"


# ---- opening documents --------------------------------------------------------


def test_open_pdf_shows_pages_and_enables_play(window, qapp, make_pdf):
    open_and_wait(qapp, window, make_pdf(["Olá mundo. Tudo bem?", "Segunda página."]))
    assert window.reading.text == "Olá mundo. Tudo bem?\n\nSegunda página."
    assert window.pdf_view.reading is window.reading
    assert status(window).startswith("doc.pdf — 2 páginas")
    assert window.page_label.text() == "Página 1 de 2"


def test_single_page_status_is_singular(window, qapp, make_pdf):
    open_and_wait(qapp, window, make_pdf(["Uma página só."]))
    assert status(window).startswith("doc.pdf — 1 página")
    assert "páginas" not in status(window)


def test_scanned_pdf_shows_its_pages_and_a_notice(window, qapp, make_pdf, notes):
    window.open_path(make_pdf(["", ""]))
    wait_until(qapp, lambda: notes)
    assert notes == [MSG_NO_TEXT]
    assert not window.play_button.isEnabled()
    assert window.pdf_view.reading is not None  # the pages are still displayed
    assert window.page_label.text() == "Página 1 de 2"


def test_symbols_only_pdf_shows_notice(window, qapp, make_pdf, notes):
    window.open_path(make_pdf(["*** --- ***"]))
    wait_until(qapp, lambda: notes)
    assert notes == [MSG_NO_TEXT]
    assert not window.play_button.isEnabled()


def test_scanned_pdf_replaces_previous_document(window, qapp, make_pdf, notes):
    open_and_wait(qapp, window, make_pdf(["Texto antigo."], name="antigo.pdf"))
    window.open_path(make_pdf([""], name="escaneado.pdf"))
    wait_until(qapp, lambda: notes)
    assert window.reading.text == ""
    assert not window.play_button.isEnabled()
    assert status(window).startswith("escaneado.pdf")


def test_invalid_file_keeps_previous_document(window, qapp, make_pdf, notes, tmp_path):
    open_and_wait(qapp, window, make_pdf(["Texto bom."]))
    before = status(window)
    garbage = tmp_path / "lixo.pdf"
    garbage.write_bytes(b"isto nao e um pdf")
    window.open_path(garbage)
    wait_until(qapp, lambda: notes)
    assert notes == [MSG_INVALID]
    assert window.reading.text == "Texto bom."
    assert window.pdf_view.reading is window.reading
    assert window.play_button.isEnabled()
    assert status(window) == before


def test_last_opened_file_wins(window, qapp, make_pdf):
    first = make_pdf(["Primeiro."], name="a.pdf")
    second = make_pdf(["Segundo."], name="b.pdf")
    window.open_path(first)
    window.open_path(second)
    wait_until(qapp, lambda: window.reading is not None and window.reading.text == "Segundo.")
    deadline = time.monotonic() + 0.1
    while time.monotonic() < deadline:
        qapp.processEvents()
    assert window.reading.text == "Segundo."
    assert status(window).startswith("b.pdf — 1 página")


def test_open_button_loads_the_chosen_file(window, qapp, make_pdf, monkeypatch):
    path = make_pdf(["Escolhido pelo diálogo."])
    monkeypatch.setattr(
        QFileDialog, "getOpenFileName", lambda *args, **kwargs: (str(path), "")
    )
    window.open_button.click()
    wait_until(qapp, lambda: window.play_button.isEnabled())
    assert window.reading.text == "Escolhido pelo diálogo."


def test_cancelled_open_dialog_changes_nothing(window, qapp, monkeypatch, notes):
    monkeypatch.setattr(QFileDialog, "getOpenFileName", lambda *args, **kwargs: ("", ""))
    window.open_button.click()
    qapp.processEvents()
    assert notes == []
    assert window.reading is None


def test_page_label_follows_the_view(window, qapp, make_pdf):
    open_and_wait(qapp, window, make_pdf(["Um.", "Dois.", "Três."]))
    assert window.page_label.text() == "Página 1 de 3"
    window.pdf_view.go_to_page(3)
    assert window.page_label.text() == "Página 3 de 3"


# ---- reading ----------------------------------------------------------------------


def test_reads_the_sentences_of_the_document(window, qapp, make_pdf, synth, out):
    open_and_wait(qapp, window, make_pdf(["Olá mundo. Tudo bem?", "Segunda página."]))
    window.play_button.click()
    wait_until(qapp, lambda: status(window) == "Leitura concluída.")
    assert synth.spoken == ["Olá mundo.", "Tudo bem?", "Segunda página."]
    assert len(out.written) == 3 * len(synth.audio)
    assert out.started_rates == [22050]
    assert window.play_button.text() == PLAY


def test_play_pause_continue_cycle(window, qapp, make_pdf, player, out, synth):
    open_and_wait(qapp, window, make_pdf(["Olá mundo. Tudo bem?"]))
    start_long_playback(qapp, window, player, out, synth)
    assert window.play_button.text() == PAUSE
    assert status(window) == "Lendo — página 1 de 1"

    window.play_button.click()
    assert player.state is PlayerState.PAUSED
    assert window.play_button.text() == CONTINUE
    assert status(window) == "Pausado"
    assert out.suspended

    window.play_button.click()
    assert player.state is PlayerState.PLAYING
    assert window.play_button.text() == PAUSE
    assert status(window) == "Lendo — página 1 de 1"
    assert not out.suspended


def test_status_shows_the_page_being_read(window, qapp, make_pdf, out, synth):
    seen = []
    window.statusBar().messageChanged.connect(seen.append)
    open_and_wait(qapp, window, make_pdf(["Um.", "Dois."]))
    out.free = 4
    synth.audio = SHORT_AUDIO
    window.play_button.click()
    wait_until(qapp, lambda: status(window) == "Leitura concluída.")
    assert "Lendo — página 1 de 2" in seen
    assert "Lendo — página 2 de 2" in seen


def test_space_toggles_exactly_once_with_focus_on_the_play_button(
    window, qapp, make_pdf, player, out, synth
):
    show_active(qapp, window)
    open_and_wait(qapp, window, make_pdf(["Olá mundo. Tudo bem?"]))
    out.free = 4
    synth.audio = LONG_AUDIO
    QTest.mouseClick(window.play_button, LEFT)  # the button now has keyboard focus
    wait_until(qapp, lambda: player.state is PlayerState.PLAYING)
    assert window.play_button.hasFocus()

    QTest.keyClick(window.play_button, Qt.Key.Key_Space)
    assert player.state is PlayerState.PAUSED
    QTest.keyClick(window.play_button, Qt.Key.Key_Space)
    assert player.state is PlayerState.PLAYING
    QTest.keyClick(window.pdf_view, Qt.Key.Key_Space)
    assert player.state is PlayerState.PAUSED


def test_space_does_nothing_without_a_document(window, qapp, player, out):
    show_active(qapp, window)
    QTest.keyClick(window, Qt.Key.Key_Space)
    assert player.state is PlayerState.STOPPED
    assert out.started_rates == []


def test_stop_button_follows_player_state(window, qapp, make_pdf, player, out, synth):
    open_and_wait(qapp, window, make_pdf(["Olá mundo. Tudo bem?"]))
    assert not window.stop_button.isEnabled()
    start_long_playback(qapp, window, player, out, synth)
    assert window.stop_button.isEnabled()
    window.play_button.click()  # pause
    assert window.stop_button.isEnabled()
    window.stop_button.click()
    assert player.state is PlayerState.STOPPED
    assert not window.stop_button.isEnabled()
    assert window.play_button.text() == PLAY
    assert status(window).startswith("doc.pdf — 1 página")


def test_play_after_stop_starts_from_the_beginning(window, qapp, make_pdf, player, out, synth):
    open_and_wait(qapp, window, make_pdf(["Olá mundo. Tudo bem?"]))
    start_long_playback(qapp, window, player, out, synth)
    window.stop_button.click()
    synth.spoken.clear()
    out.free = 1 << 20
    synth.audio = SHORT_AUDIO
    window.play_button.click()
    wait_until(qapp, lambda: status(window) == "Leitura concluída.")
    assert synth.spoken == ["Olá mundo.", "Tudo bem?"]


def test_escape_stops_reading(window, qapp, make_pdf, player, out, synth):
    show_active(qapp, window)
    open_and_wait(qapp, window, make_pdf(["Olá mundo."]))
    start_long_playback(qapp, window, player, out, synth)
    QTest.keyClick(window, Qt.Key.Key_Escape)
    assert player.state is PlayerState.STOPPED


def test_sentence_being_read_is_highlighted_on_the_page(
    window, qapp, make_pdf, player, out, synth
):
    open_and_wait(qapp, window, make_pdf(["Olá mundo. Tudo bem?"]))
    assert window.pdf_view.reading_highlight() is None
    start_long_playback(qapp, window, player, out, synth)
    first = window.reading.sentences[0]
    assert window.pdf_view.reading_highlight() == (first.start, first.end)
    window.play_button.click()  # pause: the highlight stays
    assert window.pdf_view.reading_highlight() == (first.start, first.end)
    window.stop_button.click()
    assert window.pdf_view.reading_highlight() is None


def test_highlight_clears_when_reading_finishes(window, qapp, make_pdf):
    open_and_wait(qapp, window, make_pdf(["Olá mundo."]))
    window.play_button.click()
    wait_until(qapp, lambda: status(window) == "Leitura concluída.")
    assert window.pdf_view.reading_highlight() is None


def test_view_follows_the_reading_to_later_pages(window, qapp, make_pdf, out, synth):
    open_and_wait(qapp, window, make_pdf(["Um.", "Dois.", "Três."]))
    pages = []
    window.pdf_view.page_changed.connect(pages.append)
    out.free = 4
    synth.audio = SHORT_AUDIO
    window.play_button.click()
    wait_until(qapp, lambda: status(window) == "Leitura concluída.")
    assert pages[-1] == 3


def test_opening_another_pdf_stops_playback(window, qapp, make_pdf, player, out, synth):
    open_and_wait(qapp, window, make_pdf(["Primeiro documento."], name="a.pdf"))
    start_long_playback(qapp, window, player, out, synth)
    window.open_path(make_pdf(["Segundo documento."], name="b.pdf"))
    assert player.state is PlayerState.STOPPED
    wait_until(qapp, lambda: window.reading.text == "Segundo documento.")
    assert window.play_button.text() == PLAY
    assert window.pdf_view.reading_highlight() is None
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
        wait_until(qapp, lambda: status(window) == "Leitura concluída.")
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


# ---- voices -------------------------------------------------------------------------


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
    wait_until(qapp, lambda: status(window) == "Leitura concluída.")
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


# ---- closing --------------------------------------------------------------------------


def test_closing_the_window_stops_everything(window, qapp, make_pdf, player, out, synth):
    open_and_wait(qapp, window, make_pdf(["Olá mundo."]))
    start_long_playback(qapp, window, player, out, synth)
    window.close()
    assert player.state is PlayerState.STOPPED
    assert threads_named("leitorpdf-synth") == []
    assert threads_named("leitorpdf-render") == []


# ---- where to start, reading a passage, speed (words: Um dois. Três quatro. | Cinco seis.) ----

NONE = Qt.KeyboardModifier.NoModifier
READ_HERE = "▶ Ler daqui"
READ_SELECTION = "▶ Ler seleção"
HINT = "clique no texto para escolher onde começar; arraste para ler só um trecho"


@pytest.fixture
def shown(window, qapp, make_pdf):
    """A visible window with a two-page document open."""
    show_active(qapp, window)
    open_and_wait(qapp, window, make_pdf(["Um dois. Três quatro.", "Cinco seis."]))
    return window


def word_center(window, index):
    word = window.reading.words[index]
    return window.pdf_view.to_view(
        word.page, (word.rect[0] + word.rect[2]) / 2, (word.rect[1] + word.rect[3]) / 2
    )


def click_word(window, index):
    QTest.mouseClick(window.pdf_view.viewport(), LEFT, NONE, word_center(window, index))


def click_blank(window):
    QTest.mouseClick(window.pdf_view.viewport(), LEFT, NONE, window.pdf_view.to_view(0, 300, 500))


def drag_words(window, first, last):
    viewport = window.pdf_view.viewport()
    start, end = word_center(window, first), word_center(window, last)
    QTest.mousePress(viewport, LEFT, NONE, start)
    QTest.mouseMove(viewport, (start + end) / 2)
    QTest.mouseMove(viewport, end)
    QTest.mouseRelease(viewport, LEFT, NONE, end)


def sentence_range(window, index):
    sentence = window.reading.sentences[index]
    return sentence.start, sentence.end


def read_to_the_end(qapp, window):
    window.play_button.click()
    wait_until(qapp, lambda: status(window) == "Leitura concluída.")


def test_status_has_the_hint_after_opening(shown):
    assert status(shown) == f"doc.pdf — 2 páginas · {HINT}"


def test_click_sets_the_start_point(shown, qapp, synth):
    click_word(shown, 2)
    assert shown.pdf_view.start_marker() == sentence_range(shown, 1)
    assert shown.play_button.text() == READ_HERE
    read_to_the_end(qapp, shown)
    assert synth.spoken == ["Três quatro.", "Cinco seis."]
    assert shown.pdf_view.start_marker() == sentence_range(shown, 1)  # kept for next time


def test_click_while_reading_jumps_there(shown, qapp, player, out, synth):
    start_long_playback(qapp, shown, player, out, synth)
    assert shown.pdf_view.reading_highlight() == sentence_range(shown, 0)
    click_word(shown, 3)
    wait_until(qapp, lambda: shown.pdf_view.reading_highlight() == sentence_range(shown, 1))
    assert player.state is PlayerState.PLAYING
    assert shown.pdf_view.start_marker() == sentence_range(shown, 1)


def test_click_while_paused_stops_and_sets_the_start_point(shown, qapp, player, out, synth):
    start_long_playback(qapp, shown, player, out, synth)
    shown.play_button.click()  # pause
    click_word(shown, 2)
    assert player.state is PlayerState.STOPPED
    assert shown.play_button.text() == READ_HERE


def test_double_click_starts_reading_from_there(shown, qapp, player, out, synth):
    out.free = 4
    synth.audio = LONG_AUDIO
    QTest.mouseDClick(shown.pdf_view.viewport(), LEFT, NONE, word_center(shown, 2))
    wait_until(qapp, lambda: shown.pdf_view.reading_highlight() == sentence_range(shown, 1))
    assert synth.spoken[0] == "Três quatro."
    assert player.state is PlayerState.PLAYING


def test_selection_is_read_alone(shown, qapp, synth):
    drag_words(shown, 1, 2)
    assert shown.pdf_view.selected_text() == "dois. Três"
    assert shown.play_button.text() == READ_SELECTION
    read_to_the_end(qapp, shown)
    assert synth.spoken == ["dois.", "Três"]
    assert shown.pdf_view.selection() is not None  # still selected afterwards


def test_selection_wins_over_the_start_point(shown, qapp, synth):
    click_word(shown, 4)
    drag_words(shown, 0, 1)
    assert shown.play_button.text() == READ_SELECTION
    read_to_the_end(qapp, shown)
    assert synth.spoken == ["Um dois."]


def test_highlight_follows_the_pieces_of_a_selection(shown, qapp, player, out, synth):
    drag_words(shown, 1, 2)
    start_long_playback(qapp, shown, player, out, synth)
    words = shown.reading.words
    assert shown.pdf_view.reading_highlight() == (words[1].start, words[1].end)


def test_background_click_clears_selection_and_start_point(shown):
    click_word(shown, 2)
    drag_words(shown, 0, 1)
    click_blank(shown)
    assert shown.pdf_view.selection() is None
    assert shown.pdf_view.start_marker() is None
    assert shown.play_button.text() == PLAY


def test_escape_clears_selection_then_start_point_when_stopped(shown):
    click_word(shown, 2)
    drag_words(shown, 0, 1)
    QTest.keyClick(shown, Qt.Key.Key_Escape)
    assert shown.pdf_view.selection() is None
    assert shown.pdf_view.start_marker() == sentence_range(shown, 1)
    assert shown.play_button.text() == READ_HERE
    QTest.keyClick(shown, Qt.Key.Key_Escape)
    assert shown.pdf_view.start_marker() is None
    assert shown.play_button.text() == PLAY


def test_new_document_forgets_start_point_and_selection(shown, qapp, make_pdf):
    click_word(shown, 2)
    shown.open_path(make_pdf(["Outro texto."], name="outro.pdf"))
    wait_until(qapp, lambda: shown.reading.text == "Outro texto.")
    assert shown.pdf_view.start_marker() is None
    assert shown.play_button.text() == PLAY
    read_to_the_end(qapp, shown)


def test_copy_puts_the_selection_on_the_clipboard(shown, qapp):
    qapp.clipboard().setText("antes")
    drag_words(shown, 1, 2)
    QTest.keyClick(shown, Qt.Key.Key_C, Qt.KeyboardModifier.ControlModifier)
    assert qapp.clipboard().text() == "dois. Três"


def test_context_menu_offers_what_applies(shown):
    def actions(word):
        return [action.text() for action in shown.build_context_menu(word).actions()]

    assert actions(-1) == []
    assert actions(2) == ["Ler a partir daqui"]
    drag_words(shown, 1, 2)
    assert actions(2) == ["Ler a partir daqui", "Ler seleção", "Copiar"]
    assert actions(-1) == ["Ler seleção", "Copiar"]


def test_context_menu_read_from_here(shown, qapp, synth):
    menu = shown.build_context_menu(4)
    menu.actions()[0].trigger()
    wait_until(qapp, lambda: status(shown) == "Leitura concluída.")
    assert synth.spoken == ["Cinco seis."]


def test_context_menu_read_selection(shown, qapp, synth):
    drag_words(shown, 2, 3)
    menu = shown.build_context_menu(-1)
    menu.actions()[0].trigger()
    wait_until(qapp, lambda: status(shown) == "Leitura concluída.")
    assert synth.spoken == ["Três quatro."]


def test_speed_label_and_range(window):
    assert window.speed_slider.value() == 10
    assert window.speed_label.text() == "1,0×"
    assert (window.speed_slider.minimum(), window.speed_slider.maximum()) == (5, 20)
    window.speed_slider.setValue(15)
    assert window.speed_label.text() == "1,5×"
    window.speed_slider.setValue(5)
    assert window.speed_label.text() == "0,5×"


def test_speed_is_passed_to_the_synthesizer(shown, qapp, synth):
    shown.speed_slider.setValue(20)
    read_to_the_end(qapp, shown)
    assert synth.scales == [0.5, 0.5, 0.5]


def test_changing_speed_while_reading_applies_to_following_sentences(
    shown, qapp, player, out, synth
):
    start_long_playback(qapp, shown, player, out, synth)
    assert set(synth.scales) == {1.0}
    before = len(synth.spoken)
    shown.speed_slider.setValue(18)
    shown.speed_slider.setValue(20)  # two quick changes: one re-synthesis
    wait_until(qapp, lambda: 0.5 in synth.scales)
    assert player.state is PlayerState.PLAYING
    assert shown.pdf_view.reading_highlight() == sentence_range(shown, 0)  # not restarted
    again = synth.spoken[before:]
    assert again[0] == "Três quatro."  # the sentence after the one being heard
    assert 10 / 18 not in synth.scales


def test_speed_shortcuts(shown):
    QTest.keyClick(shown, Qt.Key.Key_Plus)
    assert shown.speed_slider.value() == 11
    QTest.keyClick(shown, Qt.Key.Key_Equal)
    assert shown.speed_slider.value() == 12
    QTest.keyClick(shown, Qt.Key.Key_Minus)
    assert shown.speed_slider.value() == 11
    shown.speed_slider.setValue(20)
    QTest.keyClick(shown, Qt.Key.Key_Plus)
    assert shown.speed_slider.value() == 20
    shown.speed_slider.setValue(5)
    QTest.keyClick(shown, Qt.Key.Key_Minus)
    assert shown.speed_slider.value() == 5


# ---- page range, zoom, drag and drop ------------------------------------------------

from PySide6.QtCore import QMimeData, QPointF, QUrl  # noqa: E402
from PySide6.QtGui import QDragEnterEvent, QDropEvent  # noqa: E402
from PySide6.QtWidgets import QApplication  # noqa: E402

from leitorpdf.ui.messages import MSG_EMPTY_RANGE  # noqa: E402

CTRL = Qt.KeyboardModifier.ControlModifier


def page_range(window):
    return window.first_page_spin.value(), window.last_page_spin.value()


def drop(window, urls=(), text=None):
    """Drag something onto the window; returns whether the window accepted it."""
    mime = QMimeData()
    if urls:
        mime.setUrls(list(urls))
    if text is not None:
        mime.setText(text)
    copy = Qt.DropAction.CopyAction
    enter = QDragEnterEvent(QPointF(60, 200), copy, mime, LEFT, NONE)
    QApplication.sendEvent(window, enter)
    if not enter.isAccepted():
        return False
    QApplication.sendEvent(window, QDropEvent(QPointF(60, 200), copy, mime, LEFT, NONE))
    return True


def test_page_range_is_disabled_without_a_document(window):
    assert not window.first_page_spin.isEnabled()
    assert not window.last_page_spin.isEnabled()


def test_page_range_defaults_to_the_whole_document(window, qapp, make_pdf):
    open_and_wait(qapp, window, make_pdf(["Um.", "Dois.", "Três."]))
    assert page_range(window) == (1, 3)
    assert window.first_page_spin.isEnabled() and window.last_page_spin.isEnabled()
    for spin in (window.first_page_spin, window.last_page_spin):
        assert (spin.minimum(), spin.maximum()) == (1, 3)


def test_reads_only_the_selected_pages(window, qapp, make_pdf, synth):
    open_and_wait(qapp, window, make_pdf(["Um.", "Dois.", "Três."]))
    window.first_page_spin.setValue(2)
    read_to_the_end(qapp, window)
    assert synth.spoken == ["Dois.", "Três."]
    synth.spoken.clear()
    window.last_page_spin.setValue(2)
    read_to_the_end(qapp, window)
    assert synth.spoken == ["Dois."]


def test_first_page_never_exceeds_last(window, qapp, make_pdf):
    open_and_wait(qapp, window, make_pdf(["Um.", "Dois.", "Três."]))
    window.last_page_spin.setValue(2)
    window.first_page_spin.setValue(3)
    assert page_range(window) == (3, 3)
    window.last_page_spin.setValue(1)
    assert page_range(window) == (1, 1)


def test_changing_the_range_stops_playback_and_clears_the_start_point(
    shown, qapp, player, out, synth
):
    click_word(shown, 2)
    start_long_playback(qapp, shown, player, out, synth)
    shown.last_page_spin.setValue(1)
    assert player.state is PlayerState.STOPPED
    assert shown.pdf_view.start_marker() is None
    assert shown.play_button.text() == PLAY


def test_range_without_text_shows_notice(window, qapp, make_pdf, notes, player):
    open_and_wait(qapp, window, make_pdf(["Um.", "", "Três."]))
    window.first_page_spin.setValue(2)
    window.last_page_spin.setValue(2)
    window.play_button.click()
    assert notes == [MSG_EMPTY_RANGE]
    assert player.state is PlayerState.STOPPED


def test_start_point_inside_the_range_is_used(shown, qapp, synth):
    shown.last_page_spin.setValue(1)
    click_word(shown, 2)
    assert page_range(shown) == (1, 1)
    read_to_the_end(qapp, shown)
    assert synth.spoken == ["Três quatro."]


def test_click_before_the_range_moves_its_start(shown):
    shown.first_page_spin.setValue(2)
    click_word(shown, 0)
    assert page_range(shown) == (1, 2)
    assert shown.pdf_view.start_marker() == sentence_range(shown, 0)


def test_click_after_the_range_moves_it_there(shown, qapp, synth):
    shown.last_page_spin.setValue(1)
    shown.pdf_view.go_to_page(2)
    click_word(shown, 4)
    assert page_range(shown) == (2, 2)
    assert shown.pdf_view.start_marker() == sentence_range(shown, 2)
    read_to_the_end(qapp, shown)
    assert synth.spoken == ["Cinco seis."]


def test_new_document_resets_the_range(window, qapp, make_pdf):
    open_and_wait(qapp, window, make_pdf(["Um.", "Dois.", "Três."], name="a.pdf"))
    window.first_page_spin.setValue(2)
    window.open_path(make_pdf(["Só.", "Duas."], name="b.pdf"))
    wait_until(qapp, lambda: window.reading.page_count == 2)
    assert page_range(window) == (1, 2)
    assert window.last_page_spin.maximum() == 2


def test_zoom_controls_need_a_document(window):
    assert window.zoom_label.text() == ""
    assert not window.zoom_in_button.isEnabled()
    assert not window.zoom_out_button.isEnabled()
    assert not window.fit_button.isEnabled()


def test_zoom_buttons_and_label(shown):
    view = shown.pdf_view

    def percent():
        return f"{round(view.zoom() / (96 / 72) * 100)}%"

    start = view.zoom()
    assert shown.zoom_label.text() == percent()
    shown.zoom_in_button.click()
    assert abs(view.zoom() - start * 1.25) < 0.001
    assert shown.zoom_label.text() == percent()
    shown.zoom_out_button.click()
    shown.zoom_out_button.click()
    assert abs(view.zoom() - start / 1.25) < 0.001
    assert shown.zoom_label.text() == percent()
    shown.fit_button.click()
    assert view.is_fit_width()
    assert abs(view.zoom() - start) < 0.001


def test_zoom_shortcuts(shown):
    view = shown.pdf_view
    start = view.zoom()
    QTest.keyClick(shown, Qt.Key.Key_Plus, CTRL)
    assert view.zoom() > start
    QTest.keyClick(shown, Qt.Key.Key_0, CTRL)
    assert view.is_fit_width()
    QTest.keyClick(shown, Qt.Key.Key_Minus, CTRL)
    assert view.zoom() < start
    assert shown.speed_slider.value() == 10  # the plain + and - keys are for speed


def test_dropping_a_pdf_opens_it(window, qapp, make_pdf):
    path = make_pdf(["Arrastado e solto."])
    assert drop(window, [QUrl.fromLocalFile(str(path))])
    wait_until(qapp, lambda: window.reading is not None)
    assert window.reading.text == "Arrastado e solto."


def test_dropping_several_files_opens_the_first(window, qapp, make_pdf):
    first = make_pdf(["Primeiro."], name="a.pdf")
    second = make_pdf(["Segundo."], name="b.pdf")
    assert drop(window, [QUrl.fromLocalFile(str(first)), QUrl.fromLocalFile(str(second))])
    wait_until(qapp, lambda: window.reading is not None)
    assert window.reading.text == "Primeiro."


def test_dropping_a_web_link_or_text_is_ignored(window, qapp, notes):
    assert not drop(window, [QUrl("https://example.com/arquivo.pdf")])
    assert not drop(window, text="apenas um texto")
    qapp.processEvents()
    assert window.reading is None
    assert notes == []


def test_dropping_a_non_pdf_reports_and_keeps_the_document(
    window, qapp, make_pdf, notes, tmp_path
):
    open_and_wait(qapp, window, make_pdf(["Texto bom."]))
    picture = tmp_path / "foto.png"
    picture.write_bytes(b"\x89PNG\r\n\x1a\n" + b"\x00" * 32)
    assert drop(window, [QUrl.fromLocalFile(str(picture))])
    wait_until(qapp, lambda: notes)
    assert notes == [MSG_INVALID]
    assert window.reading.text == "Texto bom."


def test_dropping_on_the_page_area_reaches_the_window(shown, qapp, make_pdf):
    path = make_pdf(["Solto sobre a página."], name="novo.pdf")
    mime = QMimeData()
    mime.setUrls([QUrl.fromLocalFile(str(path))])
    viewport = shown.pdf_view.viewport()
    assert not viewport.acceptDrops() and shown.acceptDrops()
    copy = Qt.DropAction.CopyAction
    spot = QPointF(viewport.rect().center())
    enter = QDragEnterEvent(spot, copy, mime, LEFT, NONE)
    QApplication.sendEvent(viewport, enter)  # travels up to the window
    assert enter.isAccepted()
    QApplication.sendEvent(viewport, QDropEvent(spot, copy, mime, LEFT, NONE))
    wait_until(qapp, lambda: shown.reading.text == "Solto sobre a página.")


def test_typing_a_page_number_applies_it_whole(window, qapp, make_pdf, player, out, synth):
    # Regression: each keystroke used to count as a new value, so typing "25"
    # passed through "2" and dragged the first page down with it.
    show_active(qapp, window)
    open_and_wait(qapp, window, make_pdf([f"Página {n}." for n in range(1, 31)]))
    window.first_page_spin.setValue(10)
    start_long_playback(qapp, window, player, out, synth)
    spin = window.last_page_spin
    spin.setFocus()
    spin.selectAll()
    QTest.keyClicks(spin, "25")
    assert page_range(window) == (10, 30)  # nothing applied while typing
    assert player.state is PlayerState.PLAYING
    QTest.keyClick(spin, Qt.Key.Key_Return)
    assert page_range(window) == (10, 25)
    assert player.state is PlayerState.STOPPED
