"""Extract readable text from a PDF, one normalized string per page."""

import os
import re
from dataclasses import dataclass
from pathlib import Path

import pymupdf

from leitorpdf.core.errors import LeitorError

MSG_NOT_FOUND = (
    "Não foi possível abrir o arquivo. Verifique se ele ainda existe e se "
    "você tem permissão para lê-lo."
)
MSG_INVALID = "Este arquivo não é um PDF válido ou está danificado."
MSG_PASSWORD = (
    "Este PDF é protegido por senha. Ainda não é possível abrir PDFs com senha."
)

# A word split across lines: "exem-\nplo" -> "exemplo".
_HYPHEN_BREAK = re.compile(r"(?<=\w)-\n(?=\w)")
# Default block flags, minus ligature preservation so "ﬁ" comes out as "fi".
_TEXT_FLAGS = pymupdf.TEXTFLAGS_BLOCKS & ~pymupdf.TEXT_PRESERVE_LIGATURES
_BLOCK_TEXT = 4
_BLOCK_TYPE = 6
_TEXT_BLOCK = 0

# MuPDF reports problems through exceptions; keep its stderr chatter off.
pymupdf.TOOLS.mupdf_display_errors(False)
pymupdf.TOOLS.mupdf_display_warnings(False)


class PdfError(LeitorError):
    pass


@dataclass(frozen=True)
class PdfText:
    path: Path
    pages: tuple[str, ...]

    @property
    def has_text(self) -> bool:
        return any(self.pages)


def load_pdf(path: str | Path) -> PdfText:
    path = Path(path)
    if not path.is_file() or not os.access(path, os.R_OK):
        raise PdfError(MSG_NOT_FOUND)
    try:
        doc = pymupdf.open(path)
    except Exception as exc:
        raise PdfError(MSG_INVALID) from exc
    try:
        if not doc.is_pdf:
            raise PdfError(MSG_INVALID)
        if doc.needs_pass:
            raise PdfError(MSG_PASSWORD)
        try:
            pages = tuple(_page_text(page) for page in doc)
        except Exception as exc:
            raise PdfError(MSG_INVALID) from exc
    finally:
        doc.close()
    return PdfText(path=path, pages=pages)


def _page_text(page: pymupdf.Page) -> str:
    paragraphs = []
    for block in page.get_text("blocks", sort=True, flags=_TEXT_FLAGS):
        if block[_BLOCK_TYPE] != _TEXT_BLOCK:
            continue
        text = _HYPHEN_BREAK.sub("", block[_BLOCK_TEXT])
        text = " ".join(text.split())
        if text:
            paragraphs.append(text)
    return "\n\n".join(paragraphs)
