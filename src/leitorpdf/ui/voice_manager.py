"""Dialog to see, download and remove voices."""

from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QAbstractItemView,
    QComboBox,
    QDialog,
    QHBoxLayout,
    QHeaderView,
    QLabel,
    QMessageBox,
    QPushButton,
    QTableWidget,
    QTableWidgetItem,
    QVBoxLayout,
    QWidget,
)

from leitorpdf.core.errors import user_message
from leitorpdf.core.voices import (
    CatalogVoice,
    Voice,
    download_voice,
    fetch_catalog,
    installed_voices,
    language_label,
    parse_key,
    quality_label,
    remove_voice,
)
from leitorpdf.ui.messages import APP_NAME, show_error
from leitorpdf.ui.tasks import run_async
from leitorpdf.ui.voice_download import download_voice_with_progress

_LOADING = "Carregando lista de vozes…"
_ALL_LANGUAGES = "Todos os idiomas"
_HEADERS = ["Voz", "Idioma", "Qualidade", "Tamanho", "Situação"]
_MEGABYTE = 1_000_000


@dataclass(frozen=True)
class _Row:
    key: str
    label: str  # full label, for messages
    name: str
    language: str  # code
    quality: str
    size: str
    installed: bool


class VoiceManagerDialog(QDialog):
    def __init__(
        self,
        voices_dir: Path,
        cache_file: Path,
        parent: QWidget | None = None,
        fetch: Callable[[Path], list[CatalogVoice]] = fetch_catalog,
        download: Callable[..., Voice] = download_voice,
        notify: Callable[[str], None] | None = None,
    ) -> None:
        super().__init__(parent)
        self.changed = False  # a voice was installed or removed
        self._voices_dir = voices_dir
        self._download = download
        self._notify = notify or (lambda text: show_error(self, text))
        self._catalog: list[CatalogVoice] = []

        self.setWindowTitle(f"Vozes — {APP_NAME}")
        self.resize(640, 440)

        language_title = QLabel("Idioma:")
        self.language_combo = QComboBox()
        self.language_combo.setAccessibleName("Idioma")
        self.language_combo.currentIndexChanged.connect(self._fill_table)
        language_title.setBuddy(self.language_combo)

        self.table = QTableWidget(0, len(_HEADERS))
        self.table.setHorizontalHeaderLabels(_HEADERS)
        self.table.setAccessibleName("Vozes")
        self.table.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
        self.table.setSelectionMode(QAbstractItemView.SelectionMode.SingleSelection)
        self.table.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
        self.table.verticalHeader().setVisible(False)
        self.table.horizontalHeader().setSectionResizeMode(QHeaderView.ResizeMode.Stretch)
        self.table.itemSelectionChanged.connect(self._update_buttons)

        self.status_label = QLabel(_LOADING)
        self.status_label.setWordWrap(True)
        self.download_button = QPushButton("Baixar")
        self.download_button.clicked.connect(self._download_selected)
        self.remove_button = QPushButton("Remover")
        self.remove_button.clicked.connect(self._remove_selected)
        close_button = QPushButton("Fechar")
        close_button.clicked.connect(self.accept)

        top = QHBoxLayout()
        top.addWidget(language_title)
        top.addWidget(self.language_combo, 1)
        buttons = QHBoxLayout()
        buttons.addWidget(self.download_button)
        buttons.addWidget(self.remove_button)
        buttons.addStretch(1)
        buttons.addWidget(close_button)
        layout = QVBoxLayout(self)
        layout.addLayout(top)
        layout.addWidget(self.table, 1)
        layout.addWidget(self.status_label)
        layout.addLayout(buttons)

        self._refresh()
        # Only plain values go to the worker thread (see ui/tasks.py).
        run_async(lambda: fetch(cache_file), self._on_catalog, self._on_catalog_failed)

    # ---- data ----------------------------------------------------------------

    def _on_catalog(self, catalog: list[CatalogVoice]) -> None:
        self._catalog = catalog
        self.status_label.setText("")
        self._refresh(prefer_portuguese=True)

    def _on_catalog_failed(self, exc: Exception) -> None:
        self.status_label.setText(user_message(exc))
        self._refresh()

    def _rows(self) -> list[_Row]:
        installed = {voice.key for voice in installed_voices(self._voices_dir)}
        rows = [
            _Row(
                key=voice.key,
                label=voice.label,
                name=_pretty(voice.name),
                language=voice.language,
                quality=voice.quality,
                size=f"{round(voice.size_bytes / _MEGABYTE)} MB",
                installed=voice.key in installed,
            )
            for voice in self._catalog
        ]
        listed = {row.key for row in rows}
        for key in sorted(installed - listed):  # installed, but not in the list
            language, name, quality = parse_key(key)
            label = Voice(key, self._voices_dir / f"{key}.onnx").label
            rows.append(_Row(key, label, _pretty(name), language, quality, "—", True))
        return rows

    def _refresh(self, prefer_portuguese: bool = False) -> None:
        """Rebuild the language list and the table, keeping the choices made."""
        rows = self._rows()
        chosen = self.language_combo.currentData()
        languages: list[str] = []
        for row in rows:
            if row.language not in languages:
                languages.append(row.language)
        if prefer_portuguese or self.language_combo.count() == 0:
            chosen = "pt_BR" if "pt_BR" in languages else None
        self.language_combo.blockSignals(True)
        self.language_combo.clear()
        self.language_combo.addItem(_ALL_LANGUAGES, None)
        for code in languages:
            self.language_combo.addItem(language_label(code), code)
        index = self.language_combo.findData(chosen) if chosen else 0
        self.language_combo.setCurrentIndex(max(index, 0))
        self.language_combo.blockSignals(False)
        self._fill_table()

    def _fill_table(self) -> None:
        selected = self._selected_key()
        language = self.language_combo.currentData()
        rows = [row for row in self._rows() if language is None or row.language == language]
        self.table.setRowCount(len(rows))
        for index, row in enumerate(rows):
            cells = [
                row.name,
                language_label(row.language),
                quality_label(row.quality),
                row.size,
                "Instalada" if row.installed else "Disponível",
            ]
            for column, text in enumerate(cells):
                item = QTableWidgetItem(text)
                item.setData(Qt.ItemDataRole.UserRole, row.key)
                item.setData(Qt.ItemDataRole.UserRole + 1, row.installed)
                item.setData(Qt.ItemDataRole.UserRole + 2, row.label)
                self.table.setItem(index, column, item)
            if row.key == selected:
                self.table.selectRow(index)
        self._update_buttons()

    # ---- actions ---------------------------------------------------------------

    def _selected_item(self) -> QTableWidgetItem | None:
        row = self.table.currentRow()
        if row < 0 or not self.table.selectedItems():
            return None
        return self.table.item(row, 0)

    def _selected_key(self) -> str | None:
        item = self._selected_item()
        return item.data(Qt.ItemDataRole.UserRole) if item is not None else None

    def _update_buttons(self) -> None:
        item = self._selected_item()
        installed = item.data(Qt.ItemDataRole.UserRole + 1) if item is not None else None
        self.download_button.setEnabled(installed is False)
        self.remove_button.setEnabled(installed is True)

    def _download_selected(self) -> None:
        key = self._selected_key()
        if key is None:
            return
        voice = download_voice_with_progress(
            self, key, self._voices_dir, self._notify, self._download
        )
        if voice is not None:
            self.changed = True
        self._fill_table()

    def _remove_selected(self) -> None:
        item = self._selected_item()
        if item is None:
            return
        label = item.data(Qt.ItemDataRole.UserRole + 2)
        yes = QMessageBox.StandardButton.Yes
        answer = QMessageBox.question(
            self, APP_NAME, f"Remover a voz {label}?", yes | QMessageBox.StandardButton.No, yes
        )
        if answer != yes:
            return
        remove_voice(item.data(Qt.ItemDataRole.UserRole), self._voices_dir)
        self.changed = True
        self._fill_table()


def _pretty(name: str) -> str:
    text = name.replace("_", " ")
    return text[:1].upper() + text[1:]
