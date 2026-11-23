from PySide6.QtCore import QCoreApplication

from pagebard.app import install_translations


def test_standard_dialog_buttons_are_in_portuguese(qapp):
    assert install_translations(qapp)
    assert QCoreApplication.translate("QPlatformTheme", "Cancel") == "Cancelar"
    assert QCoreApplication.translate("QPlatformTheme", "&Yes") == "&Sim"


def test_quiet_qt_logging_silences_known_noise(qapp):
    from PySide6.QtCore import QLoggingCategory

    from pagebard.app import quiet_qt_logging

    quiet_qt_logging()
    assert not QLoggingCategory("qt.qpa.wayland.textinput").isWarningEnabled()
    assert not QLoggingCategory("qt.qpa.services").isWarningEnabled()
    assert not QLoggingCategory("qt.multimedia.ffmpeg").isInfoEnabled()
    # Inside the Flatpak sandbox Qt cannot reach PipeWire and uses PulseAudio.
    assert not QLoggingCategory("qt.multimedia.pipewire.registry").isWarningEnabled()
    assert QLoggingCategory("qt.multimedia.pipewire").isWarningEnabled()
    assert QLoggingCategory("qt.qpa.wayland.textinput").isCriticalEnabled()
    assert QLoggingCategory("qt.some.other.area").isWarningEnabled()


def test_file_given_on_the_command_line():
    from pagebard.app import file_argument

    assert file_argument(["pagebard"]) is None
    assert file_argument(["pagebard", "/tmp/a.pdf"]) == "/tmp/a.pdf"
    assert file_argument(["pagebard", "--estilo", "x", "-v"]) == "x"
    assert file_argument(["pagebard", "-platform"]) is None
    assert file_argument(["pagebard", "file:///tmp/meu%20livro.pdf"]) == "/tmp/meu livro.pdf"
