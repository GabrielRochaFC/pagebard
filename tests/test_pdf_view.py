import threading
import time

import pytest
from fakes import wait_until
from PySide6.QtCore import QPoint, Qt
from PySide6.QtGui import QColor
from PySide6.QtTest import QTest

from leitorpdf.core.pdf import load_pdf
from leitorpdf.core.reading import build_reading
from leitorpdf.ui.pdf_view import PdfView

LEFT = Qt.MouseButton.LeftButton
RIGHT = Qt.MouseButton.RightButton
NONE = Qt.KeyboardModifier.NoModifier


def render_threads():
    return [t for t in threading.enumerate() if t.name == "leitorpdf-render"]


class Signals:
    def __init__(self, view):
        self.clicked = []
        self.double_clicked = []
        self.background = 0
        self.selections = []
        self.contexts = []
        self.pages = []
        self.zooms = []
        view.word_clicked.connect(self.clicked.append)
        view.word_double_clicked.connect(self.double_clicked.append)
        view.background_clicked.connect(self._on_background)
        view.selection_changed.connect(lambda a, b: self.selections.append((a, b)))
        view.context_requested.connect(lambda word, pos: self.contexts.append((word, pos)))
        view.page_changed.connect(self.pages.append)
        view.zoom_changed.connect(self.zooms.append)

    def _on_background(self):
        self.background += 1


@pytest.fixture
def make_view(qapp):
    views = []

    def build(pages=None, size=(800, 600)):
        view = PdfView()
        view.resize(*size)
        view.show()
        views.append(view)
        return view

    yield build
    for view in views:
        view.shutdown()
        view.close()
    deadline = time.monotonic() + 2.0
    while render_threads() and time.monotonic() < deadline:
        time.sleep(0.005)
    assert render_threads() == []


@pytest.fixture
def document(make_pdf):
    path = make_pdf(["Um dois três quatro cinco.", "Seis sete.", "Oito nove dez."])
    return path, build_reading(load_pdf(path))


@pytest.fixture
def view(make_view, document, qapp):
    view = make_view()
    view.set_document(*document)
    qapp.processEvents()
    return view


@pytest.fixture
def signals(view):
    return Signals(view)


def center(view, index):
    word = view.reading.words[index]
    return view.to_view(
        word.page, (word.rect[0] + word.rect[2]) / 2, (word.rect[1] + word.rect[3]) / 2
    )


def blank_spot(view):
    """A point on page 1 far from any text."""
    return view.to_view(0, 300, 400)


def click(view, pos, button=LEFT):
    QTest.mouseClick(view.viewport(), button, NONE, pos)


