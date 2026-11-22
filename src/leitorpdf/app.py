"""Application entry point."""

import sys

from PySide6.QtCore import QCoreApplication, QLibraryInfo, QTranslator
from PySide6.QtWidgets import QApplication

from leitorpdf.ui.main_window import MainWindow
from leitorpdf.ui.messages import APP_NAME

APP_ID = "io.github.leitorpdf.LeitorPDF"


def install_translations(app: QCoreApplication) -> bool:
    """Put Qt's own texts (dialog buttons, file chooser) in Portuguese."""
    translator = QTranslator(app)
    folder = QLibraryInfo.path(QLibraryInfo.LibraryPath.TranslationsPath)
    if not translator.load("qtbase_pt_BR", folder):
        return False
    return app.installTranslator(translator)


def main() -> int:
    app = QApplication(sys.argv)
    app.setApplicationName(APP_NAME)
    app.setApplicationDisplayName(APP_NAME)
    app.setDesktopFileName(APP_ID)
    install_translations(app)
    window = MainWindow()
    window.show()
    return app.exec()
