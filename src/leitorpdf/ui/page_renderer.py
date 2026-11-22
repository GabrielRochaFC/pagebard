"""Turns PDF pages into images without ever holding up the window.

Pages are drawn by a child process (see core/render_worker.py). A thread here
feeds it and collects the images; the view picks them up with `poll()`. The
thread is given nothing from Qt except the images it produces.
"""

import json
import queue
import subprocess
import sys
import threading
from collections.abc import Iterable
from pathlib import Path

from PySide6.QtGui import QImage

# (generation, page, scale, image); image is None when the page could not be drawn.
RenderResult = tuple[int, int, float, QImage | None]

_WORKER_COMMAND = [sys.executable, "-P", "-m", "leitorpdf.core.render_worker"]


class PageRenderer:
    def __init__(self) -> None:
        self._requests: queue.SimpleQueue = queue.SimpleQueue()
        self._results: queue.SimpleQueue = queue.SimpleQueue()
        self._wanted: frozenset[tuple[int, float]] = frozenset()
        self._generation = 0
        self._thread: threading.Thread | None = None
        self._worker: subprocess.Popen | None = None

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
        worker = self._worker
        return worker.pid if worker is not None and worker.poll() is None else None

    def close(self) -> None:
        if self._thread is not None:
            self._requests.put(None)
            self._thread.join(2.0)
            self._thread = None

    # ---- on the feeding thread -------------------------------------------------

    def _run(self) -> None:
        generation = 0
        path: Path | None = None
        holder: subprocess.Popen | None = None  # the worker that has `path` open
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
            if holder is None or holder is not self._worker or holder.poll() is not None:
                holder = self._open(path)  # the worker died and was replaced
            reply = self._exchange({"op": "render", "page": page, "scale": scale})
            self._results.put((generation, page, scale, _to_image(reply)))
        self._stop_worker()

    def _open(self, path: Path | None) -> subprocess.Popen | None:
        """Have the worker open the file; returns that worker, or None on failure."""
        if self._exchange({"op": "open", "path": _text(path)}) is None:
            return None
        return self._worker

    def _exchange(self, request: dict) -> tuple[dict, bytes] | None:
        """Send one request and read its reply; None if the worker failed."""
        try:
            worker = self._ensure_worker()
            worker.stdin.write(json.dumps(request).encode() + b"\n")
            worker.stdin.flush()
            header = json.loads(worker.stdout.readline())
            size = header.get("size", 0)
            pixels = worker.stdout.read(size) if size else b""
            if len(pixels) != size:
                raise OSError("render worker closed its output")
            return header, pixels
        except (OSError, ValueError):
            self._stop_worker()
            return None

    def _ensure_worker(self) -> subprocess.Popen:
        if self._worker is None or self._worker.poll() is not None:
            self._worker = subprocess.Popen(
                _WORKER_COMMAND,
                stdin=subprocess.PIPE,
                stdout=subprocess.PIPE,
                stderr=subprocess.DEVNULL,
            )
        return self._worker

    def _stop_worker(self) -> None:
        worker, self._worker = self._worker, None
        if worker is None:
            return
        for stream in (worker.stdin, worker.stdout):
            try:
                stream.close()  # closing its input is what tells it to exit
            except OSError:
                pass
        # Reaped in the background: it may still be busy starting or drawing.
        threading.Thread(target=_reap, args=(worker,), daemon=True).start()


def _reap(worker: subprocess.Popen) -> None:
    try:
        worker.wait(timeout=2.0)
    except subprocess.TimeoutExpired:
        worker.kill()
        worker.wait()


def _text(path: Path | None) -> str | None:
    return None if path is None else str(path)


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
