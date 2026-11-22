"""Split text into sentences that are synthesized and highlighted one by one."""

import re
from dataclasses import dataclass

MAX_SENTENCE_CHARS = 300

_PARAGRAPH_BREAK = re.compile(r"\n\s*\n")
# Sentence punctuation plus any closing quotes/brackets, followed by whitespace.
_SENTENCE_END = re.compile(r"""[.!?…]+["'”’)\]»]*(?=\s)""")
_OPENERS = "\"'“‘([«—"
_SOFT_BREAKS = ",;:"
_ABBREVIATIONS = frozenset(
    "sr sra srta dr dra prof profa av art cap ed etc ex fig nº núm pág pp tel "
    "vol vs exmo ltda cia".split()
)


@dataclass(frozen=True)
class Sentence:
    text: str
    start: int
    end: int


def split_sentences(text: str) -> list[Sentence]:
    sentences: list[Sentence] = []
    position = 0
    for match in _PARAGRAPH_BREAK.finditer(text):
        _split_paragraph(text, position, match.start(), sentences)
        position = match.end()
    _split_paragraph(text, position, len(text), sentences)
    return sentences


def _split_paragraph(text: str, start: int, end: int, out: list[Sentence]) -> None:
    piece_start = start
    for match in _SENTENCE_END.finditer(text, start, end):
        if _is_sentence_boundary(text, match, start, end):
            _emit_capped(text, piece_start, match.end(), out)
            piece_start = match.end()
    _emit_capped(text, piece_start, end, out)


def _is_sentence_boundary(text: str, match: re.Match, start: int, end: int) -> bool:
    following = match.end()
    while following < end and text[following].isspace():
        following += 1
    if following >= end:
        return False  # trailing whitespace only; the paragraph end closes it
    nxt = text[following]
    if not (nxt.isupper() or nxt.isdigit() or nxt in _OPENERS):
        return False
    if match.group().startswith(".") and not match.group().startswith(".."):
        word_start = match.start()
        while word_start > start and not text[word_start - 1].isspace():
            word_start -= 1
        word = text[word_start : match.start()].lstrip(_OPENERS)
        if word.lower() in _ABBREVIATIONS:
            return False
        if len(word) == 1 and word.isupper():
            return False  # an initial, as in "J. K. Rowling"
        if len(word) == 1 and word.isalpha() and nxt.isdigit():
            return False  # "p. 45", "n. 9.394"
    return True


def _emit_capped(text: str, start: int, end: int, out: list[Sentence]) -> None:
    """Emit text[start:end], cut into pieces of at most MAX_SENTENCE_CHARS."""
    while True:
        while start < end and text[start].isspace():
            start += 1
        while end > start and text[end - 1].isspace():
            end -= 1
        if end - start <= MAX_SENTENCE_CHARS:
            _emit(text, start, end, out)
            return
        cut = _cut_point(text, start, end)
        _emit(text, start, cut, out)
        start = cut


def _cut_point(text: str, start: int, end: int) -> int:
    limit = start + MAX_SENTENCE_CHARS
    for i in range(limit - 1, start, -1):
        if text[i] in _SOFT_BREAKS and i + 1 < end and text[i + 1].isspace():
            return i + 1
    for i in range(limit - 1, start, -1):
        if text[i].isspace():
            return i
    return limit


def _emit(text: str, start: int, end: int, out: list[Sentence]) -> None:
    while end > start and text[end - 1].isspace():
        end -= 1
    piece = text[start:end]
    if any(ch.isalnum() for ch in piece):
        out.append(Sentence(text=piece, start=start, end=end))
