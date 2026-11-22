"""Run slow work off the UI thread and get the result back on it."""

from collections.abc import Callable
from typing import Any

from PySide6.QtCore import QObject, QRunnable, Qt, QThreadPool, Signal


class _Signals(QObject):
    done = Signal(object)
    failed = Signal(object)


class _Task(QRunnable):
    def __init__(self, fn: Callable[[], Any], signals: _Signals) -> None:
        super().__init__()
        self._fn = fn
        self._signals = signals

    def run(self) -> None:
        try:
            result = self._fn()
        except Exception as exc:
            self._signals.failed.emit(exc)
        else:
            self._signals.done.emit(result)


# Signal objects must outlive their task until the callback has run;
# otherwise Python may collect them while the result is still queued.
_in_flight: set[_Signals] = set()


def run_async(
    fn: Callable[[], Any],
    on_done: Callable[[Any], None],
    on_error: Callable[[Exception], None],
) -> None:
    """Call fn() on a worker thread, then on_done/on_error on the UI thread."""
    signals = _Signals()
    _in_flight.add(signals)

    def finish(callback: Callable[[Any], None], value: Any) -> None:
        _in_flight.discard(signals)
        callback(value)

    queued = Qt.ConnectionType.QueuedConnection
    signals.done.connect(lambda value: finish(on_done, value), queued)
    signals.failed.connect(lambda exc: finish(on_error, exc), queued)
    QThreadPool.globalInstance().start(_Task(fn, signals))
