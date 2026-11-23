"""Application entry point."""

import sys

from PySide6.QtCore import (
    QCoreApplication,
    QLibraryInfo,
    QLoggingCategory,
    QSettings,
    QTranslator,
    QUrl,
)
from PySide6.QtGui import QIcon
from PySide6.QtWidgets import QApplication

from pagebard.ui.main_window import MainWindow
from pagebard.ui.messages import APP_NAME

APP_ID = "io.github.gabrielrochafc.Pagebard"


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
    registration, the FFmpeg version banner, and (inside the Flatpak sandbox)
    PipeWire being out of reach before Qt settles for PulseAudio say nothing
    about this app. QT_LOGGING_RULES in the environment still overrides this.
    """
    QLoggingCategory.setFilterRules(
        "qt.qpa.wayland.textinput.warning=false\n"
        "qt.qpa.wayland.textinput.info=false\n"
        "qt.qpa.services.warning=false\n"
        "qt.multimedia.ffmpeg.info=false\n"
        "qt.multimedia.pipewire.registry.warning=false"
    )


def file_argument(argv: list[str]) -> str | None:
    """The file to open, when one was given on the command line."""
    for argument in argv[1:]:
        if argument.startswith("-"):
            continue
        url = QUrl(argument)
        if url.scheme() == "file":
            return url.toLocalFile()
        return argument
    return None


def main(argv: list[str] | None = None) -> int:
    argv = sys.argv if argv is None else argv
    quiet_qt_logging()
    app = QApplication(argv)
    app.setStyle("Fusion")  # same look on every desktop; follows light/dark
    app.setApplicationName(APP_NAME)
    app.setApplicationDisplayName(APP_NAME)
    app.setDesktopFileName(APP_ID)
    app.setWindowIcon(QIcon.fromTheme(APP_ID))  # there once the app is installed
    install_translations(app)
    window = MainWindow(settings=QSettings(APP_NAME, APP_NAME))
    window.show()
    path = file_argument(app.arguments())  # Qt has removed its own options
    if path is not None:
        window.open_path(path)
    return app.exec()
