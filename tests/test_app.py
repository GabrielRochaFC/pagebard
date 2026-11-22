from PySide6.QtCore import QCoreApplication

from leitorpdf.app import install_translations


def test_standard_dialog_buttons_are_in_portuguese(qapp):
    assert install_translations(qapp)
    assert QCoreApplication.translate("QPlatformTheme", "Cancel") == "Cancelar"
    assert QCoreApplication.translate("QPlatformTheme", "&Yes") == "&Sim"
