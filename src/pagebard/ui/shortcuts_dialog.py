"""Help window listing the keyboard shortcuts and mouse gestures."""

from PySide6.QtWidgets import (
    QAbstractItemView,
    QDialog,
    QDialogButtonBox,
    QHeaderView,
    QTableWidget,
    QTableWidgetItem,
    QVBoxLayout,
    QWidget,
)

from pagebard.core.i18n import _
from pagebard.ui.messages import APP_NAME

SHORTCUTS = [
    ("Ctrl+O", _("Open a PDF")),
    ("Ctrl+E", _("Export the reading to MP3")),
    ("Ctrl+Q", _("Quit")),
    (_("Space"), _("Play, pause or resume reading")),
    ("Esc", _("Stop reading; when stopped, clears the selection and the starting point")),
    (_("+ or ="), _("Read faster")),
    ("-", _("Read slower")),
    ("Ctrl++", _("Zoom in")),
    ("Ctrl+-", _("Zoom out")),
    ("Ctrl+0", _("Fit the page to the window width")),
    ("Ctrl+C", _("Copy the selected passage")),
    ("Page Up / Page Down", _("Scroll one screen up or down")),
    ("Home / End", _("Go to the start or the end of the document")),
    ("F1", _("Show this list")),
    (_("Click a word"), _("Start reading from that point")),
    (_("Double-click a word"), _("Read from there right away")),
    (_("Drag over the text"), _("Select a passage to read only that")),
    (_("Right click"), _("Menu with Read from here, Read selection and Copy")),
    (_("Ctrl + mouse wheel"), _("Zoom the page in or out")),
]


class ShortcutsDialog(QDialog):
    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setWindowTitle(_("Keyboard shortcuts — {app}").format(app=APP_NAME))
        self.resize(720, 620)
        self._table = QTableWidget(len(SHORTCUTS), 2)
        self._table.setHorizontalHeaderLabels([_("Key or gesture"), _("What it does")])
        self._table.setAccessibleName(_("Keyboard shortcuts"))
        self._table.verticalHeader().setVisible(False)
        self._table.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
        self._table.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
        header = self._table.horizontalHeader()
        header.setSectionResizeMode(0, QHeaderView.ResizeMode.ResizeToContents)
        header.setSectionResizeMode(1, QHeaderView.ResizeMode.Stretch)
        for row, (key, what) in enumerate(SHORTCUTS):
            self._table.setItem(row, 0, QTableWidgetItem(key))
            self._table.setItem(row, 1, QTableWidgetItem(what))
        self._table.setWordWrap(True)  # long explanations wrap instead of being cut
        self._table.resizeRowsToContents()
        buttons = QDialogButtonBox(QDialogButtonBox.StandardButton.Close)
        buttons.rejected.connect(self.reject)
        buttons.accepted.connect(self.accept)
        layout = QVBoxLayout(self)
        layout.addWidget(self._table, 1)
        layout.addWidget(buttons)

    def rows(self) -> list[tuple[str, str]]:
        return [
            (self._table.item(row, 0).text(), self._table.item(row, 1).text())
            for row in range(self._table.rowCount())
        ]


def show_shortcuts(parent: QWidget | None) -> None:
    dialog = ShortcutsDialog(parent)
    dialog.exec()
    dialog.deleteLater()
