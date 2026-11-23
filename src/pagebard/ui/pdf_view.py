"""Shows the real pages of the PDF, with highlights and word selection."""

import math
from bisect import bisect_right
from pathlib import Path

from PySide6.QtCore import QPoint, QRect, Qt, QTimer, Signal
from PySide6.QtGui import (
    QColor,
    QKeyEvent,
    QMouseEvent,
    QPainter,
    QPaintEvent,
    QPalette,
    QPixmap,
    QResizeEvent,
    QWheelEvent,
)
from PySide6.QtWidgets import QAbstractScrollArea, QApplication, QWidget

from pagebard.core.pdf import Rect
from pagebard.core.reading import Reading
from pagebard.ui.page_renderer import PageRenderer

_GAP = 12  # pixels between pages and around them
_MIN_ZOOM = 0.5
_MAX_ZOOM = 4.0
_FIT_MAX_ZOOM = 2.5
_ZOOM_STEP = 1.25
_POLL_MS = 15
_READING_COLOR = QColor("#FFE08A")
_SELECTION_COLOR = QColor(56, 132, 255, 90)
_MARKER_COLOR = QColor("#2563EB")
_EMPTY_HINT = "Abra um PDF (Ctrl+O) ou arraste o arquivo para cá"

Range = tuple[int, int]


