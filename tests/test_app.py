from PySide6.QtCore import QCoreApplication

from leitorpdf.app import install_translations


def test_standard_dialog_buttons_are_in_portuguese(qapp):
    assert install_translations(qapp)
    assert QCoreApplication.translate("QPlatformTheme", "Cancel") == "Cancelar"
    assert QCoreApplication.translate("QPlatformTheme", "&Yes") == "&Sim"


def test_quiet_qt_logging_silences_known_noise(qapp):
    from PySide6.QtCore import QLoggingCategory

    from leitorpdf.app import quiet_qt_logging

    quiet_qt_logging()
    assert not QLoggingCategory("qt.qpa.wayland.textinput").isWarningEnabled()
    assert not QLoggingCategory("qt.qpa.services").isWarningEnabled()
    assert not QLoggingCategory("qt.multimedia.ffmpeg").isInfoEnabled()
    assert QLoggingCategory("qt.qpa.wayland.textinput").isCriticalEnabled()
    assert QLoggingCategory("qt.some.other.area").isWarningEnabled()
