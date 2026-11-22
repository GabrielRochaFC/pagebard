"""Turns PDF pages into images on a thread of its own.

The thread is given nothing from Qt except the images it produces: results
travel through a plain queue and the view collects them with `poll()`.
"""

import queue
import threading
from collections.abc import Iterable
from pathlib import Path

import pymupdf
from PySide6.QtGui import QImage

from leitorpdf.core.pdf import MUPDF_LOCK

# (generation, page, scale, image); image is None when the page failed to render.
RenderResult = tuple[int, int, float, QImage | None]


class PageRenderer:
    def __init__(self) -> None:
        self._requests: queue.SimpleQueue = queue.SimpleQueue()
        self._results: queue.SimpleQueue = queue.SimpleQueue()
        self._wanted: frozenset[tuple[int, float]] = frozenset()
        self._generation = 0
        self._thread: threading.Thread | None = None

    def open(self, path: Path | None) -> int:
        """Switch to another document (or none). Returns its generation number."""
        self._generation += 1
        self._wanted = frozenset()
        if self._thread is None:
            self._thread = threading.Thread(
                target=self._run, name="leitorpdf-render", daemon=True
            )
            self._thread.start()
        self._requests.put(("open", self._generation, path))
        return self._generation

    def set_wanted(self, keys: Iterable[tuple[int, float]]) -> None:
        """Only (page, scale) pairs listed here are worth rendering."""
        self._wanted = frozenset(keys)

    def request(self, page: int, scale: float) -> None:
        self._requests.put(("render", self._generation, page, scale))

    def poll(self) -> list[RenderResult]:
        results = []
        while True:
            try:
                results.append(self._results.get_nowait())
            except queue.Empty:
                return results

    def close(self) -> None:
        if self._thread is not None:
            self._requests.put(None)
            self._thread.join(2.0)
            self._thread = None

    def _run(self) -> None:
        doc = None
        generation = 0
        while True:
            item = self._requests.get()
            if item is None:
                break
            if item[0] == "open":
                _, generation, path = item
                with MUPDF_LOCK:
                    if doc is not None:
                        doc.close()
                        doc = None
                    if path is not None:
                        try:
                            doc = pymupdf.open(path)
                        except Exception:
                            doc = None
                continue
            _, wanted_generation, page, scale = item
            if wanted_generation != generation or (page, scale) not in self._wanted:
                continue  # scrolled away or document replaced meanwhile
            image = None
            if doc is not None:
                try:
                    with MUPDF_LOCK:
                        image = _render(doc, page, scale)
                except Exception:
                    image = None
            self._results.put((generation, page, scale, image))
        if doc is not None:
            with MUPDF_LOCK:
                doc.close()


def _render(doc: pymupdf.Document, page: int, scale: float) -> QImage:
    pixmap = doc[page].get_pixmap(
        matrix=pymupdf.Matrix(scale, scale), colorspace=pymupdf.csRGB, alpha=False
    )
    image = QImage(
        pixmap.samples,
        pixmap.width,
        pixmap.height,
        pixmap.stride,
        QImage.Format.Format_RGB888,
    )
    return image.copy()  # own the pixels; the PyMuPDF buffer goes away
