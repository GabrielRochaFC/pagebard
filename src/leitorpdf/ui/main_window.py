"""The main window: open a PDF, pick a voice, play and pause."""

from collections.abc import Callable
from pathlib import Path
from typing import Any

from PySide6.QtCore import QStandardPaths, Qt, QTimer
from PySide6.QtGui import QCloseEvent, QKeySequence
from PySide6.QtWidgets import (
    QComboBox,
    QFileDialog,
    QHBoxLayout,
    QLabel,
    QMainWindow,
    QMessageBox,
    QPlainTextEdit,
    QPushButton,
    QVBoxLayout,
    QWidget,
)

from leitorpdf.core import paths
from leitorpdf.core.errors import LeitorError, user_message
from leitorpdf.core.pdf import PdfText, load_pdf
from leitorpdf.core.segmenter import Sentence, split_sentences
from leitorpdf.core.tts import Synthesizer
from leitorpdf.core.voices import DEFAULT_VOICE_KEY, Voice, installed_voices
from leitorpdf.playback.player import Player, PlayerState
from leitorpdf.ui.messages import APP_NAME, MSG_NEED_VOICE, MSG_NO_TEXT, show_error
from leitorpdf.ui.tasks import run_async
from leitorpdf.ui.voice_download import download_default_voice

_TEXT_POINT_SIZE = 13
_PLAY_TEXT = {
    PlayerState.STOPPED: "▶ Reproduzir",
    PlayerState.LOADING: "⏸ Pausar",
    PlayerState.PLAYING: "⏸ Pausar",
    PlayerState.PAUSED: "▶ Continuar",
}
_STATUS_TEXT = {
    PlayerState.LOADING: "Preparando a voz…",
    PlayerState.PLAYING: "Lendo…",
    PlayerState.PAUSED: "Pausado",
}


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
        self._synth: Any = None
        self._synth_key: str | None = None
        self._sentences: list[Sentence] = []
        self._doc_status = ""
        self._load_id = 0  # lets a newer "open" supersede one still loading
        self._last_dir = QStandardPaths.writableLocation(
            QStandardPaths.StandardLocation.DocumentsLocation
        )

        self._build_ui()
        self._player.state_changed.connect(self._on_state_changed)
        self._player.finished.connect(self._on_finished)
        self._player.error.connect(self._notify)
        self._reload_voices()
        self._show_state(self._player.state)

        if offer_download and self.voice_combo.count() == 0:
            QTimer.singleShot(0, self._offer_voice_download)

    # ---- construction ----------------------------------------------------

    def _build_ui(self) -> None:
        self.setWindowTitle(APP_NAME)
        self.resize(900, 650)

        self.open_button = QPushButton("Abrir PDF…")
        self.open_button.setShortcut(QKeySequence("Ctrl+O"))
        self.open_button.setToolTip("Abrir um arquivo PDF (Ctrl+O)")
        self.open_button.clicked.connect(self._choose_file)

        voice_label = QLabel("Voz:")
        self.voice_combo = QComboBox()
        self.voice_combo.setMinimumWidth(240)
        self.voice_combo.setAccessibleName("Voz")
        self.voice_combo.setToolTip("Voz usada na leitura")
        self.voice_combo.currentIndexChanged.connect(self._on_voice_changed)
        voice_label.setBuddy(self.voice_combo)

        self.play_button = QPushButton()
        self.play_button.setMinimumWidth(160)
        self.play_button.setToolTip("Reproduzir ou pausar a leitura (Espaço)")
        self.play_button.setEnabled(False)
        self.play_button.clicked.connect(self._on_play_clicked)

        self.text_view = QPlainTextEdit()
        self.text_view.setReadOnly(True)
        self.text_view.setPlaceholderText("Abra um PDF para começar (Ctrl+O).")
        self.text_view.setAccessibleName("Texto do documento")
        font = self.text_view.font()
        font.setPointSize(_TEXT_POINT_SIZE)
        self.text_view.setFont(font)

        top = QHBoxLayout()
        top.addWidget(self.open_button)
        top.addSpacing(16)
        top.addWidget(voice_label)
        top.addWidget(self.voice_combo)
        top.addStretch(1)
        top.addWidget(self.play_button)

        layout = QVBoxLayout()
        layout.addLayout(top)
        layout.addWidget(self.text_view, 1)
        central = QWidget()
        central.setLayout(layout)
        self.setCentralWidget(central)
        self.statusBar()

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
        """Load a PDF in the background and show its text."""
        path = Path(path)
        self._player.stop()
        self._last_dir = str(path.parent)
        self._load_id += 1
        load_id = self._load_id
        self.statusBar().showMessage("Abrindo PDF…")
        run_async(
            lambda: load_pdf(path),
            lambda doc: self._on_loaded(load_id, doc),
            lambda exc: self._on_load_failed(load_id, exc),
        )

    def _on_loaded(self, load_id: int, doc: PdfText) -> None:
        if load_id != self._load_id:
            return
        self._player.stop()
        text = "\n\n".join(page for page in doc.pages if page)
        self.text_view.setPlainText(text)
        self._sentences = split_sentences(text)
        self.play_button.setEnabled(bool(self._sentences))
        count = len(doc.pages)
        self._doc_status = f"{doc.path.name} — {count} página{'' if count == 1 else 's'}"
        self.statusBar().showMessage(self._doc_status)
        if not doc.has_text:
            self._notify(MSG_NO_TEXT)

    def _on_load_failed(self, load_id: int, exc: Exception) -> None:
        if load_id != self._load_id:
            return
        self.statusBar().showMessage(self._doc_status)
        self._notify(user_message(exc))

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

    def _synth_for(self, voice: Voice) -> Any:
        if self._synth is None or self._synth_key != voice.key:
            self._synth = self._synth_factory(voice)
            self._synth_key = voice.key
        return self._synth

    # ---- playback --------------------------------------------------------------

    def _on_play_clicked(self) -> None:
        state = self._player.state
        if state is PlayerState.STOPPED:
            self._start_reading()
        elif state is PlayerState.PAUSED:
            self._player.resume()
        else:
            self._player.pause()

    def _start_reading(self) -> None:
        if not self._sentences:
            return
        voice = self.voice_combo.currentData()
        if voice is None:
            voice = self._offer_voice_download()
            if voice is None:
                return
        try:
            synth = self._synth_for(voice)
            sample_rate = synth.sample_rate
        except LeitorError as exc:
            self._notify(str(exc))
            return
        self._player.play(
            synth.synthesize, sample_rate, [sentence.text for sentence in self._sentences]
        )

    def _on_state_changed(self, state: PlayerState) -> None:
        self._show_state(state)
        self.statusBar().showMessage(_STATUS_TEXT.get(state, self._doc_status))

    def _show_state(self, state: PlayerState) -> None:
        self.play_button.setText(_PLAY_TEXT[state])
        # setText() discards the button's shortcut, so it is set again each time.
        self.play_button.setShortcut(QKeySequence(Qt.Key.Key_Space))

    def _on_finished(self) -> None:
        self.statusBar().showMessage("Leitura concluída.")

    def closeEvent(self, event: QCloseEvent) -> None:
        self._player.stop()
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
