"""Extract readable text from a PDF, with the position of every word."""

import os
import threading
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

# (x0, y0, x1, y1) in PDF points, origin at the top-left of the displayed page.
Rect = tuple[float, float, float, float]

# Default word flags, minus ligature preservation so "ﬁ" comes out as "fi".
_TEXT_FLAGS = pymupdf.TEXTFLAGS_WORDS & ~pymupdf.TEXT_PRESERVE_LIGATURES

# PyMuPDF is not safe to call from two threads at once, even on different
# documents. Everything that touches it (loading here, page rendering in the
# viewer) takes this lock around each short burst of calls.
MUPDF_LOCK = threading.RLock()

# MuPDF reports problems through exceptions; keep its stderr chatter off.
pymupdf.TOOLS.mupdf_display_errors(False)
pymupdf.TOOLS.mupdf_display_warnings(False)


class PdfError(LeitorError):
    pass


@dataclass(frozen=True)
class Word:
    start: int  # offsets into the text of its own page
    end: int
    rect: Rect
    line: int  # same value for words on one line; grows in reading order


@dataclass(frozen=True)
class PdfText:
    path: Path
    pages: tuple[str, ...]  # normalized text of each page, "" when it has none
    words: tuple[tuple[Word, ...], ...]  # per page, in reading order
    page_sizes: tuple[tuple[float, float], ...]  # (width, height) in points

    @property
    def has_text(self) -> bool:
        return any(self.pages)


def load_pdf(path: str | Path) -> PdfText:
    path = Path(path)
    if not path.is_file() or not os.access(path, os.R_OK):
        raise PdfError(MSG_NOT_FOUND)
    try:
        with MUPDF_LOCK:
            doc = pymupdf.open(path)
    except Exception as exc:
        raise PdfError(MSG_INVALID) from exc
    try:
        with MUPDF_LOCK:
            if not doc.is_pdf:
                raise PdfError(MSG_INVALID)
            if doc.needs_pass:
                raise PdfError(MSG_PASSWORD)
            page_count = doc.page_count
        texts, words, sizes = [], [], []
        try:
            for index in range(page_count):
                with MUPDF_LOCK:  # per page, so the viewer can render in between
                    page = doc[index]
                    text, page_words = _page_content(page)
                    sizes.append((float(page.rect.width), float(page.rect.height)))
                texts.append(text)
                words.append(page_words)
        except Exception as exc:
            raise PdfError(MSG_INVALID) from exc
    finally:
        with MUPDF_LOCK:
            doc.close()
    return PdfText(
        path=path, pages=tuple(texts), words=tuple(words), page_sizes=tuple(sizes)
    )


def _page_content(page: pymupdf.Page) -> tuple[str, tuple[Word, ...]]:
    """Text of a page plus its words, in the order the file stores them.

    File order keeps the columns of a multi-column page together; sorting by
    position would interleave them line by line.
    """
    raw = [entry for entry in page.get_text("words", sort=False, flags=_TEXT_FLAGS) if entry[4]]
    rotation = page.rotation_matrix if page.rotation else None
    parts: list[str] = []
    words: list[Word] = []
    position = 0
    line_id = -1
    previous_line = None

    for index, (x0, y0, x1, y1, text, block, line, _number) in enumerate(raw):
        if (block, line) != previous_line:
            line_id += 1
            previous_line = (block, line)

        following = raw[index + 1] if index + 1 < len(raw) else None
        glue = _line_break_glue(text, block, line, following)
        if glue == "join":
            text = text[:-1]  # drop the hyphen that only marked the line break

        rect = pymupdf.Rect(x0, y0, x1, y1)
        if rotation is not None:
            rect = (rect * rotation).normalize()
        parts.append(text)
        words.append(
            Word(
                start=position,
                end=position + len(text),
                rect=(float(rect.x0), float(rect.y0), float(rect.x1), float(rect.y1)),
                line=line_id,
            )
        )
        position += len(text)

        if following is not None:
            if following[5] != block:
                separator = "\n\n"  # a new block is a new paragraph
            elif glue is not None:
                separator = ""
            else:
                separator = " "
            parts.append(separator)
            position += len(separator)

    return "".join(parts), tuple(words)


def _line_break_glue(text: str, block: int, line: int, following) -> str | None:
    """How a word ending in "-" at the end of a line attaches to the next line.

    "join": the hyphen only split a word ("exem-" + "plo" -> "exemplo").
    "keep": the hyphen is real ("1990-" + "1995", "Rio-" + "Grande").
    None: not that case; the words are separated by a space.
    """
    if following is None or following[5] != block or following[6] == line:
        return None  # not the last word of a line inside its block
    if len(text) < 2 or not text.endswith("-") or not text[-2].isalnum():
        return None
    next_text = following[4]
    if not next_text[0].isalnum():
        return None
    if text[-2].isalpha() and next_text[0].islower():
        return "join"
    return "keep"
