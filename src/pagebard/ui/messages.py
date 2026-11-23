"""Text shown to the user by the interface, and how errors are displayed."""

from PySide6.QtWidgets import QMessageBox, QWidget

from pagebard import APP_NAME
from pagebard.core.i18n import _


MSG_NO_TEXT = _("This PDF has no text to read.")
MSG_OFFER_OCR = (
    _(
        "This PDF has no text (it looks scanned). Recognize the text now? It may take "
        "a few minutes."
    )
)
MSG_OCR_NOTHING = _("Recognition found no text in this PDF.")
MSG_NEED_VOICE = (
    _(
        "To read aloud, a voice has to be downloaded (about 60 MB, only the first "
        "time). Download it now?"
    )
)
MSG_EMPTY_RANGE = _("There is no text to read on the chosen pages.")


def show_error(parent: QWidget | None, text: str) -> None:
    QMessageBox.warning(parent, APP_NAME, text)