def drag(view, start, end):
    viewport = view.viewport()
    QTest.mousePress(viewport, LEFT, NONE, start)
    QTest.mouseMove(viewport, QPoint((start.x() + end.x()) // 2, (start.y() + end.y()) // 2))
    QTest.mouseMove(viewport, end)
    QTest.mouseRelease(viewport, LEFT, NONE, end)


def test_empty_view_has_no_pages(make_view):
    view = make_view()
    signals = Signals(view)
    assert view.reading is None
    assert view.current_page() == 0
    assert view.to_page(QPoint(100, 100)) is None
    assert view.rendered_pages() == set()
    click(view, QPoint(100, 100))
    QTest.mouseDClick(view.viewport(), LEFT, NONE, QPoint(100, 100))
    drag(view, QPoint(50, 50), QPoint(300, 300))
    assert (signals.clicked, signals.double_clicked, signals.selections) == ([], [], [])
    assert view.selection() is None
    assert view.selected_text() == ""


def test_fits_page_width(view):
    assert view.is_fit_width()
    width = view.viewport().width()
    assert abs(view.page_rect(0).width() - (width - 24)) <= 2
    assert abs(view.zoom() - (width - 24) / 595) < 0.01


def test_fit_width_is_capped_on_very_wide_windows(make_view, document, qapp):
    view = make_view(size=(2600, 600))
    view.set_document(*document)
    qapp.processEvents()
    assert view.zoom() == 2.5
    rect = view.page_rect(0)
    assert abs((rect.left() + rect.right()) / 2 - view.viewport().width() / 2) <= 2  # centered


def test_pages_are_stacked(view):
    assert view.page_rect(0).top() == 12
    assert abs(view.page_rect(1).top() - (view.page_rect(0).bottom() + 1 + 12)) <= 1
    assert view.page_rect(0).height() == view.page_rect(1).height()


def test_coordinate_round_trip(view):
    view.go_to_page(2)
    page, x, y = view.to_page(view.to_view(1, 100, 200))
    assert page == 1
    assert abs(x - 100) < 1 and abs(y - 200) < 1


def test_point_between_pages_is_on_no_page(view):
    gap = view.to_view(0, 100, 842) + QPoint(0, 6)
    view.verticalScrollBar().setValue(view.page_rect(0).bottom() - 100)
    gap = QPoint(gap.x(), view.to_view(0, 100, 842).y() + 6)
    assert view.to_page(gap) is None


def test_visible_pages_get_rendered(view, qapp):
    wait_until(qapp, lambda: 0 in view.rendered_pages())
    image = view.viewport().grab().toImage()
    word = view.reading.words[0]
    top_left = view.to_view(0, word.rect[0], word.rect[1])
    bottom_right = view.to_view(0, word.rect[2], word.rect[3])
    dark = sum(
        1
        for x in range(top_left.x(), bottom_right.x())
        for y in range(top_left.y(), bottom_right.y())
        if image.pixelColor(x, y).lightness() < 100
    )
    assert dark > 20  # the glyphs of "Um"
    assert image.pixelColor(blank_spot(view)) == QColor("white")
    assert image.pixelColor(QPoint(3, 3)) != QColor("white")  # background around the page


def test_only_nearby_pages_stay_in_memory(make_view, make_pdf, qapp):
    path = make_pdf([f"Página {n}." for n in range(1, 31)])
    view = make_view()
    view.set_document(path, build_reading(load_pdf(path)))
    wait_until(qapp, lambda: 0 in view.rendered_pages())
    view.go_to_page(30)
    wait_until(qapp, lambda: 29 in view.rendered_pages())
    assert view.rendered_pages() <= {27, 28, 29}
    assert view.current_page() == 30


def test_click_on_word_emits_its_index(view, signals):
    click(view, center(view, 3))
    assert signals.clicked == [3]
    assert signals.background == 0
    assert view.selection() is None


def test_click_on_background(view, signals):
    click(view, blank_spot(view))
    assert signals.background == 1
    assert signals.clicked == []
    assert signals.selections == []


def test_drag_selects_words_in_reading_order(view, signals):
    words = view.reading.words
    drag(view, center(view, 1), center(view, 3))
    assert view.selection() == (words[1].start, words[3].end)
    assert view.selected_text() == "dois três quatro"
    assert signals.selections[-1] == (words[1].start, words[3].end)
    assert signals.clicked == []
    assert signals.background == 0


def test_dragging_backwards_selects_the_same_range(view):
    words = view.reading.words
    drag(view, center(view, 3), center(view, 1))
    assert view.selection() == (words[1].start, words[3].end)


def test_drag_starting_on_blank_space_uses_the_nearest_words(view):
    words = view.reading.words
    start = center(view, 4) + QPoint(60, 0)  # to the right of the last word of the line
    drag(view, start, center(view, 2))
    assert view.selection() == (words[2].start, words[4].end)


def test_click_clears_selection(view, signals):
    drag(view, center(view, 1), center(view, 3))
    click(view, center(view, 0))
    assert view.selection() is None
    assert signals.selections[-1] == (-1, -1)
    assert signals.clicked == [0]


def test_double_click_emits(view, signals):
    QTest.mouseDClick(view.viewport(), LEFT, NONE, center(view, 3))
    assert signals.double_clicked == [3]


def test_right_click_requests_context(view, signals):
    position = center(view, 3)
    click(view, position, RIGHT)
    click(view, blank_spot(view), RIGHT)
    assert [word for word, _ in signals.contexts] == [3, -1]
    assert signals.contexts[0][1] == view.viewport().mapToGlobal(position)
    assert signals.clicked == [] and signals.background == 0


def test_reading_highlight_is_painted(view, qapp):
    wait_until(qapp, lambda: 0 in view.rendered_pages())
    sentence = view.reading.sentences[0]
    word = view.reading.words[0]
    spot = view.to_view(0, word.rect[0], word.rect[1]) + QPoint(1, 1)

    view.set_reading_highlight(sentence.start, sentence.end)
    assert view.reading_highlight() == (sentence.start, sentence.end)
    color = view.viewport().grab().toImage().pixelColor(spot)
    assert color.red() > 200 and color.green() > 180 and color.blue() < 200  # amber

    view.clear_reading_highlight()
    assert view.reading_highlight() is None
    assert view.viewport().grab().toImage().pixelColor(spot) == QColor("white")


def test_selection_and_start_marker_are_painted(view, qapp):
    wait_until(qapp, lambda: 0 in view.rendered_pages())
    words = view.reading.words
    spot = view.to_view(0, words[1].rect[0], words[1].rect[1]) + QPoint(1, 1)
    drag(view, center(view, 1), center(view, 3))
    color = view.viewport().grab().toImage().pixelColor(spot)
    assert color.blue() > color.red()  # bluish

    view.clear_selection()
    view.set_start_marker(words[1].start, words[1].end)
    assert view.start_marker() == (words[1].start, words[1].end)
    under = view.to_view(0, (words[1].rect[0] + words[1].rect[2]) / 2, words[1].rect[3])
    color = view.viewport().grab().toImage().pixelColor(under)
    assert color.blue() > 200 and color.red() < 100  # the underline
    view.clear_start_marker()
    assert view.start_marker() is None


def test_scroll_to_brings_a_later_page_into_view(view, signals):
    target = view.reading.sentences[-1]  # on page 3
    view.scroll_to(target.start, target.end)
    assert view.current_page() == 3
    assert signals.pages[-1] == 3
    word = view.reading.words[-1]
    position = view.to_view(word.page, word.rect[0], word.rect[1])
    assert view.viewport().rect().contains(position)


def test_scroll_to_leaves_visible_text_alone(view):
    before = view.verticalScrollBar().value()
    first = view.reading.sentences[0]
    view.scroll_to(first.start, first.end)
    assert view.verticalScrollBar().value() == before


def test_zoom(view, signals):
    start = view.zoom()
    width = view.page_rect(0).width()
    view.zoom_in()
    assert abs(view.zoom() - start * 1.25) < 0.001
    assert not view.is_fit_width()
    assert signals.zooms[-1] == view.zoom()
    assert view.page_rect(0).width() > width
    for _ in range(20):
        view.zoom_in()
    assert view.zoom() == 4.0
    for _ in range(40):
        view.zoom_out()
    assert view.zoom() == 0.5
    view.fit_width()
    assert view.is_fit_width()
    assert abs(view.zoom() - start) < 0.001


def test_zoomed_pages_are_rendered_again(view, qapp):
    wait_until(qapp, lambda: 0 in view.rendered_pages())
    view.zoom_in()
    assert 0 not in view.rendered_pages()
    wait_until(qapp, lambda: 0 in view.rendered_pages())


def test_resize_keeps_fit_width(view, qapp):
    view.resize(500, 600)
    qapp.processEvents()
    assert abs(view.page_rect(0).width() - (view.viewport().width() - 24)) <= 2


def test_new_document_resets_state(view, document, qapp):
    sentence = view.reading.sentences[0]
    view.set_reading_highlight(sentence.start, sentence.end)
    view.set_start_marker(sentence.start, sentence.end)
    drag(view, center(view, 1), center(view, 3))
    view.go_to_page(3)
    signals = Signals(view)
    view.set_document(*document)
    assert view.reading_highlight() is None
    assert view.start_marker() is None
    assert view.selection() is None
    assert signals.selections == [(-1, -1)]
    assert view.verticalScrollBar().value() == 0
    assert view.current_page() == 1

    view.set_document(None, None)
    assert view.reading is None
    assert view.current_page() == 0
    assert view.rendered_pages() == set()


def test_keyboard_scrolls(view, qapp):
    view.setFocus()
    bar = view.verticalScrollBar()
    QTest.keyClick(view, Qt.Key.Key_PageDown)
    moved = bar.value()
    assert abs(moved - view.viewport().height()) <= 40
    QTest.keyClick(view, Qt.Key.Key_End)
    assert bar.value() == bar.maximum()
    QTest.keyClick(view, Qt.Key.Key_Home)
    assert bar.value() == 0


def test_does_not_accept_drops(view):
    assert not view.acceptDrops()
    assert not view.viewport().acceptDrops()


def test_page_without_text_ignores_the_mouse(make_view, make_pdf, qapp):
    path = make_pdf(["", ""])
    view = make_view()
    view.set_document(path, build_reading(load_pdf(path)))
    qapp.processEvents()
    signals = Signals(view)
    click(view, QPoint(400, 300))
    drag(view, QPoint(300, 200), QPoint(500, 400))
    QTest.mouseDClick(view.viewport(), LEFT, NONE, QPoint(400, 300))
    assert signals.clicked == [] and signals.double_clicked == []
    assert signals.selections == []
    assert signals.background >= 1
    assert view.selection() is None
