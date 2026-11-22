"""Run slow work off the UI thread and get the result back on it."""

import itertools
from collections.abc import Callable
from typing import Any

from PySide6.QtCore import QObject, QRunnable, Qt, QThreadPool, Signal


class _Bridge(QObject):
    """Carries results from worker threads to the UI thread."""

    finished = Signal(int, bool, object)  # task id, succeeded, result or exception


# Worker threads are handed only plain values and this bridge, which lives as
# long as the program: a Qt object must never be freed by a foreign thread.
_bridge: _Bridge | None = None
_callbacks: dict[int, tuple[Callable[[Any], None], Callable[[Exception], None]]] = {}
_task_ids = itertools.count(1)


class _Task(QRunnable):
    def __init__(self, task_id: int, fn: Callable[[], Any], bridge: _Bridge) -> None:
        super().__init__()
        self._task_id = task_id
        self._fn = fn
        self._bridge = bridge

    def run(self) -> None:
        try:
            result = self._fn()
        except Exception as exc:
            self._bridge.finished.emit(self._task_id, False, exc)
        else:
            self._bridge.finished.emit(self._task_id, True, result)


def run_async(
    fn: Callable[[], Any],
    on_done: Callable[[Any], None],
    on_error: Callable[[Exception], None],
) -> None:
    """Call fn() on a worker thread, then on_done/on_error on the UI thread.

    `fn` runs on another thread: it must not capture widgets or other Qt objects.
    """
    global _bridge
    if _bridge is None:
        _bridge = _Bridge()
        _bridge.finished.connect(_deliver, Qt.ConnectionType.QueuedConnection)
    task_id = next(_task_ids)
    _callbacks[task_id] = (on_done, on_error)
    QThreadPool.globalInstance().start(_Task(task_id, fn, _bridge))


def _deliver(task_id: int, succeeded: bool, payload: Any) -> None:
    on_done, on_error = _callbacks.pop(task_id)
    (on_done if succeeded else on_error)(payload)
