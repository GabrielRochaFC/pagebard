"""The main window: the PDF on screen, read aloud."""

from collections.abc import Callable
from pathlib import Path
from typing import Any

from PySide6.QtCore import QStandardPaths, Qt, QTimer
from PySide6.QtGui import (
    QCloseEvent,
    QDragEnterEvent,
    QDropEvent,
    QGuiApplication,
    QKeySequence,
    QShortcut,
)
from PySide6.QtWidgets import (
    QComboBox,
    QFileDialog,
    QHBoxLayout,
    QLabel,
    QMainWindow,
    QMenu,
    QMessageBox,
    QPushButton,
    QSlider,
    QSpinBox,
    QVBoxLayout,
    QWidget,
)

from leitorpdf.core import paths
from leitorpdf.core.errors import LeitorError, user_message
from leitorpdf.core.export import ExportCancelled, export_mp3
from leitorpdf.core.pdf import PdfText, load_pdf
from leitorpdf.core.reading import Reading, build_reading
from leitorpdf.core.segmenter import Sentence
from leitorpdf.core.tts import Synthesizer
from leitorpdf.core.voices import DEFAULT_VOICE_KEY, Voice, installed_voices
from leitorpdf.playback.player import Player, PlayerState
from leitorpdf.ui.messages import (
    APP_NAME,
    MSG_EMPTY_RANGE,
    MSG_NEED_VOICE,
    MSG_NO_TEXT,
    show_error,
)
from leitorpdf.ui.pdf_view import PdfView
from leitorpdf.ui.progress import run_with_progress
from leitorpdf.ui.tasks import run_async
from leitorpdf.ui.voice_download import download_default_voice
from leitorpdf.ui.voice_manager import VoiceManagerDialog

_HINT = "clique no texto para escolher onde começar; arraste para ler só um trecho"
_SPEED_MIN, _SPEED_MAX, _SPEED_DEFAULT = 5, 20, 10  # tenths: 0,5× to 2,0×
_SPEED_SETTLE_MS = 250  # wait for the slider to stop before re-synthesizing
_POINTS_PER_PIXEL_AT_100 = 96 / 72  # zoom shown as 100% means 96 dpi
_PLAY_TEXT = {
    PlayerState.LOADING: "⏸ Pausar",
    PlayerState.PLAYING: "⏸ Pausar",
    PlayerState.PAUSED: "▶ Continuar",
}
_STYLE = """
#header { border-bottom: 1px solid palette(mid); }
#header QPushButton {
    padding: 6px 14px;
    border: 1px solid palette(mid);
    border-radius: 6px;
    background: palette(button);
}
#header QPushButton:hover { background: palette(light); }
#header QPushButton:pressed { background: palette(midlight); }
#header QPushButton:focus { border: 2px solid #2563EB; padding: 5px 13px; }
#header QPushButton:disabled { color: palette(mid); }
#header QPushButton#playButton {
    background: #2563EB;
    border-color: #1D4ED8;
    color: white;
    font-weight: 600;
}
#header QPushButton#playButton:hover { background: #1D4ED8; }
#header QPushButton#playButton:focus { border: 2px solid palette(text); }
#header QPushButton#playButton:disabled {
    background: palette(button);
    border-color: palette(mid);
    color: palette(mid);
}
"""


class _Speech:
    """What the synthesis thread calls. Plain on purpose: nothing from Qt."""

    def __init__(self, synth: Any) -> None:
        self.synth = synth
        self.length_scale = 1.0

    def speak(self, text: str) -> bytes:
        return self.synth.synthesize(text, length_scale=self.length_scale)


def _load(path: Path) -> tuple[PdfText, Reading]:
    doc = load_pdf(path)
    return doc, build_reading(doc)


