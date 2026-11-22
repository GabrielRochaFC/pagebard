"""Application entry point."""

import sys

from PySide6.QtCore import QCoreApplication, QLibraryInfo, QLoggingCategory, QTranslator
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


def quiet_qt_logging() -> None:
    """Silence harmless chatter Qt prints on a normal run.

    Wayland text-input bookkeeping, the desktop portal refusing a second
    registration, and the FFmpeg version banner say nothing about this app.
    QT_LOGGING_RULES in the environment still overrides this.
    """
    QLoggingCategory.setFilterRules(
        "qt.qpa.wayland.textinput.warning=false\n"
        "qt.qpa.wayland.textinput.info=false\n"
        "qt.qpa.services.warning=false\n"
        "qt.multimedia.ffmpeg.info=false"
    )


def main() -> int:
    quiet_qt_logging()
    app = QApplication(sys.argv)
    app.setStyle("Fusion")  # same look on every desktop; follows light/dark
    app.setApplicationName(APP_NAME)
    app.setApplicationDisplayName(APP_NAME)
    app.setDesktopFileName(APP_ID)
    install_translations(app)
    window = MainWindow()
    window.show()
    return app.exec()