class PdfView(QAbstractScrollArea):
    word_clicked = Signal(int)  # index into reading.words
    word_double_clicked = Signal(int)
    background_clicked = Signal()
    selection_changed = Signal(int, int)  # text offsets; (-1, -1) when cleared
    context_requested = Signal(int, QPoint)  # word index or -1, global position
    page_changed = Signal(int)  # 1-based
    zoom_changed = Signal(float)

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._reading: Reading | None = None
        self._renderer = PageRenderer()
        self._generation = 0
        self._zoom = 1.0  # screen pixels per PDF point
        self._fit_width = True
        self._tops: list[int] = []
        self._sizes: list[tuple[int, int]] = []  # page sizes in pixels
        self._content_width = 0
        self._content_height = 0
        self._pixmaps: dict[int, QPixmap] = {}
        self._stale: dict[int, QPixmap] = {}  # old-zoom images shown meanwhile
        self._requested: set[int] = set()
        self._wanted: set[int] = set()  # pages worth having in memory right now
        self._page = 0
        self._highlight: Range | None = None
        self._marker: Range | None = None
        self._selection: Range | None = None
        self._overlay_rects: dict[str, dict[int, list[Rect]]] = {}
        self._pressed = False
        self._dragging = False
        self._press_pos = QPoint()
        self._press_word: int | None = None
        self._anchor_word: int | None = None
        self._swallow_release = False

        self.setVerticalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOn)
        self.setFocusPolicy(Qt.FocusPolicy.StrongFocus)
        self.setAccessibleName("Páginas do documento")
        self.viewport().setMouseTracking(True)
        self.verticalScrollBar().setSingleStep(40)
        self.horizontalScrollBar().setSingleStep(40)
        self._poll_timer = QTimer(self)
        self._poll_timer.setInterval(_POLL_MS)
        self._poll_timer.timeout.connect(self._collect_rendered)

    # ---- document ----------------------------------------------------------

    @property
    def reading(self) -> Reading | None:
        return self._reading

    def set_document(self, path: Path | None, reading: Reading | None) -> None:
        had_selection = self._selection is not None
        self._reading = reading if path is not None else None
        self._generation = self._renderer.open(path if self._reading else None)
        self._pixmaps.clear()
        self._stale.clear()
        self._requested.clear()
        self._wanted.clear()
        self._highlight = self._marker = self._selection = None
        self._overlay_rects.clear()
        self._pressed = self._dragging = False
        self._fit_width = True
        self._page = 0
        self.verticalScrollBar().setValue(0)
        self.horizontalScrollBar().setValue(0)
        self._relayout()
        if had_selection:
            self.selection_changed.emit(-1, -1)
        self.viewport().update()

    def update_reading(self, reading: Reading) -> None:
        """New text for the document already on screen (after OCR).

        Scroll position, zoom and page images stay; marks tied to the old text go.
        """
        had_selection = self._selection is not None
        self._reading = reading
        self._highlight = self._marker = self._selection = None
        self._overlay_rects.clear()
        self._pressed = self._dragging = False
        if had_selection:
            self.selection_changed.emit(-1, -1)
        self.viewport().update()

    def shutdown(self) -> None:
        """Stop the render thread. Call before the application exits."""
        self._poll_timer.stop()
        self._renderer.close()

    def rendered_pages(self) -> set[int]:
        return set(self._pixmaps)

    # ---- geometry ------------------------------------------------------------

    def zoom(self) -> float:
        return self._zoom

    def is_fit_width(self) -> bool:
        return self._fit_width

    def zoom_in(self) -> None:
        self._set_zoom(self._zoom * _ZOOM_STEP)

    def zoom_out(self) -> None:
        self._set_zoom(self._zoom / _ZOOM_STEP)

    def fit_width(self) -> None:
        self._fit_width = True
        self._relayout()

    def page_rect(self, page: int) -> QRect:
        """Where a page sits in the scrolled content, in pixels."""
        width, height = self._sizes[page]
        span = max(self.viewport().width(), self._content_width)
        return QRect((span - width) // 2, self._tops[page], width, height)

    def to_view(self, page: int, x: float, y: float) -> QPoint:
        """Viewport position of a point given in page coordinates."""
        rect = self._view_rect(page)
        return QPoint(rect.x() + round(x * self._zoom), rect.y() + round(y * self._zoom))

    def to_page(self, pos: QPoint) -> tuple[int, float, float] | None:
        """(page, x, y) under a viewport position; None outside every page."""
        page = self._page_at_y(pos.y() + self.verticalScrollBar().value())
        if page is None:
            return None
        rect = self._view_rect(page)
        if not rect.contains(pos):
            return None
        return page, (pos.x() - rect.x()) / self._zoom, (pos.y() - rect.y()) / self._zoom

    def current_page(self) -> int:
        """1-based page at the middle of the viewport; 0 without a document."""
        return self._page

    def go_to_page(self, page: int) -> None:
        if self._tops:
            index = min(max(page, 1), len(self._tops)) - 1
            self.verticalScrollBar().setValue(self._tops[index] - _GAP)

    def scroll_to(self, start: int, end: int | None = None) -> None:
        """Bring the text at [start, end) into view, if it is not already."""
        if self._reading is None:
            return
        rects = self._reading.rects(start, end if end is not None else start + 1)
        if not rects:
            return
        page = rects[0][0]
        boxes = [self._rect_to_view(page, rect) for where, rect in rects if where == page]
        top = min(box.top() for box in boxes)
        bottom = max(box.bottom() for box in boxes)
        height = self.viewport().height()
        if top < 8 or bottom > height - 8:
            bar = self.verticalScrollBar()
            bar.setValue(bar.value() + top - height // 3)
        left = min(box.left() for box in boxes)
        right = max(box.right() for box in boxes)
        if left < 8 or right > self.viewport().width() - 8:  # zoomed in
            bar = self.horizontalScrollBar()
            bar.setValue(bar.value() + left - 24)

    # ---- highlights ------------------------------------------------------------

    def set_reading_highlight(self, start: int, end: int) -> None:
        self._highlight = (start, end)
        self._set_overlay("reading", self._highlight)

    def clear_reading_highlight(self) -> None:
        self._highlight = None
        self._set_overlay("reading", None)

    def reading_highlight(self) -> Range | None:
        return self._highlight

    def set_start_marker(self, start: int, end: int) -> None:
        self._marker = (start, end)
        self._set_overlay("marker", self._marker)

    def clear_start_marker(self) -> None:
        self._marker = None
        self._set_overlay("marker", None)

    def start_marker(self) -> Range | None:
        return self._marker

    def selection(self) -> Range | None:
        return self._selection

    def selected_text(self) -> str:
        if self._reading is None or self._selection is None:
            return ""
        return self._reading.text[self._selection[0] : self._selection[1]]

    def clear_selection(self) -> None:
        self._set_selection(None)

    # ---- layout ------------------------------------------------------------------

    def _set_zoom(self, zoom: float) -> None:
        self._fit_width = False
        self._apply_zoom(min(max(zoom, _MIN_ZOOM), _MAX_ZOOM))

    def _apply_zoom(self, zoom: float) -> None:
        if self._reading is None or zoom == self._zoom:
            self._layout_pages()
            return
        bar = self.verticalScrollBar()
        fraction = bar.value() / self._content_height if self._content_height else 0.0
        self._zoom = zoom
        # Keep the old images as blurry stand-ins until the sharp ones arrive.
        self._stale = {**self._stale, **self._pixmaps}
        self._pixmaps.clear()
        self._requested.clear()
        self._layout_pages()
        bar.setValue(round(fraction * self._content_height))
        self.zoom_changed.emit(self._zoom)

    def _relayout(self) -> None:
        if self._reading is not None and self._fit_width:
            widest = max(width for width, _ in self._reading.page_sizes)
            fitted = (self.viewport().width() - 2 * _GAP) / widest
            self._apply_zoom(min(max(fitted, _MIN_ZOOM), _FIT_MAX_ZOOM))
        else:
            self._layout_pages()

    def _layout_pages(self) -> None:
        self._tops, self._sizes = [], []
        y = _GAP
        if self._reading is not None:
            for width, height in self._reading.page_sizes:
                size = (max(1, round(width * self._zoom)), max(1, round(height * self._zoom)))
                self._tops.append(y)
                self._sizes.append(size)
                y += size[1] + _GAP
        self._content_height = y if self._sizes else 0
        self._content_width = max((w for w, _ in self._sizes), default=0) + 2 * _GAP
        viewport = self.viewport()
        vertical, horizontal = self.verticalScrollBar(), self.horizontalScrollBar()
        vertical.setPageStep(viewport.height())
        vertical.setRange(0, max(0, self._content_height - viewport.height()))
        horizontal.setPageStep(viewport.width())
        horizontal.setRange(0, max(0, self._content_width - viewport.width()))
        self._refresh_pages()
        viewport.update()

    def _view_rect(self, page: int) -> QRect:
        return self.page_rect(page).translated(
            -self.horizontalScrollBar().value(), -self.verticalScrollBar().value()
        )

    def _rect_to_view(self, page: int, rect: Rect) -> QRect:
        origin = self._view_rect(page).topLeft()
        left = origin.x() + math.floor(rect[0] * self._zoom)
        top = origin.y() + math.floor(rect[1] * self._zoom)
        right = origin.x() + math.ceil(rect[2] * self._zoom)
        bottom = origin.y() + math.ceil(rect[3] * self._zoom)
        return QRect(left, top, right - left, bottom - top)

    def _page_at_y(self, content_y: int) -> int | None:
        index = bisect_right(self._tops, content_y) - 1
        if index < 0 or content_y >= self._tops[index] + self._sizes[index][1]:
            return None
        return index

    def _visible_pages(self) -> range:
        if not self._tops:
            return range(0)
        top = self.verticalScrollBar().value()
        bottom = top + self.viewport().height()
        first = max(bisect_right(self._tops, top) - 1, 0)
        last = max(bisect_right(self._tops, bottom) - 1, 0)
        return range(first, last + 1)

    def _scale(self) -> float:
        return round(self._zoom * self.devicePixelRatioF(), 4)

    def _refresh_pages(self) -> None:
        """Ask for the pages in view, forget the others, track the current page."""
        visible = self._visible_pages()
        if visible:
            wanted = set(range(max(visible[0] - 1, 0), min(visible[-1] + 2, len(self._tops))))
        else:
            wanted = set()
        scale = self._scale()
        self._wanted = wanted
        self._renderer.set_wanted((page, scale) for page in wanted)
        for cache in (self._pixmaps, self._stale):
            for page in [page for page in cache if page not in wanted]:
                del cache[page]
        self._requested &= wanted
        for page in sorted(wanted - self._requested - set(self._pixmaps)):
            self._requested.add(page)
            self._renderer.request(page, scale)
        # Not restarted while running: scroll events arrive faster than the
        # interval, and a timer restarted each time would never fire.
        if self._requested and not self._poll_timer.isActive():
            self._poll_timer.start()

        middle = self.verticalScrollBar().value() + self.viewport().height() // 2
        page = max(bisect_right(self._tops, middle), 1) if self._tops else 0
        if page != self._page:
            self._page = page
            self.page_changed.emit(page)

    def _collect_rendered(self) -> None:
        scale = self._scale()
        for generation, page, rendered_scale, image in self._renderer.poll():
            if generation != self._generation or rendered_scale != scale:
                continue
            self._requested.discard(page)
            if image is None or page not in self._wanted:
                continue  # failed, or scrolled away while it was being drawn
            pixmap = QPixmap.fromImage(image)
            pixmap.setDevicePixelRatio(self.devicePixelRatioF())
            self._pixmaps[page] = pixmap
            self._stale.pop(page, None)
            self.viewport().update(self._view_rect(page))
        if not self._requested:
            self._poll_timer.stop()

    # ---- painting --------------------------------------------------------------------

    def paintEvent(self, event: QPaintEvent) -> None:
        painter = QPainter(self.viewport())
        window = self.palette().color(QPalette.ColorRole.Window)
        painter.fillRect(event.rect(), window.darker(112 if window.lightness() > 128 else 135))
        if self._reading is None:
            font = painter.font()
            font.setPointSize(font.pointSize() + 3)
            painter.setFont(font)
            painter.setPen(self.palette().color(QPalette.ColorRole.PlaceholderText))
            painter.drawText(
                self.viewport().rect(),
                Qt.AlignmentFlag.AlignCenter | Qt.TextFlag.TextWordWrap,
                _EMPTY_HINT,
            )
            return
        for page in self._visible_pages():
            target = self._view_rect(page)
            if not target.intersects(event.rect()):
                continue
            painter.fillRect(target, Qt.GlobalColor.white)
            pixmap = self._pixmaps.get(page) or self._stale.get(page)
            if pixmap is not None:
                painter.drawPixmap(target, pixmap)
            self._paint_overlays(painter, page)
            painter.setPen(QColor(0, 0, 0, 60))
            painter.drawRect(target.adjusted(-1, -1, 0, 0))

    def _paint_overlays(self, painter: QPainter, page: int) -> None:
        for rect in self._overlay_rects.get("selection", {}).get(page, ()):
            painter.fillRect(self._rect_to_view(page, rect), _SELECTION_COLOR)
        reading = self._overlay_rects.get("reading", {}).get(page, ())
        if reading:
            # Multiply, like a highlighter pen: white turns amber, ink stays dark.
            painter.setCompositionMode(QPainter.CompositionMode.CompositionMode_Multiply)
            for rect in reading:
                painter.fillRect(self._rect_to_view(page, rect).adjusted(-2, -1, 2, 1), _READING_COLOR)
            painter.setCompositionMode(QPainter.CompositionMode.CompositionMode_SourceOver)
        for rect in self._overlay_rects.get("marker", {}).get(page, ()):
            box = self._rect_to_view(page, rect)
            baseline = self._view_rect(page).y() + round(rect[3] * self._zoom)
            painter.fillRect(QRect(box.left(), baseline - 1, box.width(), 3), _MARKER_COLOR)

    def _set_overlay(self, name: str, text_range: Range | None) -> None:
        by_page: dict[int, list[Rect]] = {}
        if self._reading is not None and text_range is not None:
            for page, rect in self._reading.rects(*text_range):
                by_page.setdefault(page, []).append(rect)
        self._overlay_rects[name] = by_page
        self.viewport().update()

    # ---- mouse and keyboard ---------------------------------------------------------------

    def _word_under(self, pos: QPoint) -> int | None:
        where = self.to_page(pos) if self._reading is not None else None
        return self._reading.word_at(*where) if where else None

    def _nearest_word(self, pos: QPoint) -> int | None:
        """Closest word to a position, even from the gaps around the pages."""
        if self._reading is None or not self._tops:
            return None
        content_y = pos.y() + self.verticalScrollBar().value()
        page = min(max(bisect_right(self._tops, content_y) - 1, 0), len(self._tops) - 1)
        rect = self._view_rect(page)
        x = min(max(pos.x(), rect.left()), rect.right())
        y = min(max(pos.y(), rect.top()), rect.bottom())
        return self._reading.nearest_word(
            page, (x - rect.x()) / self._zoom, (y - rect.y()) / self._zoom
        )

    def _set_selection(self, selection: Range | None) -> None:
        if selection == self._selection:
            return
        self._selection = selection
        self._set_overlay("selection", selection)
        self.selection_changed.emit(*(selection or (-1, -1)))

    def mousePressEvent(self, event: QMouseEvent) -> None:
        if self._reading is None:
            return
        pos = event.position().toPoint()
        if event.button() == Qt.MouseButton.RightButton:
            word = self._word_under(pos)
            self.context_requested.emit(
                -1 if word is None else word, event.globalPosition().toPoint()
            )
        elif event.button() == Qt.MouseButton.LeftButton:
            self._pressed = True
            self._dragging = False
            self._press_pos = pos
            self._press_word = self._word_under(pos)
            self._anchor_word = self._nearest_word(pos)

    def mouseMoveEvent(self, event: QMouseEvent) -> None:
        if self._reading is None:
            return
        pos = event.position().toPoint()
        if not self._pressed:
            over_word = self._word_under(pos) is not None
            self.viewport().setCursor(
                Qt.CursorShape.IBeamCursor if over_word else Qt.CursorShape.ArrowCursor
            )
            return
        if not self._dragging:
            distance = (pos - self._press_pos).manhattanLength()
            if distance < QApplication.startDragDistance():
                return
            self._dragging = True
        current = self._nearest_word(pos)
        if self._anchor_word is None or current is None:
            return
        words = self._reading.words
        first, last = sorted((self._anchor_word, current))
        self._set_selection((words[first].start, words[last].end))

    def mouseReleaseEvent(self, event: QMouseEvent) -> None:
        if event.button() != Qt.MouseButton.LeftButton or self._reading is None:
            return
        if self._swallow_release:  # second release of a double click
            self._swallow_release = False
            self._pressed = False
            return
        if not self._pressed:
            return
        self._pressed = False
        if self._dragging:
            self._dragging = False
            return
        self._set_selection(None)
        if self._press_word is not None:
            self.word_clicked.emit(self._press_word)
        else:
            self.background_clicked.emit()

    def mouseDoubleClickEvent(self, event: QMouseEvent) -> None:
        if event.button() != Qt.MouseButton.LeftButton or self._reading is None:
            return
        self._swallow_release = True
        word = self._word_under(event.position().toPoint())
        if word is not None:
            self.word_double_clicked.emit(word)

    def contextMenuEvent(self, event) -> None:
        event.accept()  # right clicks are reported from mousePressEvent

    def wheelEvent(self, event: QWheelEvent) -> None:
        if event.modifiers() & Qt.KeyboardModifier.ControlModifier:
            if event.angleDelta().y() > 0:
                self.zoom_in()
            elif event.angleDelta().y() < 0:
                self.zoom_out()
            event.accept()
            return
        super().wheelEvent(event)

    def keyPressEvent(self, event: QKeyEvent) -> None:
        bar = self.verticalScrollBar()
        if event.key() == Qt.Key.Key_Home:
            bar.setValue(bar.minimum())
        elif event.key() == Qt.Key.Key_End:
            bar.setValue(bar.maximum())
        else:
            super().keyPressEvent(event)  # arrows and Page Up/Down scroll

    def resizeEvent(self, event: QResizeEvent) -> None:
        super().resizeEvent(event)
        self._relayout()

    def scrollContentsBy(self, dx: int, dy: int) -> None:
        self._refresh_pages()
        self.viewport().update()
