"""The document as one text, tied to where each piece sits on the pages."""

from bisect import bisect_left, bisect_right
from dataclasses import dataclass

from leitorpdf.core.pdf import PdfText, Rect
from leitorpdf.core.segmenter import Sentence, split_sentences

_PAGE_BREAK = "\n\n"


@dataclass(frozen=True)
class PlacedWord:
    start: int  # offsets into Reading.text
    end: int
    page: int  # 0-based
    rect: Rect
    line: int  # unique per line across the whole document


class Reading:
    """Immutable. Offsets are positions in `text`; pages are 0-based unless noted."""

    def __init__(
        self,
        text: str,
        words: tuple[PlacedWord, ...],
        page_sizes: tuple[tuple[float, float], ...],
        page_word_ranges: tuple[tuple[int, int], ...],
    ) -> None:
        self.text = text
        self.words = words
        self.page_sizes = page_sizes
        self.page_count = len(page_sizes)
        self.sentences: tuple[Sentence, ...] = tuple(split_sentences(text))
        self._page_word_ranges = page_word_ranges
        self._word_ends = [word.end for word in words]
        self._sentence_ends = [sentence.end for sentence in self.sentences]
        self._sentence_pages = [self.page_of(s.start) for s in self.sentences]

    def rects(self, start: int, end: int) -> list[tuple[int, Rect]]:
        """(page, rectangle) covering the words in [start, end), one per line."""
        if start >= end:
            return []
        result: list[tuple[int, Rect]] = []
        current_line = None
        for index in range(bisect_right(self._word_ends, start), len(self.words)):
            word = self.words[index]
            if word.start >= end:
                break
            if word.line == current_line:
                page, box = result[-1]
                result[-1] = (page, _union(box, word.rect))
            else:
                result.append((word.page, word.rect))
                current_line = word.line
        return result

    def page_of(self, offset: int) -> int:
        """Page of the first word at or after offset (of the last word past the end)."""
        if not self.words:
            return 0
        index = min(bisect_right(self._word_ends, offset), len(self.words) - 1)
        return self.words[index].page

    def word_at(self, page: int, x: float, y: float, tolerance: float = 2.0) -> int | None:
        """Index of the word under the point, or None."""
        for index in self._page_range(page):
            x0, y0, x1, y1 = self.words[index].rect
            if x0 - tolerance <= x <= x1 + tolerance and y0 - tolerance <= y <= y1 + tolerance:
                return index
        return None

    def nearest_word(self, page: int, x: float, y: float) -> int | None:
        """Index of the word closest to the point on that page, or None."""
        best, best_distance = None, float("inf")
        for index in self._page_range(page):
            distance = _distance_squared(self.words[index].rect, x, y)
            if distance < best_distance:
                best, best_distance = index, distance
        return best

    def sentence_index_at(self, offset: int) -> int | None:
        """The sentence containing offset, or the first one after it."""
        index = bisect_right(self._sentence_ends, offset)
        return index if index < len(self.sentences) else None

    def sentence_page(self, index: int) -> int:
        return self._sentence_pages[index]

    def sentences_between(self, start: int, end: int) -> list[Sentence]:
        """Sentences of text[start:end]; the first and last may be partial."""
        if start >= end:
            return []
        return [
            Sentence(text=piece.text, start=piece.start + start, end=piece.end + start)
            for piece in split_sentences(self.text[start:end])
        ]

    def slice_for_pages(self, first: int, last: int) -> tuple[int, int]:
        """(i, j): sentences[i:j] start on pages first..last (1-based, inclusive)."""
        begin = bisect_left(self._sentence_pages, first - 1)
        finish = bisect_right(self._sentence_pages, last - 1)
        return (begin, finish) if begin < finish else (0, 0)

    def _page_range(self, page: int) -> range:
        if 0 <= page < len(self._page_word_ranges):
            return range(*self._page_word_ranges[page])
        return range(0)


def build_reading(doc: PdfText) -> Reading:
    parts: list[str] = []
    words: list[PlacedWord] = []
    ranges: list[tuple[int, int]] = []
    offset = 0
    line_base = 0
    for page, (page_text, page_words) in enumerate(zip(doc.pages, doc.words)):
        first = len(words)
        if page_text:
            if parts:
                offset += len(_PAGE_BREAK)
            for word in page_words:
                words.append(
                    PlacedWord(
                        start=offset + word.start,
                        end=offset + word.end,
                        page=page,
                        rect=word.rect,
                        line=line_base + word.line,
                    )
                )
            if page_words:
                line_base += page_words[-1].line + 1
            parts.append(page_text)
            offset += len(page_text)
        ranges.append((first, len(words)))
    return Reading(
        text=_PAGE_BREAK.join(parts),
        words=tuple(words),
        page_sizes=doc.page_sizes,
        page_word_ranges=tuple(ranges),
    )


def _union(a: Rect, b: Rect) -> Rect:
    return (min(a[0], b[0]), min(a[1], b[1]), max(a[2], b[2]), max(a[3], b[3]))


def _distance_squared(rect: Rect, x: float, y: float) -> float:
    dx = max(rect[0] - x, 0.0, x - rect[2])
    dy = max(rect[1] - y, 0.0, y - rect[3])
    return dx * dx + dy * dy
