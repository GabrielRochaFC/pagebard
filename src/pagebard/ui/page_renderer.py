"""Turns PDF pages into images without ever holding up the window.

Pages are drawn by a child process (see core/render_worker.py). A thread here
feeds it and collects the images; the view picks them up with `poll()`. The
thread is given nothing from Qt except the images it produces.
"""

import queue
import threading
from collections.abc import Iterable
from pathlib import Path

from PySide6.QtGui import QImage

from pagebard.core.worker_client import WorkerProcess

# (generation, page, scale, image); image is None when the page could not be drawn.
RenderResult = tuple[int, int, float, QImage | None]


class PageRenderer:
    def __init__(self) -> None:
        self._requests: queue.SimpleQueue = queue.SimpleQueue()
        self._results: queue.SimpleQueue = queue.SimpleQueue()
        self._wanted: frozenset[tuple[int, float]] = frozenset()
        self._generation = 0
        self._thread: threading.Thread | None = None
        self._worker = WorkerProcess()

    def open(self, path: Path | None) -> int:
        """Switch to another document (or none). Returns its generation number."""
        self._generation += 1
        self._wanted = frozenset()
        if self._thread is None:
            self._thread = threading.Thread(
                target=self._run, name="pagebard-render", daemon=True
            )
            self._thread.start()
        self._requests.put(("open", self._generation, path))
        return self._generation

    def set_wanted(self, keys: Iterable[tuple[int, float]]) -> None:
        """Only (page, scale) pairs listed here are worth drawing."""
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

    def worker_pid(self) -> int | None:
        """Process id of the drawing process, while there is one."""
        return self._worker.pid()

    def close(self) -> None:
        if self._thread is not None:
            self._requests.put(None)
            self._thread.join(2.0)
            self._thread = None

    # ---- on the feeding thread -------------------------------------------------

    def _run(self) -> None:
        generation = 0
        path: Path | None = None
        holder: int | None = None  # pid of the worker that has `path` open
        while True:
            item = self._requests.get()
            if item is None:
                break
            if item[0] == "open":
                _, generation, path = item
                holder = self._open(path)
                continue
            _, wanted_generation, page, scale = item
            if wanted_generation != generation or (page, scale) not in self._wanted:
                continue  # scrolled away or document replaced meanwhile
            if holder is None or self._worker.pid() != holder:
                holder = self._open(path)  # the worker died and was replaced
            reply = self._worker.exchange({"op": "render", "page": page, "scale": scale})
            self._results.put((generation, page, scale, _to_image(reply)))
        self._worker.stop()

    def _open(self, path: Path | None) -> int | None:
        """Have the worker open the file; returns its pid, or None on failure."""
        request = {"op": "open", "path": None if path is None else str(path)}
        if self._worker.exchange(request) is None:
            return None
        return self._worker.pid()


def _to_image(reply: tuple[dict, bytes] | None) -> QImage | None:
    if reply is None or not reply[0].get("ok") or not reply[1]:
        return None
    header, pixels = reply
    image = QImage(
        pixels,
        header["width"],
        header["height"],
        header["stride"],
        QImage.Format.Format_RGB888,
    )
    return image.copy()  # own the pixels; `pixels` is released after this
