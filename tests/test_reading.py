import pytest

from leitorpdf.core.pdf import load_pdf
from leitorpdf.core.reading import build_reading


@pytest.fixture
def reading(make_pdf):
    return build_reading(load_pdf(make_pdf(["Um dois. Três quatro.", "", "Cinco seis."])))


def center(word):
    return (word.rect[0] + word.rect[2]) / 2, (word.rect[1] + word.rect[3]) / 2


def test_text_and_sentences(reading):
    assert reading.text == "Um dois. Três quatro.\n\nCinco seis."
    assert [s.text for s in reading.sentences] == ["Um dois.", "Três quatro.", "Cinco seis."]
    assert all(reading.text[s.start : s.end] == s.text for s in reading.sentences)
    assert reading.page_count == 3
    assert reading.page_sizes == ((595.0, 842.0),) * 3


def test_words_carry_document_offsets_and_pages(reading):
    assert [reading.text[w.start : w.end] for w in reading.words] == [
        "Um", "dois.", "Três", "quatro.", "Cinco", "seis.",
    ]  # fmt: skip
    assert [w.page for w in reading.words] == [0, 0, 0, 0, 2, 2]


def test_lines_are_unique_across_pages(reading):
    assert reading.words[0].line == reading.words[3].line
    assert reading.words[4].line > reading.words[3].line


def test_rects_cover_the_words_of_a_range(reading):
    first = reading.sentences[0]
    [(page, rect)] = reading.rects(first.start, first.end)
    assert page == 0
    assert rect[0] == reading.words[0].rect[0]
    assert rect[2] == reading.words[1].rect[2]
    assert rect[2] < reading.words[2].rect[0]  # stops before "Três"


def test_rects_one_per_line(make_pdf):
    reading = build_reading(load_pdf(make_pdf(["Linha um\nlinha dois"])))
    rects = reading.rects(0, len(reading.text))
    assert len(rects) == 2
    assert rects[0][1][1] < rects[1][1][1]  # first line above the second
    assert reading.rects(3, 3) == []
    assert reading.rects(5, 2) == []


def test_rects_span_pages(reading):
    assert [page for page, _ in reading.rects(0, len(reading.text))] == [0, 2]


def test_page_of(reading):
    assert reading.page_of(0) == 0
    assert reading.page_of(reading.words[4].start + 1) == 2
    assert reading.page_of(reading.words[3].end) == 2  # the gap belongs to what follows
    assert reading.page_of(len(reading.text) + 50) == 2


def test_word_at_and_nearest(reading):
    cx, cy = center(reading.words[2])
    assert reading.word_at(0, cx, cy) == 2
    assert reading.word_at(0, 500, 700) is None
    assert reading.nearest_word(0, 500, 700) == 3
    assert reading.word_at(1, cx, cy) is None
    assert reading.nearest_word(1, cx, cy) is None
    assert reading.word_at(2, *center(reading.words[5])) == 5
    assert reading.word_at(7, cx, cy) is None
    assert reading.nearest_word(-1, cx, cy) is None


def test_word_at_tolerance(reading):
    word = reading.words[0]
    just_left = word.rect[0] - 1.5
    cy = center(word)[1]
    assert reading.word_at(0, just_left, cy) == 0
    assert reading.word_at(0, just_left, cy, tolerance=0) is None


def test_sentence_index_at(reading):
    assert reading.sentence_index_at(0) == 0
    assert reading.sentence_index_at(reading.words[2].start + 1) == 1
    assert reading.sentence_index_at(reading.words[3].end + 1) == 2  # in the page gap
    assert reading.sentence_index_at(len(reading.text)) is None


def test_sentences_between_can_be_partial(reading):
    start, end = reading.words[1].start, reading.words[2].end  # "dois. Três"
    pieces = reading.sentences_between(start, end)
    assert [s.text for s in pieces] == ["dois.", "Três"]
    assert all(reading.text[s.start : s.end] == s.text for s in pieces)
    assert reading.sentences_between(5, 5) == []


def test_slice_for_pages(reading):
    assert reading.slice_for_pages(1, 3) == (0, 3)
    assert reading.slice_for_pages(1, 1) == (0, 2)
    assert reading.slice_for_pages(2, 2) == (0, 0)
    assert reading.slice_for_pages(2, 3) == (2, 3)
    assert reading.slice_for_pages(3, 3) == (2, 3)


def test_sentence_page(reading):
    assert [reading.sentence_page(i) for i in range(3)] == [0, 0, 2]


def test_document_without_text(make_pdf):
    reading = build_reading(load_pdf(make_pdf(["", ""])))
    assert reading.text == ""
    assert reading.words == ()
    assert reading.sentences == ()
    assert reading.page_count == 2
    assert reading.rects(0, 10) == []
    assert reading.page_of(0) == 0
    assert reading.word_at(0, 10, 10) is None
    assert reading.nearest_word(0, 10, 10) is None
    assert reading.sentence_index_at(0) is None
    assert reading.sentences_between(0, 10) == []
    assert reading.slice_for_pages(1, 2) == (0, 0)
