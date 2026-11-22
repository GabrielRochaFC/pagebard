"""Download the default voice behind a progress dialog."""

import queue
import threading
from collections.abc import Callable
from pathlib import Path

from PySide6.QtCore import Qt, QTimer
from PySide6.QtWidgets import QProgressDialog, QWidget

from leitorpdf.core.errors import user_message
from leitorpdf.core.voices import (
    DEFAULT_VOICE_KEY,
    DownloadCancelled,
    Voice,
    download_voice,
)
from leitorpdf.ui.messages import APP_NAME, show_error

_MEGABYTE = 1_000_000
_POLL_MS = 30


def download_default_voice(
    parent: QWidget | None,
    voices_dir: Path,
    notify: Callable[[str], None] | None = None,
    download: Callable[..., Voice] = download_voice,
) -> Voice | None:
    """Blocks (with a responsive dialog) until done. None if cancelled or failed."""
    dialog = QProgressDialog("Baixando voz…", "Cancelar", 0, 100, parent)
    dialog.setWindowTitle(APP_NAME)
    dialog.setWindowModality(Qt.WindowModality.WindowModal)
    dialog.setMinimumDuration(0)
    dialog.setAutoClose(False)
    dialog.setAutoReset(False)
    dialog.setValue(0)

    # The download thread may outlive this dialog (a dead connection can hold
    # it for a while), so it is given nothing from Qt: only a plain queue and
    # an event. Qt objects destroyed from a foreign thread crash the program.
    cancel = threading.Event()
    events: queue.SimpleQueue = queue.SimpleQueue()
    _start_download(download, voices_dir, cancel, events)

    voice: Voice | None = None
    error: Exception | None = None

    def poll() -> None:
        nonlocal voice, error
        while True:
            try:
                kind, payload = events.get_nowait()
            except queue.Empty:
                return
            if kind == "progress":
                done, total = payload
                if total > 0:
                    dialog.setValue(min(99, done * 100 // total))
                    dialog.setLabelText(
                        f"Baixando voz… {done // _MEGABYTE} de {total // _MEGABYTE} MB"
                    )
            else:
                if kind == "done":
                    voice = payload
                elif kind == "failed":
                    error = payload
                timer.stop()
                dialog.accept()
                return

    timer = QTimer(dialog)
    timer.timeout.connect(poll)
    timer.start(_POLL_MS)
    dialog.canceled.connect(cancel.set)
    dialog.exec()
    timer.stop()
    # Closing the dialog any other way (Esc, window button) also cancels.
    # The thread is not waited for; it cleans up when it notices.
    cancel.set()

    if error is not None:
        (notify or (lambda text: show_error(parent, text)))(user_message(error))
        return None
    return voice


def _start_download(
    download: Callable[..., Voice],
    voices_dir: Path,
    cancel: threading.Event,
    events: queue.SimpleQueue,
) -> None:
    def work() -> None:
        try:
            voice = download(
                DEFAULT_VOICE_KEY,
                voices_dir,
                progress=lambda done, total: events.put(("progress", (done, total))),
                cancel=cancel,
            )
        except DownloadCancelled:
            events.put(("cancelled", None))
        except Exception as exc:
            events.put(("failed", exc))
        else:
            events.put(("done", voice))

    threading.Thread(target=work, name="leitorpdf-download", daemon=True).start()
