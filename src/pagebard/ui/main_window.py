"""The main window: the PDF on screen, read aloud."""

from collections.abc import Callable
from pathlib import Path
from typing import Any

from PySide6.QtCore import QByteArray, QEvent, QSettings, QStandardPaths, Qt, QTimer
from PySide6.QtGui import (
    QAction,
    QActionGroup,
    QCloseEvent,
    QDragEnterEvent,
    QDropEvent,
    QGuiApplication,
    QKeySequence,
    QShortcut,
)
from PySide6.QtWidgets import (
    QApplication,
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

from pagebard.core.i18n import _, decimal, ngettext
from pagebard.core import ocr, paths
from pagebard.core.errors import PagebardError, user_message
from pagebard.core.export import ExportCancelled, export_mp3
from pagebard.core.pdf import PdfText, load_pdf, with_ocr
from pagebard.core.reading import Reading, build_reading
from pagebard.core.segmenter import Sentence
from pagebard.core.tts import Synthesizer
from pagebard.core.voices import (
    DEFAULT_VOICE_KEY,
    PREFERRED_LANGUAGE,
    Voice,
    installed_voices,
)
from pagebard.playback.player import Player, PlayerState
from pagebard.ui.messages import (
    APP_NAME,
    MSG_EMPTY_RANGE,
    MSG_NEED_VOICE,
    MSG_NO_TEXT,
    MSG_OCR_NOTHING,
    MSG_OFFER_OCR,
    show_error,
)
from pagebard.ui.pdf_view import PdfView
from pagebard.ui.progress import run_with_progress
from pagebard.ui.shortcuts_dialog import show_shortcuts
from pagebard.ui.tasks import run_async
from pagebard.ui.voice_download import download_default_voice
from pagebard.ui.voice_manager import VoiceManagerDialog

_HINT = _("click the text to choose where to start; drag to read only a passage")
_SPEED_MIN, _SPEED_MAX, _SPEED_DEFAULT = 5, 20, 10  # tenths: 0,5× to 2,0×
_SPEED_SETTLE_MS = 250  # wait for the slider to stop before re-synthesizing
_POINTS_PER_PIXEL_AT_100 = 96 / 72  # zoom shown as 100% means 96 dpi
# Each language under its own name, whatever the language in use.
_LANGUAGE_NAMES = [("en", "English"), ("es", "Español"), ("pt_BR", "Português (Brasil)")]
_TEXT_SCALES = [(_("Normal"), 1.0), (_("Large"), 1.25), (_("Very large"), 1.5)]
_MIN_SIZE = (760, 520)  # at the normal text size; grows with the text
_VOICE_COMBO_WIDTH = 240
# Keys that drive the reading even while a page-number field has the focus.
_READING_KEYS = (Qt.Key.Key_Space, Qt.Key.Key_Plus, Qt.Key.Key_Minus, Qt.Key.Key_Equal)
_ABOUT = (
    _(
        "<b>Pagebard {version}</b><br>Reads PDFs aloud, without internet.<br><br>Free "
        "software, licensed AGPL-3.0-or-later.<br>Uses Piper voices, PyMuPDF (MuPDF "
        "and Tesseract) and Qt."
    )
)
# The size the interface font has before any scaling; found once per run,
# because the scale is applied to the application font itself.
_base_point_size: float | None = None
_PLAY_TEXT = {
    PlayerState.LOADING: _("⏸ Pause"),
    PlayerState.PLAYING: _("⏸ Pause"),
    PlayerState.PAUSED: _("▶ Resume"),
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
        tessdata_dir: Path | None = None,
        recognizer: Callable[..., dict] = ocr.recognize,
        ocr_downloader: Callable[..., None] = ocr.download_language,
        settings: QSettings | None = None,
    ) -> None:
        super().__init__()
        global _base_point_size
        if _base_point_size is None:
            _base_point_size = QApplication.font().pointSizeF()
        self._settings = settings  # None: nothing is remembered between runs
        self._remembering = False  # off while the window is being set up
        self._text_scale = 1.0
        self._exporter = exporter
        self._tessdata_dir = tessdata_dir if tessdata_dir is not None else paths.tessdata_dir()
        self._recognizer = recognizer
        self._ocr_downloader = ocr_downloader
        self._doc: PdfText | None = None
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
        self._restore_preferences()
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
        self.setMinimumSize(*_MIN_SIZE)
        self.setStyleSheet(_STYLE)

        self.open_button = QPushButton(_("Open PDF…"))
        self.open_button.setToolTip(_("Open a PDF file (Ctrl+O)"))
        self.open_button.clicked.connect(self._choose_file)

        self.play_button = QPushButton()
        self.play_button.setObjectName("playButton")
        self.play_button.setMinimumWidth(160)
        self.play_button.setToolTip(_("Read aloud or pause (Space)"))
        self.play_button.setEnabled(False)
        self.play_button.clicked.connect(self._on_play_clicked)

        self.stop_button = QPushButton(_("⏹ Stop"))
        self.stop_button.setToolTip(_("Stop reading (Esc)"))
        self.stop_button.clicked.connect(self._player.stop)

        self.export_button = QPushButton(_("Export MP3…"))
        self.export_button.setToolTip(_("Save the reading of the chosen pages as an MP3 file"))
        self.export_button.setEnabled(False)
        self.export_button.clicked.connect(self._export)


        voice_label = QLabel(_("Voice:"))
        self.voice_combo = QComboBox()
        self.voice_combo.setMinimumWidth(_VOICE_COMBO_WIDTH)
        self.voice_combo.setAccessibleName(_("Voice"))
        self.voice_combo.setToolTip(_("Voice used for reading"))
        self.voice_combo.currentIndexChanged.connect(self._on_voice_changed)
        voice_label.setBuddy(self.voice_combo)
        self.voices_button = QPushButton(_("Voices…"))
        self.voices_button.setToolTip(_("Download or remove voices"))
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

        speed_title = QLabel(_("Speed:"))
        self.speed_slider = QSlider(Qt.Orientation.Horizontal)
        self.speed_slider.setRange(_SPEED_MIN, _SPEED_MAX)
        self.speed_slider.setValue(_SPEED_DEFAULT)
        self.speed_slider.setPageStep(1)
        self.speed_slider.setFixedWidth(150)
        self.speed_slider.setAccessibleName(_("Speed"))
        self.speed_slider.setToolTip(_("Reading speed (+ and - keys)"))
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

        pages_title = QLabel(_("Pages:"))
        self.first_page_spin = QSpinBox()
        self.first_page_spin.setAccessibleName(_("First page to read"))
        self.first_page_spin.setToolTip(_("First page to read"))
        self.last_page_spin = QSpinBox()
        self.last_page_spin.setAccessibleName(_("Last page to read"))
        self.last_page_spin.setToolTip(_("Last page to read"))
        for spin in (self.first_page_spin, self.last_page_spin):
            spin.setMinimumWidth(64)
            # Apply a typed number when it is complete (Enter or leaving the
            # field), not digit by digit: "25" must not pass through "2".
            spin.setKeyboardTracking(False)
            spin.installEventFilter(self)  # see eventFilter
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
        self.zoom_out_button.setToolTip(_("Zoom out (Ctrl+-)"))
        self.zoom_out_button.setAccessibleName(_("Zoom out"))
        self.zoom_in_button = QPushButton("+")
        self.zoom_in_button.setToolTip(_("Zoom in (Ctrl++)"))
        self.zoom_in_button.setAccessibleName(_("Zoom in"))
        self.zoom_label = QLabel()
        self.zoom_label.setMinimumWidth(44)
        self.zoom_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.fit_button = QPushButton(_("Fit width"))
        self.fit_button.setToolTip(_("Fit the page to the window width (Ctrl+0)"))
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

        self._build_menus()
        copy = QShortcut(QKeySequence(QKeySequence.StandardKey.Copy), self)
        copy.activated.connect(self._copy_selection)

    def _action(self, text: str, slot, *shortcuts: str, repeat: bool = True) -> QAction:
        action = QAction(text, self)
        action.triggered.connect(slot)
        if shortcuts:
            action.setShortcuts([QKeySequence(keys) for keys in shortcuts])
        action.setAutoRepeat(repeat)
        return action

    def _build_menus(self) -> None:
        """Every command is in the menu bar; each key has exactly one owner here.

        Space belongs to a window action and not to the button: a focused
        button would also "click" on the key release and toggle twice.
        """
        self.open_action = self._action(_("Open PDF…"), self._choose_file, "Ctrl+O")
        self.export_action = self._action(_("Export MP3…"), self._export, "Ctrl+E")
        self.ocr_action = self._action(_("Recognize text (OCR)…"), self._run_ocr)
        self.quit_action = self._action(_("Quit"), self.close, "Ctrl+Q")
        self.play_action = self._action(
            _("Play / Pause"), self._on_space, "Space", repeat=False
        )
        self.stop_action = self._action(_("Stop"), self._on_escape, "Esc", repeat=False)
        self.faster_action = self._action(_("Faster"), lambda: self._nudge_speed(1), "+", "=")
        self.slower_action = self._action(_("Slower"), lambda: self._nudge_speed(-1), "-")
        self.voices_action = self._action(_("Voices…"), self._open_voice_manager)
        self.zoom_in_action = self._action(
            _("Zoom in page"), self.pdf_view.zoom_in, "Ctrl++", "Ctrl+="
        )
        self.zoom_out_action = self._action(_("Zoom out page"), self.pdf_view.zoom_out, "Ctrl+-")
        self.fit_action = self._action(_("Fit width"), self._fit_width, "Ctrl+0")
        self.shortcuts_action = self._action(
            _("Keyboard shortcuts"), lambda: show_shortcuts(self), "F1"
        )
        self.about_action = self._action(_("About Pagebard"), self._show_about)
        for action in (self.export_action, self.ocr_action):
            action.setEnabled(False)

        bar = self.menuBar()
        file_menu = bar.addMenu(_("&File"))
        file_menu.addActions([self.open_action, self.export_action, self.ocr_action])
        file_menu.addSeparator()
        file_menu.addAction(self.quit_action)
        reading_menu = bar.addMenu(_("&Reading"))
        reading_menu.addActions([self.play_action, self.stop_action])
        reading_menu.addSeparator()
        reading_menu.addActions([self.faster_action, self.slower_action])
        reading_menu.addSeparator()
        reading_menu.addAction(self.voices_action)
        view_menu = bar.addMenu(_("&View"))
        view_menu.addActions([self.zoom_in_action, self.zoom_out_action, self.fit_action])
        view_menu.addSeparator()
        text_menu = view_menu.addMenu(_("Interface text size"))
        group = QActionGroup(self)
        self.text_scale_actions: list[QAction] = []
        for label, scale in _TEXT_SCALES:
            action = QAction(label, self, checkable=True)
            action.setChecked(scale == self._text_scale)
            action.triggered.connect(lambda _checked, scale=scale: self.set_text_scale(scale))
            group.addAction(action)
            text_menu.addAction(action)
            self.text_scale_actions.append(action)
        language_menu = view_menu.addMenu(_("Language"))
        language_group = QActionGroup(self)
        saved = self._recall("language")
        choices = [("auto", _("Automatic (system)"))] + _LANGUAGE_NAMES
        current = saved if saved in [code for code, _name in _LANGUAGE_NAMES] else "auto"
        self.language_actions: list[QAction] = []
        for code, name in choices:
            action = QAction(name, self, checkable=True)
            action.setChecked(code == current)
            action.triggered.connect(lambda _checked, code=code: self._choose_language(code))
            language_group.addAction(action)
            language_menu.addAction(action)
            self.language_actions.append(action)
        help_menu = bar.addMenu(_("&Help"))
        help_menu.addActions([self.shortcuts_action, self.about_action])

    def _choose_language(self, code: str) -> None:
        """Remember the language; texts are built at start-up, so it applies next time."""
        self._remember("language", code)
        QMessageBox.information(
            self, APP_NAME, _("Restart Pagebard to use the new language.")
        )

    def _show_about(self) -> None:
        from pagebard import __version__

        QMessageBox.about(self, _("About Pagebard"), _ABOUT.format(version=__version__))

    # ---- preferences ---------------------------------------------------------

    @property
    def text_scale(self) -> float:
        return self._text_scale

    def set_text_scale(self, scale: float) -> None:
        """Size of the interface text: 1.0, 1.25 or 1.5 times the usual."""
        if scale not in [value for _label, value in _TEXT_SCALES]:
            return
        self._text_scale = scale
        font = QApplication.font()
        font.setPointSizeF(_base_point_size * scale)
        QApplication.setFont(font)  # windows of their own, like the file chooser
        # Widgets under a style sheet ignore inherited fonts, so the size goes
        # into the sheet; it also reaches the dialogs opened from this window.
        self.setStyleSheet(f"{_STYLE}\n* {{ font-size: {font.pointSizeF():g}pt; }}")
        # Bigger text needs more room: do not let the header be squeezed.
        self.setMinimumSize(round(_MIN_SIZE[0] * scale), round(_MIN_SIZE[1] * scale))
        self.voice_combo.setMinimumWidth(round(_VOICE_COMBO_WIDTH * scale))
        for action, (_label, value) in zip(self.text_scale_actions, _TEXT_SCALES):
            action.setChecked(value == scale)
        self._remember("text_scale", scale)

    def _remember(self, key: str, value: Any) -> None:
        if self._settings is not None and self._remembering:
            self._settings.setValue(key, value)

    def _recall(self, key: str) -> Any:
        return self._settings.value(key) if self._settings is not None else None

    def _restore_preferences(self) -> None:
        """Apply what was remembered; anything odd falls back to the default."""
        self._reload_voices(select_key=_as_text(self._recall("voice")))
        speed = _as_number(self._recall("speed"))
        if speed is not None and _SPEED_MIN <= speed <= _SPEED_MAX and speed == int(speed):
            self.speed_slider.setValue(int(speed))
        scale = _as_number(self._recall("text_scale"))
        if scale is not None and scale != 1.0:
            self.set_text_scale(scale)
        folder = _as_text(self._recall("last_dir"))
        if folder and Path(folder).is_dir():
            self._last_dir = folder
        geometry = self._recall("geometry")
        if isinstance(geometry, QByteArray):
            self.restoreGeometry(geometry)
        self._remembering = True  # from here on, changes are the user's

    # ---- opening a document ------------------------------------------------

    def _choose_file(self) -> None:
        path, _filter = QFileDialog.getOpenFileName(
            self,
            _("Open PDF"),
            self._last_dir,
            _("PDF documents (*.pdf);;All files (*)"),
        )
        if path:
            self.open_path(path)

    def open_path(self, path: str | Path) -> None:
        """Load a PDF in the background and show it."""
        path = Path(path)
        self._player.stop()
        self._last_dir = str(path.parent)
        self._remember("last_dir", self._last_dir)
        self._load_id += 1
        load_id = self._load_id
        self.statusBar().showMessage(_("Opening PDF…"))
        run_async(
            lambda: _load(path),
            lambda loaded: self._on_loaded(load_id, *loaded),
            lambda exc: self._on_load_failed(load_id, exc),
        )

    def _on_loaded(self, load_id: int, doc: PdfText, reading: Reading) -> None:
        if load_id != self._load_id:
            return
        self._show_document(doc, reading, fresh=True)
        if reading.sentences:
            return  # readable; picture-only pages are only noted in the status bar
        if doc.scanned_pages:
            if self._ask(MSG_OFFER_OCR):
                self._run_ocr()
        else:
            self._notify(MSG_NO_TEXT)

    def _show_document(self, doc: PdfText, reading: Reading, fresh: bool) -> None:
        """Put a document on screen; `fresh` is False when only its text changed."""
        self._player.stop()
        self._doc = doc
        self._doc_path = doc.path
        self._reading = reading
        self._playing = []
        self._start_sentence = None
        if fresh:
            self.pdf_view.set_document(doc.path, reading)
            self._reset_page_range()
        else:
            self.pdf_view.update_reading(reading)
            for spin in (self.first_page_spin, self.last_page_spin):
                spin.setEnabled(bool(reading.sentences))
        self._update_zoom_controls()
        self.play_button.setEnabled(bool(reading.sentences))
        self.export_button.setEnabled(bool(reading.sentences))
        self.export_action.setEnabled(bool(reading.sentences))
        self.ocr_action.setEnabled(bool(doc.scanned_pages))
        count = reading.page_count
        self._doc_status = ngettext(
            "{name} — {count} page", "{name} — {count} pages", count
        ).format(name=doc.path.name, count=count)
        scanned = len(doc.scanned_pages)
        if reading.sentences and scanned:
            self._doc_status += " · " + ngettext(
                "{count} page without text: use File → Recognize text (OCR)",
                "{count} pages without text: use File → Recognize text (OCR)",
                scanned,
            ).format(count=scanned)
        elif reading.sentences:
            self._doc_status += f" · {_HINT}"
        self.statusBar().showMessage(self._doc_status)
        self._update_page_label()
        self._show_state(self._player.state)

    def _ask(self, text: str) -> bool:
        yes = QMessageBox.StandardButton.Yes
        answer = QMessageBox.question(
            self, APP_NAME, text, yes | QMessageBox.StandardButton.No, yes
        )
        return answer == yes

    # ---- text recognition (OCR) ------------------------------------------------

    def _run_ocr(self) -> None:
        """Recognize the text of the scanned pages of the open document."""
        doc = self._doc
        if doc is None or not doc.scanned_pages:
            return
        self._player.stop()
        voice = self.voice_combo.currentData()
        language = ocr.language_for(
            voice.language if voice is not None else PREFERRED_LANGUAGE
        )
        # Everything the worker threads touch is plain: no widgets, no self.
        tessdata, pages, path = self._tessdata_dir, list(doc.scanned_pages), doc.path
        downloader, recognizer = self._ocr_downloader, self._recognizer
        cancelled = (ocr.OcrCancelled,)

        if not ocr.has_language(language, tessdata):

            def fetch(report, cancel):
                downloader(language, tessdata, progress=report, cancel=cancel)

            status, _nothing = run_with_progress(
                self, _("Downloading recognition data…"), fetch, self._notify, cancelled
            )
            if status != "done":
                return

        def work(report, cancel):
            def progress(done: int, total: int) -> None:
                text = _("Recognizing text… page {done} of {total}")
                report(done, total, text.format(done=done, total=total))

            recognized = recognizer(
                path, pages, language, tessdata, progress=progress, cancel=cancel
            )
            updated = with_ocr(doc, recognized)  # big documents: keep it off the UI
            return updated, build_reading(updated)

        status, result = run_with_progress(
            self, _("Recognizing text…"), work, self._notify, cancelled
        )
        if status != "done" or self._doc is not doc:
            return  # cancelled, failed, or another document took over meanwhile
        updated, reading = result
        found = len(doc.scanned_pages) - len(updated.scanned_pages)
        if found == 0:
            self._notify(MSG_OCR_NOTHING)
            return
        self._show_document(updated, reading, fresh=False)
        self.statusBar().showMessage(
            ngettext(
                "Text recognized on {count} page.", "Text recognized on {count} pages.", found
            ).format(count=found)
        )

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
            self.page_label.setText(
                _("Page {page} of {count}").format(page=page, count=self._reading.page_count)
            )

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
        for control in (
            self.zoom_out_button, self.zoom_in_button, self.fit_button,
            self.zoom_out_action, self.zoom_in_action, self.fit_action,
        ):  # fmt: skip
            control.setEnabled(has_document)
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
        voice = self.voice_combo.currentData()
        if voice is not None:
            self._remember("voice", voice.key)

    def _open_voice_manager(self) -> None:
        before = self.voice_combo.currentData()
        dialog = self._voice_manager(self)
        dialog.exec()
        if isinstance(dialog, QWidget):
            dialog.deleteLater()
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
            menu.addAction(_("Read from here")).triggered.connect(
                lambda: self._read_from_word(word)
            )
        if self.pdf_view.selection() is not None:
            menu.addAction(_("Read selection")).triggered.connect(self._start_reading)
            menu.addAction(_("Copy")).triggered.connect(self._copy_selection)
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
        self.speed_label.setText(f"{decimal(value / 10)}×")
        self._length_scale = 10 / value
        self._remember("speed", value)
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
        except PagebardError as exc:
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
        chosen, _filter = QFileDialog.getSaveFileName(
            self,
            _("Export to MP3"),
            str(self._doc_path.with_suffix(".mp3")),
            _("MP3 audio (*.mp3)"),
        )
        if not chosen:
            return
        dest = Path(chosen)
        if dest.suffix.lower() != ".mp3":
            dest = dest.with_name(dest.name + ".mp3")
            # The dialog checked the name as typed, not this one.
            question = _("The file {name} already exists. Replace it?")
            if dest.exists() and not self._ask(question.format(name=dest.name)):
                return

        # Everything the worker thread touches is plain: no widgets, no self.
        exporter, title = self._exporter, self._doc_path.stem
        voice = _Speech(speech.synth)
        voice.length_scale = self._length_scale

        def work(report, cancel):
            def progress(done: int, total: int) -> None:
                text = _("Exporting to MP3… sentence {done} of {total}")
                report(done, total, text.format(done=done, total=total))

            exporter(
                texts, voice.speak, sample_rate, dest,
                progress=progress, cancel=cancel, title=title,
            )  # fmt: skip

        status, _nothing = run_with_progress(
            self, _("Exporting to MP3…"), work, self._notify, cancelled=(ExportCancelled,)
        )
        if status == "done":
            self.statusBar().showMessage(_("MP3 saved to {path}").format(path=dest))
        elif status == "cancelled":
            self.statusBar().showMessage(_("Export cancelled."))

    def _on_sentence_started(self, index: int) -> None:
        if self._reading is None or index >= len(self._playing):
            return
        sentence = self._playing[index]
        self.pdf_view.set_reading_highlight(sentence.start, sentence.end)
        self.pdf_view.scroll_to(sentence.start, sentence.end)
        page = self._reading.page_of(sentence.start) + 1
        self._reading_status = _("Reading — page {page} of {count}").format(
            page=page, count=self._reading.page_count
        )
        if self._player.state is PlayerState.PLAYING:
            self.statusBar().showMessage(self._reading_status)

    def _on_state_changed(self, state: PlayerState) -> None:
        self._show_state(state)
        if state is PlayerState.STOPPED:
            self.pdf_view.clear_reading_highlight()
            self._reading_status = ""
            message = self._doc_status
        elif state is PlayerState.PAUSED:
            message = _("Paused")
        elif state is PlayerState.LOADING:
            message = _("Preparing the voice…")
        else:
            message = self._reading_status or _("Reading…")
        self.statusBar().showMessage(message)

    def _show_state(self, state: PlayerState) -> None:
        self.play_button.setText(_PLAY_TEXT.get(state) or self._idle_play_text())
        self.stop_button.setEnabled(state is not PlayerState.STOPPED)

    def _idle_play_text(self) -> str:
        if self.pdf_view.selection() is not None:
            return _("▶ Read selection")
        if self._start_sentence is not None:
            return _("▶ Read from here")
        return _("▶ Play")

    def _on_finished(self) -> None:
        self.statusBar().showMessage(_("Reading finished."))

    def eventFilter(self, watched, event) -> bool:
        """Let Space, + and - reach the reading while a page field has focus.

        A number field would otherwise claim those keys as text.
        """
        if (
            event.type() == QEvent.Type.ShortcutOverride
            and watched in (self.first_page_spin, self.last_page_spin)
            and event.key() in _READING_KEYS
            and not event.modifiers() & Qt.KeyboardModifier.ControlModifier
        ):
            event.ignore()
            return True
        return super().eventFilter(watched, event)

    def closeEvent(self, event: QCloseEvent) -> None:
        self._remember("geometry", self.saveGeometry())
        self._player.shutdown()
        self.pdf_view.shutdown()
        super().closeEvent(event)


def _as_text(value: Any) -> str | None:
    return value if isinstance(value, str) and value else None


def _as_number(value: Any) -> float | None:
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def _first_local_file(event: QDropEvent) -> str | None:
    for url in event.mimeData().urls():
        if url.isLocalFile():
            return url.toLocalFile()
    return None


def _preferred_index(voices: list[Voice], select_key: str | None) -> int:
    """Requested voice, else the default, else one in the preferred language, else the first."""
    if not voices:
        return -1
    keys = [voice.key for voice in voices]
    for wanted in (select_key, DEFAULT_VOICE_KEY):
        if wanted in keys:
            return keys.index(wanted)
    for index, voice in enumerate(voices):
        if voice.language == PREFERRED_LANGUAGE:
            return index
    return 0