class MainWindow(QMainWindow):
    def __init__(
        self,
        player: Player | None = None,
        voices_dir: Path | None = None,
        notify: Callable[[str], None] | None = None,
        synth_factory: Callable[[Voice], Any] | None = None,
        offer_download: bool = True,
        voice_manager: Callable[[QWidget], Any] | None = None,
        exporter: Callable[..., None] = export_mp3,
    ) -> None:
        super().__init__()
        self._exporter = exporter
        self._doc_path: Path | None = None
        self._player = player if player is not None else Player(parent=self)
        self._voices_dir = voices_dir if voices_dir is not None else paths.voices_dir()
        self._notify = notify or (lambda text: show_error(self, text))
        self._synth_factory = synth_factory or (lambda voice: Synthesizer(voice.path))
        self._voice_manager = voice_manager or (
            lambda parent: VoiceManagerDialog(
                self._voices_dir, paths.data_dir() / "voices.json", parent
            )
        )
        self._speech: _Speech | None = None
        self._speech_key: str | None = None
        self._reading: Reading | None = None
        self._playing: list[Sentence] = []  # what the player is reading now
        self._start_sentence: int | None = None  # where "play" begins, if chosen
        self._length_scale = 1.0
        self._adjusting_range = False  # page spins being set by the program
        self._doc_status = ""
        self._reading_status = ""
        self._load_id = 0  # lets a newer "open" supersede one still loading
        self._last_dir = QStandardPaths.writableLocation(
            QStandardPaths.StandardLocation.DocumentsLocation
        )

        self._build_ui()
        self._player.state_changed.connect(self._on_state_changed)
        self._player.sentence_started.connect(self._on_sentence_started)
        self._player.finished.connect(self._on_finished)
        self._player.error.connect(self._notify)
        self.pdf_view.page_changed.connect(self._update_page_label)
        self.pdf_view.word_clicked.connect(self._on_word_clicked)
        self.pdf_view.word_double_clicked.connect(self._on_word_double_clicked)
        self.pdf_view.background_clicked.connect(self._clear_start_point)
        self.pdf_view.selection_changed.connect(self._on_selection_changed)
        self.pdf_view.context_requested.connect(self._on_context_requested)
        self.pdf_view.zoom_changed.connect(self._update_zoom_controls)
        self._reload_voices()
        self._reset_page_range()
        self._update_zoom_controls()
        self.setAcceptDrops(True)
        self._show_state(self._player.state)

        if offer_download and self.voice_combo.count() == 0:
            QTimer.singleShot(0, self._offer_voice_download)

    @property
    def reading(self) -> Reading | None:
        return self._reading

    # ---- construction ----------------------------------------------------

    def _build_ui(self) -> None:
        self.setWindowTitle(APP_NAME)
        self.resize(1100, 800)
        self.setMinimumSize(760, 520)
        self.setStyleSheet(_STYLE)

        self.open_button = QPushButton("Abrir PDF…")
        self.open_button.setShortcut(QKeySequence("Ctrl+O"))
        self.open_button.setToolTip("Abrir um arquivo PDF (Ctrl+O)")
        self.open_button.clicked.connect(self._choose_file)

        self.play_button = QPushButton()
        self.play_button.setObjectName("playButton")
        self.play_button.setMinimumWidth(160)
        self.play_button.setToolTip("Ler em voz alta ou pausar (Espaço)")
        self.play_button.setEnabled(False)
        self.play_button.clicked.connect(self._on_play_clicked)

        self.stop_button = QPushButton("⏹ Parar")
        self.stop_button.setToolTip("Parar a leitura (Esc)")
        self.stop_button.clicked.connect(self._player.stop)

        self.export_button = QPushButton("Exportar MP3…")
        self.export_button.setToolTip("Gravar a leitura das páginas escolhidas num arquivo MP3")
        self.export_button.setEnabled(False)
        self.export_button.clicked.connect(self._export)

        voice_label = QLabel("Voz:")
        self.voice_combo = QComboBox()
        self.voice_combo.setMinimumWidth(240)
        self.voice_combo.setAccessibleName("Voz")
        self.voice_combo.setToolTip("Voz usada na leitura")
        self.voice_combo.currentIndexChanged.connect(self._on_voice_changed)
        voice_label.setBuddy(self.voice_combo)
        self.voices_button = QPushButton("Vozes…")
        self.voices_button.setToolTip("Baixar ou remover vozes")
        self.voices_button.clicked.connect(self._open_voice_manager)

        row1 = QHBoxLayout()
        row1.setSpacing(8)
        row1.addWidget(self.open_button)
        row1.addSpacing(12)
        row1.addWidget(self.play_button)
        row1.addWidget(self.stop_button)
        row1.addWidget(self.export_button)
        row1.addStretch(1)
        row1.addWidget(voice_label)
        row1.addWidget(self.voice_combo)
        row1.addWidget(self.voices_button)

        speed_title = QLabel("Velocidade:")
        self.speed_slider = QSlider(Qt.Orientation.Horizontal)
        self.speed_slider.setRange(_SPEED_MIN, _SPEED_MAX)
        self.speed_slider.setValue(_SPEED_DEFAULT)
        self.speed_slider.setPageStep(1)
        self.speed_slider.setFixedWidth(150)
        self.speed_slider.setAccessibleName("Velocidade")
        self.speed_slider.setToolTip("Velocidade da leitura (teclas + e -)")
        self.speed_slider.valueChanged.connect(self._on_speed_changed)
        speed_title.setBuddy(self.speed_slider)
        self.speed_label = QLabel()
        self.speed_label.setMinimumWidth(36)
        self._speed_timer = QTimer(self)
        self._speed_timer.setSingleShot(True)
        self._speed_timer.setInterval(_SPEED_SETTLE_MS)
        self._speed_timer.timeout.connect(self._player.resynthesize_upcoming)

        self._row2 = QHBoxLayout()
        self._row2.setSpacing(8)
        self._row2.addWidget(speed_title)
        self._row2.addWidget(self.speed_slider)
        self._row2.addWidget(self.speed_label)
        self._on_speed_changed(self.speed_slider.value())

        pages_title = QLabel("Páginas:")
        self.first_page_spin = QSpinBox()
        self.first_page_spin.setAccessibleName("Primeira página a ler")
        self.first_page_spin.setToolTip("Primeira página a ler")
        self.last_page_spin = QSpinBox()
        self.last_page_spin.setAccessibleName("Última página a ler")
        self.last_page_spin.setToolTip("Última página a ler")
        for spin in (self.first_page_spin, self.last_page_spin):
            spin.setMinimumWidth(64)
            # Apply a typed number when it is complete (Enter or leaving the
            # field), not digit by digit: "25" must not pass through "2".
            spin.setKeyboardTracking(False)
        self.first_page_spin.valueChanged.connect(self._on_first_page_changed)
        self.last_page_spin.valueChanged.connect(self._on_last_page_changed)
        pages_title.setBuddy(self.first_page_spin)
        self._row2.addSpacing(16)
        self._row2.addWidget(pages_title)
        self._row2.addWidget(self.first_page_spin)
        self._row2.addWidget(QLabel("a"))
        self._row2.addWidget(self.last_page_spin)
        self._row2.addStretch(1)

        self.zoom_out_button = QPushButton("−")
        self.zoom_out_button.setToolTip("Diminuir a página (Ctrl+-)")
        self.zoom_out_button.setAccessibleName("Diminuir a página")
        self.zoom_in_button = QPushButton("+")
        self.zoom_in_button.setToolTip("Aumentar a página (Ctrl++)")
        self.zoom_in_button.setAccessibleName("Aumentar a página")
        self.zoom_label = QLabel()
        self.zoom_label.setMinimumWidth(44)
        self.zoom_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.fit_button = QPushButton("Ajustar à largura")
        self.fit_button.setToolTip("Ajustar a página à largura da janela (Ctrl+0)")
        self._row2.addWidget(self.zoom_out_button)
        self._row2.addWidget(self.zoom_label)
        self._row2.addWidget(self.zoom_in_button)
        self._row2.addWidget(self.fit_button)

        header = QWidget()
        header.setObjectName("header")
        header_layout = QVBoxLayout(header)
        header_layout.setContentsMargins(12, 10, 12, 10)
        header_layout.setSpacing(8)
        header_layout.addLayout(row1)
        header_layout.addLayout(self._row2)

        self.pdf_view = PdfView()
        self.zoom_out_button.clicked.connect(self.pdf_view.zoom_out)
        self.zoom_in_button.clicked.connect(self.pdf_view.zoom_in)
        self.fit_button.clicked.connect(self._fit_width)

        central = QWidget()
        layout = QVBoxLayout(central)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(0)
        layout.addWidget(header)
        layout.addWidget(self.pdf_view, 1)
        self.setCentralWidget(central)

        self.page_label = QLabel()
        self.statusBar().addPermanentWidget(self.page_label)

        # Window-wide keys. Space is not a button shortcut on purpose: a focused
        # button would also "click" on the key release and toggle twice.
        space = QShortcut(QKeySequence(Qt.Key.Key_Space), self)
        space.setAutoRepeat(False)
        space.activated.connect(self._on_space)
        escape = QShortcut(QKeySequence(Qt.Key.Key_Escape), self)
        escape.setAutoRepeat(False)
        escape.activated.connect(self._on_escape)
        for keys, step in (("+", 1), ("=", 1), ("-", -1)):
            shortcut = QShortcut(QKeySequence(keys), self)
            shortcut.activated.connect(lambda step=step: self._nudge_speed(step))
        copy = QShortcut(QKeySequence(QKeySequence.StandardKey.Copy), self)
        copy.activated.connect(self._copy_selection)
        for keys, action in (
            ("Ctrl++", self.pdf_view.zoom_in),
            ("Ctrl+=", self.pdf_view.zoom_in),
            ("Ctrl+-", self.pdf_view.zoom_out),
            ("Ctrl+0", self._fit_width),
        ):
            QShortcut(QKeySequence(keys), self).activated.connect(action)

    # ---- opening a document ------------------------------------------------

    def _choose_file(self) -> None:
        path, _ = QFileDialog.getOpenFileName(
            self,
            "Abrir PDF",
            self._last_dir,
            "Documentos PDF (*.pdf);;Todos os arquivos (*)",
        )
        if path:
            self.open_path(path)

    def open_path(self, path: str | Path) -> None:
        """Load a PDF in the background and show it."""
        path = Path(path)
        self._player.stop()
        self._last_dir = str(path.parent)
        self._load_id += 1
        load_id = self._load_id
        self.statusBar().showMessage("Abrindo PDF…")
        run_async(
            lambda: _load(path),
            lambda loaded: self._on_loaded(load_id, *loaded),
            lambda exc: self._on_load_failed(load_id, exc),
        )

    def _on_loaded(self, load_id: int, doc: PdfText, reading: Reading) -> None:
        if load_id != self._load_id:
            return
        self._player.stop()
        self._reading = reading
        self._playing = []
        self._start_sentence = None
        self.pdf_view.set_document(doc.path, reading)
        self._doc_path = doc.path
        self._reset_page_range()
        self._update_zoom_controls()
        self.play_button.setEnabled(bool(reading.sentences))
        self.export_button.setEnabled(bool(reading.sentences))
        count = reading.page_count
        self._doc_status = f"{doc.path.name} — {count} página{'' if count == 1 else 's'}"
        if reading.sentences:
            self._doc_status += f" · {_HINT}"
        self.statusBar().showMessage(self._doc_status)
        self._update_page_label()
        self._show_state(self._player.state)
        if not reading.sentences:
            self._notify(MSG_NO_TEXT)

    def _on_load_failed(self, load_id: int, exc: Exception) -> None:
        if load_id != self._load_id:
            return
        self.statusBar().showMessage(self._doc_status)
        self._notify(user_message(exc))

    def _update_page_label(self, _page: int = 0) -> None:
        page = self.pdf_view.current_page()
        if self._reading is None or page == 0:
            self.page_label.setText("")
        else:
            self.page_label.setText(f"Página {page} de {self._reading.page_count}")

    # ---- page range, zoom, drag and drop ---------------------------------------

    def _reset_page_range(self) -> None:
        count = self._reading.page_count if self._reading is not None else 1
        readable = self._reading is not None and bool(self._reading.sentences)
        self._adjusting_range = True
        for spin, value in ((self.first_page_spin, 1), (self.last_page_spin, count)):
            spin.setRange(1, count)
            spin.setValue(value)
            spin.setEnabled(readable)
        self._adjusting_range = False

    def _set_page_range(self, first: int, last: int) -> None:
        """Change the spins without it counting as the user editing them."""
        self._adjusting_range = True
        self.first_page_spin.setValue(first)
        self.last_page_spin.setValue(last)
        self._adjusting_range = False

    def _on_first_page_changed(self, value: int) -> None:
        if self._adjusting_range:
            return
        self._set_page_range(value, max(value, self.last_page_spin.value()))
        self._on_range_edited()

    def _on_last_page_changed(self, value: int) -> None:
        if self._adjusting_range:
            return
        self._set_page_range(min(value, self.first_page_spin.value()), value)
        self._on_range_edited()

    def _on_range_edited(self) -> None:
        self._player.stop()
        chosen = self._start_sentence
        if chosen is not None and self._reading is not None:
            page = self._reading.sentence_page(chosen) + 1
            if not self.first_page_spin.value() <= page <= self.last_page_spin.value():
                self._clear_start_point()

    def _fit_width(self) -> None:
        self.pdf_view.fit_width()
        self._update_zoom_controls()

    def _update_zoom_controls(self, _zoom: float = 0.0) -> None:
        has_document = self._reading is not None
        for button in (self.zoom_out_button, self.zoom_in_button, self.fit_button):
            button.setEnabled(has_document)
        if has_document:
            percent = round(self.pdf_view.zoom() / _POINTS_PER_PIXEL_AT_100 * 100)
            self.zoom_label.setText(f"{percent}%")
        else:
            self.zoom_label.setText("")

    def dragEnterEvent(self, event: QDragEnterEvent) -> None:
        if _first_local_file(event) is not None:
            event.acceptProposedAction()

    def dropEvent(self, event: QDropEvent) -> None:
        path = _first_local_file(event)
        if path is not None:
            event.acceptProposedAction()
            self.open_path(path)

    # ---- voices --------------------------------------------------------------

    def _reload_voices(self, select_key: str | None = None) -> None:
        voices = installed_voices(self._voices_dir)
        self.voice_combo.blockSignals(True)
        self.voice_combo.clear()
        for voice in voices:
            self.voice_combo.addItem(voice.label, voice)
        self.voice_combo.setCurrentIndex(_preferred_index(voices, select_key))
        self.voice_combo.blockSignals(False)

    def _on_voice_changed(self, _index: int) -> None:
        self._player.stop()

    def _open_voice_manager(self) -> None:
        before = self.voice_combo.currentData()
        self._voice_manager(self).exec()
        self._reload_voices(select_key=before.key if before is not None else None)
        after = self.voice_combo.currentData()
        if before is not None and (after is None or after.key != before.key):
            self._player.stop()  # the voice being used is gone

    def _offer_voice_download(self) -> Voice | None:
        yes = QMessageBox.StandardButton.Yes
        answer = QMessageBox.question(
            self, APP_NAME, MSG_NEED_VOICE, yes | QMessageBox.StandardButton.No, yes
        )
        if answer != yes:
            return None
        voice = download_default_voice(self, self._voices_dir)
        if voice is None:
            return None
        self._reload_voices(select_key=voice.key)
        return self.voice_combo.currentData()

    def _speech_for(self, voice: Voice) -> _Speech:
        if self._speech is None or self._speech_key != voice.key:
            self._speech = _Speech(self._synth_factory(voice))
            self._speech.length_scale = self._length_scale
            self._speech_key = voice.key
        return self._speech

    # ---- playback --------------------------------------------------------------

    def _on_play_clicked(self) -> None:
        state = self._player.state
        if state is PlayerState.STOPPED:
            self._start_reading()
        elif state is PlayerState.PAUSED:
            self._player.resume()
        else:
            self._player.pause()

    def _on_space(self) -> None:
        if self.play_button.isEnabled():
            self._on_play_clicked()

    def _on_escape(self) -> None:
        if self._player.state is not PlayerState.STOPPED:
            self._player.stop()
        elif self.pdf_view.selection() is not None:
            self.pdf_view.clear_selection()
        else:
            self._clear_start_point()

    def _reading_scope(self) -> tuple[list[Sentence], int]:
        """The sentences to read and which one to start with."""
        selection = self.pdf_view.selection()
        if selection is not None:
            return self._reading.sentences_between(*selection), 0
        first, last = self._reading.slice_for_pages(
            self.first_page_spin.value(), self.last_page_spin.value()
        )
        chosen = self._start_sentence
        start = chosen - first if chosen is not None and first <= chosen < last else 0
        return list(self._reading.sentences[first:last]), start

    # ---- choosing what to read -------------------------------------------------

    def _set_start_point(self, word: int) -> bool:
        """Make the sentence of that word the place where reading begins."""
        if self._reading is None:
            return False
        index = self._reading.sentence_index_at(self._reading.words[word].start)
        if index is None:
            return False
        self._start_sentence = index
        page = self._reading.sentence_page(index) + 1
        if not self.first_page_spin.value() <= page <= self.last_page_spin.value():
            # The chosen place wins: stretch the page range to include it.
            last = self.last_page_spin.value()
            self._set_page_range(page, last if last >= page else self._reading.page_count)
        sentence = self._reading.sentences[index]
        self.pdf_view.set_start_marker(sentence.start, sentence.end)
        self._show_state(self._player.state)
        return True

    def _clear_start_point(self) -> None:
        self._start_sentence = None
        self.pdf_view.clear_start_marker()
        self._show_state(self._player.state)

    def _on_word_clicked(self, word: int) -> None:
        if not self._set_start_point(word):
            return
        state = self._player.state
        if state is PlayerState.PAUSED:
            self._player.stop()  # "continue" would go on from the old place
        elif state is not PlayerState.STOPPED:
            self._start_reading()  # jump there right away

    def _on_word_double_clicked(self, word: int) -> None:
        if self._set_start_point(word):
            self._start_reading()

    def _on_selection_changed(self, _start: int, _end: int) -> None:
        self._show_state(self._player.state)

    def _copy_selection(self) -> None:
        text = self.pdf_view.selected_text()
        if text:
            QGuiApplication.clipboard().setText(text)

    def build_context_menu(self, word: int) -> QMenu:
        """Menu for a right click on that word (-1: not on a word)."""
        menu = QMenu(self)
        if word >= 0:
            menu.addAction("Ler a partir daqui").triggered.connect(
                lambda: self._read_from_word(word)
            )
        if self.pdf_view.selection() is not None:
            menu.addAction("Ler seleção").triggered.connect(self._start_reading)
            menu.addAction("Copiar").triggered.connect(self._copy_selection)
        return menu

    def _read_from_word(self, word: int) -> None:
        self.pdf_view.clear_selection()
        self._on_word_double_clicked(word)

    def _on_context_requested(self, word: int, position) -> None:
        menu = self.build_context_menu(word)
        if not menu.isEmpty():
            menu.exec(position)

    # ---- speed ---------------------------------------------------------------------

    def _on_speed_changed(self, value: int) -> None:
        self.speed_label.setText(f"{value / 10:.1f}×".replace(".", ","))
        self._length_scale = 10 / value
        if self._speech is not None:
            self._speech.length_scale = self._length_scale
        if self._player.state is not PlayerState.STOPPED:
            self._speed_timer.start()

    def _nudge_speed(self, step: int) -> None:
        self.speed_slider.setValue(self.speed_slider.value() + step)

    def _start_reading(self) -> None:
        if self._reading is None:
            return
        sentences, start = self._reading_scope()
        if not sentences:
            self._notify(MSG_EMPTY_RANGE)
            return
        ready = self._voice_ready()
        if ready is None:
            return
        speech, sample_rate = ready
        self._playing = sentences
        self._player.play(
            speech.speak, sample_rate, [sentence.text for sentence in sentences], start
        )

    def _voice_ready(self) -> tuple[_Speech, int] | None:
        """The voice to speak with and its sample rate; None if there is none."""
        voice = self.voice_combo.currentData()
        if voice is None:
            voice = self._offer_voice_download()
            if voice is None:
                return None
        try:
            speech = self._speech_for(voice)
            return speech, speech.synth.sample_rate
        except LeitorError as exc:
            self._notify(str(exc))
            return None

    # ---- export ------------------------------------------------------------------

    def _export(self) -> None:
        """Save the reading of the chosen pages as an MP3 file."""
        if self._reading is None or self._doc_path is None:
            return
        self._player.stop()
        first, last = self._reading.slice_for_pages(
            self.first_page_spin.value(), self.last_page_spin.value()
        )
        texts = [sentence.text for sentence in self._reading.sentences[first:last]]
        if not texts:
            self._notify(MSG_EMPTY_RANGE)
            return
        ready = self._voice_ready()
        if ready is None:
            return
        speech, sample_rate = ready
        chosen, _ = QFileDialog.getSaveFileName(
            self,
            "Exportar para MP3",
            str(self._doc_path.with_suffix(".mp3")),
            "Áudio MP3 (*.mp3)",
        )
        if not chosen:
            return
        dest = Path(chosen)
        if dest.suffix.lower() != ".mp3":
            dest = dest.with_name(dest.name + ".mp3")

        # Everything the worker thread touches is plain: no widgets, no self.
        exporter, title = self._exporter, self._doc_path.stem
        voice = _Speech(speech.synth)
        voice.length_scale = self._length_scale

        def work(report, cancel):
            def progress(done: int, total: int) -> None:
                report(done, total, f"Exportando para MP3… frase {done} de {total}")

            exporter(
                texts, voice.speak, sample_rate, dest,
                progress=progress, cancel=cancel, title=title,
            )  # fmt: skip

        status, _ = run_with_progress(
            self, "Exportando para MP3…", work, self._notify, cancelled=(ExportCancelled,)
        )
        if status == "done":
            self.statusBar().showMessage(f"MP3 gravado em {dest}")
        elif status == "cancelled":
            self.statusBar().showMessage("Exportação cancelada.")

    def _on_sentence_started(self, index: int) -> None:
        if self._reading is None or index >= len(self._playing):
            return
        sentence = self._playing[index]
        self.pdf_view.set_reading_highlight(sentence.start, sentence.end)
        self.pdf_view.scroll_to(sentence.start, sentence.end)
        page = self._reading.page_of(sentence.start) + 1
        self._reading_status = f"Lendo — página {page} de {self._reading.page_count}"
        if self._player.state is PlayerState.PLAYING:
            self.statusBar().showMessage(self._reading_status)

    def _on_state_changed(self, state: PlayerState) -> None:
        self._show_state(state)
        if state is PlayerState.STOPPED:
            self.pdf_view.clear_reading_highlight()
            self._reading_status = ""
            message = self._doc_status
        elif state is PlayerState.PAUSED:
            message = "Pausado"
        elif state is PlayerState.LOADING:
            message = "Preparando a voz…"
        else:
            message = self._reading_status or "Lendo…"
        self.statusBar().showMessage(message)

    def _show_state(self, state: PlayerState) -> None:
        self.play_button.setText(_PLAY_TEXT.get(state) or self._idle_play_text())
        self.stop_button.setEnabled(state is not PlayerState.STOPPED)

    def _idle_play_text(self) -> str:
        if self.pdf_view.selection() is not None:
            return "▶ Ler seleção"
        if self._start_sentence is not None:
            return "▶ Ler daqui"
        return "▶ Reproduzir"

    def _on_finished(self) -> None:
        self.statusBar().showMessage("Leitura concluída.")

    def closeEvent(self, event: QCloseEvent) -> None:
        self._player.shutdown()
        self.pdf_view.shutdown()
        super().closeEvent(event)


def _first_local_file(event: QDropEvent) -> str | None:
    for url in event.mimeData().urls():
        if url.isLocalFile():
            return url.toLocalFile()
    return None


def _preferred_index(voices: list[Voice], select_key: str | None) -> int:
    """Requested voice, else the default one, else any pt_BR voice, else the first."""
    if not voices:
        return -1
    keys = [voice.key for voice in voices]
    for wanted in (select_key, DEFAULT_VOICE_KEY):
        if wanted in keys:
            return keys.index(wanted)
    for index, voice in enumerate(voices):
        if voice.language == "pt_BR":
            return index
    return 0
