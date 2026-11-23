"""Text shown to the user by the interface, and how errors are displayed."""

from PySide6.QtWidgets import QMessageBox, QWidget

APP_NAME = "Pagebard"

MSG_NO_TEXT = "Este PDF não tem texto para ler."
MSG_OFFER_OCR = (
    "Este PDF não tem texto (parece escaneado). Reconhecer o texto agora? "
    "Pode levar alguns minutos."
)
MSG_OCR_NOTHING = "O reconhecimento não encontrou texto neste PDF."
MSG_NEED_VOICE = (
    "Para ler em voz alta é preciso baixar uma voz (63 MB, só na primeira "
    "vez). Baixar agora?"
)
MSG_EMPTY_RANGE = "Não há texto para ler nas páginas escolhidas."


def show_error(parent: QWidget | None, text: str) -> None:
    QMessageBox.warning(parent, APP_NAME, text)
