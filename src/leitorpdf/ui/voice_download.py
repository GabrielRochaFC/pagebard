"""Download the default voice behind a progress dialog."""

import threading
from collections.abc import Callable
from pathlib import Path
from typing import Any

from PySide6.QtCore import QObject, Qt, Signal
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


class _Signals(QObject):
    progress = Signal(object, object)  # bytes done, bytes total
    done = Signal(object)  # Voice, or None when cancelled
    failed = Signal(object)  # Exception


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

    cancel = threading.Event()
    signals = _Signals()
    outcome: dict[str, Any] = {}

    def work() -> None:
        try:
            voice = download(
                DEFAULT_VOICE_KEY,
                voices_dir,
                progress=signals.progress.emit,
                cancel=cancel,
            )
        except DownloadCancelled:
            signals.done.emit(None)
        except Exception as exc:
            signals.failed.emit(exc)
        else:
            signals.done.emit(voice)

    def on_progress(done: int, total: int) -> None:
        if total > 0:
            dialog.setValue(min(99, done * 100 // total))
            dialog.setLabelText(
                f"Baixando voz… {done // _MEGABYTE} de {total // _MEGABYTE} MB"
            )

    def on_done(voice: Voice | None) -> None:
        outcome["voice"] = voice
        dialog.accept()

    def on_failed(exc: Exception) -> None:
        outcome["error"] = exc
        dialog.accept()

    queued = Qt.ConnectionType.QueuedConnection
    signals.progress.connect(on_progress, queued)
    signals.done.connect(on_done, queued)
    signals.failed.connect(on_failed, queued)
    dialog.canceled.connect(cancel.set)

    thread = threading.Thread(target=work, name="leitorpdf-download", daemon=True)
    thread.start()
    dialog.exec()
    # Closing the dialog any other way (Esc, window button) also cancels.
    # The thread is not waited for: a dead connection can hold it for a while,
    # and it cleans up after itself when it finally notices.
    if "voice" not in outcome and "error" not in outcome:
        cancel.set()

    if "error" in outcome:
        (notify or (lambda text: show_error(parent, text)))(user_message(outcome["error"]))
        return None
    return outcome.get("voice")
