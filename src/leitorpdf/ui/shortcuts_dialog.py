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

from leitorpdf.ui.messages import APP_NAME

SHORTCUTS = [
    ("Ctrl+O", "Abrir um PDF"),
    ("Ctrl+E", "Exportar a leitura para MP3"),
    ("Ctrl+Q", "Sair"),
    ("Espaço", "Reproduzir, pausar ou continuar a leitura"),
    ("Esc", "Parar a leitura; parado, limpa a seleção e o ponto de início"),
    ("+ ou =", "Leitura mais rápida"),
    ("-", "Leitura mais devagar"),
    ("Ctrl++", "Aumentar a página"),
    ("Ctrl+-", "Diminuir a página"),
    ("Ctrl+0", "Ajustar a página à largura da janela"),
    ("Ctrl+C", "Copiar o trecho selecionado"),
    ("Page Up / Page Down", "Rolar uma tela para cima ou para baixo"),
    ("Home / End", "Ir ao começo ou ao fim do documento"),
    ("F1", "Mostrar esta lista"),
    ("Clique numa palavra", "Começar a leitura daquele ponto"),
    ("Duplo clique numa palavra", "Ler a partir dali imediatamente"),
    ("Arrastar sobre o texto", "Selecionar um trecho para ler só ele"),
    ("Botão direito", "Menu com Ler a partir daqui, Ler seleção e Copiar"),
    ("Ctrl + roda do mouse", "Aumentar ou diminuir a página"),
]


class ShortcutsDialog(QDialog):
    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setWindowTitle(f"Atalhos de teclado — {APP_NAME}")
        self.resize(720, 620)
        self._table = QTableWidget(len(SHORTCUTS), 2)
        self._table.setHorizontalHeaderLabels(["Tecla ou gesto", "O que faz"])
        self._table.setAccessibleName("Atalhos de teclado")
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
