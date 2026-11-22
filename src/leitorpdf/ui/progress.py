"""Run something slow behind a progress dialog that can be cancelled."""

import queue
import threading
from collections.abc import Callable
from typing import Any

from PySide6.QtCore import Qt, QTimer
from PySide6.QtWidgets import QProgressDialog, QWidget

from leitorpdf.core.errors import user_message
from leitorpdf.ui.messages import APP_NAME, show_error

_POLL_MS = 30

# report(done, total, text=None): total 0 means "unknown"; text replaces the label.
Report = Callable[..., None]
Work = Callable[[Report, threading.Event], Any]


class Cancelled(Exception):
    """Raise from the work to say it stopped because it was asked to."""


def run_with_progress(
    parent: QWidget | None,
    label: str,
    work: Work,
    notify: Callable[[str], None] | None = None,
    cancelled: tuple[type[BaseException], ...] = (Cancelled,),
) -> tuple[str, Any]:
    """Run work(report, cancel) on a thread while a modal dialog shows progress.

    Returns ("done", result), ("cancelled", None) or ("failed", None); a failure
    has already been shown to the user through `notify` when this returns.
    """
    dialog = QProgressDialog(label, "Cancelar", 0, 100, parent)
    dialog.setWindowTitle(APP_NAME)
    dialog.setWindowModality(Qt.WindowModality.WindowModal)
    dialog.setMinimumDuration(0)
    dialog.setAutoClose(False)
    dialog.setAutoReset(False)
    dialog.setValue(0)

    # The thread may outlive this dialog (a dead connection can hold it for a
    # while), so it is given nothing from Qt: only a plain queue and an event.
    # Qt objects freed by a foreign thread crash the program.
    cancel = threading.Event()
    events: queue.SimpleQueue = queue.SimpleQueue()
    _start(work, cancel, events, cancelled)

    outcome: tuple[str, Any] = ("cancelled", None)
    error: BaseException | None = None

    def poll() -> None:
        nonlocal outcome, error
        while True:
            try:
                kind, payload = events.get_nowait()
            except queue.Empty:
                return
            if kind == "progress":
                if cancel.is_set():
                    continue  # touching the dialog now would show it again
                done, total, text = payload
                if total > 0:
                    dialog.setMaximum(100)
                    dialog.setValue(min(99, done * 100 // total))
                else:
                    dialog.setMaximum(0)  # busy indicator
                if text:
                    dialog.setLabelText(text)
                continue
            if kind == "done":
                outcome = ("done", payload)
            elif kind == "failed":
                outcome, error = ("failed", None), payload
            timer.stop()
            dialog.accept()
            return

    timer = QTimer(dialog)
    timer.timeout.connect(poll)
    timer.start(_POLL_MS)
    # A lambda, not `cancel.set`: connecting a bound method makes PySide watch
    # `cancel` through a weak reference, and that watcher would run on the
    # worker thread if the thread were the last one holding the event.
    dialog.canceled.connect(lambda: cancel.set())
    dialog.exec()
    timer.stop()
    # Closing the dialog any other way (Esc, window button) also cancels. The
    # thread is not waited for; it cleans up after itself when it notices.
    cancel.set()
    dialog.hide()
    dialog.deleteLater()  # or they pile up as children of the window

    if error is not None:
        (notify or (lambda text: show_error(parent, text)))(user_message(error))
    return outcome


def _start(
    work: Work,
    cancel: threading.Event,
    events: queue.SimpleQueue,
    cancelled: tuple[type[BaseException], ...],
) -> None:
    def report(done: int, total: int, text: str | None = None) -> None:
        events.put(("progress", (done, total, text)))

    def run() -> None:
        try:
            result = work(report, cancel)
        except cancelled:
            events.put(("cancelled", None))
        except Exception as exc:
            events.put(("failed", exc))
        else:
            events.put(("done", result))

    threading.Thread(target=run, name="leitorpdf-work", daemon=True).start()
