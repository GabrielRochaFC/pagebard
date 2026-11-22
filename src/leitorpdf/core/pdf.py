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

# Marks where a word may be split at a line end; shown as "-" only there.
_SOFT_HYPHEN = "\u00ad"
# Fewer lines than this in a column say too little about where its margin is.
_MIN_COLUMN_LINES = 6
# Beyond this many lines the layout is a table or a drawing, not paragraphs.
_MAX_LINES_FOR_LAYOUT = 1500

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
            if not doc.is_pdf or doc.page_count == 0:
                raise PdfError(MSG_INVALID)
            if doc.needs_pass:
                raise PdfError(MSG_PASSWORD)
            page_count = doc.page_count
        raw_pages, sizes = [], []
        try:
            for index in range(page_count):
                with MUPDF_LOCK:  # per page, so other PyMuPDF work can interleave
                    page = doc[index]
                    entries = page.get_text("words", sort=False, flags=_TEXT_FLAGS)
                    rotation = page.rotation_matrix if page.rotation else None
                    sizes.append((float(page.rect.width), float(page.rect.height)))
                raw = [entry for entry in entries if entry[4].replace(_SOFT_HYPHEN, "")]
                raw_pages.append((raw, rotation))
        except Exception as exc:
            raise PdfError(MSG_INVALID) from exc
    finally:
        with MUPDF_LOCK:
            doc.close()

    # A file that marks its line-break hyphens with soft hyphens tells them
    # apart from real ones, so there a plain "-" at a line end is a real hyphen.
    marks_soft_hyphens = any(
        _SOFT_HYPHEN in entry[4] for raw, _ in raw_pages for entry in raw
    )
    texts, words = [], []
    for raw, rotation in raw_pages:
        text, page_words = _page_content(raw, rotation, marks_soft_hyphens)
        texts.append(text)
        words.append(page_words)
    return PdfText(
        path=path, pages=tuple(texts), words=tuple(words), page_sizes=tuple(sizes)
    )


@dataclass(frozen=True)
class _Line:
    block: int
    first: int  # index of its first and last word in the page's word list
    last: int
    x0: float
    y0: float
    x1: float
    y1: float
    first_word_width: float

    @property
    def height(self) -> float:
        return self.y1 - self.y0


def _page_content(raw: list, rotation, marks_soft_hyphens: bool) -> tuple[str, tuple[Word, ...]]:
    """Text of a page plus its words, in the order the file stores them.

    File order keeps the columns of a multi-column page together; sorting by
    position would interleave them line by line.
    """
    lines = _split_lines(raw)
    starts_paragraph = _paragraph_starts(lines, raw)
    parts: list[str] = []
    words: list[Word] = []
    position = 0

    for line_id, line in enumerate(lines):
        for index in range(line.first, line.last + 1):
            x0, y0, x1, y1, text = raw[index][:5]
            following = raw[index + 1] if index + 1 < len(raw) else None
            ends_line = index == line.last and following is not None
            new_paragraph = ends_line and starts_paragraph[line_id + 1]
            glue = None
            if ends_line and not new_paragraph:
                glue = _line_break_glue(text, following[4], marks_soft_hyphens)
            if glue == "join" and text.endswith("-"):
                text = text[:-1]  # the hyphen only marked the line break
            text = text.replace(_SOFT_HYPHEN, "")

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
                separator = "\n\n" if new_paragraph else ("" if glue else " ")
                parts.append(separator)
                position += len(separator)

    return "".join(parts), tuple(words)


def _split_lines(raw: list) -> list[_Line]:
    lines: list[_Line] = []
    start = 0
    for index in range(1, len(raw) + 1):
        if index < len(raw) and raw[index][5:7] == raw[start][5:7]:
            continue
        chunk = raw[start:index]
        lines.append(
            _Line(
                block=chunk[0][5],
                first=start,
                last=index - 1,
                x0=min(entry[0] for entry in chunk),
                y0=min(entry[1] for entry in chunk),
                x1=max(entry[2] for entry in chunk),
                y1=max(entry[3] for entry in chunk),
                first_word_width=chunk[0][2] - chunk[0][0],
            )
        )
        start = index
    return lines


def _paragraph_starts(lines: list[_Line], raw: list) -> list[bool]:
    """For each line, whether it begins a new paragraph.

    MuPDF's blocks are not paragraphs: with wide line spacing every line is a
    block of its own, and tight lists share one block. What tells a wrapped
    line from an ended one is typesetting: a line is only broken when the next
    word did not fit.
    """
    starts = [True] * len(lines)
    if len(lines) > _MAX_LINES_FOR_LAYOUT:
        for index in range(1, len(lines)):
            starts[index] = lines[index].block != lines[index - 1].block
        return starts
    edges: dict[int, float | None] = {}
    for index in range(1, len(lines)):
        above, line = lines[index - 1], lines[index]
        if raw[above.last][4].endswith(_SOFT_HYPHEN):
            starts[index] = False  # a word cut in two always goes on
            continue
        if index - 1 not in edges:
            edges[index - 1] = _column_right_edge(above, lines)
        starts[index] = not _continues(above, line, edges[index - 1])
    return starts


def _continues(above: _Line, line: _Line, right_edge: float | None) -> bool:
    """Whether `line` carries on the paragraph of the line stored before it."""
    same_block = above.block == line.block
    if right_edge is None:
        return same_block  # too little on the page to judge: trust the blocks
    taller = max(above.height, line.height)
    if taller <= 0 or abs(above.height - line.height) > 0.15 * taller:
        return False  # another font size: a heading, a caption
    wrapped = above.x1 + 0.25 * above.height + line.first_word_width > right_edge - 1.0
    if not wrapped:
        return False  # the next word would have fit: the line ended on purpose
    if same_block:
        return True
    below = line.y0 >= above.y0 + 0.5 * above.height
    if below:
        close = line.y0 - above.y1 <= 0.8 * min(above.height, line.height)
        overlapping = min(above.x1, line.x1) > max(above.x0, line.x0)
        return close and overlapping
    return line.y1 < above.y0 and line.x0 > above.x0  # top of the next column


def _column_right_edge(line: _Line, lines: list[_Line]) -> float | None:
    """Where lines of this column usually end; None if too few to tell."""
    ends = sorted(
        other.x1
        for other in lines
        if min(other.x1, line.x1) > max(other.x0, line.x0)
        and abs(other.height - line.height) <= 0.15 * max(other.height, line.height)
    )
    if len(ends) < _MIN_COLUMN_LINES:
        return None
    return ends[int(0.9 * (len(ends) - 1))]  # ignores the odd wider line


def _line_break_glue(text: str, next_text: str, marks_soft_hyphens: bool) -> str | None:
    """How the last word of a line attaches to the first word of the next.

    "join": a hyphen that only split the word ("exem-" + "plo" -> "exemplo").
    "keep": the hyphen is real ("1990-" + "1995", "estabeleceu-" + "se").
    None: nothing special; the words are separated by a space.
    """
    if text.endswith(_SOFT_HYPHEN):
        return "join"
    if len(text) < 2 or not text.endswith("-") or not text[-2].isalnum():
        return None
    if not next_text[:1].isalnum():
        return None
    if marks_soft_hyphens:
        return "keep"
    if text[-2].isalpha() and next_text[0].islower():
        return "join"
    return "keep"
