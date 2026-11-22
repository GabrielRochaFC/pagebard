"""Download a voice behind a progress dialog."""

from collections.abc import Callable
from pathlib import Path

from PySide6.QtWidgets import QWidget

from leitorpdf.core.voices import (
    DEFAULT_VOICE_KEY,
    DownloadCancelled,
    Voice,
    download_voice,
)
from leitorpdf.ui.progress import run_with_progress

_MEGABYTE = 1_000_000


def download_voice_with_progress(
    parent: QWidget | None,
    key: str,
    voices_dir: Path,
    notify: Callable[[str], None] | None = None,
    download: Callable[..., Voice] = download_voice,
) -> Voice | None:
    """Blocks (with a responsive dialog) until done. None if cancelled or failed."""

    def work(report, cancel):
        def progress(done: int, total: int) -> None:
            text = None
            if total > 0:
                text = f"Baixando voz… {done // _MEGABYTE} de {total // _MEGABYTE} MB"
            report(done, total, text)

        return download(key, voices_dir, progress=progress, cancel=cancel)

    status, voice = run_with_progress(
        parent, "Baixando voz…", work, notify, cancelled=(DownloadCancelled,)
    )
    return voice if status == "done" else None


def download_default_voice(
    parent: QWidget | None,
    voices_dir: Path,
    notify: Callable[[str], None] | None = None,
    download: Callable[..., Voice] = download_voice,
) -> Voice | None:
    return download_voice_with_progress(parent, DEFAULT_VOICE_KEY, voices_dir, notify, download)
