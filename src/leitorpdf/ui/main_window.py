"""The main window: the PDF on screen, read aloud."""

from collections.abc import Callable
from pathlib import Path
from typing import Any

from PySide6.QtCore import QStandardPaths, Qt, QTimer
from PySide6.QtGui import QCloseEvent, QKeySequence, QShortcut
from PySide6.QtWidgets import (
    QComboBox,
    QFileDialog,
    QHBoxLayout,
    QLabel,
    QMainWindow,
    QMessageBox,
    QPushButton,
    QVBoxLayout,
    QWidget,
)

from leitorpdf.core import paths
from leitorpdf.core.errors import LeitorError, user_message
from leitorpdf.core.pdf import PdfText, load_pdf
from leitorpdf.core.reading import Reading, build_reading
from leitorpdf.core.segmenter import Sentence
from leitorpdf.core.tts import Synthesizer
from leitorpdf.core.voices import DEFAULT_VOICE_KEY, Voice, installed_voices
from leitorpdf.playback.player import Player, PlayerState
from leitorpdf.ui.messages import APP_NAME, MSG_NEED_VOICE, MSG_NO_TEXT, show_error
from leitorpdf.ui.pdf_view import PdfView
from leitorpdf.ui.tasks import run_async
from leitorpdf.ui.voice_download import download_default_voice

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
    ) -> None:
        super().__init__()
        self._player = player if player is not None else Player(parent=self)
        self._voices_dir = voices_dir if voices_dir is not None else paths.voices_dir()
        self._notify = notify or (lambda text: show_error(self, text))
        self._synth_factory = synth_factory or (lambda voice: Synthesizer(voice.path))
        self._speech: _Speech | None = None
        self._speech_key: str | None = None
        self._reading: Reading | None = None
        self._playing: list[Sentence] = []  # what the player is reading now
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
        self._reload_voices()
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

        voice_label = QLabel("Voz:")
        self.voice_combo = QComboBox()
        self.voice_combo.setMinimumWidth(240)
        self.voice_combo.setAccessibleName("Voz")
        self.voice_combo.setToolTip("Voz usada na leitura")
        self.voice_combo.currentIndexChanged.connect(self._on_voice_changed)
        voice_label.setBuddy(self.voice_combo)

        row1 = QHBoxLayout()
        row1.setSpacing(8)
        row1.addWidget(self.open_button)
        row1.addSpacing(12)
        row1.addWidget(self.play_button)
        row1.addWidget(self.stop_button)
        row1.addStretch(1)
        row1.addWidget(voice_label)
        row1.addWidget(self.voice_combo)

        self._row2 = QHBoxLayout()
        self._row2.setSpacing(8)

        header = QWidget()
        header.setObjectName("header")
        header_layout = QVBoxLayout(header)
        header_layout.setContentsMargins(12, 10, 12, 10)
        header_layout.setSpacing(8)
        header_layout.addLayout(row1)
        header_layout.addLayout(self._row2)

        self.pdf_view = PdfView()

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
        self.pdf_view.set_document(doc.path, reading)
        self.play_button.setEnabled(bool(reading.sentences))
        count = reading.page_count
        self._doc_status = f"{doc.path.name} — {count} página{'' if count == 1 else 's'}"
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

    def _reading_scope(self) -> tuple[list[Sentence], int]:
        """The sentences to read and which one to start with."""
        return list(self._reading.sentences), 0

    def _start_reading(self) -> None:
        if self._reading is None:
            return
        sentences, start = self._reading_scope()
        if not sentences:
            return
        voice = self.voice_combo.currentData()
        if voice is None:
            voice = self._offer_voice_download()
            if voice is None:
                return
        try:
            speech = self._speech_for(voice)
            sample_rate = speech.synth.sample_rate
        except LeitorError as exc:
            self._notify(str(exc))
            return
        self._playing = sentences
        self._player.play(
            speech.speak, sample_rate, [sentence.text for sentence in sentences], start
        )

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
        return "▶ Reproduzir"

    def _on_finished(self) -> None:
        self.statusBar().showMessage("Leitura concluída.")

    def closeEvent(self, event: QCloseEvent) -> None:
        self._player.shutdown()
        self.pdf_view.shutdown()
        super().closeEvent(event)


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
