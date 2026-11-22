"""Text shown to the user by the interface, and how errors are displayed."""

from PySide6.QtWidgets import QMessageBox, QWidget

APP_NAME = "LeitorPDF"

MSG_NO_TEXT = (
    "Este PDF não tem texto para ler — parece ser um documento escaneado. "
    "O reconhecimento de texto (OCR) ainda não está disponível."
)
MSG_NEED_VOICE = (
    "Para ler em voz alta é preciso baixar uma voz (63 MB, só na primeira "
    "vez). Baixar agora?"
)
MSG_EMPTY_RANGE = "Não há texto para ler nas páginas escolhidas."


def offer_ocr_text(scanned: int, total: int) -> str:
    """The question asked when a PDF has pages that are only pictures."""
    if scanned == total:
        return (
            "Este PDF não tem texto (parece escaneado). Reconhecer o texto agora? "
            "Pode levar alguns minutos."
        )
    return (
        f"{scanned} de {total} páginas deste PDF não têm texto (parecem escaneadas). "
        "Reconhecer o texto delas agora? Pode levar alguns minutos."
    )


def show_error(parent: QWidget | None, text: str) -> None:
    QMessageBox.warning(parent, APP_NAME, text)
